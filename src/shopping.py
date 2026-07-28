from typing import Any

from .suggestion import (
    DEFAULT_MATCH_WEIGHT,
    DEFAULT_TIME_WEIGHT,
    RECENCY_CAP_DAYS,
    calculate_score,
)


def suggest_quick_shopping(dishes, available_ingredients, days_since_last,
                           match_weight=DEFAULT_MATCH_WEIGHT,
                           time_weight=DEFAULT_TIME_WEIGHT,
                           max_missing=1):
    # ingredient name -> {"dishes": set[str], "still_missing": int, "score": float}.
    # The values are heterogeneous, so the inner mapping stays loose rather than
    # pulling in a TypedDict for three keys used in one function.
    best_by_ingredient: dict[str, dict[str, Any]] = {}

    for dish in dishes:
        missing_essentials = [
            ing for ing, is_essential in dish.ingredients.items()
            if is_essential and ing not in available_ingredients
        ]

        if not missing_essentials or len(missing_essentials) > max_missing:
            continue

        simulated_ingredients = available_ingredients | set(missing_essentials)
        days = days_since_last.get(dish.name, RECENCY_CAP_DAYS)
        score = calculate_score(dish, simulated_ingredients, days,
                                match_weight=match_weight, time_weight=time_weight)
        if score <= 0:
            continue

        basket = len(missing_essentials)
        for missing_ingredient in missing_essentials:
            entry = best_by_ingredient.get(missing_ingredient)
            if entry is None:
                best_by_ingredient[missing_ingredient] = {
                    "dishes": {dish.name},
                    "still_missing": basket,
                    "score": score,
                }
                continue
            # Everything a row reports must describe the same basket — the
            # cheapest way to reach a meal through this ingredient. Letting
            # ``dishes`` accumulate across every basket size while ``score`` and
            # ``still_missing`` tracked only the cheapest produced rows reading
            # "buy this one thing, unlocks 3 dishes" when the single purchase
            # unlocked one and the other two were three items away. A dish only
            # reachable from a pricier basket is still surfaced — through the
            # other ingredients that basket needs, at their true basket size.
            if basket < entry["still_missing"]:
                entry["still_missing"] = basket
                entry["score"] = score
                entry["dishes"] = {dish.name}
            elif basket == entry["still_missing"]:
                entry["dishes"].add(dish.name)
                entry["score"] = max(entry["score"], score)

    result = [
        (ing, ", ".join(sorted(data["dishes"])), data["score"],
         len(data["dishes"]), data["still_missing"])
        for ing, data in best_by_ingredient.items()
    ]
    # Cheapest basket first, then reach, then score. Reach alone is the wrong
    # lead key once max_missing > 1: an ingredient named by three dishes that
    # each need two more items unlocks nothing when bought alone, and would
    # otherwise outrank an ingredient that puts dinner on the table tonight.
    # Reach is now measured within the reported basket, so the two keys are on
    # the same scale rather than the tiebreak silently spanning every basket.
    result.sort(key=lambda x: (x[4], -x[3], -x[2], x[0]))
    return result
