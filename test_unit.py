"""Unit tests for domain logic modules.

These tests are stateless — they test pure functions and dataclass behavior
without touching data files on disk.

Usage:
    python3 test_unit.py
"""

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
_tools_mod = importlib.import_module(".tools", _PLUGIN_DIR.name)

Dish = _dish_mod.Dish
calculate_score = _suggestion_mod.calculate_score
suggest_dishes = _suggestion_mod.suggest_dishes
suggest_quick_shopping = _shopping_mod.suggest_quick_shopping
_normalize_ingredients = _tools_mod._normalize_ingredients

# ---------------------------------------------------------------------------
# Assertion helper (same style as test_integration_smoke.py)
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
# Runner
# ---------------------------------------------------------------------------


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

    print(f"\n{'='*40}")
    print(f"  {_passed} passed, {_failed} failed")
    print(f"{'='*40}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
