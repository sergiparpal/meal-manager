"""Tool: get_missing_for_dish — what a specific dish still needs."""

from ..repositories import dish_repo, fridge_repo
from ._common import normalize_dish_name, require_arg, tool_handler

NAME = "get_missing_for_dish"

SCHEMA = {
    "description": (
        "Report what a specific dish is still missing from the fridge. Returns "
        "{dish, cookable, missing_essential, missing_optional}. Use when the "
        "user asks whether they can make a named dish, or what they would need "
        "to buy for it."
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


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    raw_name = require_arg(args, "dish_name")
    name = normalize_dish_name(raw_name)

    dishes = dish_repo.load()
    dish = next((d for d in dishes if d.name == name), None)
    if dish is None:
        raise LookupError(f"'{raw_name}' is not in the recipe catalog.")

    fridge = fridge_repo.load_set()
    missing_essential = sorted(
        ing for ing, is_essential in dish.ingredients.items()
        if is_essential and ing not in fridge
    )
    missing_optional = sorted(
        ing for ing, is_essential in dish.ingredients.items()
        if not is_essential and ing not in fridge
    )

    return {
        "dish": dish.name,
        "cookable": not missing_essential,
        "missing_essential": missing_essential,
        "missing_optional": missing_optional,
    }
