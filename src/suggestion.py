# Default weights for the blended score. Match weight covers ingredient
# coverage; time weight rewards dishes that haven't been cooked recently.
DEFAULT_MATCH_WEIGHT = 0.6
DEFAULT_TIME_WEIGHT = 0.4

# Essentials are a gate, not a score. Every dish that reaches calculate_score has
# already been proven to have all of them (suggest_dishes filters with
# can_cook_with; suggest_quick_shopping simulates the one missing essential), so
# scoring them again only adds a constant with no discriminating power.
#
# The ingredient signal is therefore the number of OPTIONAL ingredients actually
# in stock, capped so a long optional list cannot dominate. This is an absolute
# count rather than an intra-dish ratio on purpose: a ratio makes declaring no
# optionals score identically to having them all, which penalizes well-described
# recipes. With a count, declaring an optional you have raises the score and
# declaring one you lack is free.
OPTIONAL_CAP = 3

# Recency normalization: dishes cooked within COOLDOWN_DAYS are excluded;
# dishes cooked >= RECENCY_CAP_DAYS receive the maximum recency score.
COOLDOWN_DAYS = 2
RECENCY_CAP_DAYS = 14


def score_components(dish, available_ingredients, days_since_last):
    """Return the ``(match, recency)`` pair behind a dish's score, or None.

    Both terms are in [0, 1] and neither depends on the blend weights, so a
    caller that ranks the same catalog under several candidate weights (the
    tuning learner) computes them once instead of per candidate. ``None``
    means the dish is gated out entirely — cooked inside the cooldown window,
    or carrying no ingredients at all — which is what ``calculate_score``
    reports as a flat 0.
    """
    if days_since_last < COOLDOWN_DAYS:
        return None

    if not dish.ingredients:
        return None

    optionals = [ing for ing, is_essential in dish.ingredients.items() if not is_essential]
    available_optionals = sum(1 for ing in optionals if ing in available_ingredients)

    match_percentage = min(available_optionals, OPTIONAL_CAP) / OPTIONAL_CAP
    normalized_time = min(days_since_last, RECENCY_CAP_DAYS) / float(RECENCY_CAP_DAYS)
    return match_percentage, normalized_time


def calculate_score(dish, available_ingredients, days_since_last,
                    match_weight=DEFAULT_MATCH_WEIGHT, time_weight=DEFAULT_TIME_WEIGHT):
    components = score_components(dish, available_ingredients, days_since_last)
    if components is None:
        return 0
    match_percentage, normalized_time = components
    return match_weight * match_percentage + time_weight * normalized_time


def suggest_dishes(dishes, available_ingredients, days_since_last,
                   match_weight=DEFAULT_MATCH_WEIGHT, time_weight=DEFAULT_TIME_WEIGHT):
    ranking = []
    for dish in dishes:
        if not dish.can_cook_with(available_ingredients):
            continue
        days = days_since_last.get(dish.name, RECENCY_CAP_DAYS)
        score = calculate_score(dish, available_ingredients, days,
                                match_weight=match_weight, time_weight=time_weight)
        if score > 0:
            ranking.append((dish, score))
    ranking.sort(key=lambda x: x[1], reverse=True)
    return ranking
