"""Tool: get_quick_shopping_list — single-ingredient unlocks."""

from ..repositories import dish_repo, fridge_repo
from ..shopping import suggest_quick_shopping
from ._common import days_since_last_cook, tool_handler

NAME = "get_quick_shopping_list"

SCHEMA = {
    "description": (
        "Get a smart shopping list of single ingredients that would unlock "
        "new dishes. For each dish missing exactly one essential ingredient, "
        "returns {missing_ingredient, unlocks_dishes, score} sorted by "
        "projected score. An empty list means no single-ingredient unlocks."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    dishes = dish_repo.load()
    fridge = fridge_repo.load_set()
    days = days_since_last_cook()

    shopping = suggest_quick_shopping(dishes, fridge, days)
    return [
        {
            "missing_ingredient": ingredient,
            "unlocks_dishes": dishes_str,
            "score": round(score, 2),
        }
        for ingredient, dishes_str, score in shopping
    ]
