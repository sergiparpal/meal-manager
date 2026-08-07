"""Unit tests for domain logic modules.

These tests are stateless — they test pure functions and dataclass behavior
without touching data files on disk.

Usage:
    python3 test_unit.py
"""

import copy
import importlib
import json
import shutil
import sys
import tempfile
import traceback
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
_repos_mod = importlib.import_module(".src.repositories", _PLUGIN_DIR.name)
_history_event_mod = importlib.import_module(".src.history_event", _PLUGIN_DIR.name)
_filelock_mod = importlib.import_module(".src.filelock", _PLUGIN_DIR.name)
_src_mod = importlib.import_module(".src", _PLUGIN_DIR.name)
reject_unknown_args = _handlers_common.reject_unknown_args

Dish = _dish_mod.Dish
calculate_score = _suggestion_mod.calculate_score
score_components = _suggestion_mod.score_components
DEFAULT_TIME_WEIGHT = _suggestion_mod.DEFAULT_TIME_WEIGHT
OPTIONAL_CAP = _suggestion_mod.OPTIONAL_CAP
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


def run(test_fn):
    """Run one test function, recording an exception as a failure.

    An unguarded call means one raised exception aborts every test after it, so
    a single mistake hides the rest of the suite. Catching here keeps the run
    going and still fails the process via the _failed counter.
    """
    global _failed
    try:
        test_fn()
    except Exception as exc:
        _failed += 1
        print(f"  FAIL  {test_fn.__name__} raised {type(exc).__name__}: {exc}")
        traceback.print_exc()


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


def test_dish_instructions():
    print("\n-- Dish.instructions --")
    plain = Dish(name="pasta", ingredients={"pasta": True})
    check("defaults to None", plain.instructions is None)
    check("to_dict omits the key entirely when unset",
          "instructions" not in plain.to_dict(), f"got {plain.to_dict()}")

    dish = Dish(name="pasta", ingredients={"pasta": True},
                instructions="  Boil water. Add pasta.  ")
    check("stored stripped", dish.instructions == "Boil water. Add pasta.")
    check("to_dict emits the key when set",
          dish.to_dict().get("instructions") == "Boil water. Add pasta.")

    blank = Dish(name="pasta", instructions="   \n  ")
    check("whitespace-only normalizes to None", blank.instructions is None)
    check("blank still omitted from to_dict", "instructions" not in blank.to_dict())

    try:
        Dish(name="pasta", instructions="x" * (_dish_mod.MAX_INSTRUCTIONS_LENGTH + 1))
        check("over-length raises", False, "should have raised ValueError")
    except ValueError as exc:
        check("over-length raises ValueError", "too long" in str(exc), str(exc))

    # Length is checked after stripping, so padding alone cannot trip the cap.
    padded = Dish(name="pasta",
                  instructions="  " + "x" * _dish_mod.MAX_INSTRUCTIONS_LENGTH + "  ")
    check("length checked after stripping",
          len(padded.instructions) == _dish_mod.MAX_INSTRUCTIONS_LENGTH)

    for bad in (42, ["step one"], {"step": 1}, True):
        try:
            Dish(name="pasta", instructions=bad)
            check(f"non-string {type(bad).__name__} raises", False, "no exception")
        except ValueError:
            check(f"non-string {type(bad).__name__} raises", True)

    round_tripped = Dish.from_dict(dish.to_dict())
    check("from_dict(to_dict(dish)) preserves instructions",
          round_tripped.instructions == "Boil water. Add pasta.")
    check("from_dict without the key yields None",
          Dish.from_dict({"name": "x", "ingredients": {"a": True}}).instructions is None)


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

    # Essentials are a gate, not a score: a dish with no optionals contributes
    # nothing from the match term, so a fully-rested dish scores exactly the
    # recency weight.
    score = calculate_score(dish, {"rice", "chicken"}, 14)
    check("positive score", score > 0, f"got {score}")
    check("essentials-only dish scores the recency term",
          abs(score - DEFAULT_TIME_WEIGHT) < 0.001, f"got {score}")

    # The ceiling needs OPTIONAL_CAP optionals in stock.
    rich = Dish(name="rich")
    rich.ingredients = {"rice": True, "a": False, "b": False, "c": False}
    top = calculate_score(rich, {"rice", "a", "b", "c"}, 14)
    check("max score = 1.0", abs(top - 1.0) < 0.001, f"got {top}")


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


def test_calculate_score_declaring_optionals_never_penalizes():
    print("\n-- calculate_score (declaring optionals never penalizes) --")
    # Same real dish, described at two levels of detail. The fridge holds
    # everything the detailed version declares except one optional.
    terse = Dish(name="terse", ingredients={"chicken": True, "rice": True})
    detailed = Dish(name="detailed", ingredients={
        "chicken": True, "rice": True,
        "onion": False, "garlic": False, "parsley": False,
    })
    fridge = {"chicken", "rice", "onion", "garlic"}

    terse_score = calculate_score(terse, fridge, 14)
    detailed_score = calculate_score(detailed, fridge, 14)
    check("describing the recipe better never lowers its score",
          detailed_score >= terse_score,
          f"terse={terse_score} detailed={detailed_score}")
    check("present optionals raise the score",
          detailed_score > terse_score,
          f"terse={terse_score} detailed={detailed_score}")


def test_calculate_score_match_depends_on_present_count_only():
    print("\n-- calculate_score (match depends on present count only) --")
    # Two dishes, same number of optionals IN STOCK (one), different numbers
    # declared. Under the old intra-dish ratio these diverged; they must not now.
    few = Dish(name="few", ingredients={"base": True, "a": False})
    many = Dish(name="many", ingredients={
        "base": True, "a": False, "x": False, "y": False, "z": False,
    })
    fridge = {"base", "a"}
    check("equal present-optional counts score equally",
          abs(calculate_score(few, fridge, 14) - calculate_score(many, fridge, 14)) < 1e-9,
          f"{calculate_score(few, fridge, 14)} vs {calculate_score(many, fridge, 14)}")

    # And a dish declaring nothing is not treated as fully stocked.
    bare = Dish(name="bare", ingredients={"base": True})
    check("declaring no optionals is not a free full match",
          calculate_score(bare, fridge, 14) < calculate_score(few, fridge, 14))


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


def test_suggest_quick_shopping_max_missing():
    print("\n-- suggest_quick_shopping (max_missing) --")
    d = Dish(name="stew", ingredients={"beef": True, "potato": True, "carrot": True})
    # Nothing in the fridge: two-away and three-away dishes are invisible at the
    # default threshold, which is exactly the empty-fridge blind spot.
    check("default threshold stays single-unlock",
          suggest_quick_shopping([d], set(), {}) == [])
    check("threshold 2 still excludes a three-away dish",
          suggest_quick_shopping([d], set(), {}, max_missing=2) == [])
    result = suggest_quick_shopping([d], set(), {}, max_missing=3)
    check("threshold 3 surfaces the dish", len(result) == 3, f"got {result}")
    check("every missing essential is credited",
          {row[0] for row in result} == {"beef", "potato", "carrot"}, f"got {result}")
    check("still_missing reports the basket size",
          all(row[4] == 3 for row in result), f"got {result}")


def test_suggest_quick_shopping_prefers_cheapest_basket():
    print("\n-- suggest_quick_shopping (cheapest basket leads) --")
    # 'flour' is named by three dishes that each need two MORE items, so buying
    # it alone unlocks nothing. 'eggs' puts dinner on the table tonight. Reach
    # alone would rank flour first and bury the answer the user actually wants.
    dishes = [
        Dish(name="cake", ingredients={"flour": True, "sugar": True, "butter": True}),
        Dish(name="bread", ingredients={"flour": True, "yeast": True, "water": True}),
        Dish(name="pastry", ingredients={"flour": True, "lard": True, "jam": True}),
        Dish(name="omelette", ingredients={"eggs": True, "oil": True}),
    ]
    result = suggest_quick_shopping(dishes, {"oil"}, {}, max_missing=3)
    check("true one-item unlock ranks first",
          result[0][0] == "eggs" and result[0][4] == 1, f"got {result[:2]}")
    check("higher-reach-but-useless ingredient ranks below it",
          result[1][0] == "flour" and result[1][4] == 3, f"got {result[:2]}")
    # Within one basket size, reach is still the tiebreaker.
    by_basket_three = [row for row in result if row[4] == 3]
    check("reach still leads within a basket size",
          by_basket_three[0][0] == "flour", f"got {by_basket_three}")


