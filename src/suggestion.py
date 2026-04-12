# Default weights for the blended score. Match weight covers ingredient
# coverage; time weight rewards dishes that haven't been cooked recently.
DEFAULT_MATCH_WEIGHT = 0.6
DEFAULT_TIME_WEIGHT = 0.4

# Within the ingredient match, essentials dominate; optionals only nudge.
ESSENTIAL_WEIGHT = 0.8
OPTIONAL_WEIGHT = 0.2

# Recency normalization: dishes cooked within COOLDOWN_DAYS are excluded;
# dishes cooked >= RECENCY_CAP_DAYS receive the maximum recency score.
COOLDOWN_DAYS = 2
RECENCY_CAP_DAYS = 14


def calculate_score(dish, available_ingredients, days_since_last,
                    match_weight=DEFAULT_MATCH_WEIGHT, time_weight=DEFAULT_TIME_WEIGHT):
    if days_since_last < COOLDOWN_DAYS:
        return 0

    if not dish.ingredients:
        return 0

    essentials = [ing for ing, imp in dish.ingredients.items() if imp]
    optionals = [ing for ing, imp in dish.ingredients.items() if not imp]

    available_essentials = sum(1 for ing in essentials if ing in available_ingredients)
    available_optionals = sum(1 for ing in optionals if ing in available_ingredients)

    essential_percentage = available_essentials / len(essentials) if essentials else 1.0
    optional_percentage = available_optionals / len(optionals) if optionals else 1.0

    match_percentage = essential_percentage * ESSENTIAL_WEIGHT + optional_percentage * OPTIONAL_WEIGHT

    normalized_time = min(days_since_last, RECENCY_CAP_DAYS) / float(RECENCY_CAP_DAYS)

    return match_weight * match_percentage + time_weight * normalized_time


def suggest_dishes(dishes, available_ingredients, days_since_last):
    ranking = []
    for dish in dishes:
        if not dish.can_cook_with(available_ingredients):
            continue
        days = days_since_last.get(dish.name.strip().lower(), RECENCY_CAP_DAYS)
        score = calculate_score(dish, available_ingredients, days)
        if score > 0:
            ranking.append((dish, score))
    ranking.sort(key=lambda x: x[1], reverse=True)
    return ranking
