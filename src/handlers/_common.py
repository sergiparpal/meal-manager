"""Shared helpers for tool handlers.

Validation, normalization, and the common ``@tool_handler`` decorator live
here so each individual handler module stays focused on its own tool's logic.
"""

import functools
import json
import logging
from datetime import date

from ..dish import Dish
from ..repositories import alias_repo, history_repo

logger = logging.getLogger(__name__)

# tool_handler creates loggers under the hardcoded ``meal_manager.handlers``
# namespace (independent of how the package is imported). Attach a NullHandler
# there once so library users without logging configured don't see noise.
logging.getLogger("meal_manager.handlers").addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Input limits (safety net for LLM-generated arguments)
# ---------------------------------------------------------------------------

MAX_NAME_LEN = 200
MAX_INGREDIENTS = 100
MAX_BATCH_SIZE = 50
MAX_FRIDGE_UPDATE = 200
MAX_PORTION_COUNT = 99


# ---------------------------------------------------------------------------
# Handler decorator
# ---------------------------------------------------------------------------
# Centralizes the boilerplate every tool used to repeat: JSON serialization
# of the success result, logging + structured error envelope on failure.
# Handlers return Python objects and raise on validation/business errors.

def _safe_error_message(exc: BaseException) -> str:
    """Map an exception to the text that may leave the process.

    Handlers raise ``ValueError`` / ``LookupError`` deliberately, with wording
    written for the user, so those pass through verbatim. Everything else is
    replaced: an ``OSError`` carries absolute filesystem paths and a
    ``JSONDecodeError`` carries byte offsets into file contents, and both end up
    in the model's context and the user's chat. The catch-all default is the
    point — an unanticipated exception type is exactly the case where
    ``str(exc)`` is most likely to publish something we did not mean to.

    Full detail is still logged by the caller via ``logger.exception``.
    """
    # JSONDecodeError subclasses ValueError, so it must be tested first or it
    # would never match.
    if isinstance(exc, json.JSONDecodeError):
        return "Stored data could not be read"
    if isinstance(exc, (ValueError, LookupError)):
        return str(exc)
    if isinstance(exc, OSError):
        return "Storage is temporarily unavailable"
    return "An internal error occurred"


def reject_unknown_args(args: dict, allowed: set[str]) -> None:
    """Raise unless every key in *args* is declared in *allowed*.

    An unknown key means the caller's mental model of the tool is wrong
    (``dish_name`` for ``name``, ``qty`` for a count). Silently ignoring it
    either surfaces as a confusing "missing argument" error about a different
    key, or lets the handler run with defaults the caller never asked for.
    """
    if not isinstance(args, dict):
        raise ValueError("tool arguments must be an object")
    unknown = set(args) - allowed
    if unknown:
        raise ValueError(f"unknown arguments: {sorted(unknown)}")


def tool_handler(name: str, schema: dict | None = None, *, extra_args: set | None = None):
    """Wrap a tool function with JSON serialization and a unified error envelope.

    The wrapped function returns a Python object (dict, list, str, ...). On
    success it is encoded with ``json.dumps(..., ensure_ascii=False)``. Any
    exception is logged via ``logger.exception`` and surfaced as
    ``{"error": ...}`` so all tool errors share one shape; the message itself
    goes through :func:`_safe_error_message`.

    When *schema* is supplied, incoming ``args`` keys are validated against
    ``schema["properties"]`` (widened by *extra_args*) before the handler runs.
    Deriving the allowed set from the schema itself means the check can never
    drift from the tool's declared interface. ``schema=None`` keeps the
    unvalidated behaviour.
    """
    log = logging.getLogger(f"meal_manager.handlers.{name}")
    allowed = None
    if schema is not None:
        allowed = set(schema.get("properties", {})) | (extra_args or set())

    def decorate(fn):
        @functools.wraps(fn)
        def runner(args, **kwargs):
            try:
                # Inside the try on purpose: a rejected argument must come back
                # through the normal error envelope, not escape the wrapper.
                if allowed is not None:
                    reject_unknown_args(args, allowed)
                return json.dumps(fn(args, **kwargs), ensure_ascii=False)
            except Exception as exc:
                log.exception("%s failed", name)
                return json.dumps(
                    {"error": _safe_error_message(exc)}, ensure_ascii=False
                )

        return runner

    return decorate


