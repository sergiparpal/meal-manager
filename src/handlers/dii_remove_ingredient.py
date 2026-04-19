"""Tool: dii_remove_ingredient — drop a selected ingredient from a session."""

from ..dii import remove_ingredient
from ._common import tool_handler

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


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    return remove_ingredient(args["session_id"], args["ingredient"])
