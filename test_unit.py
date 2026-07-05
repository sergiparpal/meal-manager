"""Unit tests for domain logic modules.

These tests are stateless — they test pure functions and dataclass behavior
without touching data files on disk.

Usage:
    python3 test_unit.py
"""

import copy
import importlib
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: make relative imports work when running standalone.
# ---------------------------------------------------------------------------

_PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_PLUGIN_DIR.parent))
_pkg = importlib.import_module(_PLUGIN_DIR.name)

_dish_mod = importlib.import_module(".src.dish", _PLUGIN_DIR.name)
_suggestion_mod = importlib.import_module(".src.suggestion", _PLUGIN_DIR.name)
_shopping_mod = importlib.import_module(".src.shopping", _PLUGIN_DIR.name)
_tuning_mod = importlib.import_module(".src.tuning", _PLUGIN_DIR.name)
_handlers_common = importlib.import_module(".src.handlers._common", _PLUGIN_DIR.name)

Dish = _dish_mod.Dish
calculate_score = _suggestion_mod.calculate_score
suggest_dishes = _suggestion_mod.suggest_dishes
suggest_quick_shopping = _shopping_mod.suggest_quick_shopping
tuning = _tuning_mod
_normalize_ingredients = _handlers_common.normalize_ingredients

# ---------------------------------------------------------------------------
# Assertion helper (same style as test_integration.py)
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        msg = f"  FAIL  {label}"
        if detail:
            msg += f"  -- {detail}"
        print(msg)


# ---------------------------------------------------------------------------
# Dish tests
# ---------------------------------------------------------------------------


def test_dish_normalize_ingredient():
    print("\n-- Dish.normalize_ingredient --")
    check("strips and lowercases", Dish.normalize_ingredient("  Rice  ") == "rice")
    check("empty string", Dish.normalize_ingredient("   ") == "")
    check("already normalized", Dish.normalize_ingredient("tomato") == "tomato")


def test_dish_normalize_name():
    print("\n-- Dish.normalize_name --")
    check("strips and lowercases", Dish.normalize_name("  Pasta CARBONARA  ") == "pasta carbonara")
    check("empty string", Dish.normalize_name("   ") == "")
    check("already normalized", Dish.normalize_name("tortilla") == "tortilla")


def test_dish_can_cook_with():
    print("\n-- Dish.can_cook_with --")
    dish = Dish(name="test")
    dish.ingredients = {"rice": True, "chicken": True, "pepper": False}

    check("all essentials available", dish.can_cook_with({"rice", "chicken", "pepper"}))
    check("essentials only", dish.can_cook_with({"rice", "chicken"}))
    check("missing essential", not dish.can_cook_with({"rice", "pepper"}))
    check("empty fridge", not dish.can_cook_with(set()))
    check("extra ingredients ok", dish.can_cook_with({"rice", "chicken", "pepper", "salt"}))


def test_dish_can_cook_with_no_ingredients():
    print("\n-- Dish.can_cook_with (no ingredients) --")
    dish = Dish(name="test")
    check("no ingredients = can cook", dish.can_cook_with(set()))


def test_dish_can_cook_with_only_optional():
    print("\n-- Dish.can_cook_with (only optional) --")
    dish = Dish(name="test")
    dish.ingredients = {"salt": False, "pepper": False}
    check("only optionals = can cook", dish.can_cook_with(set()))


def test_dish_to_dict():
    print("\n-- Dish.to_dict --")
    dish = Dish(name="pasta")
    dish.ingredients = {"pasta": True, "sauce": False}
    d = dish.to_dict()
    check("has name", d["name"] == "pasta")
    check("has ingredients", d["ingredients"] == {"pasta": True, "sauce": False})
    check("no prep_time", "prep_time" not in d)


