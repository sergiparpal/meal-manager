"""Tool: finalize_ingredient_session — commit a DII session to fridge/dish."""

from ..dii import finalize_session
from ._common import tool_handler

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
    commit_to_fridge = args.get("commit_to_fridge", True)
    commit_to_dish = args.get("commit_to_dish", True)
    if not isinstance(commit_to_fridge, bool):
        raise ValueError("commit_to_fridge must be a boolean")
    if not isinstance(commit_to_dish, bool):
        raise ValueError("commit_to_dish must be a boolean")
    return finalize_session(
        args["session_id"],
        commit_to_fridge=commit_to_fridge,
        commit_to_dish=commit_to_dish,
    )