def test_suggest_quick_shopping_score_matches_cheapest_unlock():
    print("\n-- suggest_quick_shopping (row describes the cheapest unlock) --")
    # 'x' unlocks 'near' on its own (score 0.4) and 'far' as part of a 3-item
    # basket (score 1.0). Reporting 1.0 next to still_missing=1 would promise a
    # meal that basket cannot buy.
    dishes = [
        Dish(name="near", ingredients={"x": True, "have": True}),
        Dish(name="far", ingredients={"x": True, "p": True, "q": True,
                                      "o1": False, "o2": False, "o3": False}),
    ]
    result = suggest_quick_shopping(dishes, {"have", "o1", "o2", "o3"}, {}, max_missing=3)
    row = next(r for r in result if r[0] == "x")
    check("still_missing is the smallest basket", row[4] == 1, f"got {row}")
    check("score belongs to that basket's dish, not the pricier one",
          abs(row[2] - 0.4) < 1e-9, f"got {row}")
    # Reach is scoped to the reported basket too. Counting every dish that
    # merely names the ingredient made the row read "buy this one thing,
    # unlocks 2 dishes" while the single purchase unlocked one — the same
    # promise the score fix above exists to prevent, one field over.
    check("reach counts only what this basket reaches", row[3] == 1, f"got {row}")
    check("the pricier dish is not advertised here",
          row[1] == "near", f"got {row}")
    # 'far' is still reachable — through the ingredients its own basket needs,
    # at that basket's true size.
    far_row = next(r for r in result if r[0] == "p")
    check("pricier dish still surfaces at its real basket size",
          far_row[1] == "far" and far_row[4] == 3, f"got {far_row}")


def test_suggest_quick_shopping_ranks_by_reach():
    print("\n-- suggest_quick_shopping (ranks by reach) --")
    # 'shared' unlocks two dishes; 'solo' unlocks one. Reach must win.
    a = Dish(name="dish a", ingredients={"have": True, "shared": True})
    b = Dish(name="dish b", ingredients={"have": True, "shared": True, "extra": False})
    c = Dish(name="dish c", ingredients={"have": True, "solo": True, "o1": False,
                                         "o2": False, "o3": False})
    fridge = {"have", "extra", "o1", "o2", "o3"}
    result = suggest_quick_shopping([a, b, c], fridge, {})
    check("highest-reach ingredient ranks first",
          result[0][0] == "shared", f"got {result}")
    check("reach count is reported", result[0][3] == 2, f"got {result}")


# ---------------------------------------------------------------------------
# Fridge repository tests
# ---------------------------------------------------------------------------


def test_fridge_repository_counts():
    print("\n-- JsonFridgeRepository (counts) --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_fridge_"))
    try:
        repo = _repos_mod.JsonFridgeRepository(tmp / "fridge.json")
        repo.save({"onion": 2, "salt": None, "gone": 0})

        check("load round-trips counts", repo.load() == {"onion": 2, "salt": None, "gone": 0})
        check("load_set excludes zero counts", repo.load_set() == {"onion", "salt"})

        previous = repo.consume(["onion", "salt", "gone", "absent"])
        check("consume reports only what changed", previous == {"onion": 2}, f"got {previous}")
        check("onion decremented", repo.load()["onion"] == 1)
        check("staple untouched", repo.load()["salt"] is None)
        check("zero stays zero", repo.load()["gone"] == 0)
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_fridge_repository_non_finite_counts():
    print("\n-- JsonFridgeRepository (non-finite counts) --")
    # Python's json module accepts NaN/Infinity literals, and both explode in
    # int() outside the loader's parse guard — NaN with ValueError, Infinity
    # with OverflowError — taking every fridge-backed tool down with them.
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_nonfinite_"))
    try:
        repo = _repos_mod.JsonFridgeRepository(tmp / "fridge.json")
        (tmp / "fridge.json").write_text(
            '{"onion": 2, "bad": NaN, "worse": Infinity}', encoding="utf-8")
        loaded = repo.load()
        check("non-finite counts dropped, file still usable",
              loaded == {"onion": 2}, f"got {loaded}")
        check("load_set survives", repo.load_set() == {"onion"})
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_expiry_status():
    print("\n-- expiry_status --")
    from datetime import date as _date
    from datetime import timedelta as _timedelta
    _json_fridge = importlib.import_module(".src.repositories.json_fridge",
                                           _PLUGIN_DIR.name)
    status = _json_fridge.expiry_status
    soon_days = _json_fridge.EXPIRING_SOON_DAYS
    today = _date(2026, 7, 27)

    def at(offset):
        return (today + _timedelta(days=offset)).isoformat()

    check("no date yields no status", status(None, today) is None)
    check("expiring today counts as expiring soon, not expired",
          status(at(0), today) == "expiring_soon")
    check("the last day inside the window is expiring soon",
          status(at(soon_days), today) == "expiring_soon")
    check("one day past the window is fresh",
          status(at(soon_days + 1), today) == "fresh")
    check("yesterday is expired", status(at(-1), today) == "expired")
    check("far future is fresh", status(at(365), today) == "fresh")
    check("unreadable dates are treated as no date",
          status("not-a-date", today) is None)
    check("accepts a date object", status(today, today) == "expiring_soon")