def test_dish_from_dict():
    print("\n-- Dish.from_dict --")
    # Without prep_time
    dish = Dish.from_dict({"name": "Pasta", "ingredients": {"Rice": True}})
    check("name lowercased", dish.name == "pasta")
    check("ingredient lowercased", "rice" in dish.ingredients)

    # With prep_time (backward compat — silently ignored)
    dish2 = Dish.from_dict({"name": "Soup", "prep_time": 20, "ingredients": {"water": True}})
    check("prep_time ignored", dish2.name == "soup")
    check("ingredients loaded", dish2.ingredients == {"water": True})

    # Missing ingredients
    dish3 = Dish.from_dict({"name": "Empty"})
    check("missing ingredients = empty dict", dish3.ingredients == {})


def test_dish_from_dict_invalid():
    print("\n-- Dish.from_dict (invalid) --")
    try:
        Dish.from_dict({"name": "Soup", "ingredients": []})
        check("rejects non-dict ingredients", False, "should have raised ValueError")
    except ValueError:
        check("rejects non-dict ingredients", True)

    try:
        Dish.from_dict({"name": "   ", "ingredients": {}})
        check("rejects blank name", False, "should have raised ValueError")
    except ValueError:
        check("rejects blank name", True)


def test_dish_add_ingredient_validation():
    print("\n-- Dish.add_ingredient (validation) --")
    dish = Dish(name="test")

    try:
        dish.add_ingredient("   ", True)
        check("rejects blank ingredient", False, "should have raised ValueError")
    except ValueError:
        check("rejects blank ingredient", True)

    try:
        dish.add_ingredient("salt", "yes")
        check("rejects non-bool flags", False, "should have raised ValueError")
    except ValueError:
        check("rejects non-bool flags", True)


def test_dish_add_ingredient():
    print("\n-- Dish.add_ingredient --")
    dish = Dish(name="test")
    dish.add_ingredient("  RICE  ", True)
    dish.add_ingredient("Pepper", False)
    check("rice normalized", "rice" in dish.ingredients)
    check("rice is essential", dish.ingredients["rice"] is True)
    check("pepper normalized", "pepper" in dish.ingredients)
    check("pepper is optional", dish.ingredients["pepper"] is False)


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


def test_calculate_score_basic():
    print("\n-- calculate_score (basic) --")
    dish = Dish(name="test")
    dish.ingredients = {"rice": True, "chicken": True}

    score = calculate_score(dish, {"rice", "chicken"}, 14)
    check("positive score", score > 0, f"got {score}")
    check("max score = 1.0", abs(score - 1.0) < 0.001, f"got {score}")


def test_calculate_score_cooldown():
    print("\n-- calculate_score (cooldown) --")
    dish = Dish(name="test")
    dish.ingredients = {"rice": True}

    check("0 days = blocked", calculate_score(dish, {"rice"}, 0) == 0)
    check("1 day = blocked", calculate_score(dish, {"rice"}, 1) == 0)
    check("2 days = allowed", calculate_score(dish, {"rice"}, 2) > 0)


def test_calculate_score_no_ingredients():
    print("\n-- calculate_score (no ingredients) --")
    dish = Dish(name="test")
    check("empty ingredients = 0", calculate_score(dish, set(), 14) == 0)


def test_calculate_score_partial_ingredients():
    print("\n-- calculate_score (partial) --")
    dish = Dish(name="test")
    dish.ingredients = {"rice": True, "chicken": True, "pepper": False}

    full = calculate_score(dish, {"rice", "chicken", "pepper"}, 14)
    without_optional = calculate_score(dish, {"rice", "chicken"}, 14)
    check("optional increases score", full > without_optional, f"{full} > {without_optional}")


def test_calculate_score_recency_scaling():
    print("\n-- calculate_score (recency scaling) --")
    dish = Dish(name="test")
    dish.ingredients = {"rice": True}

    score_2 = calculate_score(dish, {"rice"}, 2)
    score_7 = calculate_score(dish, {"rice"}, 7)
    score_14 = calculate_score(dish, {"rice"}, 14)
    score_30 = calculate_score(dish, {"rice"}, 30)

    check("more days = higher score", score_2 < score_7 < score_14, f"{score_2}, {score_7}, {score_14}")
    check("14+ days capped", abs(score_14 - score_30) < 0.001, f"{score_14} vs {score_30}")


# ---------------------------------------------------------------------------
# suggest_dishes tests
# ---------------------------------------------------------------------------


