"""Tool: dii_add_suggested — accept the current DII suggestion."""

from ..dii import add_suggested_ingredient
from ._common import require_arg, tool_handler

NAME = "dii_add_suggested"

SCHEMA = {
    "description": (
        "Accept the currently shown ingredient suggestion in a DII session. "
        "Adds it to the selected list and reveals the next suggestion from "
        "the hidden queue."
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
    return add_suggested_ingredient(require_arg(args, "session_id"))