def test_fridge_entries_grammar():
    print("\n-- JsonFridgeRepository.load_entries / save_entries --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_fridge_"))
    try:
        path = tmp / "fridge.json"
        repo = _repos_mod.JsonFridgeRepository(path)

        path.write_text(json.dumps({
            "milk": {"count": 2, "expires_on": "2026-08-01"},
            "salt": None,
            "onion": 3,
            "gone": 0,
        }), encoding="utf-8")

        entries = repo.load_entries()
        check("object form parsed",
              entries["milk"] == {"count": 2, "expires_on": "2026-08-01"},
              f"got {entries}")
        check("legacy scalar loads with no expiry",
              entries["onion"] == {"count": 3, "expires_on": None}, f"got {entries}")
        check("null still means pantry staple",
              entries["salt"] == {"count": None, "expires_on": None}, f"got {entries}")

        # Invariant 3: the count-only view is unchanged.
        check("load() keeps its {name: count} contract",
              repo.load() == {"milk": 2, "salt": None, "onion": 3, "gone": 0},
              f"got {repo.load()}")
        check("load_set() is unaffected by expiry",
              repo.load_set() == {"milk", "salt", "onion"}, f"got {repo.load_set()}")

        repo.save_entries(entries)
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Entries without an expiry must stay bare scalars or every existing
        # fridge.json would churn the moment anything touched it.
        check("no-expiry entries round-trip as bare scalars",
              raw["onion"] == 3 and raw["salt"] is None and raw["gone"] == 0,
              f"got {raw}")
        check("expiry entries round-trip as objects",
              raw["milk"] == {"count": 2, "expires_on": "2026-08-01"}, f"got {raw}")

        # A mistyped date must cost the date, not the food.
        path.write_text(json.dumps({"cheese": {"count": 1, "expires_on": "08/2026"}}),
                        encoding="utf-8")
        check("unreadable expires_on keeps the ingredient",
              repo.load_entries() == {"cheese": {"count": 1, "expires_on": None}},
              f"got {repo.load_entries()}")

        # The non-finite guard has to apply inside the object form too.
        path.write_text('{"a": {"count": NaN}, "b": {"count": Infinity}, "c": 2}',
                        encoding="utf-8")
        check("non-finite counts dropped in the object form too",
              repo.load_entries() == {"c": {"count": 2, "expires_on": None}},
              f"got {repo.load_entries()}")

        # An object without a count means one portion, exactly like a list entry.
        path.write_text(json.dumps({"bread": {"expires_on": "2026-08-01"}}),
                        encoding="utf-8")
        check("object without a count means one portion",
              repo.load_entries()["bread"]["count"] == 1, f"got {repo.load_entries()}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_fridge_mutations_preserve_expiry():
    print("\n-- JsonFridgeRepository: mutations keep expiry --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_fridge_"))
    try:
        path = tmp / "fridge.json"
        repo = _repos_mod.JsonFridgeRepository(path)
        repo.save_entries({
            "milk": {"count": 2, "expires_on": "2026-08-01"},
            "salt": {"count": None, "expires_on": None},
        })

        # consume() works off the count-only view; writing that back verbatim
        # would silently erase every date on the way out.
        repo.consume(["milk"])
        check("consume decrements without losing the date",
              repo.load_entries()["milk"] == {"count": 1, "expires_on": "2026-08-01"},
              f"got {repo.load_entries()}")

        repo.save({"milk": 5, "salt": None})
        check("count-only save keeps the date",
              repo.load_entries()["milk"] == {"count": 5, "expires_on": "2026-08-01"},
              f"got {repo.load_entries()}")

        repo.remove_items(["milk"])
        check("remove_items drops the whole entry",
              "milk" not in repo.load_entries(), f"got {repo.load_entries()}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_normalize_ingredient_entries():
    print("\n-- normalize_ingredient_entries --")
    entries = _handlers_common.normalize_ingredient_entries
    check("list means one portion each",
          entries(["Milk", "eggs"]) == {"milk": {"count": 1}, "eggs": {"count": 1}},
          f"got {entries(['Milk', 'eggs'])}")
    check("counts and staples pass through",
          entries({"a": 3, "salt": None}) == {"a": {"count": 3}, "salt": {"count": None}},
          f"got {entries({'a': 3, 'salt': None})}")
    check("object form carries the date",
          entries({"milk": {"count": 2, "expires_on": "2026-08-01"}})
          == {"milk": {"count": 2, "expires_on": "2026-08-01"}},
          f"got {entries({'milk': {'count': 2, 'expires_on': '2026-08-01'}})}")

    # "leave the date alone" and "clear the date" must be distinguishable.
    check("an omitted expires_on leaves the key out",
          "expires_on" not in entries({"milk": 2})["milk"])
    check("an explicit null keeps the key",
          entries({"milk": {"count": 2, "expires_on": None}})["milk"]["expires_on"]
          is None)

    for label, bad in (
        ("malformed date", {"milk": {"count": 1, "expires_on": "08/2026"}}),
        ("non-string date", {"milk": {"count": 1, "expires_on": 20260801}}),
        ("unknown field", {"milk": {"count": 1, "best_before": "2026-08-01"}}),
        ("bad count", {"milk": {"count": "two"}}),
        ("boolean count", {"milk": True}),
        ("negative count", {"milk": -1}),
        ("colliding keys", {"Milk": 1, "milk": 2}),
    ):
        try:
            entries(bad)
            check(f"{label} rejected", False, "no exception")
        except ValueError:
            check(f"{label} rejected", True)


def test_alias_repository():
    print("\n-- JsonAliasRepository --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_alias_"))
    try:
        path = tmp / "aliases.json"
        repo = _repos_mod.JsonAliasRepository(path)

        check("missing file loads as empty", repo.load() == {})
        check("resolve returns the input unchanged when unmapped",
              repo.resolve("tomate") == "tomate")
        check("nothing is created just by reading", not path.exists())

        repo.add("tomates", "tomate")
        check("alias resolves to its canonical", repo.resolve("tomates") == "tomate")
        check("canonical resolves to itself", repo.resolve("tomate") == "tomate")

        # A later merge that retires the previous canonical must re-point the
        # old alias too, or the single-hop resolve would stop one link short.
        repo.add("tomate", "tomate pera")
        check("pre-existing alias is re-pointed, no chain forms",
              repo.resolve("tomates") == "tomate pera", f"got {repo.load()}")
        check("the retired name resolves to the new canonical",
              repo.resolve("tomate") == "tomate pera", f"got {repo.load()}")
        check("no alias points at another alias",
              not (set(repo.load().values()) & set(repo.load())), f"got {repo.load()}")

        try:
            repo.add("sal", "sal")
            check("self-alias rejected", False, "no exception")
        except ValueError:
            check("self-alias rejected", True)

        path.write_text("{not json", encoding="utf-8")
        check("corrupt file loads as empty", repo.load() == {})
        path.write_text('["a", "b"]', encoding="utf-8")
        check("non-object file loads as empty", repo.load() == {})
        path.write_text('{"a": 1, "": "x", "b": "", "ok": "canon"}', encoding="utf-8")
        check("non-string and blank entries are skipped",
              repo.load() == {"ok": "canon"}, f"got {repo.load()}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def _history_repo_in_tmp(tmp):
    return _repos_mod.JsonHistoryRepository(tmp / "history.json")


def test_history_projects_latest_per_dish():
    print("\n-- JsonHistoryRepository.load (projection) --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_history_"))
    try:
        repo = _history_repo_in_tmp(tmp)
        repo.append_event("paella", "2026-07-26")
        repo.append_event("stew", "2026-01-05")
        repo.append_event("paella", "2026-08-01")
        check("projects the latest date per dish",
              repo.load() == {"paella": "2026-08-01", "stew": "2026-01-05"},
              f"got {repo.load()}")
        check("every event is retained",
              len(repo.load_events()) == 3, f"got {repo.load_events()}")

        stored = json.loads((tmp / "history.json").read_text(encoding="utf-8"))
        check("written in the v2 envelope",
              stored.get("schema_version") == 2 and len(stored.get("events", [])) == 3,
              f"got {stored}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_history_older_event_cannot_rewind_the_cooldown():
    print("\n-- JsonHistoryRepository: an older event never wins --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_history_"))
    try:
        repo = _history_repo_in_tmp(tmp)
        repo.append_event("paella", "2026-07-26")
        # This is the bug the old single-value model needed an `only_if_newer`
        # flag to avoid. Under the log the projection takes the maximum, so
        # backdating a forgotten meal cannot reset a cook from this morning.
        repo.append_event("paella", "2026-06-26", backfilled=True)
        check("backdated event does not move the projection",
              repo.load()["paella"] == "2026-07-26", f"got {repo.load()}")
        check("but the backdated event is still on record",
              any(e.cooked_on == "2026-06-26" and e.backfilled
                  for e in repo.load_events()),
              f"got {[e.to_dict() for e in repo.load_events()]}")

        repo.append_event("paella", "2026-09-01")
        check("a genuinely newer event does move it",
              repo.load()["paella"] == "2026-09-01", f"got {repo.load()}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_history_retract_versus_delete():
    print("\n-- JsonHistoryRepository: retract vs delete --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_history_"))
    try:
        repo = _history_repo_in_tmp(tmp)
        old = repo.append_event("paella", "2026-05-01")
        recent = repo.append_event("paella", "2026-07-26")

        retracted = repo.retract_latest_for_dish("Paella")
        check("retracts the most recent cook", retracted.id == recent.id)
        check("projection falls back to the earlier cook",
              repo.load()["paella"] == "2026-05-01", f"got {repo.load()}")
        check("retracted event is still in the log",
              len(repo.load_events()) == 2, f"got {repo.load_events()}")
        check("retracted event is marked, not removed",
              any(e.id == recent.id and not e.active for e in repo.load_events()))

        check("retracting an already-retracted id returns None",
              repo.retract_event(recent.id) is None)
        check("retracting an unknown id returns None",
              repo.retract_event("cook_nope") is None)

        # Hard delete is the rollback path: the row must vanish entirely.
        check("delete_event reports success", repo.delete_event(old.id) is True)
        check("deleted event is gone from the log",
              [e.id for e in repo.load_events()] == [recent.id],
              f"got {[e.id for e in repo.load_events()]}")
        check("deleting an unknown id reports failure",
              repo.delete_event(old.id) is False)
        check("projection is empty once the last active event is gone",
              repo.load() == {}, f"got {repo.load()}")

        check("retract_latest_for_dish on an unknown dish returns None",
              repo.retract_latest_for_dish("nothing here") is None)
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_history_legacy_migration():
    print("\n-- JsonHistoryRepository: legacy {dish: date} migration --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_history_"))
    try:
        path = tmp / "history.json"
        legacy = {"Paella": "2026-07-26", "stew": "2026-01-05", "bad": "nope"}
        path.write_text(json.dumps(legacy), encoding="utf-8")

        repo = _history_repo_in_tmp(tmp)
        events = repo.load_events()
        check("one event per readable entry", len(events) == 2, f"got {events}")
        check("names normalized",
              {e.dish_name for e in events} == {"paella", "stew"},
              f"got {[e.dish_name for e in events]}")
        check("projection matches the legacy mapping",
              repo.load() == {"paella": "2026-07-26", "stew": "2026-01-05"},
              f"got {repo.load()}")
        check("load_events never writes", json.loads(path.read_text()) == legacy)

        # Ids must be a pure function of the entry: migration re-runs in memory
        # on every load until the first write, and a random id would duplicate
        # the row the moment something did write.
        second = _history_repo_in_tmp(tmp).load_events()
        check("ids are deterministic across migrations",
              sorted(e.id for e in events) == sorted(e.id for e in second),
              f"{sorted(e.id for e in events)} vs {sorted(e.id for e in second)}")

        repo.append_event("paella", "2026-08-02")
        stored = json.loads(path.read_text(encoding="utf-8"))
        check("the next write persists the v2 shape",
              stored.get("schema_version") == 2 and len(stored["events"]) == 3,
              f"got {stored}")
        check("no duplicates after the rewrite",
              len({e["id"] for e in stored["events"]}) == 3, f"got {stored}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_history_corruption():
    print("\n-- JsonHistoryRepository: corrupt storage --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_history_"))
    try:
        path = tmp / "history.json"
        repo = _history_repo_in_tmp(tmp)

        for label, content in (
            ("invalid JSON", "{not json"),
            ("top-level list", "[1, 2, 3]"),
            ("unsupported schema_version", '{"schema_version": 99, "events": []}'),
            ("non-list events", '{"schema_version": 2, "events": {}}'),
            ("invalid event row", '{"schema_version": 2, "events": [{"id": "x"}]}'),
        ):
            path.write_text(content, encoding="utf-8")
            check(f"{label}: non-strict yields an empty log",
                  repo.load_events() == [], f"got {repo.load_events()}")
            try:
                repo.load_events(strict=True)
                check(f"{label}: strict raises", False, "no exception")
            except _repos_mod.HistoryDataError:
                check(f"{label}: strict raises HistoryDataError", True)

        check("load() tolerates corruption", repo.load() == {})
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_cooking_event_from_dict_strict():
    print("\n-- CookingEvent.from_dict (strict) --")
    complete = {
        "id": "cook_abc",
        "dish_name": "Paella",
        "cooked_on": "2026-07-26",
        "recorded_at": "2026-07-26T10:00:00+00:00",
        "backfilled": False,
        "retracted_at": None,
    }
    event = _history_event_mod.CookingEvent.from_dict(complete)
    check("round-trips", event.to_dict()["dish_name"] == "paella", f"got {event}")
    check("active when not retracted", event.active is True)

    missing = {k: v for k, v in complete.items() if k != "recorded_at"}
    try:
        _history_event_mod.CookingEvent.from_dict(missing)
        check("missing key raises", False, "no exception")
    except ValueError as exc:
        check("missing key raises ValueError naming it",
              "recorded_at" in str(exc), str(exc))

    try:
        _history_event_mod.CookingEvent.from_dict({**complete, "portions": 2})
        check("unknown key raises", False, "no exception")
    except ValueError as exc:
        check("unknown key raises ValueError naming it",
              "portions" in str(exc), str(exc))

    for label, override in (
        ("bad id prefix", {"id": "evt_abc"}),
        ("blank dish name", {"dish_name": "   "}),
        ("bad cooked_on", {"cooked_on": "26-07-2026"}),
        ("naive recorded_at", {"recorded_at": "2026-07-26T10:00:00"}),
        ("non-bool backfilled", {"backfilled": "yes"}),
        ("naive retracted_at", {"retracted_at": "2026-07-26T10:00:00"}),
    ):
        try:
            _history_event_mod.CookingEvent.from_dict({**complete, **override})
            check(f"{label} raises", False, "no exception")
        except ValueError:
            check(f"{label} raises ValueError", True)


