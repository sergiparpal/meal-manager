"""Tool: list_dishes — every recipe in the catalog, without the cooking steps."""

from ..repositories import dish_repo
from ._common import tool_handler

NAME = "list_dishes"

SCHEMA = {
    "description": (
        "List every dish in the recipe catalog, sorted by name, as "
        "{dishes: [{name, essential, optional, has_instructions}], count}. "
        "Cooking steps are left out to keep the listing short; read them for "
        "one dish with get_dish_recipe. Use when the user asks which recipes "
        "they have saved, to check whether the catalog is empty or small "
        "before offering to help populate it (get_meal_suggestions returns [] "
        "both for an empty catalog and for one with nothing cookable), or to "
        "spot near-duplicate ingredient spellings across recipes."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    # Lock-free read, consistent with the other read-only tools.
    dishes = sorted(dish_repo.load(), key=lambda d: d.name)
    return {
        "dishes": [
            {
                "name": dish.name,
                "essential": sorted(k for k, v in dish.ingredients.items() if v),
                "optional": sorted(k for k, v in dish.ingredients.items() if not v),
                "has_instructions": dish.instructions is not None,
            }
            for dish in dishes
        ],
        "count": len(dishes),
    }
