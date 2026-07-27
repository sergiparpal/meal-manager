"""Tool: get_dish_recipe — full recipe for one dish, instructions included."""

from ..repositories import dish_repo
from ._common import normalize_dish_name, require_arg, tool_handler

NAME = "get_dish_recipe"

SCHEMA = {
    "description": (
        "Return the complete recipe for one dish: its essential ingredients, "
        "its optional ingredients, and its cooking instructions (null when "
        "none have been recorded). Use when the user asks how to cook "
        "something, what goes into a dish, or to read back the steps."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name from the catalog",
        },
    },
    "required": ["dish_name"],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    raw_name = require_arg(args, "dish_name")
    name = normalize_dish_name(raw_name)

    # Lock-free read, consistent with the other read-only tools.
    dish = next((d for d in dish_repo.load() if d.name == name), None)
    if dish is None:
        raise LookupError(f"'{raw_name}' is not in the recipe catalog.")

    return {
        "dish_name": dish.name,
        "essential": sorted(k for k, v in dish.ingredients.items() if v),
        "optional": sorted(k for k, v in dish.ingredients.items() if not v),
        "instructions": dish.instructions,
    }
