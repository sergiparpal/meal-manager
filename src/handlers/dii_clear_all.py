"""Tool: dii_clear_all — reset selected ingredients in a DII session."""

from ..dii import clear_all_ingredients
from ._common import require_arg, tool_handler

NAME = "dii_clear_all"

SCHEMA = {
    "description": (
        "Clear all selected ingredients from a DII session, resetting the "
        "essential and optional lists. Sets recalculation_needed=true when "
        "something was actually cleared."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
    },
    "required": ["session_id"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    return clear_all_ingredients(require_arg(args, "session_id"))
