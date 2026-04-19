"""Tool: dii_get_state — read DII session state without mutating it."""

from ..dii import get_session_state
from ._common import tool_handler

NAME = "dii_get_state"

SCHEMA = {
    "description": (
        "Get the current state of a DII session without modifying it. "
        "Returns the full session state including next_actions and instructions "
        "to guide the interaction flow."
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
    return get_session_state(args["session_id"])
