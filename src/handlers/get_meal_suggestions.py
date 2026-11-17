"""Tool: get_meal_suggestions — ranked dishes cookable from current fridge."""

from .. import tuning
from ..repositories import dish_repo, fridge_repo, history_repo, tuning_repo
from ..suggestion import suggest_dishes
from ._common import days_since_last_cook, tool_handler

NAME = "get_meal_suggestions"

HISTORY_DAMAGED_WARNING = (
    "The cooking history file (history.json) is damaged and could not be "
    "read, so these suggestions do not know what the user cooked recently: "
    "a dish they had yesterday can come first. Tell the user. Registering a "
    "meal starts a new history and keeps the damaged file aside, as "
    "history.json.unreadable-<time>."
)

SCHEMA = {
    "description": (
        "Get ranked meal suggestions from the saved recipes, based on the "
        "current fridge contents and cooking history. Dishes cooked fewer "
        "than 2 days ago are excluded. Returns a list of {dish, score} "
        "objects sorted by descending score. An empty list means no saved "
        "recipe can be suggested right now; it is not a cue to propose a "
        "dish of your own. Call list_dishes to tell an empty catalog (offer "
        "to set up the user's usual dishes) from one where nothing is "
        "cookable. If the cooking history file is damaged, the result is "
        "{suggestions, warning} instead of the list: tell the user."
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
    suggestions = [
        {"dish": dish.name, "score": round(score, 2)}
        for dish, score in ranking
    ]
    if history_repo.damaged():
        # The history reads as empty, so no dish is cooling down and recency
        # ranks nothing. A plain list would hide that from the agent and the
        # user alike; the list shape stays as it was for every other case.
        return {"suggestions": suggestions, "warning": HISTORY_DAMAGED_WARNING}
    return suggestions
