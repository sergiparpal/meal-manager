"""Tool: set_dish_instructions — attach or clear cooking steps for a dish."""

from ..dish import MAX_INSTRUCTIONS_LENGTH, Dish
from ..repositories import dish_repo
from ._common import normalize_dish_name, require_arg, tool_handler

NAME = "set_dish_instructions"

SCHEMA = {
    "description": (
        "Set or clear the cooking instructions for a dish already in the "
        "catalog. Free-form text — steps, timings, temperatures, whatever the "
        "user dictates — up to "
        f"{MAX_INSTRUCTIONS_LENGTH:,} characters. Pass null (or a blank "
        "string) to clear the instructions. Replaces any existing text rather "
        "than appending to it. Read them back with get_dish_recipe."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name from the catalog",
        },
        "instructions": {
            "type": ["string", "null"],
            "description": (
                "The cooking steps. null or blank clears whatever is stored."
            ),
        },
    },
    "required": ["dish_name", "instructions"],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    raw_name = require_arg(args, "dish_name")
    # ``require_arg`` tests membership, not truthiness, so an explicit null
    # (the documented way to clear) is accepted while an absent key is not.
    raw_instructions = require_arg(args, "instructions")
    name = normalize_dish_name(raw_name)

    with dish_repo.lock:
        dishes = dish_repo.load()
        dish = next((d for d in dishes if d.name == name), None)
        if dish is None:
            raise LookupError(f"'{raw_name}' is not in the recipe catalog.")

        # Validate through Dish so the length/blank rules live in exactly one
        # place instead of being restated at the tool boundary.
        dish.instructions = Dish.normalize_instructions(raw_instructions)
        dish_repo.save(dishes)

    return {
        "dish_name": dish.name,
        "instructions": dish.instructions,
        "cleared": dish.instructions is None,
    }