# ---------------------------------------------------------------------------
# Handler argument validation
# ---------------------------------------------------------------------------


def test_reject_unknown_args():
    print("\n-- reject_unknown_args --")
    allowed = {"dish_name", "date"}

    ok = True
    try:
        reject_unknown_args({}, allowed)
        reject_unknown_args({"dish_name": "paella"}, allowed)
        reject_unknown_args({"dish_name": "paella", "date": "2026-01-01"}, allowed)
    except ValueError:
        ok = False
    check("declared keys pass", ok)

    try:
        reject_unknown_args({"dish_name": "paella", "qty": 2}, allowed)
        check("unknown key raises", False, "no exception")
    except ValueError as exc:
        check("unknown key raises ValueError naming it", "qty" in str(exc), str(exc))

    try:
        reject_unknown_args(["dish_name"], allowed)
        check("non-dict args raises", False, "no exception")
    except ValueError as exc:
        check("non-dict args raises ValueError", "object" in str(exc), str(exc))

    widened = True
    try:
        reject_unknown_args({"dish_name": "paella", "trace_id": "x"},
                            allowed | {"trace_id"})
    except ValueError:
        widened = False
    check("extra_args widens the allowed set", widened)


def test_safe_error_message():
    print("\n-- _safe_error_message --")
    import json as _json
    safe = _handlers_common._safe_error_message

    check("ValueError passes through verbatim",
          safe(ValueError("dish name cannot be empty")) == "dish name cannot be empty")
    check("LookupError passes through verbatim",
          safe(LookupError("'paella' is not in the recipe catalog."))
          == "'paella' is not in the recipe catalog.")
    check("KeyError passes through (a LookupError subclass)",
          safe(KeyError("dish_name")) == "'dish_name'")

    check("OSError is replaced",
          safe(OSError(13, "Permission denied", "/home/user/data/dishes.json"))
          == "Storage is temporarily unavailable")
    check("FileNotFoundError is replaced",
          safe(FileNotFoundError(2, "No such file", "/srv/data/fridge.json"))
          == "Storage is temporarily unavailable")

    try:
        _json.loads("{oops")
        decode_exc = None
    except _json.JSONDecodeError as exc:
        decode_exc = exc
    # JSONDecodeError subclasses ValueError, so ordering inside the mapper is
    # what keeps it from leaking byte offsets into file contents.
    check("JSONDecodeError is matched before ValueError",
          decode_exc is not None and safe(decode_exc) == "Stored data could not be read",
          f"got {safe(decode_exc) if decode_exc else 'no exception'}")

    check("unanticipated types get the generic default",
          safe(RuntimeError("connection to 10.0.0.4:5432 refused"))
          == "An internal error occurred")
    check("TypeError gets the generic default",
          safe(TypeError("unsupported operand")) == "An internal error occurred")


def test_tool_handler_sanitizes_envelope():
    print("\n-- tool_handler (sanitized error envelope) --")
    import json as _json
    schema = {"type": "object", "properties": {}}

    @_handlers_common.tool_handler("boom_os", schema)
    def raises_oserror(args, **kwargs):
        raise PermissionError(13, "Permission denied", "/home/user/data/dishes.json")

    res = _json.loads(raises_oserror({}))
    check("OSError envelope hides the path",
          res == {"error": "Storage is temporarily unavailable"}, f"got {res}")

    @_handlers_common.tool_handler("boom_value", schema)
    def raises_valueerror(args, **kwargs):
        raise ValueError("ingredients cannot be empty")

    res2 = _json.loads(raises_valueerror({}))
    check("deliberate ValueError still visible verbatim",
          res2 == {"error": "ingredients cannot be empty"}, f"got {res2}")


def test_tool_handler_validates_against_schema():
    print("\n-- tool_handler (schema-derived validation) --")
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}

    @_handlers_common.tool_handler("fake_tool", schema)
    def handler(args, **kwargs):
        return {"ok": args.get("a")}

    import json as _json
    good = _json.loads(handler({"a": "x"}))
    check("declared argument passes through", good == {"ok": "x"}, f"got {good}")

    bad = _json.loads(handler({"a": "x", "b": 1}))
    check("unknown argument returns an error envelope", "error" in bad, f"got {bad}")
    check("error names the offending key", "b" in bad.get("error", ""), f"got {bad}")

    @_handlers_common.tool_handler("legacy_tool")
    def legacy(args, **kwargs):
        return {"ok": True}

    unvalidated = _json.loads(legacy({"anything": 1}))
    check("schema=None stays unvalidated", unvalidated == {"ok": True},
          f"got {unvalidated}")


# ---------------------------------------------------------------------------
# _normalize_ingredients tests
# ---------------------------------------------------------------------------


def test_score_components_agree_with_calculate_score():
    print("\n-- score_components (agrees with calculate_score) --")
    dish = Dish(name="test", ingredients={"base": True, "a": False, "b": False})
    fridge = {"base", "a"}
    for days in (0, 1, 2, 7, 14, 30):
        components = score_components(dish, fridge, days)
        expected = calculate_score(dish, fridge, days, match_weight=0.7, time_weight=0.3)
        if components is None:
            check(f"gated day {days} scores 0", expected == 0, f"got {expected}")
        else:
            match, recency = components
            blended = 0.7 * match + 0.3 * recency
            check(f"day {days} blend matches", abs(blended - expected) < 1e-12,
                  f"{blended} vs {expected}")
    check("no-ingredient dish is gated",
          score_components(Dish(name="bare"), fridge, 14) is None)


def test_dish_rejects_colliding_ingredient_keys():
    print("\n-- Dish: colliding ingredient keys rejected --")
    # {"Rice": True, "rice": False} is a contradiction, not a duplicate:
    # silently keeping one flag drops a declaration made on purpose.
    try:
        Dish(name="soup", ingredients={"Rice": True, "rice": False})
        check("rejects contradictory colliding keys", False, "should have raised")
    except ValueError:
        check("rejects contradictory colliding keys", True)
    # Loading from disk stays permissive so an existing catalog row with the
    # same quirk is not dropped from the catalog entirely.
    loaded = Dish.from_dict({"name": "soup", "ingredients": {"Rice": True, "rice": False}})
    check("from_dict still loads legacy rows", loaded.ingredients == {"rice": False},
          f"got {loaded.ingredients}")


def test_normalize_ingredients_rejects_colliding_dict_keys():
    print("\n-- normalize_ingredients: colliding dict keys rejected --")
    try:
        _normalize_ingredients({"Tomato": True, "tomato": False})
        check("dict collision rejected", False, "should have raised")
    except ValueError:
        check("dict collision rejected", True)
    # A list carries no flag, so repeats collapse without losing anything.
    check("list repeats still collapse",
          _normalize_ingredients(["Tomato", "tomato"]) == {"tomato": True})