def require_arg(args: dict, key: str):
    """Fetch a required argument, raising a clear message if it is absent.

    Handlers used to index ``args[key]`` directly, so a missing field surfaced
    as a bare ``KeyError`` (``{"error": "'key'"}``). This yields an explicit
    "required argument" message instead.
    """
    if not isinstance(args, dict) or key not in args:
        raise ValueError(f"'{key}' is a required argument")
    return args[key]


def maybe_parse_json_arg(value):
    """Coerce a possibly-JSON-string argument to its parsed form.

    Some LLMs serialize array/object arguments as JSON strings. Returns the
    parsed value on success, or the original string unchanged if it is not valid
    JSON, leaving type validation to the caller. Shared by every handler that
    accepts array/object arguments so the coercion behaves identically.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _normalize_label(value: str, *, label: str) -> str:
    normalized = Dish._clean(value, label=label.lower())
    if not normalized:
        raise ValueError(f"{label} cannot be empty")
    if len(normalized) > MAX_NAME_LEN:
        raise ValueError(f"{label} too long (max {MAX_NAME_LEN} chars)")
    return normalized


def normalize_dish_name(name: str) -> str:
    return _normalize_label(name, label="Dish name")


def normalize_ingredient_name(name: str) -> str:
    """Normalize an ingredient name and collapse it onto its canonical spelling.

    Alias resolution lives here, at the tool boundary, and deliberately *not*
    in ``Dish.normalize_ingredient``: the domain layer stays pure and I/O-free.
    That asymmetry is intentional — do not "fix" it by pushing the lookup down.

    Because this reads the alias map, handlers must normalize their arguments
    **before** acquiring any repository lock. The lock order is
    ``alias -> dish -> fridge``.
    """
    return alias_repo.resolve(_normalize_label(name, label="Ingredient name"))


def normalize_ingredients(ingredients) -> dict:
    """Accept ingredients as dict {name: bool} or list [name, ...] (all essential).
    Also handles JSON strings (some LLMs serialize the argument).
    Raises ValueError if the input cannot be parsed."""
    ingredients = maybe_parse_json_arg(ingredients)
    if isinstance(ingredients, str):
        raise ValueError(f"Cannot parse ingredients string: {ingredients!r}")
    if isinstance(ingredients, list):
        # Every list entry means the same thing (essential), so repeats collapse
        # without losing information.
        result = {}
        for ing in ingredients:
            result[normalize_ingredient_name(ing)] = True
    elif isinstance(ingredients, dict):
        result = {}
        for key, value in ingredients.items():
            if not isinstance(value, bool):
                raise ValueError(f"ingredient '{key}' must be true or false")
            name = normalize_ingredient_name(key)
            # Unlike a list, two dict keys that collide after normalization can
            # disagree ({"Rice": true, "rice": false}). Reject rather than let
            # one flag silently win.
            if name in result:
                raise ValueError(f"duplicate ingredient '{name}' after normalization")
            result[name] = value
    else:
        raise ValueError(f"ingredients must be a dict or list, got {type(ingredients).__name__}")
    if not result:
        raise ValueError("ingredients cannot be empty")
    # Enforce the cap on the de-duplicated result, so a list containing repeats
    # that collapses under the limit is still accepted.
    if len(result) > MAX_INGREDIENTS:
        raise ValueError(f"Too many ingredients (max {MAX_INGREDIENTS})")
    return result


def normalize_ingredient_names(ingredients) -> list[str]:
    """Accept ``["a", "b"]`` or ``{"a": 3}`` -> ``["a", "b"]`` (order preserved).

    For paths where a portion count is meaningless — fridge removal deletes the
    entry outright — so a count that happens to be present is ignored rather
    than validated. Without this, echoing back a count seen in ``list_fridge``
    would fail a removal on a limit that does not apply to it.
    """
    ingredients = maybe_parse_json_arg(ingredients)
    if isinstance(ingredients, str):
        raise ValueError(f"Cannot parse ingredients string: {ingredients!r}")
    if isinstance(ingredients, dict):
        raw_names = list(ingredients.keys())
    elif isinstance(ingredients, list):
        raw_names = ingredients
    else:
        raise ValueError(
            f"ingredients must be a dict or list, got {type(ingredients).__name__}"
        )
    return list(dict.fromkeys(normalize_ingredient_name(name) for name in raw_names))


def _normalize_expiry(raw, *, name: str) -> str:
    """Validate an ISO expiry date supplied by the caller.

    Strict, unlike ``JsonFridgeRepository`` on load: a value arriving through a
    tool call can still be corrected, whereas one already on disk would only be
    lost. The codebase applies that asymmetry elsewhere too.
    """
    if not isinstance(raw, str):
        raise ValueError(f"expires_on for '{name}' must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError(f"invalid expires_on {raw!r} for '{name}': {exc}") from exc


def normalize_ingredient_entries(ingredients) -> dict:
    """Accept the fridge's full input grammar -> ``{name: spec}``.

    Handles ``["a", "b"]`` (one portion each), ``{"a": 3, "salt": None}``
    (counts, ``None`` = pantry staple), and the object form
    ``{"milk": {"count": 2, "expires_on": "2026-08-01"}}``.

    Each returned spec always has ``"count"``. It has ``"expires_on"`` only
    when the caller actually supplied one, so a handler can tell "clear the
    date" (explicit ``null``) apart from "leave the date alone" (key absent).
    """
    ingredients = maybe_parse_json_arg(ingredients)
    if isinstance(ingredients, str):
        raise ValueError(f"Cannot parse ingredients string: {ingredients!r}")
    if isinstance(ingredients, list):
        return {
            normalize_ingredient_name(ing): {"count": 1} for ing in ingredients
        }
    if not isinstance(ingredients, dict):
        raise ValueError(
            f"ingredients must be a dict or list, got {type(ingredients).__name__}"
        )

    result: dict = {}
    for raw_name, raw_value in ingredients.items():
        name = normalize_ingredient_name(raw_name)
        # Colliding keys can carry different counts or dates, so one silently
        # winning would discard something the caller supplied deliberately.
        if name in result:
            raise ValueError(f"duplicate ingredient '{name}' after normalization")

        if isinstance(raw_value, dict):
            unknown = set(raw_value) - {"count", "expires_on"}
            if unknown:
                raise ValueError(
                    f"unknown fields for '{raw_name}': {sorted(unknown)}"
                )
            # A bare list entry means one portion; an object that omits the
            # count means the same thing.
            spec = {"count": _validate_count(raw_value.get("count", 1), raw_name)}
            if "expires_on" in raw_value:
                raw_expiry = raw_value["expires_on"]
                spec["expires_on"] = (
                    None if raw_expiry is None
                    else _normalize_expiry(raw_expiry, name=raw_name)
                )
        else:
            spec = {"count": _validate_count(raw_value, raw_name)}

        result[name] = spec
    return result


def _validate_count(raw_count, raw_name):
    if raw_count is None:
        return None
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raise ValueError(f"count for '{raw_name}' must be an integer or null")
    if not 0 <= raw_count <= MAX_PORTION_COUNT:
        raise ValueError(
            f"count for '{raw_name}' must be between 0 and {MAX_PORTION_COUNT}"
        )
    return raw_count


def days_since_last_cook() -> dict[str, int]:
    """Build a mapping of dish name -> days since it was last cooked."""
    history = history_repo.load()
    today = date.today()
    result = {}
    for name, date_str in history.items():
        try:
            days = (today - date.fromisoformat(date_str)).days
        except ValueError as exc:
            logger.warning("Skipping malformed history entry %r: %s", name, exc)
            continue
        if days < 0:
            # Only reachable from a hand-edited file or a clock jump — the tool
            # boundary rejects future dates. Clamping keeps the dish gated by
            # the cooldown instead of scoring it, but say so: otherwise the dish
            # silently disappears from suggestions with nothing to point at.
            logger.warning(
                "History entry %r is dated in the future (%s); treating it as cooked today",
                name,
                date_str,
            )
        # history_repo.load() already returns normalized (stripped/lowercased)
        # keys, so no re-normalization is needed here.
        result[name] = max(days, 0)
    return result
