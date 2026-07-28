"""Tool: get_quick_shopping_list — near-miss ingredient unlocks."""

from .. import tuning
from ..repositories import dish_repo, fridge_repo, tuning_repo
from ..shopping import suggest_quick_shopping
from ._common import days_since_last_cook, tool_handler

NAME = "get_quick_shopping_list"

SCHEMA = {
    "description": (
        "Get a smart shopping list of ingredients that would unlock new dishes. "
        "For each dish missing at most 'max_missing' essential ingredients, "
        "returns {missing_ingredient, unlocks_dishes, unlocks_count, "
        "still_missing, score}. 'still_missing' is the size of the smallest "
        "basket that unlocks a dish through this ingredient — 1 means buying it "
        "alone is enough. Every other field describes that same cheapest basket: "
        "'unlocks_dishes' and 'unlocks_count' cover the dishes it actually "
        "reaches, and 'score' is the best of those dishes — never a meal the "
        "basket cannot buy. Rows are sorted by basket size first, so genuine "
        "one-item unlocks lead, then by how many dishes are reached, then by "
        "projected score. An empty list means no unlocks at that threshold."
    ),
    "type": "object",
    "properties": {
        "max_missing": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": (
                "How many essential ingredients a dish may be short of and still "
                "appear. 1 (the default) lists only single-ingredient unlocks. "
                "Raise to 2-3 when the fridge is nearly empty and the default "
                "returns nothing."
            ),
        },
    },
    "required": [],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    # ``tool_handler`` validates the argument keys against SCHEMA before this
    # runs, and that check rejects a non-dict outright, so ``args`` is a dict.
    max_missing = args.get("max_missing", 1)
    if isinstance(max_missing, bool) or not isinstance(max_missing, int):
        raise ValueError("max_missing must be an integer")
    if not 1 <= max_missing <= 5:
        raise ValueError("max_missing must be between 1 and 5")

    dishes = dish_repo.load()
    fridge = fridge_repo.load_set()
    days = days_since_last_cook()

    match_weight, time_weight = tuning.deployed_weights(tuning_repo.load())
    shopping = suggest_quick_shopping(dishes, fridge, days,
                                      match_weight=match_weight, time_weight=time_weight,
                                      max_missing=max_missing)
    return [
        {
            "missing_ingredient": ingredient,
            "unlocks_dishes": dishes_str,
            "unlocks_count": count,
            "still_missing": still_missing,
            "score": round(score, 2),
        }
        for ingredient, dishes_str, score, count, still_missing in shopping
    ]
