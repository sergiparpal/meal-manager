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
    best_by_ingredient = {}

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

        for missing_ingredient in missing_essentials:
            entry = best_by_ingredient.setdefault(
                missing_ingredient,
                {"dishes": set(), "max_score": 0, "still_missing": len(missing_essentials)},
            )
            entry["dishes"].add(dish.name)
            entry["max_score"] = max(entry["max_score"], score)
            entry["still_missing"] = min(entry["still_missing"], len(missing_essentials))

    result = [
        (ing, ", ".join(sorted(data["dishes"])), data["max_score"],
         len(data["dishes"]), data["still_missing"])
        for ing, data in best_by_ingredient.items()
    ]
    result.sort(key=lambda x: (-x[3], -x[2], x[0]))
    return result
