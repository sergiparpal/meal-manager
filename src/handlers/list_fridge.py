"""Tool: list_fridge — return current fridge contents."""

from ..repositories import fridge_repo
from ._common import tool_handler

NAME = "list_fridge"

SCHEMA = {
    "description": (
        "Return the current contents of the fridge as "
        "{in_stock: {ingredient: portion_count}, out_of_stock: [ingredient]}. "
        "A portion count of null means a pantry staple that never runs out "
        "(salt, oil, spices); a number is roughly how many dishes' worth is on "
        "hand. 'out_of_stock' lists ingredients the user is known to have run "
        "out of, which is more informative than never having had them. Use "
        "when the user asks what they have in the fridge or wants to see the "
        "inventory."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    fridge = fridge_repo.load()
    return {
        "in_stock": {k: v for k, v in sorted(fridge.items()) if v is None or v > 0},
        "out_of_stock": sorted(k for k, v in fridge.items() if v == 0),
    }
