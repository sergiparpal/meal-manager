"""Tool: get_meal_suggestions — ranked dishes cookable from current fridge."""

from ..repositories import dish_repo, fridge_repo
from ..suggestion import suggest_dishes
from ._common import days_since_last_cook, tool_handler

NAME = "get_meal_suggestions"

SCHEMA = {
    "description": (
        "Get ranked meal suggestions based on the current fridge contents "
        "and cooking history. Dishes cooked fewer than 2 days ago are "
        "excluded. Returns a list of {dish, score} objects sorted by "
        "descending score. An empty list means no dishes can be suggested."
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

    ranking = suggest_dishes(dishes, fridge, days)
    return [
        {"dish": dish.name, "score": round(score, 2)}
        for dish, score in ranking
    ]
