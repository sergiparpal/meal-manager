"""Tool: get_meal_suggestions — ranked dishes cookable from current fridge."""

from .. import tuning
from ..repositories import dish_repo, fridge_repo, tuning_repo
from ..suggestion import suggest_dishes
from ._common import days_since_last_cook, tool_handler

NAME = "get_meal_suggestions"

SCHEMA = {
    "description": (
        "Get ranked meal suggestions from the saved recipes, based on the "
        "current fridge contents and cooking history. Dishes cooked fewer "
        "than 2 days ago are excluded. Returns a list of {dish, score} "
        "objects sorted by descending score. An empty list means no saved "
        "recipe can be suggested right now; it is not a cue to propose a "
        "dish of your own. Call list_dishes to tell an empty catalog (offer "
        "to set up the user's usual dishes) from one where nothing is "
        "cookable."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    dishes = dish_repo.load()
    fridge = fridge_repo.load_set()
    days = days_since_last_cook()

    match_weight, time_weight = tuning.deployed_weights(tuning_repo.load())
    ranking = suggest_dishes(dishes, fridge, days,
                             match_weight=match_weight, time_weight=time_weight)
    return [
        {"dish": dish.name, "score": round(score, 2)}
        for dish, score in ranking
    ]
