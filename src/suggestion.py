def calculate_score(dish, available_ingredients, days_since_last,
                    match_weight=0.6, time_weight=0.4):
    if days_since_last < 2:
        return 0

    if not dish.ingredients:
        return 0

    else:
        essentials = [ing for ing, imp in dish.ingredients.items() if imp]
        optionals = [ing for ing, imp in dish.ingredients.items() if not imp]

        available_essentials = sum(1 for ing in essentials if ing in available_ingredients)
        available_optionals = sum(1 for ing in optionals if ing in available_ingredients)

        essential_percentage = available_essentials / len(essentials) if essentials else 1.0
        optional_percentage = available_optionals / len(optionals) if optionals else 1.0

        match_percentage = essential_percentage * 0.8 + optional_percentage * 0.2

    normalized_time = min(days_since_last, 14) / 14.0

    return match_weight * match_percentage + time_weight * normalized_time


def suggest_dishes(dishes, available_ingredients, days_since_last):
    ranking = []
    for dish in dishes:
        if not dish.can_cook_with(available_ingredients):
            continue
        days = days_since_last.get(dish.name.strip().lower(), 14)
        score = calculate_score(dish, available_ingredients, days)
        if score > 0:
            ranking.append((dish, score))
    ranking.sort(key=lambda x: x[1], reverse=True)
    return ranking
