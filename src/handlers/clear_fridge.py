"""Tool: clear_fridge — empty the fridge inventory."""

from ..repositories import fridge_repo
from ._common import tool_handler

NAME = "clear_fridge"

SCHEMA = {
    "description": (
        "Empty the fridge completely. Use when the user wants to reset the "
        "fridge inventory, e.g. after a move or a full cleanout."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    with fridge_repo.lock:
        fridge = fridge_repo.load()
        count = len(fridge)
        fridge_repo.save([])

    if count == 0:
        return "The fridge was already empty."
    return f"Cleared the fridge ({count} ingredient{'s' if count != 1 else ''} removed)."
