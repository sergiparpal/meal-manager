"""Tool: add_dish — add a new recipe to the catalog."""

from ..dish import Dish
from ..repositories import dish_repo
from ._common import normalize_dish_name, normalize_ingredients, tool_handler

NAME = "add_dish"

SCHEMA = {
    "description": (
        "Add a new recipe to the catalog. Use when the user wants to teach "
        "the system a new dish. The ingredients dict maps ingredient name to "
        "a boolean: true = essential, false = optional."
    ),
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "name of the new dish",
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
                "Ingredients for the dish. Either an object mapping ingredient "
                "name to boolean (true = essential, false = optional), or a "
                "plain list of ingredient names (all treated as essential)."
            ),
        },
    },
    "required": ["name", "ingredients"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    ingredients = normalize_ingredients(args["ingredients"])
    name = normalize_dish_name(args["name"])

    with dish_repo.lock:
        dishes = dish_repo.load()
        if any(d.name == name for d in dishes):
            raise ValueError(f"a dish called '{name}' already exists in the catalog.")

        new_dish = Dish(name=name)
        for ing, essential in ingredients.items():
            new_dish.add_ingredient(ing, essential)
        dishes.append(new_dish)
        dish_repo.save(dishes)

    essential_count = sum(1 for v in new_dish.ingredients.values() if v)
    optional_count = len(new_dish.ingredients) - essential_count
    return f"Added '{name}' to the catalog ({essential_count} essential, {optional_count} optional ingredients)."