def test_suggest_dishes_basic():
    print("\n-- suggest_dishes (basic) --")
    d1 = Dish(name="rice bowl")
    d1.ingredients = {"rice": True}
    d2 = Dish(name="chicken soup")
    d2.ingredients = {"chicken": True, "water": True}

    fridge = {"rice"}
    days = {"rice bowl": 14, "chicken soup": 14}

    result = suggest_dishes([d1, d2], fridge, days)
    check("only rice bowl suggested", len(result) == 1)
    check("correct dish", result[0][0].name == "rice bowl")


def test_suggest_dishes_excludes_recent():
    print("\n-- suggest_dishes (excludes recent) --")
    d1 = Dish(name="rice bowl")
    d1.ingredients = {"rice": True}

    result = suggest_dishes([d1], {"rice"}, {"rice bowl": 1})
    check("cooked yesterday = excluded", len(result) == 0)


def test_suggest_dishes_default_recency():
    print("\n-- suggest_dishes (default recency) --")
    d1 = Dish(name="new dish")
    d1.ingredients = {"rice": True}

    result = suggest_dishes([d1], {"rice"}, {})
    check("new dish suggested", len(result) == 1)


# ---------------------------------------------------------------------------
# suggest_quick_shopping tests
# ---------------------------------------------------------------------------


def test_suggest_quick_shopping_basic():
    print("\n-- suggest_quick_shopping (basic) --")
    d1 = Dish(name="omelette")
    d1.ingredients = {"eggs": True, "oil": True}

    fridge = {"oil"}
    result = suggest_quick_shopping([d1], fridge, {})
    check("one suggestion", len(result) == 1)
    check("missing eggs", result[0][0] == "eggs")
    check("unlocks omelette", "omelette" in result[0][1].lower())


def test_suggest_quick_shopping_two_missing():
    print("\n-- suggest_quick_shopping (two missing) --")
    d1 = Dish(name="omelette")
    d1.ingredients = {"eggs": True, "oil": True}

    result = suggest_quick_shopping([d1], set(), {})
    check("no suggestion when 2 missing", len(result) == 0)


def test_suggest_quick_shopping_groups_by_ingredient():
    print("\n-- suggest_quick_shopping (groups by ingredient) --")
    d1 = Dish(name="fried eggs")
    d1.ingredients = {"eggs": True, "oil": True}
    d2 = Dish(name="omelette")
    d2.ingredients = {"eggs": True, "butter": True}

    fridge = {"oil", "butter"}
    result = suggest_quick_shopping([d1, d2], fridge, {})
    check("eggs unlocks both", len(result) == 1)
    check("ingredient is eggs", result[0][0] == "eggs")


# ---------------------------------------------------------------------------
# _normalize_ingredients tests
# ---------------------------------------------------------------------------


def test_normalize_ingredients_dict():
    print("\n-- _normalize_ingredients (dict) --")
    result = _normalize_ingredients({"Rice": True, "  Chicken ": False})
    check("keys normalized", result == {"rice": True, "chicken": False})


def test_normalize_ingredients_list():
    print("\n-- _normalize_ingredients (list) --")
    result = _normalize_ingredients(["Rice", "Chicken"])
    check("all essential", result == {"rice": True, "chicken": True})


def test_normalize_ingredients_json_string_dict():
    print("\n-- _normalize_ingredients (JSON string dict) --")
    result = _normalize_ingredients('{"Rice": true, "Chicken": false}')
    check("parsed from string", result == {"rice": True, "chicken": False})


def test_normalize_ingredients_json_string_list():
    print("\n-- _normalize_ingredients (JSON string list) --")
    result = _normalize_ingredients('["Rice", "Chicken"]')
    check("parsed from string", result == {"rice": True, "chicken": True})


def test_normalize_ingredients_invalid():
    print("\n-- _normalize_ingredients (invalid) --")
    try:
        _normalize_ingredients(42)
        check("rejects int", False, "should have raised ValueError")
    except ValueError:
        check("rejects int", True)

    try:
        _normalize_ingredients("not json")
        check("rejects bad string", False, "should have raised ValueError")
    except ValueError:
        check("rejects bad string", True)


