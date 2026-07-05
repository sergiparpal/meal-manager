from .suggestion import (
    DEFAULT_MATCH_WEIGHT,
    DEFAULT_TIME_WEIGHT,
    RECENCY_CAP_DAYS,
    calculate_score,
)


def suggest_quick_shopping(dishes, available_ingredients, days_since_last,
                           match_weight=DEFAULT_MATCH_WEIGHT,
                           time_weight=DEFAULT_TIME_WEIGHT):
    best_by_ingredient = {}

    for dish in dishes:
        missing_essentials = [
            ing for ing, is_essential in dish.ingredients.items()
            if is_essential and ing not in available_ingredients
        ]

        if len(missing_essentials) != 1:
            continue

        missing_ingredient = missing_essentials[0]
        simulated_ingredients = available_ingredients | {missing_ingredient}
        days = days_since_last.get(dish.name, RECENCY_CAP_DAYS)
        score = calculate_score(dish, simulated_ingredients, days,
                                match_weight=match_weight, time_weight=time_weight)

        if score <= 0:
            continue

        if missing_ingredient not in best_by_ingredient:
            best_by_ingredient[missing_ingredient] = {"dishes": set(), "max_score": 0}
        best_by_ingredient[missing_ingredient]["dishes"].add(dish.name)
        best_by_ingredient[missing_ingredient]["max_score"] = max(
            best_by_ingredient[missing_ingredient]["max_score"],
            score
        )

    result = [
        (ing, ", ".join(sorted(data["dishes"])), data["max_score"])
        for ing, data in best_by_ingredient.items()
    ]
    result.sort(key=lambda x: x[2], reverse=True)
    return result
