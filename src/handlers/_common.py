"""Shared helpers for tool handlers.

Validation, normalization, and the common ``@tool_handler`` decorator live
here so each individual handler module stays focused on its own tool's logic.
"""

import functools
import json
import logging
from datetime import date

from ..dish import Dish
from ..repositories import history_repo

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


# ---------------------------------------------------------------------------
# Handler decorator
# ---------------------------------------------------------------------------
# Centralizes the boilerplate every tool used to repeat: JSON serialization
# of the success result, logging + structured error envelope on failure.
# Handlers return Python objects and raise on validation/business errors.

def tool_handler(name: str):
    """Wrap a tool function with JSON serialization and a unified error envelope.

    The wrapped function returns a Python object (dict, list, str, ...). On
    success it is encoded with ``json.dumps(..., ensure_ascii=False)``. Any
    exception is logged via ``logger.exception`` and surfaced as
    ``{"error": str(exc)}`` so all tool errors share one shape.
    """
    log = logging.getLogger(f"meal_manager.handlers.{name}")

    def decorate(fn):
        @functools.wraps(fn)
        def runner(args, **kwargs):
            try:
                return json.dumps(fn(args, **kwargs), ensure_ascii=False)
            except Exception as exc:
                log.exception("%s failed", name)
                return json.dumps({"error": str(exc)}, ensure_ascii=False)

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
    return _normalize_label(name, label="Ingredient name")


def normalize_ingredients(ingredients) -> dict:
    """Accept ingredients as dict {name: bool} or list [name, ...] (all essential).
    Also handles JSON strings (some LLMs serialize the argument).
    Raises ValueError if the input cannot be parsed."""
    ingredients = maybe_parse_json_arg(ingredients)
    if isinstance(ingredients, str):
        raise ValueError(f"Cannot parse ingredients string: {ingredients!r}")
    if isinstance(ingredients, list):
        result = {}
        for ing in ingredients:
            result[normalize_ingredient_name(ing)] = True
    elif isinstance(ingredients, dict):
        result = {}
        for key, value in ingredients.items():
            if not isinstance(value, bool):
                raise ValueError(f"ingredient '{key}' must be true or false")
            result[normalize_ingredient_name(key)] = value
    else:
        raise ValueError(f"ingredients must be a dict or list, got {type(ingredients).__name__}")
    if not result:
        raise ValueError("ingredients cannot be empty")
    # Enforce the cap on the de-duplicated result, so a list containing repeats
    # that collapses under the limit is still accepted.
    if len(result) > MAX_INGREDIENTS:
        raise ValueError(f"Too many ingredients (max {MAX_INGREDIENTS})")
    return result


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
        # history_repo.load() already returns normalized (stripped/lowercased)
        # keys, so no re-normalization is needed here.
        result[name] = max(days, 0)
    return result