# ---------------------------------------------------------------------------
# Online weight tuning (src/tuning.py)
# ---------------------------------------------------------------------------


def test_tuning_initial_state():
    print("\n-- tuning.initialize_state --")
    state = tuning.initialize_state()
    check("deploys prior w", state["deployed_match_weight"] == tuning.PRIOR_W)
    check("time weight complements availability",
          abs(state["deployed_match_weight"] + state["deployed_time_weight"] - 1.0) < 1e-9)
    check("zero observations", state["observations"] == 0)
    check("all candidates in band",
          all(tuning.BAND[0] <= w <= tuning.BAND[1] for w in state["candidates"]))
    check("anchor is the initial argmax",
          max(state["candidates"], key=lambda w: tuning._mean(state, tuning._key(w))) == tuning.PRIOR_W)


def test_tuning_deployed_weights_fallback():
    print("\n-- tuning.deployed_weights (fallback) --")
    mw, tw = tuning.deployed_weights({})
    check("falls back to prior blend", mw == tuning.PRIOR_W and abs(mw + tw - 1.0) < 1e-9)


def test_tuning_validate_state():
    print("\n-- tuning.validate_state --")
    good = tuning.initialize_state()
    check("accepts a well-formed state", tuning.validate_state(good) is good)
    check("rejects non-dict", tuning.validate_state("nope")["observations"] == 0)
    check("rejects missing fields", tuning.validate_state({"version": 1})["observations"] == 0)


def test_tuning_compute_rewards_not_cookable():
    print("\n-- tuning.compute_rewards (cooked dish not cookable) --")
    d1 = Dish(name="needs eggs")
    d1.ingredients = {"eggs": True}
    d2 = Dish(name="rice")
    d2.ingredients = {"rice": True}
    rewards = tuning.compute_rewards("needs eggs", [d1, d2], {"rice"}, {}, tuning.CANDIDATES)
    check("returns None (degenerate)", rewards is None)


def test_tuning_compute_rewards_single_dish():
    print("\n-- tuning.compute_rewards (N < 2) --")
    d1 = Dish(name="rice")
    d1.ingredients = {"rice": True}
    rewards = tuning.compute_rewards("rice", [d1], {"rice"}, {}, tuning.CANDIDATES)
    check("returns None (no ranking signal)", rewards is None)


def test_tuning_compute_rewards_top_rank():
    print("\n-- tuning.compute_rewards (top rank -> 1.0) --")
    top = Dish(name="top dish")
    top.ingredients = {"a": True}
    low = Dish(name="low dish")
    low.ingredients = {"b": True, "x": False}
    dishes = [top, low]
    fridge = {"a", "b"}  # optional x absent -> low dish scores strictly lower
    days = {"top dish": 14, "low dish": 2}
    rewards = tuning.compute_rewards("top dish", dishes, fridge, days, tuning.CANDIDATES)
    check("returns a reward dict", rewards is not None)
    check("winning candidate gets reward 1.0",
          abs(rewards[tuning._key(0.60)] - 1.0) < 1e-9, f"got {rewards}")


def test_tuning_apply_update_pure():
    print("\n-- tuning.apply_update (pure, non-mutating) --")
    state = tuning.initialize_state()
    snapshot = copy.deepcopy(state)
    rewards = {tuning._key(w): 1.0 for w in tuning.CANDIDATES}
    new_state = tuning.apply_update(state, rewards)
    check("input left unchanged", state == snapshot)
    check("observations incremented", new_state["observations"] == 1)
    check("count discounted then +1",
          abs(new_state["C"][tuning._key(0.60)]
              - (tuning.GAMMA * snapshot["C"][tuning._key(0.60)] + 1)) < 1e-9)


def _favor_high_w(state, times):
    """Apply a reward monotone in w so the top candidate (0.80) clearly wins."""
    rewards = {tuning._key(w): (w - 0.40) / 0.40 for w in tuning.CANDIDATES}
    for _ in range(times):
        state = tuning.apply_update(state, rewards)
    return tuning.select_deployed(state)


