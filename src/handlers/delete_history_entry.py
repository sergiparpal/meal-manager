"""Tool: delete_history_entry — undo a cook registration."""

from ..repositories import history_repo
from ._common import normalize_dish_name, tool_handler

NAME = "delete_history_entry"

SCHEMA = {
    "description": (
        "Remove a dish from the cooking history. This is the undo for "
        "register_cooked_meal. Use when the user registered a meal by "
        "mistake or wants to reset the recency cooldown for a dish."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name to remove from history",
        },
    },
    "required": ["dish_name"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    raw_name = args["dish_name"]
    name = normalize_dish_name(raw_name)
    if not history_repo.remove_entry(name):
        raise LookupError(f"'{raw_name}' not found in cooking history.")
    return f"Removed '{name}' from cooking history."
