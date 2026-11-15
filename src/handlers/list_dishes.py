"""Tool: list_dishes — every recipe in the catalog, without the cooking steps."""

from .. import unreadable_json
from ..repositories import dish_repo
from ._common import tool_handler

NAME = "list_dishes"

DAMAGED_WARNING = (
    "The saved recipes file (dishes.json) is damaged and could not be read, so "
    "this list is empty even if the user has recipes. Tell the user. Saving a "
    "recipe now first keeps the damaged file aside, as "
    "dishes.json.unreadable-<time>, so what it held is not lost."
)

SCHEMA = {
    "description": (
        "List every dish in the recipe catalog, sorted by name, as "
        "{dishes: [{name, essential, optional, has_instructions}], count}. "
        "Cooking steps are left out to keep the listing short; read them for "
        "one dish with get_dish_recipe. Use when the user asks which recipes "
        "they have saved, to check whether the catalog is empty or small "
        "before offering to help populate it (get_meal_suggestions returns [] "
        "both for an empty catalog and for one with nothing cookable), or to "
        "spot near-duplicate ingredient spellings across recipes. If the saved "
        "file is damaged, the list is empty and a 'warning' says so: tell "
        "the user, and don't say they have no recipes."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    # Lock-free read, consistent with the other read-only tools.
    dishes = sorted(dish_repo.load(), key=lambda d: d.name)
    result = {
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
    if unreadable_json(dish_repo.path):
        # The repository reads a damaged file as an empty catalog. Without
        # this, the agent told the user they had no recipes (E2E, G1).
        result["warning"] = DAMAGED_WARNING
    return result