def test_normalize_ingredient_names():
    print("\n-- normalize_ingredient_names --")
    names = _handlers_common.normalize_ingredient_names
    check("list normalized and deduped",
          names([" Rice ", "rice", "Pasta"]) == ["rice", "pasta"])
    # A count attached to a name is ignored, not validated: removal deletes the
    # entry outright, so MAX_PORTION_COUNT does not apply to it.
    check("dict values ignored", names({"Rice": 500, "pasta": -3}) == ["rice", "pasta"])
    check("JSON string accepted", names('["Rice"]') == ["rice"])


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
    print("\n-- tuning.compute_rewards (w-dependent ranking -> signal) --")
    # 'old dish' has no optionals but maximum recency; 'fresh dish' has three
    # optionals in stock but was cooked recently. Low w favours the first, high w
    # the second, so the reward vector varies across candidates.
    old = Dish(name="old dish", ingredients={"a": True})
    fresh = Dish(name="fresh dish", ingredients={
        "b": True, "o1": False, "o2": False, "o3": False,
    })
    dishes = [old, fresh]
    fridge = {"a", "b", "o1", "o2", "o3"}
    days = {"old dish": 14, "fresh dish": 3}

    rewards = tuning.compute_rewards("old dish", dishes, fridge, days, tuning.CANDIDATES)
    check("returns a reward dict", rewards is not None, f"got {rewards}")
    spread = max(rewards.values()) - min(rewards.values())
    check("reward discriminates between candidates", spread > 0.5, f"spread {spread}")
    check("the low-w candidate ranks it top",
          abs(rewards[tuning._key(0.40)] - 1.0) < 1e-9, f"got {rewards}")


def test_tuning_compute_rewards_uniform_skipped():
    print("\n-- tuning.compute_rewards (uniform reward skipped) --")
    # Neither dish declares optionals, so the match term is identical and the
    # ordering is recency-driven and weight-independent: no signal about w.
    a = Dish(name="dish a", ingredients={"a": True})
    b = Dish(name="dish b", ingredients={"b": True})
    rewards = tuning.compute_rewards(
        "dish a", [a, b], {"a", "b"}, {"dish a": 14, "dish b": 3}, tuning.CANDIDATES
    )
    check("weight-independent ranking yields no signal", rewards is None, f"got {rewards}")


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


def test_dish_rejects_invalid_ingredient_values():
    print("\n-- Dish: invalid ingredient names/flags rejected on construction --")
    # add_ingredient has always checked both, but direct construction skipped
    # them: a truthy non-bool then read as "essential" via can_cook_with, so
    # {"": "yes"} became a nameless blocking ingredient nothing could satisfy.
    try:
        Dish(name="soup", ingredients={"   ": True})
        check("empty ingredient name rejected", False, "should have raised")
    except ValueError:
        check("empty ingredient name rejected", True)

    try:
        Dish(name="soup", ingredients={"rice": "yes"})
        check("non-boolean essential flag rejected", False, "should have raised")
    except ValueError:
        check("non-boolean essential flag rejected", True)

    ok = Dish(name="soup", ingredients={"Rice": True, "Basil": False})
    check("valid ingredients still accepted",
          ok.ingredients == {"rice": True, "basil": False}, f"got {ok.ingredients}")

    # from_dict routes through add_ingredient, which already rejected both, so
    # the repository keeps treating such a row as malformed rather than losing
    # the whole catalog.
    try:
        Dish.from_dict({"name": "soup", "ingredients": {"rice": "yes"}})
        check("from_dict still rejects a non-boolean flag", False, "should have raised")
    except ValueError:
        check("from_dict still rejects a non-boolean flag", True)


def test_alias_repository_cache_invalidation():
    print("\n-- JsonAliasRepository: cached reads stay correct --")
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_alias_cache_"))
    try:
        path = tmp / "aliases.json"
        repo = _repos_mod.JsonAliasRepository(path)

        check("missing file resolves to the input", repo.resolve("tomate") == "tomate")
        repo.add("tomates", "tomate")
        check("a write is visible immediately", repo.resolve("tomates") == "tomate")

        # Repeated reads are served from the cache; they must stay correct.
        check("repeated reads stay correct",
              all(repo.resolve("tomates") == "tomate" for _ in range(5)))

        # load() hands back a copy: add() mutates what it receives, and the
        # cached mapping is shared.
        borrowed = repo.load()
        borrowed["injected"] = "nonsense"
        check("load() returns a copy, not the cache",
              repo.resolve("injected") == "injected", f"got {repo.load()}")

        # A write through the repository invalidates.
        repo.add("tomate", "tomate pera")
        check("a later write invalidates the cache",
              repo.resolve("tomates") == "tomate pera", f"got {repo.load()}")

        # An out-of-band edit is caught by the stat fingerprint.
        path.write_text('{"berenjena": "aubergine"}', encoding="utf-8")
        check("an external rewrite is picked up",
              repo.resolve("berenjena") == "aubergine", f"got {repo.load()}")

        path.unlink()
        check("deletion is picked up", repo.resolve("berenjena") == "berenjena")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_tuning_deployed_weight_off_grid():
    print("\n-- tuning.select_deployed (deployed weight off the candidate grid) --")
    # BAND's floor (0.35) is below the candidate grid (0.40+), and
    # deployed_weights clamps into BAND, so the stored weight can be a value
    # with no accumulated mass. _mean read that as 0.0, which let any candidate
    # clear HYSTERESIS_MARGIN and bypass the gate entirely.
    state = tuning.initialize_state()
    state["observations"] = tuning.MIN_OBSERVATIONS + 5
    for w in tuning.CANDIDATES:
        key = tuning._key(w)
        state["C"][key] = 1.0
        state["S"][key] = 0.50
    state["deployed_match_weight"] = 0.35          # in BAND, not a candidate
    state["S"][tuning._key(0.40)] = 0.51           # nearest candidate to 0.35
    state["S"][tuning._key(0.65)] = 0.52           # best overall, but only +0.01

    result = tuning.select_deployed(state)
    check("an off-grid weight snaps onto the grid",
          result["deployed_match_weight"] in tuning.CANDIDATES,
          f"got {result['deployed_match_weight']}")
    # Treating the off-grid weight's absent mass as a 0.0 mean let 0.65 clear
    # the margin against nothing and take over. Measured against the nearest
    # real candidate its advantage is +0.01, well inside the margin.
    check("hysteresis is enforced from an off-grid start",
          result["deployed_match_weight"] == 0.40,
          f"got {result['deployed_match_weight']}")
    check("weights still sum to 1.0",
          abs(result["deployed_match_weight"] + result["deployed_time_weight"] - 1.0) < 1e-9)


def test_tuning_reward_denominator_uses_ranking_size():
    print("\n-- tuning.compute_rewards (reward is normalized over the ranking) --")
    # Guard against dividing by zero: a single rankable dish carries no signal
    # about w, so the event must be skipped rather than scored over a
    # one-entry ranking.
    dishes = [Dish(name=n, ingredients={"x": True}) for n in ("a", "b", "c")]
    rewards = tuning.compute_rewards(
        "a", dishes, {"x"}, {"a": 10, "b": 0, "c": 0}, tuning.CANDIDATES
    )
    check("a one-dish ranking carries no signal", rewards is None, f"got {rewards}")

    # Three cookable dishes, one of them inside the cooldown window, so the
    # ranking the user actually saw holds two. "rich" wins on availability,
    # "stale" wins on recency, and they trade places as w moves across the grid.
    dishes2 = [
        Dish(name="rich", ingredients={"x": True, "o1": False, "o2": False, "o3": False}),
        Dish(name="stale", ingredients={"x": True}),
        Dish(name="cooling", ingredients={"x": True}),
    ]
    fridge = {"x", "o1", "o2", "o3"}
    days = {"rich": 3, "stale": 14, "cooling": 0}
    rewards2 = tuning.compute_rewards("rich", dishes2, fridge, days, tuning.CANDIDATES)

    check("a discriminating event produces rewards", rewards2 is not None, f"got {rewards2}")
    if rewards2 is not None:
        check("every reward is within [0, 1]",
              all(0.0 <= v <= 1.0 for v in rewards2.values()), f"got {rewards2}")
        # The decisive assertion. Bottom place in a two-dish ranking is 0.0.
        # Counting the cooldown-gated dish in the denominator — which is what
        # the bug did — would have made it (3-2)/2 = 0.5 instead.
        check("bottom of a two-dish ranking scores exactly 0.0",
              min(rewards2.values()) == 0.0, f"got {rewards2}")
        check("top of a two-dish ranking scores exactly 1.0",
              max(rewards2.values()) == 1.0, f"got {rewards2}")
        check("low availability weight ranks the recency pick first",
              rewards2[tuning._key(0.40)] == 0.0, f"got {rewards2}")
        check("high availability weight ranks the cooked dish first",
              rewards2[tuning._key(0.80)] == 1.0, f"got {rewards2}")


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

    # NaN/Infinity pass an isinstance check but freeze the learner silently:
    # every NaN comparison is False, so the hysteresis test can never fire.
    for label, bad in (("NaN", float("nan")), ("Infinity", float("inf"))):
        poisoned = copy.deepcopy(tuning.initialize_state())
        poisoned["S"][tuning._key(0.60)] = bad
        check(f"rejects {label} mass",
              tuning.validate_state(poisoned)["observations"] == 0)


