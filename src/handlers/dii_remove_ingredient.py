"""Tool: dii_remove_ingredient — drop a selected ingredient from a session."""

from ..dii import remove_ingredient
from ._common import normalize_ingredient_name, require_arg, tool_handler

NAME = "dii_remove_ingredient"

SCHEMA = {
    "description": (
        "Remove a specific ingredient from a DII session's selected list. "
        "If the removed ingredient was essential, the response includes "
        "recalculation_needed=true signaling the agent should re-evaluate "
        "the remaining suggestions."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
        "ingredient": {
            "type": "string",
            "description": "Ingredient name to remove",
        },
    },
    "required": ["session_id", "ingredient"],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    # Resolve aliases exactly as dii_add_manual does. Without it a retired
    # spelling could be added (canonicalized on the way in) and then never
    # removed, because the removal looked for the name the user typed.
    ingredient = normalize_ingredient_name(require_arg(args, "ingredient"))
    return remove_ingredient(require_arg(args, "session_id"), ingredient)