def test_tuning_cold_start():
    print("\n-- tuning.select_deployed (cold start) --")
    state = _favor_high_w(tuning.initialize_state(), tuning.MIN_OBSERVATIONS - 5)
    check("stays at prior below MIN_OBSERVATIONS",
          state["deployed_match_weight"] == tuning.PRIOR_W,
          f"got {state['deployed_match_weight']}")


def test_tuning_shift_after_warmup():
    print("\n-- tuning.select_deployed (shifts once warm) --")
    state = _favor_high_w(tuning.initialize_state(), tuning.MIN_OBSERVATIONS + 20)
    check("shifts upward after MIN_OBSERVATIONS",
          state["deployed_match_weight"] > tuning.PRIOR_W,
          f"got {state['deployed_match_weight']}")
    check("stays within band",
          tuning.BAND[0] <= state["deployed_match_weight"] <= tuning.BAND[1])
    check("weights still sum to 1.0",
          abs(state["deployed_match_weight"] + state["deployed_time_weight"] - 1.0) < 1e-9)


def test_tuning_hysteresis():
    print("\n-- tuning.select_deployed (hysteresis) --")
    state = tuning.initialize_state()
    state["observations"] = tuning.MIN_OBSERVATIONS + 5
    for w in tuning.CANDIDATES:
        key = tuning._key(w)
        state["C"][key] = 1.0
        state["S"][key] = 0.50
    state["S"][tuning._key(0.60)] = 0.60   # current deployed mean
    state["S"][tuning._key(0.65)] = 0.62   # best, but only +0.02 (< margin 0.03)
    result = tuning.select_deployed(state)
    check("sub-margin advantage does not switch deploy",
          result["deployed_match_weight"] == 0.60,
          f"got {result['deployed_match_weight']}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def test_dish_ingredient_keys_normalized_on_construction():
    print("\n-- Dish: ingredient keys normalized on direct construction --")
    d = Dish(name="Soup", ingredients={"  Tomato ": True, "BASIL": False})
    check("ingredient keys stripped+lowercased",
          set(d.ingredients.keys()) == {"tomato", "basil"}, f"got {list(d.ingredients)}")
    check("can_cook_with matches normalized fridge", d.can_cook_with({"tomato"}) is True)


def test_normalize_ingredients_empty_rejected():
    print("\n-- normalize_ingredients: empty rejected --")
    for value in ([], {}, "[]", "{}"):
        try:
            _normalize_ingredients(value)
            check(f"rejects empty {value!r}", False, "should have raised ValueError")
        except ValueError:
            check(f"rejects empty {value!r}", True)


def test_normalize_ingredients_dedup_under_limit():
    print("\n-- normalize_ingredients: dedupes before applying the cap --")
    # A list with many repeats that collapses to a single unique key must be
    # accepted (the cap applies to the de-duplicated result, not the raw list).
    result = _normalize_ingredients(["tomato"] * 150)
    check("repeats collapse to one ingredient", result == {"tomato": True}, f"got {result}")
    # Genuinely too many distinct ingredients is still rejected.
    try:
        _normalize_ingredients([f"ing{i}" for i in range(101)])
        check("rejects >100 distinct ingredients", False, "should have raised")
    except ValueError:
        check("rejects >100 distinct ingredients", True)


def test_tuning_deployed_weights_clamps_out_of_band():
    print("\n-- tuning.deployed_weights (clamp + re-derive) --")
    mw, tw = tuning.deployed_weights(
        {"deployed_match_weight": 1.5, "deployed_time_weight": 0.4}
    )
    check("clamps match weight to band upper bound", mw == tuning.BAND[1], f"got {mw}")
    check("re-derives complementary time weight", abs(mw + tw - 1.0) < 1e-9, f"got {tw}")
    mw2, _ = tuning.deployed_weights({"deployed_match_weight": 0.0})
    check("clamps match weight to band lower bound", mw2 == tuning.BAND[0], f"got {mw2}")


def test_tuning_validate_state_corruption_branches():
    print("\n-- tuning.validate_state (corruption branches) --")

    mismatched = copy.deepcopy(tuning.initialize_state())
    mismatched["candidates"] = [0.1, 0.2, 0.3]
    check("rejects mismatched candidate set",
          tuning.validate_state(mismatched)["observations"] == 0)

    missing_key = copy.deepcopy(tuning.initialize_state())
    missing_key["S"].pop(next(iter(missing_key["S"])))
    check("rejects S/C key mismatch",
          tuning.validate_state(missing_key)["observations"] == 0)

    non_numeric = copy.deepcopy(tuning.initialize_state())
    non_numeric["C"][next(iter(non_numeric["C"]))] = "lots"
    check("rejects non-numeric mass",
          tuning.validate_state(non_numeric)["observations"] == 0)

    boolean_mass = copy.deepcopy(tuning.initialize_state())
    boolean_mass["S"][next(iter(boolean_mass["S"]))] = True
    check("rejects boolean mass (bool is not a valid float here)",
          tuning.validate_state(boolean_mass)["observations"] == 0)


def test_tuning_compute_rewards_no_signal():
    print("\n-- tuning.compute_rewards (no-signal cook returns None) --")
    a = Dish(name="rice bowl", ingredients={"rice": True})
    b = Dish(name="pasta", ingredients={"noodles": True})
    dishes = [a, b]
    fridge = {"rice", "noodles"}
    # The cooked dish is cookable but was cooked today (days=0 < COOLDOWN_DAYS),
    # so it scores 0 for every candidate and carries no learning signal.
    rewards = tuning.compute_rewards(
        "rice bowl", dishes, fridge, {"rice bowl": 0}, tuning.CANDIDATES
    )
    check("cooldown-zeroed cook yields no signal (None)", rewards is None, f"got {rewards}")
    # Sanity contrast: a normal cook does produce a reward dict.
    rewards2 = tuning.compute_rewards(
        "rice bowl", dishes, fridge, {"rice bowl": 14, "pasta": 3}, tuning.CANDIDATES
    )
    check("normal cook produces rewards", isinstance(rewards2, dict) and len(rewards2) > 0)


def main():
    test_dish_normalize_ingredient()
    test_dish_normalize_name()
    test_dish_can_cook_with()
    test_dish_can_cook_with_no_ingredients()
    test_dish_can_cook_with_only_optional()
    test_dish_to_dict()
    test_dish_from_dict()
    test_dish_from_dict_invalid()
    test_dish_add_ingredient()
    test_dish_add_ingredient_validation()
    test_dish_ingredient_keys_normalized_on_construction()

    test_calculate_score_basic()
    test_calculate_score_cooldown()
    test_calculate_score_no_ingredients()
    test_calculate_score_partial_ingredients()
    test_calculate_score_recency_scaling()

    test_suggest_dishes_basic()
    test_suggest_dishes_excludes_recent()
    test_suggest_dishes_default_recency()

    test_suggest_quick_shopping_basic()
    test_suggest_quick_shopping_two_missing()
    test_suggest_quick_shopping_groups_by_ingredient()

    test_normalize_ingredients_dict()
    test_normalize_ingredients_list()
    test_normalize_ingredients_json_string_dict()
    test_normalize_ingredients_json_string_list()
    test_normalize_ingredients_invalid()
    test_normalize_ingredients_empty_rejected()
    test_normalize_ingredients_dedup_under_limit()

    test_tuning_initial_state()
    test_tuning_deployed_weights_fallback()
    test_tuning_deployed_weights_clamps_out_of_band()
    test_tuning_validate_state()
    test_tuning_validate_state_corruption_branches()
    test_tuning_compute_rewards_not_cookable()
    test_tuning_compute_rewards_single_dish()
    test_tuning_compute_rewards_top_rank()
    test_tuning_compute_rewards_no_signal()
    test_tuning_apply_update_pure()
    test_tuning_cold_start()
    test_tuning_shift_after_warmup()
    test_tuning_hysteresis()

    print(f"\n{'='*40}")
    print(f"  {_passed} passed, {_failed} failed")
    print(f"{'='*40}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