def test_tuning_validate_state_rejects_unusable_candidates():
    print("\n-- tuning.validate_state (candidate list must be usable) --")
    # Every candidate is arithmetic input further down: select_deployed compares
    # it against BAND and compute_rewards blends with it. Checking the candidate
    # set by *filtering* non-numeric entries let a list that merely contained
    # the right values validate; the junk then raised TypeError inside
    # select_deployed, which register_cooked_meal swallows — so the learner
    # froze permanently with nothing but a log line to show for it.
    for label, bad in (
        ("a string", "junk"),
        ("None", None),
        ("a nested list", [0.5]),
        ("a bool", True),
        ("NaN", float("nan")),
    ):
        polluted = copy.deepcopy(tuning.initialize_state())
        polluted["candidates"] = [*tuning.CANDIDATES, bad]
        polluted["observations"] = 50
        restored = tuning.validate_state(polluted)
        check(f"rejects a candidate list containing {label}",
              restored["observations"] == 0, f"got {restored['candidates']}")
        # The whole point: whatever comes back must survive the real consumers.
        tuning.select_deployed(restored)

    duplicated = copy.deepcopy(tuning.initialize_state())
    duplicated["candidates"] = [*tuning.CANDIDATES, tuning.CANDIDATES[0]]
    duplicated["observations"] = 50
    check("rejects a duplicated candidate (a set comparison hid it)",
          tuning.validate_state(duplicated)["observations"] == 0)

    good = copy.deepcopy(tuning.initialize_state())
    good["observations"] = 50
    check("an intact candidate list still validates",
          tuning.validate_state(good) is good)


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
    # Sanity contrast: a normal cook does produce a reward dict. 'pasta' needs
    # optionals in stock, otherwise both dishes have an identical match term and
    # the ranking is weight-independent — which the uniform-reward guard skips.
    b.ingredients = {"noodles": True, "sauce": False, "basil": False, "cheese": False}
    rewards2 = tuning.compute_rewards(
        "rice bowl", dishes, fridge | {"sauce", "basil", "cheese"},
        {"rice bowl": 14, "pasta": 3}, tuning.CANDIDATES
    )
    check("normal cook produces rewards", isinstance(rewards2, dict) and len(rewards2) > 0)


# ---------------------------------------------------------------------------
# Dish repository rollback tests
# ---------------------------------------------------------------------------


def test_dish_repo_restore_adds_back():
    print("\n-- JsonDishRepository.restore (delta-rollback) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_dish_"))
    try:
        repo = _repos_mod.JsonDishRepository(tmp / "dishes.json")
        paella = Dish(name="paella", ingredients={"arroz": True, "azafran": False})
        stew = Dish(name="stew", ingredients={"beans": True})
        repo.save([paella, stew])

        # Simulate delete_dish having removed the row.
        repo.save([stew])
        check("dish is gone before restore", [d.name for d in repo.load()] == ["stew"])

        check("restore reports it re-added the dish", repo.restore(paella) is True)
        names = sorted(d.name for d in repo.load())
        check("dish is back in the catalog", names == ["paella", "stew"], f"got {names}")
        restored = next(d for d in repo.load() if d.name == "paella")
        check("ingredients survive the round trip",
              restored.ingredients == {"arroz": True, "azafran": False},
              f"got {restored.ingredients}")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def test_dish_repo_restore_is_a_noop_when_present():
    print("\n-- JsonDishRepository.restore (name already present) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_dish_"))
    try:
        repo = _repos_mod.JsonDishRepository(tmp / "dishes.json")
        original = Dish(name="paella", ingredients={"arroz": True})
        repo.save([original])

        # A concurrent writer already put a same-named dish back, so the
        # rollback must not fire and must not duplicate the row.
        replacement = Dish(name="paella", ingredients={"arroz": True, "pollo": True})
        check("restore declines when the name is present",
              repo.restore(replacement) is False)
        dishes = repo.load()
        check("no duplicate row was written", len(dishes) == 1, f"got {len(dishes)}")
        check("the stored dish is untouched",
              dishes[0].ingredients == {"arroz": True}, f"got {dishes[0].ingredients}")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# atomic_write_json tests
# ---------------------------------------------------------------------------


def test_atomic_write_json_cleans_up_on_failure():
    print("\n-- atomic_write_json (cleanup on failure) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_atomic_"))
    try:
        target = tmp / "state.json"
        target.write_text('{"kept": true}', encoding="utf-8")

        try:
            _src_mod.atomic_write_json(target, {"x": object()})
            check("non-serializable payload raises", False, "no exception")
        except TypeError:
            check("non-serializable payload raises", True)

        leftovers = [p.name for p in tmp.iterdir() if p.name.endswith(".tmp")]
        check("no temp file is left behind", leftovers == [], f"got {leftovers}")
        check("the pre-existing target is intact",
              target.read_text(encoding="utf-8") == '{"kept": true}',
              f"got {target.read_text(encoding='utf-8')!r}")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_write_json_replaces_existing():
    print("\n-- atomic_write_json (happy path) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_atomic_"))
    try:
        target = tmp / "nested" / "state.json"
        _src_mod.atomic_write_json(target, {"a": 1})
        check("parent directory is created lazily", target.exists())
        check("payload round-trips", json.loads(target.read_text(encoding="utf-8")) == {"a": 1})

        _src_mod.atomic_write_json(target, {"b": 2})
        check("target is replaced, not appended",
              json.loads(target.read_text(encoding="utf-8")) == {"b": 2})
        leftovers = [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")]
        check("no temp file survives a successful write", leftovers == [], f"got {leftovers}")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# DataDirLock tests
# ---------------------------------------------------------------------------


def _lock_in_tmp(tmp):
    return _filelock_mod.DataDirLock(tmp / ".lock")


def test_data_lock_is_reentrant():
    print("\n-- DataDirLock (reentrancy) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_lock_"))
    try:
        lock = _lock_in_tmp(tmp)
        check("starts unheld", lock._depth == 0)
        # Repository methods nest (save -> load_entries) and every repository
        # shares this one object, so a non-reentrant lock would deadlock here.
        with lock:
            check("depth 1 after first acquire", lock._depth == 1)
            with lock:
                check("depth 2 after nested acquire", lock._depth == 2)
                with lock:
                    check("depth 3 after third acquire", lock._depth == 3)
                check("depth unwinds to 2", lock._depth == 2)
            check("depth unwinds to 1", lock._depth == 1)
        check("depth unwinds to 0", lock._depth == 0)
        check("file descriptor released", lock._fd is None)
        check("lock file was created", (tmp / ".lock").exists())
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def test_data_lock_configure_rejects_while_held():
    print("\n-- DataDirLock (configure while held) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_lock_"))
    try:
        lock = _lock_in_tmp(tmp)
        with lock:
            try:
                lock.configure(tmp / "other.lock")
                check("configure while held rejected", False, "no exception")
            except RuntimeError:
                check("configure while held rejected", True)
            check("path unchanged after refusal", lock.path == tmp / ".lock")
        lock.configure(tmp / "other.lock")
        check("configure works once released", lock.path == tmp / "other.lock")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def test_data_lock_releases_on_exception():
    print("\n-- DataDirLock (release on exception) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_lock_"))
    try:
        lock = _lock_in_tmp(tmp)
        try:
            with lock:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        check("depth back to 0 after an exception", lock._depth == 0)
        check("fd released after an exception", lock._fd is None)
        with lock:
            check("a fresh acquisition still succeeds", lock._depth == 1)
        check("and unwinds again", lock._depth == 0)
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


_CHILD_PROBE = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("REFUSED")
else:
    print("ACQUIRED")
