"""Tool: init_ingredient_session — create or reset a DII session."""

import json
import uuid

from ..dii import create_session, get_session_state
from ._common import (
    MAX_INGREDIENTS,
    normalize_dish_name,
    normalize_ingredient_name,
    tool_handler,
)

NAME = "init_ingredient_session"

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
            "description": "How many top ingredients to auto-select (default 3)",
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


def _maybe_parse_json(value):
    """LLMs sometimes serialize array arguments as JSON strings — accept both."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _validate_parallel_arrays(ingredients, is_essential):
    if not isinstance(ingredients, list) or not isinstance(is_essential, list):
        raise ValueError("ingredients and is_essential must be arrays")
    if len(ingredients) != len(is_essential):
        raise ValueError(
            f"ingredients ({len(ingredients)}) and is_essential "
            f"({len(is_essential)}) must have the same length"
        )
    if len(ingredients) > MAX_INGREDIENTS:
        raise ValueError(f"Too many ingredients (max {MAX_INGREDIENTS})")
    for ing in ingredients:
        normalize_ingredient_name(ing)
    for flag in is_essential:
        if not isinstance(flag, bool):
            raise ValueError("is_essential must contain boolean values")


def _build_ranked(ingredients, is_essential):
    return [
        {"ingredient": ing, "is_essential": ess}
        for ing, ess in zip(ingredients, is_essential)
    ]


def _coerce_pre_select(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 3
    if n < 0:
        raise ValueError("pre_select_top_n must be >= 0")
    return n


def _resolve_session_id(provided):
    if provided is None:
        return uuid.uuid4().hex[:16], False
    if not isinstance(provided, str) or not provided.strip():
        raise ValueError("session_id must be a non-empty string when provided")
    return provided.strip(), True


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    dish_name = normalize_dish_name(args["dish_name"])
    ingredients = _maybe_parse_json(args["ingredients"])
    is_essential = _maybe_parse_json(args["is_essential"])

    _validate_parallel_arrays(ingredients, is_essential)
    ranked = _build_ranked(ingredients, is_essential)
    pre_select = _coerce_pre_select(args.get("pre_select_top_n", 3))
    session_id, reuse = _resolve_session_id(args.get("session_id"))

    session = create_session(
        session_id=session_id,
        dish_name=dish_name,
        ranked_ingredients=ranked,
        pre_select_top_n=pre_select,
        reuse_existing=reuse,
    )
    return get_session_state(session.session_id)
