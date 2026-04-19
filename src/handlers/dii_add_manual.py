"""Tool: dii_add_manual — add a user-typed ingredient outside the funnel."""

from ..dii import add_manual_ingredient
from ._common import normalize_ingredient_name, tool_handler

NAME = "dii_add_manual"

SCHEMA = {
    "description": (
        "Manually add an ingredient to a DII session that was not in the "
        "suggestion queue. Use when the user names a custom ingredient to "
        "add directly rather than accepting the current suggestion."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
        "ingredient": {
            "type": "string",
            "description": "Ingredient name to add",
        },
        "is_essential": {
            "type": "boolean",
            "description": "True if essential, False if optional (default true)",
        },
    },
    "required": ["session_id", "ingredient"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    ingredient = normalize_ingredient_name(args["ingredient"])
    is_essential = args.get("is_essential", True)
    if not isinstance(is_essential, bool):
        raise ValueError("is_essential must be a boolean")
    return add_manual_ingredient(args["session_id"], ingredient, is_essential)