"""


def test_data_lock_excludes_another_process():
    print("\n-- DataDirLock (cross-process exclusion) --")
    if _filelock_mod.fcntl is None:
        print("  SKIP  fcntl unavailable on this platform")
        return
    import shutil as _shutil
    import subprocess
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_lock_"))
    try:
        lock = _lock_in_tmp(tmp)
        path = str(tmp / ".lock")

        def probe():
            # Non-blocking acquisition in the child, so it answers immediately
            # and the test never has to sleep to coordinate.
            done = subprocess.run(
                [sys.executable, "-c", _CHILD_PROBE, path],
                capture_output=True, text=True, timeout=30,
            )
            return done.stdout.strip()

        with lock:
            check("another process is refused while we hold it",
                  probe() == "REFUSED", "child was not blocked")
        check("another process acquires it once released",
              probe() == "ACQUIRED", "child could not acquire after release")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def test_repositories_share_one_lock():
    print("\n-- DataDirLock (shared across repositories) --")
    import shutil as _shutil
    import tempfile
    from pathlib import Path as _Path
    shared = _filelock_mod.data_lock
    check("dish and fridge share one lock object",
          _repos_mod.dish_repo.lock is _repos_mod.fridge_repo.lock)
    check("tuning shares it too", _repos_mod.tuning_repo.lock is shared)
    check("alias shares it too", _repos_mod.alias_repo.lock is shared)
    check("history shares it too", _repos_mod.history_repo._lock is shared)

    # configure() redirects the singletons globally, so put the paths back.
    previous = _repos_mod.dish_repo.path.parent
    tmp = _Path(tempfile.mkdtemp(prefix="mm_lock_cfg_"))
    try:
        _repos_mod.configure(tmp)
        check("configure moves the lock into the new data dir",
              shared.path == tmp / ".lock", f"got {shared.path}")
    finally:
        _repos_mod.configure(previous)
        _shutil.rmtree(tmp, ignore_errors=True)
    check("configure restores the previous lock path",
          shared.path == previous / ".lock", f"got {shared.path}")


def _run_all():
    run(test_dish_normalize_ingredient)
    run(test_dish_normalize_name)
    run(test_dish_can_cook_with)
    run(test_dish_can_cook_with_no_ingredients)
    run(test_dish_can_cook_with_only_optional)
    run(test_dish_to_dict)
    run(test_dish_from_dict)
    run(test_dish_from_dict_invalid)
    run(test_dish_add_ingredient)
    run(test_dish_add_ingredient_validation)
    run(test_dish_ingredient_keys_normalized_on_construction)
    run(test_dish_rejects_colliding_ingredient_keys)
    run(test_dish_instructions)

    run(test_calculate_score_basic)
    run(test_calculate_score_cooldown)
    run(test_calculate_score_no_ingredients)
    run(test_calculate_score_partial_ingredients)
    run(test_calculate_score_declaring_optionals_never_penalizes)
    run(test_calculate_score_match_depends_on_present_count_only)
    run(test_calculate_score_recency_scaling)
    run(test_score_components_agree_with_calculate_score)

    run(test_suggest_dishes_basic)
    run(test_suggest_dishes_excludes_recent)
    run(test_suggest_dishes_default_recency)

    run(test_suggest_quick_shopping_basic)
    run(test_suggest_quick_shopping_two_missing)
    run(test_suggest_quick_shopping_groups_by_ingredient)
    run(test_suggest_quick_shopping_max_missing)
    run(test_suggest_quick_shopping_ranks_by_reach)
    run(test_suggest_quick_shopping_prefers_cheapest_basket)
    run(test_suggest_quick_shopping_score_matches_cheapest_unlock)

    run(test_fridge_repository_counts)
    run(test_fridge_unreadable_file_degrades_quietly)
    run(test_fridge_repository_non_finite_counts)

    run(test_expiry_status)
    run(test_fridge_entries_grammar)
    run(test_fridge_mutations_preserve_expiry)
    run(test_normalize_ingredient_entries)

    run(test_alias_repository)

    run(test_dish_repo_restore_adds_back)
    run(test_dish_repo_restore_is_a_noop_when_present)

    run(test_atomic_write_json_cleans_up_on_failure)
    run(test_atomic_write_preserves_file_mode)
    run(test_atomic_write_sweeps_stale_temps)
    run(test_dii_session_from_dict_validates)
    run(test_dii_finalizer_essential_wins)
    run(test_atomic_write_json_replaces_existing)

    # -- DataDirLock --
    run(test_data_lock_is_reentrant)
    run(test_data_lock_configure_rejects_while_held)
    run(test_data_lock_releases_on_exception)
    run(test_data_lock_excludes_another_process)
    run(test_repositories_share_one_lock)

    run(test_cooking_event_from_dict_strict)
    run(test_history_projects_latest_per_dish)
    run(test_history_older_event_cannot_rewind_the_cooldown)
    run(test_history_retract_versus_delete)
    run(test_history_legacy_migration)
    run(test_history_corruption)

    run(test_normalize_ingredients_dict)
    run(test_normalize_ingredients_list)
    run(test_normalize_ingredients_json_string_dict)
    run(test_normalize_ingredients_json_string_list)
    run(test_normalize_ingredients_invalid)
    run(test_normalize_ingredients_empty_rejected)
    run(test_normalize_ingredients_dedup_under_limit)
    run(test_normalize_ingredients_rejects_colliding_dict_keys)
    run(test_normalize_ingredient_names)

    run(test_reject_unknown_args)
    run(test_tool_handler_validates_against_schema)
    run(test_safe_error_message)
    run(test_tool_handler_sanitizes_envelope)

    run(test_tuning_initial_state)
    run(test_tuning_deployed_weights_fallback)
    run(test_tuning_deployed_weights_clamps_out_of_band)
    run(test_tuning_validate_state)
    run(test_tuning_validate_state_corruption_branches)
    run(test_tuning_validate_state_rejects_unusable_candidates)
    run(test_tuning_compute_rewards_not_cookable)
    run(test_tuning_compute_rewards_single_dish)
    run(test_tuning_compute_rewards_top_rank)
    run(test_tuning_compute_rewards_uniform_skipped)
    run(test_tuning_compute_rewards_no_signal)
    run(test_tuning_apply_update_pure)
    run(test_tuning_cold_start)
    run(test_tuning_shift_after_warmup)
    run(test_tuning_hysteresis)

    # Regression tests for the code-review findings.
    run(test_dish_rejects_invalid_ingredient_values)
    run(test_alias_repository_cache_invalidation)
    run(test_tuning_deployed_weight_off_grid)
    run(test_tuning_reward_denominator_uses_ranking_size)

    # Repository automation: the hook and the workflow still gate what they say.
    run(test_pre_commit_hook_exists_and_is_executable)
    run(test_pre_commit_hook_runs_both_suites)
    run(test_pre_commit_hook_needs_nothing_installed)
    run(test_ci_runs_both_suites)
    run(test_ci_matrix_covers_the_declared_python_floor)
    run(test_ci_actions_are_pinned_to_full_shas)
    run(test_every_ci_job_feeds_the_gate)
    run(test_ci_checks_the_suites_left_the_checkout_untouched)


def test_fridge_unreadable_file_degrades_quietly():
    print("\n-- JsonFridgeRepository (unreadable file degrades) --")
    import os
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_fridge_"))
    try:
        path = tmp / "fridge.json"
        repo = _repos_mod.JsonFridgeRepository(path)
        repo.save({"onion": 2})
        os.chmod(path, 0o000)
        if os.access(path, os.R_OK):  # running as root — the probe is meaningless
            print("  SKIP  unreadable-file probe (running with override access)")
            return
        # An OSError used to escape load_entries, making fridge.json the only
        # data file whose permissions glitch produced an error envelope while
        # dishes/history/aliases/tuning all degraded to empty.
        check("unreadable fridge loads as empty, not an exception",
              repo.load_entries() == {} and repo.load() == {})
        check("load_set degrades too", repo.load_set() == set())
    finally:
        import contextlib as _contextlib
        import shutil as _shutil
        with _contextlib.suppress(OSError):
            os.chmod(tmp / "fridge.json", 0o644)
        _shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_write_preserves_file_mode():
    print("\n-- atomic_write_json (keeps the target's permissions) --")
    import os
    import stat as _stat
    import tempfile
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_atomic_"))
    try:
        path = tmp / "data.json"
        path.write_text("{}")
        os.chmod(path, 0o644)
        _src_mod.atomic_write_json(path, {"a": 1})
        # mkstemp creates 0600 and os.replace carries that onto the target, so
        # every write through here used to silently narrow the file.
        check("existing mode survives the replace",
              _stat.S_IMODE(path.stat().st_mode) == 0o644,
              f"got {oct(_stat.S_IMODE(path.stat().st_mode))}")

        fresh = tmp / "fresh.json"
        _src_mod.atomic_write_json(fresh, {"b": 2})
        check("a brand-new file is not owner-only",
              _stat.S_IMODE(fresh.stat().st_mode) == 0o644,
              f"got {oct(_stat.S_IMODE(fresh.stat().st_mode))}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_atomic_write_sweeps_stale_temps():
    print("\n-- atomic_write_json (sweeps orphaned temp files) --")
    import os
    import tempfile
    import time as _time
    from pathlib import Path as _Path
    tmp = _Path(tempfile.mkdtemp(prefix="mm_atomic_"))
    try:
        # A write killed between mkstemp and os.replace leaves this behind, and
        # nothing else ever scans the data directory.
        stale = tmp / f"{_src_mod._TMP_PREFIX}dead{_src_mod._TMP_SUFFIX}"
        stale.write_text("{}")
        old = _time.time() - _src_mod._STALE_TMP_SECONDS - 60
        os.utime(stale, (old, old))

        fresh = tmp / f"{_src_mod._TMP_PREFIX}live{_src_mod._TMP_SUFFIX}"
        fresh.write_text("{}")

        unrelated = tmp / "notours.tmp"
        unrelated.write_text("{}")

        _src_mod.atomic_write_json(tmp / "data.json", {"a": 1})

        check("stale temp file is removed", not stale.exists())
        check("a temp file that could still be in flight is left alone",
              fresh.exists())
        check("temp files this module did not create are never touched",
              unrelated.exists())
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


def test_dii_session_from_dict_validates():
    print("\n-- dii.session.from_dict (validates a restored backup) --")
    _session_mod = importlib.import_module(".src.dii.session", _PLUGIN_DIR.name)
    base = {
        "session_id": "abc123",
        "dish_name": "Stew",
        "essential_ingredients": ["beef"],
        "optional_ingredients": [],
        "hidden_queue": [],
        "current_suggestion": None,
        "created_at": "2026-07-28T00:00:00+00:00",
        "last_activity": "2026-07-28T00:00:00+00:00",
        "finalized": False,
        "pending_recalculation": False,
    }
    ok = _session_mod.from_dict(base)
    check("a well-formed backup round-trips", ok.essential_ingredients == ["beef"])
    check("dish name is normalized on restore", ok.dish_name == "stew")

    # The lists are mutually exclusive by design. A backup carrying a name in
    # both used to reach the finalizer, whose map union resolved the collision
    # as optional — demoting an essential and letting can_cook_with approve a
    # dish the user cannot make.
    both = {**base, "optional_ingredients": ["beef", "thyme"]}
    resolved = _session_mod.from_dict(both)
    check("essential wins when a backup lists a name in both",
          resolved.essential_ingredients == ["beef"]
          and resolved.optional_ingredients == ["thyme"],
          f"got {resolved.essential_ingredients} / {resolved.optional_ingredients}")

    # The engine indexes item["ingredient"] directly; a queue entry without it
    # surfaced to the user as {"error": "'ingredient'"}.
    for label, bad in (
        ("a queue entry with no 'ingredient'", {"hidden_queue": [{"is_essential": True}]}),
        ("a non-object queue entry", {"hidden_queue": ["beef"]}),
        ("a non-bool is_essential", {"hidden_queue": [{"ingredient": "x", "is_essential": 1}]}),
        ("a malformed current_suggestion", {"current_suggestion": {"nope": 1}}),
        ("a non-list ingredient field", {"essential_ingredients": "beef"}),
        ("a non-string ingredient", {"essential_ingredients": [7]}),
        ("a non-bool finalized", {"finalized": "yes"}),
    ):
        try:
            _session_mod.from_dict({**base, **bad})
            check(f"rejects {label}", False, "no error raised")
        except (KeyError, TypeError, ValueError):
            # The store treats any of these as a corrupt backup and unlinks it.
            check(f"rejects {label}", True)


def test_dii_finalizer_essential_wins():
    print("\n-- dii.finalizer (essential wins over optional) --")
    import tempfile
    from pathlib import Path as _Path
    _session_mod = importlib.import_module(".src.dii.session", _PLUGIN_DIR.name)
    _finalizer_mod = importlib.import_module(".src.dii.finalizer", _PLUGIN_DIR.name)
    tmp = _Path(tempfile.mkdtemp(prefix="mm_final_"))
    try:
        dish_repo = _repos_mod.JsonDishRepository(tmp / "dishes.json")
        fridge_repo = _repos_mod.JsonFridgeRepository(tmp / "fridge.json")
        session = _session_mod.DIISession(
            session_id="s1",
            dish_name="stew",
            essential_ingredients=["beef"],
            optional_ingredients=["beef", "thyme"],
        )
        _finalizer_mod.commit(
            session,
            commit_to_fridge=False,
            commit_to_dish=True,
            dish_repo=dish_repo,
            fridge_repo=fridge_repo,
        )
        stored = dish_repo.load()[0]
        check("a name in both lists commits as essential",
              stored.ingredients == {"beef": True, "thyme": False},
              f"got {stored.ingredients}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Repository automation
#
# Not domain logic: these read files in the checkout. They live in this script
# because the repo has two, and this is the one that runs without fixtures.
#
# They cover a class of failure that never announces itself. A hook that lost
# its executable bit, a workflow renamed, a job added but left out of
# `ci-complete`'s `needs:` — none of those produce an error. They stop gating,
# quietly, and the first sign is a broken main.
# ---------------------------------------------------------------------------

_HOOK = _PLUGIN_DIR / ".githooks" / "pre-commit"
_WORKFLOW = _PLUGIN_DIR / ".github" / "workflows" / "tests.yml"
_SUITES = ("test_unit.py", "test_integration.py")


def _workflow_text():
    return _WORKFLOW.read_text(encoding="utf-8")


def _workflow_jobs():
    """Top-level job names: the two-space-indented bare keys under `jobs:`.

    Split on `jobs:` first — `permissions:` and `concurrency:` also carry
    two-space keys, and they sit above it.
    """
    import re

    body = _workflow_text().split("\njobs:\n", 1)[1]
    return [m.group(1) for m in re.finditer(r"^  ([A-Za-z0-9_-]+):$", body, re.M)]


def test_pre_commit_hook_exists_and_is_executable():
    print("\n-- .githooks/pre-commit (present, executable) --")
    import os

    check("the hook is committed", _HOOK.is_file(), f"missing {_HOOK}")
    check("the hook is executable", os.access(_HOOK, os.X_OK),
          "git skips a hook without the executable bit, and says nothing")


def test_pre_commit_hook_runs_both_suites():
    print("\n-- .githooks/pre-commit (runs both suites) --")
    text = _HOOK.read_text(encoding="utf-8")
    for suite in _SUITES:
        check(f"the hook runs {suite}", suite in text, "not referenced")
    check("the hook says how to install itself", "core.hooksPath" in text,
          "it is versioned but does not activate on its own")


def test_pre_commit_hook_needs_nothing_installed():
    print("\n-- .githooks/pre-commit (no virtualenv) --")
    # Naming mypy or coverage in a comment is fine; invoking them is not. A
    # hook that fails on a clean clone is a hook people turn off.
    commands = [ln for ln in _HOOK.read_text(encoding="utf-8").splitlines()
                if not ln.lstrip().startswith("#")]
    for tool in ("pip ", "mypy", "coverage", ".venv"):
        check(f"the hook does not invoke {tool.strip()}",
              not any(tool in ln for ln in commands),
              "those live in CI, which is where the gate is")


def test_ci_runs_both_suites():
    print("\n-- tests.yml (runs both suites) --")
    text = _workflow_text()
    for suite in _SUITES:
        check(f"CI runs {suite}", f"python3 {suite}" in text, "not invoked")


def test_ci_matrix_covers_the_declared_python_floor():
    print("\n-- tests.yml (matrix covers the declared floor) --")
    import re

    declared = re.search(r"Python (\d+\.\d+)\+",
                         (_PLUGIN_DIR / "AGENTS.md").read_text(encoding="utf-8"))
    check("AGENTS.md still declares a minimum", declared is not None,
          "no 'Python X.Y+' found, so there is nothing to hold CI to")
    if declared:
        floor = declared.group(1)
        # Scoped to the matrix list on purpose: the `types` and `coverage` jobs
        # also name a python-version, so a substring search over the whole file
        # passes even after the floor is dropped from the matrix.
        listed = re.search(r"python-version: \[([^\]]*)\]", _workflow_text())
        versions = {v.strip().strip("\"'") for v in listed.group(1).split(",")} \
            if listed else set()
        check(f"the matrix includes the floor {floor}", floor in versions,
              f"the declared minimum is the one version that must be tested; "
              f"matrix is {sorted(versions)}")


def test_ci_actions_are_pinned_to_full_shas():
    print("\n-- tests.yml (actions pinned to SHAs) --")
    import re

    refs = re.findall(r"^\s*- uses: \S+@(\S+)", _workflow_text(), re.M)
    check("there are actions to check", bool(refs), "no `uses:` lines found")
    for ref in refs:
        check(f"{ref[:12]}... is a full commit SHA",
              re.fullmatch(r"[0-9a-f]{40}", ref) is not None,
              "a tag can be repointed by its owner; a commit SHA cannot")


def test_every_ci_job_feeds_the_gate():
    print("\n-- tests.yml (every job feeds ci-complete) --")
    import re

    jobs = _workflow_jobs()
    check("the gate job exists", "ci-complete" in jobs, f"jobs found: {jobs}")
    needs = re.search(r"needs: \[([^\]]*)\]", _workflow_text())
    listed = {n.strip() for n in needs.group(1).split(",")} if needs else set()
    missing = [j for j in jobs if j != "ci-complete" and j not in listed]
    check("no job gates nothing", not missing,
          f"{missing} missing from ci-complete's needs: main requires that one "
          "check, so a job outside it cannot block a merge")


def test_ci_checks_the_suites_left_the_checkout_untouched():
    print("\n-- tests.yml (checkout untouched) --")
    text = _workflow_text()
    check("CI checks data/ was not created", "if [ -e data ]" in text,
          "data/ is gitignored, so git status alone would not notice it")
    check("CI checks the tree is clean", "git status --porcelain" in text,
          "catches a suite writing anywhere else in the checkout")


def main():
    # Every repository shares one lock object, and its path is global state: a
    # repository constructed against a tmp path still locks whatever data_lock
    # currently points at. Without this redirect the tests that build their own
    # repositories would create and flock <plugin_root>/data/.lock — and
    # AGENTS.md is explicit that tests never touch the real data/.
    original_data_dir = _repos_mod.dish_repo.path.parent
    run_tmp = Path(tempfile.mkdtemp(prefix="mm_unit_"))
    _repos_mod.configure(run_tmp)
    try:
        _run_all()
    finally:
        _repos_mod.configure(original_data_dir)
        shutil.rmtree(run_tmp, ignore_errors=True)

    print(f"\n{'='*40}")
    print(f"  {_passed} passed, {_failed} failed")
    print(f"{'='*40}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
