"""Tool: delete_history_entry — undo a cook registration."""

from ..repositories import history_repo
from ._common import normalize_dish_name, require_arg, tool_handler

NAME = "delete_history_entry"

SCHEMA = {
    "description": (
        "Retract the most recent cook of a dish. This is the undo for "
        "register_cooked_meal: use it when the user registered a meal by "
        "mistake or wants to reset the recency cooldown for a dish. It takes "
        "back one cook, not the dish's whole history — earlier cooks stay on "
        "record, and the retracted one remains visible through "
        "list_cooking_history. Call it again to take back the one before it."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name whose latest cook should be retracted",
        },
    },
    "required": ["dish_name"],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    raw_name = require_arg(args, "dish_name")
    name = normalize_dish_name(raw_name)
    event = history_repo.retract_latest_for_dish(name)
    if event is None:
        raise LookupError(f"'{raw_name}' not found in cooking history.")
    return (
        f"Retracted the cook of '{name}' recorded for {event.cooked_on}. "
        "It no longer counts toward the recency cooldown."
    )
