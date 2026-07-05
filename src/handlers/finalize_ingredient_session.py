"""Tool: finalize_ingredient_session — commit a DII session to fridge/dish."""

from ..dii import finalize_session
from ._common import require_arg, tool_handler

NAME = "finalize_ingredient_session"

SCHEMA = {
    "description": (
        "Finalize a DII session, committing the selected ingredients. "
        "Can optionally add ingredients to the fridge and/or create/update "
        "the dish in the catalog. Cleans up the session afterwards."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
        "commit_to_fridge": {
            "type": "boolean",
            "description": "Add selected ingredients to fridge inventory (default true)",
        },
        "commit_to_dish": {
            "type": "boolean",
            "description": "Create/update the dish in the catalog with these ingredients (default true)",
        },
    },
    "required": ["session_id"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    # Bool validation of the commit flags lives in finalize_session (the API
    # layer), so it is not duplicated here.
    return finalize_session(
        require_arg(args, "session_id"),
        commit_to_fridge=args.get("commit_to_fridge", True),
        commit_to_dish=args.get("commit_to_dish", True),
    )
