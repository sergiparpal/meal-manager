"""Tool: edit_dish — replace a dish's ingredient list."""

from ..repositories import dish_repo
from ._common import normalize_dish_name, normalize_ingredients, tool_handler

NAME = "edit_dish"

SCHEMA = {
    "description": (
        "Replace the ingredients of an existing dish in the catalog. This "
        "performs a full replacement, not a merge. Use when the user wants "
        "to change a recipe's ingredient list."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name to edit",
        },
        "ingredients": {
            "oneOf": [
                {
                    "type": "object",
                    "additionalProperties": {"type": "boolean"},
                    "description": "ingredient name -> true (essential) or false (optional)",
                },
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "list of ingredient names (all default to essential)",
                },
            ],
            "description": (
                "New ingredients for the dish. Either an object mapping "
                "ingredient name to boolean (true = essential, false = "
                "optional), or a plain list of ingredient names (all "
                "treated as essential)."
            ),
        },
    },
    "required": ["dish_name", "ingredients"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    raw_name = args["dish_name"]
    ingredients = normalize_ingredients(args["ingredients"])
    name = normalize_dish_name(raw_name)

    with dish_repo.lock:
        dishes = dish_repo.load()
        dish = next((d for d in dishes if d.name == name), None)
        if dish is None:
            raise LookupError(f"'{raw_name}' not found in the catalog.")

        dish.ingredients = ingredients
        dish_repo.save(dishes)

    essential_count = sum(1 for v in dish.ingredients.values() if v)
    optional_count = len(dish.ingredients) - essential_count
    return f"Updated '{name}' ingredients ({essential_count} essential, {optional_count} optional)."
