"""Tool: add_dishes_batch — bulk-add recipes, skipping duplicates."""

from ..dish import Dish
from ..repositories import dish_repo
from ._common import (
    MAX_BATCH_SIZE,
    normalize_dish_name,
    normalize_ingredients,
    tool_handler,
)

NAME = "add_dishes_batch"

SCHEMA = {
    "description": (
        "Add multiple new recipes to the catalog in a single call. Use when "
        "the user wants to add several dishes at once, e.g. during initial "
        "catalog setup. Skips dishes that already exist. Each dish's "
        "ingredients can be an object (name -> bool) or a plain list of "
        "names (all treated as essential)."
    ),
    "type": "object",
    "properties": {
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "name of the dish",
                    },
                    "ingredients": {
                        "oneOf": [
                            {
                                "type": "object",
                                "additionalProperties": {"type": "boolean"},
                            },
                            {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        ],
                        "description": (
                            "Ingredients as object (name -> bool) or list "
                            "(all essential)."
                        ),
                    },
                },
                "required": ["name", "ingredients"],
            },
            "description": "list of dishes to add",
        },
    },
    "required": ["dishes"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    dishes_input = args["dishes"]
    if not isinstance(dishes_input, list):
        raise ValueError("dishes must be an array")
    if len(dishes_input) > MAX_BATCH_SIZE:
        raise ValueError(f"Too many dishes in batch (max {MAX_BATCH_SIZE})")

    with dish_repo.lock:
        dishes = dish_repo.load()
        existing = {d.name for d in dishes}

        added = []
        skipped = []
        for entry in dishes_input:
            if not isinstance(entry, dict):
                raise ValueError("each dish must be an object")
            name = normalize_dish_name(entry["name"])
            if name in existing:
                skipped.append(name)
                continue
            ingredients = normalize_ingredients(entry["ingredients"])
            new_dish = Dish(name=name)
            for ing, essential in ingredients.items():
                new_dish.add_ingredient(ing, essential)
            dishes.append(new_dish)
            existing.add(name)
            added.append(name)

        if added:
            dish_repo.save(dishes)

    return {"added": added, "skipped": skipped}
