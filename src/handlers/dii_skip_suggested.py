"""Tool: dii_skip_suggested — reject the current DII suggestion."""

from ..dii import skip_suggested_ingredient
from ._common import tool_handler

NAME = "dii_skip_suggested"

SCHEMA = {
    "description": (
        "Skip/reject the currently shown ingredient suggestion in a DII "
        "session without adding it. Advances to the next suggestion."
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
    return skip_suggested_ingredient(args["session_id"])
