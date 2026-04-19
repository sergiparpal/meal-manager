"""Tool: list_fridge — return current fridge contents."""

from ..repositories import fridge_repo
from ._common import tool_handler

NAME = "list_fridge"

SCHEMA = {
    "description": (
        "Return the current contents of the fridge as a list of ingredient "
        "strings. Use when the user asks what they have in the fridge or "
        "wants to see the inventory."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    return fridge_repo.load()
