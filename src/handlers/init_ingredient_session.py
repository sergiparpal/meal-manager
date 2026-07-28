"""Tool: init_ingredient_session — create or reset a DII session."""

import uuid

from ..dii import create_session, get_session_state, validate_session_id
from ._common import (
    MAX_INGREDIENTS,
    maybe_parse_json_arg,
    normalize_dish_name,
    normalize_ingredient_name,
    require_arg,
    tool_handler,
)

NAME = "init_ingredient_session"

DEFAULT_PRE_SELECT = 3

SCHEMA = {
    "description": (
        "Initialize a Dynamic Ingredient Interface session for a dish. "
        "The agent provides ranked ingredient suggestions. Top N are auto-selected. "
        "Returns session state with the first hidden suggestion revealed. "
        "To recalculate after removing an essential ingredient, pass the existing "
        "session_id — the session will be reset in place and the same id reused."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "Name of the dish to configure ingredients for",
        },
        "ingredients": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of ingredient names in order of relevance (highest first)",
        },
        "is_essential": {
            "type": "array",
            "items": {"type": "boolean"},
            "description": "Parallel array - true if ingredient at same index is essential, false if optional",
        },
        "pre_select_top_n": {
            "type": "integer",
            "minimum": 0,
            "description": (
                f"How many top ingredients to auto-select "
                f"(default {DEFAULT_PRE_SELECT})"
            ),
        },
        "session_id": {
            "type": "string",
            "description": (
                "Optional. When recalculating an existing session, pass its id "
                "here to reset it in place. Omit to create a brand-new session."
            ),
        },
    },
    "required": ["dish_name", "ingredients", "is_essential"],
}


def _canonical_ingredients(ingredients, is_essential) -> list[str]:
    """Validate the parallel arrays and return the canonical ingredient names.

    The canonical names are what the session must be built from. Resolving
    them here and discarding the result would leave the whole DII path blind to
    ingredient aliases: the engine normalizes with ``Dish.normalize_ingredient``,
    which strips and lowercases but deliberately never touches the alias map.
    A session seeded with a retired spelling would then commit that spelling
    straight back into the catalog and the fridge, recreating the duplicate the
    merge existed to remove.

    Runs before any repository lock is taken, as the ``alias -> dish -> fridge``
    lock order requires.
    """
    if not isinstance(ingredients, list) or not isinstance(is_essential, list):
        raise ValueError("ingredients and is_essential must be arrays")
    if len(ingredients) != len(is_essential):
        raise ValueError(
            f"ingredients ({len(ingredients)}) and is_essential "
            f"({len(is_essential)}) must have the same length"
        )
    if len(ingredients) > MAX_INGREDIENTS:
        raise ValueError(f"Too many ingredients (max {MAX_INGREDIENTS})")
    for flag in is_essential:
        if not isinstance(flag, bool):
            raise ValueError("is_essential must contain boolean values")
    return [normalize_ingredient_name(ing) for ing in ingredients]


def _build_ranked(ingredients, is_essential):
    # The real guarantee is the length check in _canonical_ingredients above,
    # the only path that reaches here. strict=True is defense in depth: if a
    # future caller arrives without that check, a silent truncation becomes a
    # raised error.
    return [
        {"ingredient": ing, "is_essential": ess}
        for ing, ess in zip(ingredients, is_essential, strict=True)
    ]


def _coerce_pre_select(value):
    """Validate ``pre_select_top_n``, defaulting only when it is absent.

    Coercing with a bare ``int()`` and falling back to the default on failure
    meant a caller that passed nonsense got a silently different selection than
    it asked for. Every other argument in this package is rejected outright.
    """
    if value is None:
        return DEFAULT_PRE_SELECT
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("pre_select_top_n must be an integer")
    if value < 0:
        raise ValueError("pre_select_top_n must be >= 0")
    return value


def _resolve_session_id(provided):
    if provided is None:
        return uuid.uuid4().hex[:16], False
    if not isinstance(provided, str) or not provided.strip():
        raise ValueError("session_id must be a non-empty string when provided")
    # Reject path-unsafe ids up front (ids become session filenames).
    return validate_session_id(provided.strip()), True


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    dish_name = normalize_dish_name(require_arg(args, "dish_name"))
    ingredients = maybe_parse_json_arg(require_arg(args, "ingredients"))
    is_essential = maybe_parse_json_arg(require_arg(args, "is_essential"))

    canonical = _canonical_ingredients(ingredients, is_essential)
    ranked = _build_ranked(canonical, is_essential)
    pre_select = _coerce_pre_select(args.get("pre_select_top_n"))
    session_id, reuse = _resolve_session_id(args.get("session_id"))

    session = create_session(
        session_id=session_id,
        dish_name=dish_name,
        ranked_ingredients=ranked,
        pre_select_top_n=pre_select,
        reuse_existing=reuse,
    )
    return get_session_state(session.session_id)
