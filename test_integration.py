"""Integration smoke test for all 26 meal_manager tools.

The test creates a throw-away data directory under ``tempfile.gettempdir()``
and points the repositories + DII session store at it via the package-level
``configure()`` entry points. The real ``data/`` directory is never touched,
so the script is safe to run concurrently and never pollutes live state.

Usage:
    python3 test_integration.py
"""

import importlib
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: make relative imports work when running standalone.
# We import the plugin directory as a package so that internal relative
# imports (e.g. ``from .src.repositories import dish_repo``) resolve correctly.
# ---------------------------------------------------------------------------

_PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_PLUGIN_DIR.parent))
_pkg = importlib.import_module(_PLUGIN_DIR.name)

_repos_mod = importlib.import_module(".src.repositories", _PLUGIN_DIR.name)
_dii_mod = importlib.import_module(".src.dii", _PLUGIN_DIR.name)
_tuning_mod = importlib.import_module(".src.tuning", _PLUGIN_DIR.name)
_handlers_common = importlib.import_module(".src.handlers._common", _PLUGIN_DIR.name)
_handlers_pkg = importlib.import_module(".src.handlers", _PLUGIN_DIR.name)

# ---------------------------------------------------------------------------
# Tmp data directory lifecycle
# ---------------------------------------------------------------------------

_DATA_FILES = ["dishes.json", "fridge.json", "history.json", "tuning.json"]
_TMP_DATA_DIR: Path | None = None


def _setup_tmp_data():
    """Create a tmp data dir, seed it, and point the package at it.

    Called once before any handler runs. ``_repos_mod.configure`` mutates
    the singleton ``path`` attributes in place, so every handler module
    that already captured ``dish_repo`` / ``fridge_repo`` / ``history_repo``
    at import time transparently starts reading/writing here.
    """
    global _TMP_DATA_DIR
    _TMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="meal_manager_test_"))
    (_TMP_DATA_DIR / "sessions").mkdir(parents=True, exist_ok=True)
    _repos_mod.configure(_TMP_DATA_DIR)
    _dii_mod.configure(_TMP_DATA_DIR / "sessions")
    _seed()


def _teardown_tmp_data():
    """Remove the tmp directory entirely — nothing on disk needs restoring."""
    global _TMP_DATA_DIR
    if _TMP_DATA_DIR is not None and _TMP_DATA_DIR.exists():
        shutil.rmtree(_TMP_DATA_DIR)
    _TMP_DATA_DIR = None


# Backwards-compatible aliases so external harnesses (and the AGENTS.md
# single-test recipe) keep working without edits.
_backup = _setup_tmp_data
_restore = _teardown_tmp_data


# ---------------------------------------------------------------------------
# Seed data for a clean test environment
# ---------------------------------------------------------------------------

def _seed():
    """Write known initial state so tests are deterministic."""
    assert _TMP_DATA_DIR is not None, "_setup_tmp_data must run before _seed"

    (_TMP_DATA_DIR / "dishes.json").write_text(json.dumps({
        "dishes": [
            {
                "name": "Arroz con Pollo",
                "ingredients": {"arroz": True, "pollo": True, "pimientos": False},
            },
            {
                "name": "Tortilla de patatas",
                "ingredients": {"huevos": True, "patatas": True, "cebolla": False},
            },
        ]
    }, ensure_ascii=False), encoding="utf-8")

    (_TMP_DATA_DIR / "fridge.json").write_text(
        json.dumps(["arroz", "patatas"], ensure_ascii=False), encoding="utf-8"
    )

    (_TMP_DATA_DIR / "history.json").write_text(
        json.dumps({"tortilla de patatas": "2026-03-20"}, ensure_ascii=False),
        encoding="utf-8",
    )

    # Clean sessions on re-seed (single-test helpers may call _seed again).
    sessions = _TMP_DATA_DIR / "sessions"
    if sessions.exists():
        shutil.rmtree(sessions)
    sessions.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Assertion helper
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


def parse(raw: str) -> Any:
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Import tools (after path setup)
# ---------------------------------------------------------------------------


def _load_handler(module_suffix: str):
    """Import a handler module and return its HANDLER callable."""
    mod = importlib.import_module(f".src.handlers.{module_suffix}", _PLUGIN_DIR.name)
    return mod.HANDLER


get_meal_suggestions = _load_handler("get_meal_suggestions")
get_quick_shopping_list = _load_handler("get_quick_shopping_list")
get_missing_for_dish = _load_handler("get_missing_for_dish")
update_fridge_inventory = _load_handler("update_fridge_inventory")
register_cooked_meal = _load_handler("register_cooked_meal")
delete_history_entry = _load_handler("delete_history_entry")
list_fridge = _load_handler("list_fridge")
add_dish = _load_handler("add_dish")
add_dishes_batch = _load_handler("add_dishes_batch")
delete_dish = _load_handler("delete_dish")
edit_dish = _load_handler("edit_dish")
clear_fridge = _load_handler("clear_fridge")
init_ingredient_session = _load_handler("init_ingredient_session")
dii_add_suggested = _load_handler("dii_add_suggested")
dii_skip_suggested = _load_handler("dii_skip_suggested")
dii_remove_ingredient = _load_handler("dii_remove_ingredient")
dii_add_manual = _load_handler("dii_add_manual")
dii_clear_all = _load_handler("dii_clear_all")
finalize_ingredient_session = _load_handler("finalize_ingredient_session")
dii_get_state = _load_handler("dii_get_state")
get_tuning_state = _load_handler("get_tuning_state")
set_dish_instructions = _load_handler("set_dish_instructions")
get_dish_recipe = _load_handler("get_dish_recipe")
list_cooking_history = _load_handler("list_cooking_history")
merge_ingredient_alias = _load_handler("merge_ingredient_alias")
list_ingredient_aliases = _load_handler("list_ingredient_aliases")

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_fridge():
    print("\n-- list_fridge --")
    result = parse(list_fridge({}))
    check("returns the in_stock/out_of_stock shape",
          set(result) == {"in_stock", "out_of_stock", "expiry", "expiring_soon",
                          "expired"}, f"got {result}")
    check("no expiry recorded for the seeded legacy file",
          result["expiry"] == {} and result["expiring_soon"] == []
          and result["expired"] == [], f"got {result}")
    in_stock = result["in_stock"]
    check("contains seeded items", "arroz" in in_stock and "patatas" in in_stock)
    check("has exactly 2 items", len(in_stock) == 2, f"got {in_stock}")
    check("legacy list seeded one portion each",
          in_stock == {"arroz": 1, "patatas": 1}, f"got {in_stock}")
    check("nothing out of stock yet", result["out_of_stock"] == [], f"got {result}")


def test_update_fridge_add():
    print("\n-- update_fridge_inventory (add) --")
    result = parse(update_fridge_inventory({"action": "add", "ingredients": ["pollo", "huevos"]}))
    check("returns success string", isinstance(result, str) and "error" not in result.lower())

    fridge = parse(list_fridge({}))["in_stock"]
    check("pollo added", fridge.get("pollo") == 1, f"got {fridge}")
    check("huevos added", fridge.get("huevos") == 1, f"got {fridge}")
    check("originals preserved", "arroz" in fridge and "patatas" in fridge)


def test_update_fridge_add_duplicate():
    print("\n-- update_fridge_inventory (add duplicate) --")
    result = parse(update_fridge_inventory({"action": "add", "ingredients": ["pollo"]}))
    check("returns success string", isinstance(result, str) and "error" not in result.lower(),
          f"got {result}")
    # Adding an ingredient already present now accumulates portions rather than
    # being a no-op — one more pollo means one more dish's worth.
    fridge = parse(list_fridge({}))["in_stock"]
    check("adding again accumulates portions", fridge.get("pollo") == 2, f"got {fridge}")
    # Put it back to one portion so the tests that follow see the historical state.
    update_fridge_inventory({"action": "set", "ingredients": {"pollo": 1}})
    check("set restores one portion",
          parse(list_fridge({}))["in_stock"].get("pollo") == 1)


def test_fridge_legacy_list_migrates():
    print("\n-- fridge (legacy list migrates to counts) --")
    fridge = _repos_mod.fridge_repo.load()
    check("legacy list loads as a dict", isinstance(fridge, dict), f"got {fridge}")
    check("each legacy name becomes one portion",
          fridge.get("arroz") == 1 and fridge.get("patatas") == 1, f"got {fridge}")


def test_fridge_counts_and_staples():
    print("\n-- fridge (counts, staples, set) --")
    update_fridge_inventory({"action": "add", "ingredients": {"cebolla": 3}})
    check("count is stored", _repos_mod.fridge_repo.load().get("cebolla") == 3)

    update_fridge_inventory({"action": "add", "ingredients": {"cebolla": 2}})
    check("add accumulates", _repos_mod.fridge_repo.load().get("cebolla") == 5)

    update_fridge_inventory({"action": "set", "ingredients": {"cebolla": 1}})
    check("set overwrites", _repos_mod.fridge_repo.load().get("cebolla") == 1)

    # 'pimenton' rather than 'sal': the DII tests below commit 'sal' to the
    # fridge and assert it was a fresh addition.
    update_fridge_inventory({"action": "add", "ingredients": {"pimenton": None}})
    check("null marks a staple", _repos_mod.fridge_repo.load().get("pimenton") is None)
    update_fridge_inventory({"action": "add", "ingredients": {"pimenton": 5}})
    check("adding to a staple is a no-op",
          _repos_mod.fridge_repo.load().get("pimenton") is None)

    bad = parse(update_fridge_inventory({"action": "add", "ingredients": {"x": -1}}))
    check("rejects negative counts", "error" in bad, f"got {bad}")


def test_cook_decrements_instead_of_deleting():
    print("\n-- register_cooked_meal (decrements) --")
    add_dish({"name": "Count Dish", "ingredients": {"cnt_a": True, "cnt_b": True}})
    update_fridge_inventory({"action": "set",
                             "ingredients": {"cnt_a": 3, "cnt_b": None}})

    register_cooked_meal({"dish_name": "Count Dish"})
    fridge = _repos_mod.fridge_repo.load()
    check("essential is decremented, not deleted", fridge.get("cnt_a") == 2, f"got {fridge}")
    check("staple is untouched", fridge.get("cnt_b") is None, f"got {fridge}")
    check("still cookable after one cook", "cnt_a" in _repos_mod.fridge_repo.load_set())

    # Drain it and confirm the zero entry is kept and excluded from availability.
    update_fridge_inventory({"action": "set", "ingredients": {"cnt_a": 1}})
    _repos_mod.history_repo.retract_all_for_dish("count dish")
    register_cooked_meal({"dish_name": "Count Dish"})
    check("count floors at zero", _repos_mod.fridge_repo.load().get("cnt_a") == 0)
    check("zero-count entry is not available",
          "cnt_a" not in _repos_mod.fridge_repo.load_set())


def test_register_cooked_meal_backdated():
    print("\n-- register_cooked_meal (backdated) --")
    from datetime import date as _date, timedelta as _timedelta
    add_dish({"name": "Backdate Dish", "ingredients": {"bd_a": True}})
    update_fridge_inventory({"action": "set", "ingredients": {"bd_a": 2}})

    past = (_date.today() - _timedelta(days=4)).isoformat()
    result = parse(register_cooked_meal({"dish_name": "Backdate Dish", "date": past}))
    check("backdated cook succeeds", "error" not in str(result), f"got {result}")
    check("history records the given date",
          _repos_mod.history_repo.load().get("backdate dish") == past,
          f"got {_repos_mod.history_repo.load()}")
    check("fridge is still consumed",
          _repos_mod.fridge_repo.load().get("bd_a") == 1,
          f"got {_repos_mod.fridge_repo.load()}")

    future = (_date.today() + _timedelta(days=1)).isoformat()
    bad = parse(register_cooked_meal({"dish_name": "Backdate Dish", "date": future}))
    check("future date rejected", "error" in bad, f"got {bad}")
    bad2 = parse(register_cooked_meal({"dish_name": "Backdate Dish", "date": "not-a-date"}))
    check("malformed date rejected", "error" in bad2, f"got {bad2}")


def test_register_cooked_meal_backdate_preserves_newer():
    print("\n-- register_cooked_meal (backdating keeps the newer entry) --")
    from datetime import date as _date, timedelta as _timedelta
    add_dish({"name": "Paella Reciente", "ingredients": {"pr_a": True}})
    update_fridge_inventory({"action": "set", "ingredients": {"pr_a": 10}})

    register_cooked_meal({"dish_name": "Paella Reciente"})
    today = _date.today().isoformat()
    check("today's cook recorded",
          _repos_mod.history_repo.load().get("paella reciente") == today)

    # Recording a forgotten meal from a month ago must not erase this morning's
    # cook and hand the dish back to the engine inside its cooldown window.
    old = (_date.today() - _timedelta(days=30)).isoformat()
    result = parse(register_cooked_meal({"dish_name": "Paella Reciente", "date": old}))
    check("backdated cook still succeeds", "error" not in str(result), f"got {result}")
    check("newer history entry preserved",
          _repos_mod.history_repo.load().get("paella reciente") == today,
          f"got {_repos_mod.history_repo.load()}")
    check("response explains the entry was kept",
          "more recent" in result, f"got {result}")
    check("fridge still consumed for the backdated meal",
          _repos_mod.fridge_repo.load().get("pr_a") == 8,
          f"got {_repos_mod.fridge_repo.load()}")
    check("dish stays gated by the cooldown",
          not any(s["dish"] == "paella reciente" for s in parse(get_meal_suggestions({}))),
          f"got {parse(get_meal_suggestions({}))}")

    # A genuinely older-then-newer sequence still advances normally.
    register_cooked_meal({"dish_name": "Paella Reciente"})
    check("same-day re-register is fine",
          _repos_mod.history_repo.load().get("paella reciente") == today)


def test_update_fridge_remove_ignores_counts():
    print("\n-- update_fridge_inventory (remove ignores portion counts) --")
    update_fridge_inventory({"action": "set", "ingredients": {"rm_a": 3, "rm_b": 1}})
    # Echoing back a count seen in list_fridge used to fail removal on a limit
    # that does not apply to it.
    result = parse(update_fridge_inventory({
        "action": "remove", "ingredients": {"rm_a": 500}}))
    check("removal with an out-of-range count succeeds",
          isinstance(result, str) and "removed" in result.lower(), f"got {result}")
    check("entry actually gone", "rm_a" not in _repos_mod.fridge_repo.load())
    result2 = parse(update_fridge_inventory({
        "action": "remove", "ingredients": {"rm_b": None}}))
    check("removal with a null count succeeds",
          isinstance(result2, str) and "removed" in result2.lower(), f"got {result2}")
    # 'add' and 'set' still police counts, where they do mean something.
    bad = parse(update_fridge_inventory({"action": "add", "ingredients": {"rm_c": 500}}))
    check("add still rejects out-of-range counts", "error" in bad, f"got {bad}")


def test_update_fridge_remove():
    print("\n-- update_fridge_inventory (remove) --")
    result = parse(update_fridge_inventory({"action": "remove", "ingredients": ["huevos"]}))
    check("returns success string", isinstance(result, str) and "removed" in result.lower())

    fridge = parse(list_fridge({}))
    check("huevos removed", "huevos" not in fridge["in_stock"], f"got {fridge}")
    check("remove deletes outright rather than zeroing",
          "huevos" not in fridge["out_of_stock"], f"got {fridge}")


def test_get_meal_suggestions():
    print("\n-- get_meal_suggestions --")
    # Fridge now has: arroz, patatas, pollo (huevos removed above)
    result = parse(get_meal_suggestions({}))
    check("returns a list", isinstance(result, list))
    check("arroz con pollo suggested",
          any(s["dish"].lower() == "arroz con pollo" for s in result),
          f"got {result}")
    # Tortilla needs huevos (removed), should not appear
    check("tortilla not suggested (missing huevos)", not any("tortilla" in s["dish"] for s in result))


def test_get_quick_shopping_list():
    print("\n-- get_quick_shopping_list --")
    result = parse(get_quick_shopping_list({}))
    check("returns a list", isinstance(result, list))
    # Tortilla needs huevos (one essential missing) -- should appear
    check("huevos unlocks tortilla",
          any(s["missing_ingredient"] == "huevos" for s in result),
          f"got {result}")


def test_get_quick_shopping_list_max_missing():
    print("\n-- get_quick_shopping_list (max_missing) --")
    result = parse(get_quick_shopping_list({"max_missing": 2}))
    check("returns a list", isinstance(result, list), f"got {result}")
    check("rows carry the new fields",
          all({"missing_ingredient", "unlocks_dishes", "unlocks_count",
               "still_missing", "score"} == set(r.keys()) for r in result),
          f"got {result}")
    bad = parse(get_quick_shopping_list({"max_missing": 0}))
    check("rejects out-of-range threshold", "error" in bad, f"got {bad}")
    bad2 = parse(get_quick_shopping_list({"max_missing": "two"}))
    check("rejects non-integer threshold", "error" in bad2, f"got {bad2}")


def test_get_missing_for_dish():
    print("\n-- get_missing_for_dish --")
    result = parse(get_missing_for_dish({"dish_name": "Arroz con Pollo"}))
    check("reports the dish", result.get("dish") == "arroz con pollo", f"got {result}")
    check("pollo is missing", "pollo" in result.get("missing_essential", []), f"got {result}")
    check("pimientos is a missing optional",
          "pimientos" in result.get("missing_optional", []), f"got {result}")
    check("not cookable", result.get("cookable") is False, f"got {result}")
    bogus = parse(get_missing_for_dish({"dish_name": "no such dish"}))
    check("unknown dish errors", "error" in bogus, f"got {bogus}")


def test_register_cooked_meal():
    print("\n-- register_cooked_meal --")
    result = parse(register_cooked_meal({"dish_name": "arroz con pollo"}))
    check("success message", isinstance(result, str) and "registered" in result.lower(),
          f"got: {result}")
    fridge = parse(list_fridge({}))
    # Both essentials were at one portion, so cooking drains them to zero: they
    # leave in_stock but are remembered as run-out rather than deleted.
    check("consumes essentials from fridge",
          "arroz" not in fridge["in_stock"] and "pollo" not in fridge["in_stock"],
          f"got {fridge}")
    check("drained essentials are remembered as out of stock",
          "arroz" in fridge["out_of_stock"] and "pollo" in fridge["out_of_stock"],
          f"got {fridge}")


def test_register_cooked_meal_bogus():
    print("\n-- register_cooked_meal (nonexistent dish) --")
    result = parse(register_cooked_meal({"dish_name": "Plato Inventado"}))
    check("returns error", isinstance(result, dict) and "error" in result, f"got: {result}")
    # Sanitizing the envelope must not over-reach: a LookupError raised
    # deliberately by a handler is user-facing text and stays verbatim.
    check("LookupError message survives sanitization",
          "Plato Inventado" in result.get("error", "")
          and "catalog" in result.get("error", ""), f"got: {result}")


def test_register_cooked_meal_rollback():
    print("\n-- register_cooked_meal (rollback) --")
    before = _repos_mod.history_repo.load()

    original_save = _repos_mod.fridge_repo.save_entries
    try:
        def fail_save(_entries):
            raise RuntimeError("boom")

        _repos_mod.fridge_repo.save_entries = fail_save
        result = parse(register_cooked_meal({"dish_name": "tortilla de patatas"}))
        check("returns error on fridge failure", isinstance(result, dict) and "error" in result)
        check("history restored after failure", _repos_mod.history_repo.load() == before)
    finally:
        _repos_mod.fridge_repo.save_entries = original_save


def test_delete_history_entry():
    print("\n-- delete_history_entry --")
    result = parse(delete_history_entry({"dish_name": "arroz con pollo"}))
    check("success message", isinstance(result, str) and "retracted" in result.lower(),
          f"got: {result}")
    check("dish leaves the projection",
          "arroz con pollo" not in _repos_mod.history_repo.load(),
          f"got {_repos_mod.history_repo.load()}")
    # Retraction is not deletion: the row survives so the user can still see
    # that the cook was recorded and taken back.
    check("the retracted event survives in the log",
          any(e.dish_name == "arroz con pollo" and not e.active
              for e in _repos_mod.history_repo.load_events()),
          f"got {[e.to_dict() for e in _repos_mod.history_repo.load_events()]}")


def test_delete_history_entry_bogus():
    print("\n-- delete_history_entry (nonexistent) --")
    result = parse(delete_history_entry({"dish_name": "nada"}))
    check("returns error", isinstance(result, dict) and "error" in result, f"got: {result}")


def test_add_dish_dict():
    print("\n-- add_dish (dict ingredients) --")
    result = parse(add_dish({
        "name": "Ensalada",
        "ingredients": {"lechuga": True, "tomate": True, "aceitunas": False},
    }))
    check("success message", isinstance(result, str) and "added" in result.lower(), f"got: {result}")


def test_add_dish_list():
    print("\n-- add_dish (list ingredients) --")
    result = parse(add_dish({
        "name": "Pasta Sencilla",
        "ingredients": ["pasta", "aceite"],
    }))
    check("success message", isinstance(result, str) and "added" in result.lower(), f"got: {result}")


def test_add_dish_duplicate():
    print("\n-- add_dish (duplicate) --")
    result = parse(add_dish({
        "name": "Ensalada",
        "ingredients": {"lechuga": True},
    }))
    check("returns error for duplicate", isinstance(result, dict) and "error" in result, f"got: {result}")


def test_add_dish_invalid_inputs():
    print("\n-- add_dish (invalid inputs) --")
    blank_name = parse(add_dish({
        "name": "   ",
        "ingredients": {"lechuga": True},
    }))
    check("rejects blank name", isinstance(blank_name, dict) and "error" in blank_name)

    bad_ingredient = parse(add_dish({
        "name": "Sopa Rara",
        "ingredients": {"caldo": "yes"},
    }))
    check("rejects non-boolean ingredient values", isinstance(bad_ingredient, dict) and "error" in bad_ingredient)


def test_edit_dish():
    print("\n-- edit_dish --")
    result = parse(edit_dish({
        "dish_name": "Ensalada",
        "ingredients": {"lechuga": True, "tomate": True, "pepino": False, "aceitunas": False},
    }))
    check("success message", isinstance(result, str) and "updated" in result.lower(), f"got: {result}")


def test_edit_dish_bogus():
    print("\n-- edit_dish (nonexistent) --")
    result = parse(edit_dish({
        "dish_name": "Plato Fantasma",
        "ingredients": {"agua": True},
    }))
    check("returns error", isinstance(result, dict) and "error" in result, f"got: {result}")


def test_delete_dish():
    print("\n-- delete_dish --")
    result = parse(delete_dish({"dish_name": "Pasta Sencilla"}))
    check("success message", isinstance(result, str) and "deleted" in result.lower())


def test_delete_dish_bogus():
    print("\n-- delete_dish (nonexistent) --")
    result = parse(delete_dish({"dish_name": "Nada"}))
    check("returns error", isinstance(result, dict) and "error" in result, f"got: {result}")


def test_add_dishes_batch():
    print("\n-- add_dishes_batch --")
    result = parse(add_dishes_batch({
        "dishes": [
            {"name": "Gazpacho", "ingredients": {"tomate": True, "pepino": True, "pimiento": False}},
            {"name": "Sopa de ajo", "ingredients": ["ajo", "pan", "huevos"]},
            {"name": "Ensalada", "ingredients": {"lechuga": True}},  # already exists
        ],
    }))
    check("returns dict with added/skipped", isinstance(result, dict) and "added" in result)
    check("added 2 dishes", len(result["added"]) == 2, f"got {result['added']}")
    check("skipped 1 duplicate", len(result["skipped"]) == 1, f"got {result['skipped']}")


def test_dii_finalize_rollback():
    print("\n-- DII: finalize rollback --")
    fridge_before = parse(list_fridge({}))
    state = parse(init_ingredient_session({
        "dish_name": "Rollback Test",
        "ingredients": ["harina"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    sid = state["session_id"]

    original_save = _repos_mod.dish_repo.save
    try:
        def fail_save(_dishes):
            raise RuntimeError("boom")

        _repos_mod.dish_repo.save = fail_save
        result = parse(finalize_ingredient_session({"session_id": sid}))
        check("returns error on dish failure", isinstance(result, dict) and "error" in result)
        check("fridge rolled back after failure", parse(list_fridge({})) == fridge_before)
    finally:
        _repos_mod.dish_repo.save = original_save
        parse(finalize_ingredient_session({
            "session_id": sid,
            "commit_to_fridge": False,
            "commit_to_dish": False,
        }))


def test_clear_fridge():
    print("\n-- clear_fridge --")
    result = parse(clear_fridge({}))
    check("success message", isinstance(result, str) and "cleared" in result.lower(), f"got: {result}")

    fridge = parse(list_fridge({}))
    check("fridge is empty",
          not fridge["in_stock"] and not fridge["out_of_stock"], f"got {fridge}")


def test_clear_fridge_already_empty():
    print("\n-- clear_fridge (already empty) --")
    result = parse(clear_fridge({}))
    check("already empty message", isinstance(result, str) and "already empty" in result.lower())


# ---------------------------------------------------------------------------
# DII lifecycle tests
# ---------------------------------------------------------------------------

def test_dii_full_lifecycle():
    print("\n-- DII: full lifecycle --")

    # Flat parallel arrays: ingredients + is_essential (ordered by relevance)
    ingredients = ["harina", "tomate", "mozzarella", "albahaca", "aceite de oliva", "oregano"]
    is_essential = [True, True, True, False, False, False]

    # 1. Init session (pre_select_top_n=3 by default)
    state = parse(init_ingredient_session({
        "dish_name": "Pizza Margherita",
        "ingredients": ingredients,
        "is_essential": is_essential,
    }))
    check("session created", "session_id" in state, f"got: {state}")
    sid = state["session_id"]
    check("3 essentials pre-selected",
          state["essential_ingredients"] == ["harina", "tomate", "mozzarella"])
    check("current suggestion is albahaca",
          state["current_suggestion"]["ingredient"] == "albahaca")
    check("queue has 2 remaining", state["queue_remaining"] == 2)

    # 2. Add the suggested ingredient (albahaca)
    state = parse(dii_add_suggested({"session_id": sid}))
    check("albahaca added to optionals", "albahaca" in state["optional_ingredients"])
    check("next suggestion is aceite de oliva",
          state["current_suggestion"]["ingredient"] == "aceite de oliva")

    # 3. Skip the current suggestion (aceite de oliva)
    state = parse(dii_skip_suggested({"session_id": sid}))
    check("aceite skipped, not in any list",
          "aceite de oliva" not in state["essential_ingredients"]
          and "aceite de oliva" not in state["optional_ingredients"])
    check("next suggestion is oregano",
          state["current_suggestion"]["ingredient"] == "oregano")

    # 4. Skip oregano too -- queue should exhaust
    state = parse(dii_skip_suggested({"session_id": sid}))
    check("queue exhausted", state["queue_exhausted"] is True)
    check("no current suggestion", state["current_suggestion"] is None)

    # 5. Add manual ingredient
    state = parse(dii_add_manual({
        "session_id": sid,
        "ingredient": "Jamon Serrano",
        "is_essential": False,
    }))
    check("jamon added to optionals", "jamon serrano" in state["optional_ingredients"])

    # 6. Remove an essential ingredient -- should signal recalculation
    state = parse(dii_remove_ingredient({"session_id": sid, "ingredient": "mozzarella"}))
    check("mozzarella removed", "mozzarella" not in state["essential_ingredients"])
    check("recalculation_needed", state["recalculation_needed"] is True)
    check("pending_recalculation", state["pending_recalculation"] is True)

    # 7. Re-init in place (recalculation reuses the same session_id)
    state = parse(init_ingredient_session({
        "session_id": sid,
        "dish_name": "Pizza Margherita",
        "ingredients": ["harina", "tomate", "queso de cabra"],
        "is_essential": [True, True, True],
        "pre_select_top_n": 3,
    }))
    check("recalc reuses same session_id", state["session_id"] == sid)
    check("queso de cabra pre-selected", "queso de cabra" in state["essential_ingredients"])
    check("recalculation flag cleared after re-init",
          state["pending_recalculation"] is False)

    # 8. Finalize
    state = parse(finalize_ingredient_session({"session_id": sid}))
    check("finalized", state["finalized"] is True)
    check("committed to dish", state["committed_to_dish"] is True)
    check("committed to fridge", state["committed_to_fridge"] is True)

    # Verify fridge got the ingredients
    fridge = parse(list_fridge({}))["in_stock"]
    check("harina in fridge after finalize", fridge.get("harina") == 1, f"got {fridge}")
    check("tomate in fridge after finalize", fridge.get("tomate") == 1, f"got {fridge}")
    check("queso de cabra in fridge after finalize",
          fridge.get("queso de cabra") == 1, f"got {fridge}")


def test_dii_clear_all():
    print("\n-- DII: clear_all --")
    state = parse(init_ingredient_session({
        "dish_name": "Test Clear",
        "ingredients": ["a", "b"],
        "is_essential": [True, True],
        "pre_select_top_n": 2,
    }))
    sid = state["session_id"]
    check("has ingredients before clear",
          len(state["essential_ingredients"]) == 2)

    state = parse(dii_clear_all({"session_id": sid}))
    check("all cleared", len(state["essential_ingredients"]) == 0
          and len(state["optional_ingredients"]) == 0)
    check("recalculation needed after clear", state["recalculation_needed"] is True)


def test_dii_expired_session():
    print("\n-- DII: expired/invalid session --")
    result = parse(dii_add_suggested({"session_id": "nonexistent_id"}))
    check("error for bad session_id", "error" in result, f"got: {result}")


def test_dii_finalize_twice():
    print("\n-- DII: finalize idempotent --")
    state = parse(init_ingredient_session({
        "dish_name": "Doble Final",
        "ingredients": ["x"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    sid = state["session_id"]

    first = parse(finalize_ingredient_session({"session_id": sid}))
    check("first finalize commits", first["finalized"] is True, f"got: {first}")
    # Finalized sessions are retained (persisted) so a repeat finalize is
    # idempotent: it must report the "already finalized" warning rather than a
    # misleading "not found", and must not commit a second time.
    state2 = parse(finalize_ingredient_session({"session_id": sid}))
    check("second finalize is idempotent with a warning",
          "warning" in state2 and "finalized" in state2["warning"].lower()
          and state2.get("finalized") is True,
          f"got: {state2}")


def test_dii_finalize_options():
    print("\n-- DII: finalize with commit options --")
    state = parse(init_ingredient_session({
        "dish_name": "Solo Nevera",
        "ingredients": ["sal"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    sid = state["session_id"]

    state = parse(finalize_ingredient_session({
        "session_id": sid,
        "commit_to_fridge": True,
        "commit_to_dish": False,
    }))
    check("committed to fridge", state["committed_to_fridge"] is True)
    check("did not commit to dish", state["committed_to_dish"] is False)


def test_dii_get_state():
    print("\n-- DII: dii_get_state --")
    state = parse(init_ingredient_session({
        "dish_name": "State Test",
        "ingredients": ["a", "b", "c"],
        "is_essential": [True, True, False],
        "pre_select_top_n": 2,
    }))
    sid = state["session_id"]

    result = parse(dii_get_state({"session_id": sid}))
    check("returns session_id", result["session_id"] == sid)
    check("returns dish_name", result["dish_name"] == "state test")
    check("returns essentials", result["essential_ingredients"] == ["a", "b"])
    check("returns current_suggestion", result["current_suggestion"]["ingredient"] == "c")
    check("returns next_actions", len(result["next_actions"]) > 0)
    check("not finalized", result["finalized"] is False)

    # Error path: invalid session
    err = parse(dii_get_state({"session_id": "bogus_id"}))
    check("error for bad session_id", "error" in err, f"got: {err}")


def test_dii_add_manual_empty():
    print("\n-- DII: add_manual empty ingredient --")
    state = parse(init_ingredient_session({
        "dish_name": "Empty Test",
        "ingredients": ["algo"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    sid = state["session_id"]

    result = parse(dii_add_manual({"session_id": sid, "ingredient": "   "}))
    check("error for empty ingredient", "error" in result, f"got: {result}")


# ---------------------------------------------------------------------------
# Online weight tuning
# ---------------------------------------------------------------------------

def test_online_weight_tuning():
    print("\n-- online weight tuning --")
    from datetime import date as _date, timedelta as _timedelta

    # Give the two dishes opposing profiles so the ranking depends on w and the
    # cook produces a real (non-skipped) learning event: A is well-rested but has
    # no optionals, B has three optionals in stock but was cooked recently.
    add_dish({"name": "Tuning Dish A", "ingredients": {"tun_a": True}})
    add_dish({"name": "Tuning Dish B", "ingredients": {
        "tun_b": True, "tun_o1": False, "tun_o2": False, "tun_o3": False,
    }})
    update_fridge_inventory({"action": "set", "ingredients": {
        "tun_a": 5, "tun_b": 5, "tun_o1": None, "tun_o2": None, "tun_o3": None,
    }})
    _repos_mod.history_repo.append_event(
        "tuning dish b", (_date.today() - _timedelta(days=3)).isoformat()
    )

    register_cooked_meal({"dish_name": "Tuning Dish A"})

    check("tuning.json created", (_TMP_DATA_DIR / "tuning.json").exists())

    state = _repos_mod.tuning_repo.load()
    check("observations recorded", state["observations"] >= 1, f"got {state['observations']}")
    check("deployed match weight within band",
          _tuning_mod.BAND[0] <= state["deployed_match_weight"] <= _tuning_mod.BAND[1],
          f"got {state['deployed_match_weight']}")

    # get_meal_suggestions must keep the {dish, score} contract.
    suggestions = parse(get_meal_suggestions({}))
    check("suggestions keep {dish, score} shape",
          isinstance(suggestions, list)
          and all(set(s.keys()) == {"dish", "score"} for s in suggestions),
          f"got {suggestions}")

    # get_tuning_state exposes a complementary weight pair.
    ts = parse(get_tuning_state({}))
    check("tuning state reports weights",
          "availability_weight" in ts and "recency_weight" in ts, f"got {ts}")
    check("weights sum to ~1.0",
          abs(ts["availability_weight"] + ts["recency_weight"] - 1.0) < 1e-6,
          f"got {ts}")
    check("reports candidate grid",
          isinstance(ts.get("candidates"), list) and len(ts["candidates"]) > 0)


# ---------------------------------------------------------------------------
# Regression tests for the review fixes
# ---------------------------------------------------------------------------

def test_missing_required_arg_message():
    print("\n-- validation: missing required arg yields a clear message --")
    res = parse(add_dish({"name": "No Ingredients"}))
    check("missing 'ingredients' reported clearly",
          "error" in res and "ingredients" in res["error"]
          and "required" in res["error"].lower(), f"got: {res}")
    res2 = parse(register_cooked_meal({}))
    check("missing 'dish_name' reported clearly",
          "error" in res2 and "dish_name" in res2["error"]
          and "required" in res2["error"].lower(), f"got: {res2}")


def test_history_event_log_on_disk():
    print("\n-- register_cooked_meal writes a v2 event log --")
    from datetime import date as _date, timedelta as _timedelta
    add_dish({"name": "Log Dish", "ingredients": {"log_a": True}})
    update_fridge_inventory({"action": "set", "ingredients": {"log_a": 5}})

    register_cooked_meal({"dish_name": "Log Dish"})
    stored = json.loads((_TMP_DATA_DIR / "history.json").read_text(encoding="utf-8"))
    check("file uses schema_version 2", stored.get("schema_version") == 2, f"got {stored}")
    rows = [e for e in stored.get("events", []) if e["dish_name"] == "log dish"]
    check("exactly one event recorded", len(rows) == 1, f"got {rows}")
    check("today's cook is not marked backfilled",
          rows[0]["backfilled"] is False, f"got {rows[0]}")
    check("recorded_at is timezone-aware",
          "+" in rows[0]["recorded_at"] or rows[0]["recorded_at"].endswith("Z"),
          f"got {rows[0]}")

    old = (_date.today() - _timedelta(days=40)).isoformat()
    register_cooked_meal({"dish_name": "Log Dish", "date": old})
    stored = json.loads((_TMP_DATA_DIR / "history.json").read_text(encoding="utf-8"))
    rows = [e for e in stored["events"] if e["dish_name"] == "log dish"]
    check("backdated cook appends a second event", len(rows) == 2, f"got {rows}")
    check("backdated cook is marked backfilled",
          any(e["cooked_on"] == old and e["backfilled"] is True for e in rows),
          f"got {rows}")
    check("the older event does not move the projection",
          _repos_mod.history_repo.load()["log dish"] == _date.today().isoformat(),
          f"got {_repos_mod.history_repo.load()}")


def test_history_rollback_hard_deletes_the_event():
    print("\n-- register_cooked_meal rollback leaves no trace --")
    add_dish({"name": "Rollback Dish", "ingredients": {"rb_a": True}})
    update_fridge_inventory({"action": "set", "ingredients": {"rb_a": 5}})
    before = len(_repos_mod.history_repo.load_events())

    original_consume = _repos_mod.fridge_repo.consume
    try:
        def fail_consume(_names):
            raise RuntimeError("boom")

        _repos_mod.fridge_repo.consume = fail_consume
        result = parse(register_cooked_meal({"dish_name": "Rollback Dish"}))
        check("returns an error envelope", "error" in result, f"got {result}")
    finally:
        _repos_mod.fridge_repo.consume = original_consume

    events = _repos_mod.history_repo.load_events()
    # A rolled-back cook never happened, so it must be hard-deleted rather than
    # retracted — a retracted row would read as "the user took this back".
    check("no event for the failed cook remains",
          not any(e.dish_name == "rollback dish" for e in events),
          f"got {[e.to_dict() for e in events]}")
    check("the rest of the log is untouched", len(events) == before, f"got {events}")


def test_delete_history_entry_releases_the_cooldown():
    print("\n-- delete_history_entry releases the recency cooldown --")
    add_dish({"name": "Cooldown Dish", "ingredients": {"cd_a": True}})
    update_fridge_inventory({"action": "set", "ingredients": {"cd_a": 5}})
    register_cooked_meal({"dish_name": "Cooldown Dish"})

    gated = parse(get_meal_suggestions({}))
    check("a dish cooked today is gated out",
          not any(s["dish"] == "cooldown dish" for s in gated), f"got {gated}")

    delete_history_entry({"dish_name": "Cooldown Dish"})
    freed = parse(get_meal_suggestions({}))
    check("retracting the cook makes it suggestible again",
          any(s["dish"] == "cooldown dish" for s in freed), f"got {freed}")


def test_list_cooking_history():
    print("\n-- list_cooking_history --")
    # A self-contained log: wipe history so the assertions are exact.
    (_TMP_DATA_DIR / "history.json").write_text(
        json.dumps({"schema_version": 2, "events": []}), encoding="utf-8"
    )
    empty = parse(list_cooking_history({}))
    check("empty history returns no rows",
          empty.get("events") == [] and empty.get("count") == 0, f"got {empty}")

    add_dish({"name": "Hist One", "ingredients": {"h_a": True}})
    add_dish({"name": "Hist Two", "ingredients": {"h_b": True}})
    update_fridge_inventory({"action": "set", "ingredients": {"h_a": 9, "h_b": 9}})
    register_cooked_meal({"dish_name": "Hist One"})
    register_cooked_meal({"dish_name": "Hist Two"})

    res = parse(list_cooking_history({}))
    names = [e["dish_name"] for e in res["events"]]
    check("both cooks listed", set(names) == {"hist one", "hist two"}, f"got {names}")
    check("newest first", names[0] == "hist two", f"got {names}")
    check("rows carry a derived status",
          all(e["status"] == "active" for e in res["events"]), f"got {res}")

    filtered = parse(list_cooking_history({"dish_name": "Hist One"}))
    check("dish_name filters and normalizes its input",
          [e["dish_name"] for e in filtered["events"]] == ["hist one"], f"got {filtered}")

    limited = parse(list_cooking_history({"limit": 1}))
    check("limit truncates", limited["count"] == 1, f"got {limited}")
    check("truncation is reported", limited["truncated"] is True, f"got {limited}")

    exact = parse(list_cooking_history({"limit": 2}))
    check("an exact-fit limit is not reported as truncated",
          exact["count"] == 2 and exact["truncated"] is False, f"got {exact}")

    delete_history_entry({"dish_name": "Hist Two"})
    with_retracted = parse(list_cooking_history({"include_retracted": True}))
    check("retracted events are shown by default",
          any(e["status"] == "retracted" for e in with_retracted["events"]),
          f"got {with_retracted}")
    without = parse(list_cooking_history({"include_retracted": False}))
    check("include_retracted=False hides them",
          all(e["status"] == "active" for e in without["events"])
          and without["count"] == 1, f"got {without}")


def test_list_cooking_history_validation():
    print("\n-- list_cooking_history (validation) --")
    for bad_limit in (0, 1001, -5):
        res = parse(list_cooking_history({"limit": bad_limit}))
        check(f"limit={bad_limit} rejected",
              "error" in res and "limit" in res["error"], f"got {res}")

    # isinstance(True, int) is True in Python, so a bool must not slip through
    # as limit=1.
    res = parse(list_cooking_history({"limit": True}))
    check("limit=true rejected as a non-integer",
          "error" in res and "integer" in res["error"], f"got {res}")

    res2 = parse(list_cooking_history({"limit": "10"}))
    check("string limit rejected", "error" in res2, f"got {res2}")

    res3 = parse(list_cooking_history({"include_retracted": "yes"}))
    check("non-boolean include_retracted rejected",
          "error" in res3 and "include_retracted" in res3["error"], f"got {res3}")

    res4 = parse(list_cooking_history({"unknown": 1}))
    check("unknown argument rejected", "error" in res4, f"got {res4}")


def test_list_cooking_history_surfaces_corruption():
    print("\n-- list_cooking_history (corrupt storage) --")
    original = (_TMP_DATA_DIR / "history.json").read_text(encoding="utf-8")
    try:
        (_TMP_DATA_DIR / "history.json").write_text("{not json", encoding="utf-8")
        res = parse(list_cooking_history({}))
        # An empty list here would read as "you have never cooked anything",
        # which is a different and much worse answer than "I cannot read this".
        check("corrupt history surfaces as an error, not an empty log",
              "error" in res, f"got {res}")
    finally:
        (_TMP_DATA_DIR / "history.json").write_text(original, encoding="utf-8")


def test_fridge_expiry_end_to_end():
    print("\n-- update_fridge_inventory / list_fridge (expiry) --")
    from datetime import date as _date, timedelta as _timedelta
    soon = (_date.today() + _timedelta(days=2)).isoformat()
    stale = (_date.today() - _timedelta(days=2)).isoformat()
    later = (_date.today() + _timedelta(days=60)).isoformat()

    update_fridge_inventory({"action": "set", "ingredients": {
        "exp_soon": {"count": 2, "expires_on": soon},
        "exp_old": {"count": 1, "expires_on": stale},
        "exp_fresh": {"count": 1, "expires_on": later},
        "exp_none": 4,
    }})

    fridge = parse(list_fridge({}))
    check("expiry dates are reported",
          fridge["expiry"]["exp_soon"]["expires_on"] == soon, f"got {fridge}")
    check("expiring_soon is collected",
          fridge["expiring_soon"] == ["exp_soon"], f"got {fridge}")
    check("expired is collected", fridge["expired"] == ["exp_old"], f"got {fridge}")
    check("a far-off date is fresh",
          fridge["expiry"]["exp_fresh"]["status"] == "fresh", f"got {fridge}")
    check("an entry with no date is absent from expiry",
          "exp_none" not in fridge["expiry"], f"got {fridge}")

    # The date is the user's estimate, not ground truth. Flag it, never
    # silently delete their food.
    check("expired items are still in stock",
          fridge["in_stock"].get("exp_old") == 1, f"got {fridge}")
    check("expired items are still usable",
          "exp_old" in _repos_mod.fridge_repo.load_set(),
          f"got {_repos_mod.fridge_repo.load_set()}")

    # A plain restock must not quietly erase a date the user gave us.
    update_fridge_inventory({"action": "add", "ingredients": {"exp_soon": 1}})
    after = parse(list_fridge({}))
    check("restocking preserves the recorded date",
          after["expiry"]["exp_soon"]["expires_on"] == soon, f"got {after}")
    check("restocking still increments the count",
          after["in_stock"]["exp_soon"] == 3, f"got {after}")

    update_fridge_inventory({"action": "set", "ingredients": {
        "exp_soon": {"count": 3, "expires_on": None},
    }})
    cleared = parse(list_fridge({}))
    check("an explicit null clears the date",
          "exp_soon" not in cleared["expiry"], f"got {cleared}")

    # Entries with no expiry must stay bare scalars on disk.
    raw = json.loads((_TMP_DATA_DIR / "fridge.json").read_text(encoding="utf-8"))
    check("no-expiry entries stay bare scalars on disk",
          raw["exp_none"] == 4, f"got {raw['exp_none']}")
    check("expiry entries are stored as objects",
          raw["exp_old"] == {"count": 1, "expires_on": stale}, f"got {raw['exp_old']}")


def test_fridge_expiry_validation():
    print("\n-- update_fridge_inventory (expiry validation) --")
    res = parse(update_fridge_inventory({"action": "set", "ingredients": {
        "bad_exp": {"count": 1, "expires_on": "08/2026"},
    }}))
    check("malformed expires_on returns an error envelope",
          "error" in res and "expires_on" in res["error"], f"got {res}")

    res2 = parse(update_fridge_inventory({"action": "set", "ingredients": {
        "bad_exp": {"count": 1, "best_before": "2026-08-01"},
    }}))
    check("unknown field inside the object rejected",
          "error" in res2 and "best_before" in res2["error"], f"got {res2}")

    check("nothing was written for the rejected input",
          "bad_exp" not in _repos_mod.fridge_repo.load(),
          f"got {_repos_mod.fridge_repo.load()}")


def _clear_aliases():
    """Drop the alias map so a test starts from an un-aliased boundary."""
    path = _TMP_DATA_DIR / "aliases.json"
    if path.exists():
        path.unlink()


def test_merge_ingredient_alias_catalog_only():
    print("\n-- merge_ingredient_alias (catalog only) --")
    _clear_aliases()
    add_dish({"name": "Alias Cat", "ingredients": {"al_tomates": True, "al_sal": False}})

    res = parse(merge_ingredient_alias({"from_name": "al_tomates", "to_name": "al_tomate"}))
    check("reports the dish it rewrote",
          res.get("dishes_updated") == ["alias cat"], f"got {res}")
    check("fridge untouched", res.get("fridge_merged") is False, f"got {res}")

    recipe = parse(get_dish_recipe({"dish_name": "Alias Cat"}))
    check("recipe now uses the canonical name",
          recipe["essential"] == ["al_tomate"], f"got {recipe}")

    listed = parse(list_ingredient_aliases({}))
    check("alias is recorded",
          listed["aliases"].get("al_tomates") == "al_tomate", f"got {listed}")


def test_merge_ingredient_alias_fridge_counts():
    print("\n-- merge_ingredient_alias (fridge counts) --")
    _clear_aliases()
    update_fridge_inventory({"action": "set", "ingredients": {"al_f1": 2, "al_f2": 3}})
    res = parse(merge_ingredient_alias({"from_name": "al_f1", "to_name": "al_f2"}))
    check("counts are summed", res.get("resulting_count") == 5, f"got {res}")
    check("fridge merge reported", res.get("fridge_merged") is True, f"got {res}")
    fridge = _repos_mod.fridge_repo.load()
    check("the retired key is gone", "al_f1" not in fridge, f"got {fridge}")

    # A staple never runs out, so it wins over any finite count.
    _clear_aliases()
    update_fridge_inventory({"action": "set", "ingredients": {"al_s1": 3, "al_s2": None}})
    res2 = parse(merge_ingredient_alias({"from_name": "al_s1", "to_name": "al_s2"}))
    check("staple wins over a count", res2.get("resulting_count") is None, f"got {res2}")
    check("stored as a staple",
          _repos_mod.fridge_repo.load().get("al_s2") is None,
          f"got {_repos_mod.fridge_repo.load()}")

    # And the sum cannot exceed the portion cap.
    _clear_aliases()
    update_fridge_inventory({"action": "set", "ingredients": {"al_c1": 60, "al_c2": 60}})
    res3 = parse(merge_ingredient_alias({"from_name": "al_c1", "to_name": "al_c2"}))
    check("summed count is clamped at MAX_PORTION_COUNT",
          res3.get("resulting_count") == _handlers_common.MAX_PORTION_COUNT,
          f"got {res3}")

    # Renaming a key the canonical does not yet have carries the count over.
    _clear_aliases()
    update_fridge_inventory({"action": "set", "ingredients": {"al_r1": 4}})
    res4 = parse(merge_ingredient_alias({"from_name": "al_r1", "to_name": "al_r2"}))
    check("a plain rename keeps the count", res4.get("resulting_count") == 4, f"got {res4}")
    check("canonical key now holds it",
          _repos_mod.fridge_repo.load().get("al_r2") == 4,
          f"got {_repos_mod.fridge_repo.load()}")


def test_merge_ingredient_alias_essential_wins():
    print("\n-- merge_ingredient_alias (essential wins) --")
    _clear_aliases()
    add_dish({"name": "Alias Ess", "ingredients": {"al_e_opt": False, "al_e_ess": True}})

    merge_ingredient_alias({"from_name": "al_e_opt", "to_name": "al_e_ess"})
    recipe = parse(get_dish_recipe({"dish_name": "Alias Ess"}))
    # Demoting an essential to optional would let can_cook_with approve a dish
    # the user cannot actually make.
    check("merging an optional into an essential keeps it essential",
          recipe["essential"] == ["al_e_ess"] and recipe["optional"] == [],
          f"got {recipe}")

    _clear_aliases()
    add_dish({"name": "Alias Ess2", "ingredients": {"al_e2_ess": True, "al_e2_opt": False}})
    merge_ingredient_alias({"from_name": "al_e2_ess", "to_name": "al_e2_opt"})
    recipe2 = parse(get_dish_recipe({"dish_name": "Alias Ess2"}))
    check("essential wins in the other direction too",
          recipe2["essential"] == ["al_e2_opt"] and recipe2["optional"] == [],
          f"got {recipe2}")


def test_merge_ingredient_alias_boundary_resolution():
    print("\n-- merge_ingredient_alias (boundary canonicalizes later input) --")
    _clear_aliases()
    update_fridge_inventory({"action": "set", "ingredients": {"al_b_canon": 1}})
    merge_ingredient_alias({"from_name": "al_b_dup", "to_name": "al_b_canon"})

    # The whole point of persisting the alias: input spelled the old way must
    # land on the canonical key from now on.
    update_fridge_inventory({"action": "set", "ingredients": {"al_b_dup": 7}})
    fridge = _repos_mod.fridge_repo.load()
    check("the old name writes through to the canonical key",
          fridge.get("al_b_canon") == 7, f"got {fridge}")
    check("no entry is created under the old name",
          "al_b_dup" not in fridge, f"got {fridge}")


def test_merge_ingredient_alias_unlocks_a_dish():
    print("\n-- merge_ingredient_alias (unlocks a previously uncookable dish) --")
    _clear_aliases()
    add_dish({"name": "Alias Unlock", "ingredients": {"al_u_tomates": True}})
    update_fridge_inventory({"action": "set", "ingredients": {"al_u_tomate": 5}})

    before = parse(get_meal_suggestions({}))
    check("dish is not cookable while the spellings are split",
          not any(s["dish"] == "alias unlock" for s in before), f"got {before}")

    merge_ingredient_alias({"from_name": "al_u_tomates", "to_name": "al_u_tomate"})

    after = parse(get_meal_suggestions({}))
    check("merging makes the dish cookable",
          any(s["dish"] == "alias unlock" for s in after), f"got {after}")


def test_merge_ingredient_alias_errors():
    print("\n-- merge_ingredient_alias (errors) --")
    _clear_aliases()
    res = parse(merge_ingredient_alias({"from_name": "al_same", "to_name": "al_same"}))
    check("merging a name onto itself errors",
          "error" in res and "already the canonical" in res["error"], f"got {res}")

    merge_ingredient_alias({"from_name": "al_x", "to_name": "al_y"})
    # `from_name` resolves through the alias map too, so a repeat merge lands on
    # the canonical name and is correctly reported as a no-op.
    res2 = parse(merge_ingredient_alias({"from_name": "al_x", "to_name": "al_y"}))
    check("re-merging an already-merged pair errors", "error" in res2, f"got {res2}")

    res3 = parse(merge_ingredient_alias({"from_name": "al_z"}))
    check("missing to_name reported clearly",
          "error" in res3 and "to_name" in res3["error"], f"got {res3}")

    res4 = parse(merge_ingredient_alias({"from_name": "   ", "to_name": "al_q"}))
    check("blank name rejected", "error" in res4, f"got {res4}")
    _clear_aliases()


def test_dish_instructions_roundtrip():
    print("\n-- set_dish_instructions / get_dish_recipe --")
    add_dish({
        "name": "Recipe Test",
        "ingredients": {"harina": True, "azucar": False},
    })

    res = parse(set_dish_instructions({
        "dish_name": "Recipe Test",
        "instructions": "  Mix, then bake 30 min at 180C.  ",
    }))
    check("set reports the stored text",
          res.get("instructions") == "Mix, then bake 30 min at 180C.", f"got: {res}")
    check("set reports cleared=False", res.get("cleared") is False, f"got: {res}")

    recipe = parse(get_dish_recipe({"dish_name": "recipe test"}))
    check("recipe returns the instructions",
          recipe.get("instructions") == "Mix, then bake 30 min at 180C.", f"got: {recipe}")
    check("recipe splits essential/optional",
          recipe.get("essential") == ["harina"] and recipe.get("optional") == ["azucar"],
          f"got: {recipe}")

    cleared = parse(set_dish_instructions({
        "dish_name": "Recipe Test",
        "instructions": None,
    }))
    check("null clears", cleared.get("cleared") is True
          and cleared.get("instructions") is None, f"got: {cleared}")
    after = parse(get_dish_recipe({"dish_name": "Recipe Test"}))
    check("recipe reports None after clearing",
          after.get("instructions") is None, f"got: {after}")


def test_edit_dish_preserves_instructions():
    print("\n-- edit_dish preserves instructions --")
    add_dish({"name": "Preserve Test", "ingredients": {"a": True}})
    set_dish_instructions({
        "dish_name": "Preserve Test",
        "instructions": "Step one. Step two.",
    })

    edit_dish({"dish_name": "Preserve Test", "ingredients": {"a": True, "b": False}})

    recipe = parse(get_dish_recipe({"dish_name": "Preserve Test"}))
    check("instructions survive an ingredient edit",
          recipe.get("instructions") == "Step one. Step two.", f"got: {recipe}")
    check("ingredients actually changed",
          recipe.get("optional") == ["b"], f"got: {recipe}")


def test_dish_instructions_errors():
    print("\n-- set_dish_instructions / get_dish_recipe (errors) --")
    res = parse(set_dish_instructions({
        "dish_name": "No Such Dish",
        "instructions": "anything",
    }))
    check("unknown dish returns an error envelope",
          "error" in res and "No Such Dish" in res["error"], f"got: {res}")

    res2 = parse(get_dish_recipe({"dish_name": "No Such Dish"}))
    check("get_dish_recipe on unknown dish errors",
          "error" in res2, f"got: {res2}")

    res3 = parse(set_dish_instructions({"dish_name": "Recipe Test"}))
    check("missing 'instructions' is required, not defaulted",
          "error" in res3 and "instructions" in res3["error"], f"got: {res3}")

    res4 = parse(set_dish_instructions({
        "dish_name": "Recipe Test",
        "instructions": 42,
    }))
    check("non-string instructions rejected",
          "error" in res4 and "string" in res4["error"], f"got: {res4}")


def test_add_dish_with_instructions():
    print("\n-- add_dish (instructions argument) --")
    add_dish({
        "name": "Inline Recipe",
        "ingredients": ["agua"],
        "instructions": "Boil it.",
    })
    recipe = parse(get_dish_recipe({"dish_name": "Inline Recipe"}))
    check("instructions stored at creation time",
          recipe.get("instructions") == "Boil it.", f"got: {recipe}")

    # A dish added without instructions must not write the key at all, so an
    # existing dishes.json round-trips with no diff.
    add_dish({"name": "No Recipe", "ingredients": ["agua"]})
    raw = json.loads((_TMP_DATA_DIR / "dishes.json").read_text(encoding="utf-8"))
    row = next(d for d in raw["dishes"] if d.get("name") == "no recipe")
    check("dish without instructions omits the key on disk",
          "instructions" not in row, f"got: {row}")


def test_unknown_argument_rejected():
    print("\n-- validation: unknown arguments are rejected --")
    res = parse(add_dish({
        "dish_name": "Wrong Key",  # the real argument is 'name'
        "ingredients": {"a": True},
    }))
    check("unknown argument returns an error envelope",
          "error" in res and "dish_name" in res["error"], f"got: {res}")

    res2 = parse(list_fridge({"limit": 5}))
    check("no-argument tool also rejects unknown keys",
          "error" in res2 and "limit" in res2["error"], f"got: {res2}")

    res3 = parse(register_cooked_meal({"dish_name": "Arroz con Pollo", "qty": 2}))
    check("unknown key rejected before the handler runs",
          "error" in res3 and "qty" in res3["error"], f"got: {res3}")

    ok = parse(list_fridge({}))
    check("valid empty arguments still succeed", "error" not in ok, f"got: {ok}")


def test_add_dishes_batch_partial_failure():
    print("\n-- add_dishes_batch: partial failure keeps valid dishes --")
    res = parse(add_dishes_batch({"dishes": [
        {"name": "Valid One", "ingredients": {"a": True}},
        {"name": "Bad One", "ingredients": {"b": "nope"}},  # non-bool -> fails
        {"name": "Valid Two", "ingredients": ["c"]},
    ]}))
    check("valid dishes added despite a bad entry",
          set(res.get("added", [])) == {"valid one", "valid two"}, f"got: {res}")
    check("bad entry surfaced in 'failed'",
          any(f.get("name") == "Bad One" for f in res.get("failed", [])), f"got: {res}")


def test_dii_remove_optional_no_recalc():
    print("\n-- DII: removing an optional does not trigger recalculation --")
    state = parse(init_ingredient_session({
        "dish_name": "Opt Test",
        "ingredients": ["ess1", "opt1"],
        "is_essential": [True, False],
        "pre_select_top_n": 2,
    }))
    sid = state["session_id"]
    check("optional pre-selected", "opt1" in state["optional_ingredients"])
    res = parse(dii_remove_ingredient({"session_id": sid, "ingredient": "opt1"}))
    check("optional removed", "opt1" not in res["optional_ingredients"])
    check("no recalculation for optional removal",
          res["recalculation_needed"] is False, f"got: {res}")
    check("no pending recalculation", res["pending_recalculation"] is False, f"got: {res}")
    res2 = parse(dii_remove_ingredient({"session_id": sid, "ingredient": "ess1"}))
    check("recalculation for essential removal",
          res2["recalculation_needed"] is True, f"got: {res2}")


def test_edit_dish_empty_rejected():
    print("\n-- edit_dish: empty ingredient set rejected (no silent wipe) --")
    add_dish({"name": "Guardable", "ingredients": {"x": True, "y": False}})
    res = parse(edit_dish({"dish_name": "Guardable", "ingredients": []}))
    check("empty edit returns an error", "error" in res, f"got: {res}")
    guard = next((d for d in _repos_mod.dish_repo.load() if d.name == "guardable"), None)
    check("recipe not wiped by empty edit",
          guard is not None and len(guard.ingredients) == 2,
          f"got: {guard and guard.ingredients}")


def test_dii_finalize_empty_selection_no_wipe():
    print("\n-- DII: finalize with empty selection does not wipe a recipe --")
    add_dish({"name": "Precious", "ingredients": {"p": True, "q": False}})
    state = parse(init_ingredient_session({
        "dish_name": "Precious",
        "ingredients": ["p"],
        "is_essential": [True],
        "pre_select_top_n": 0,  # nothing selected
    }))
    sid = state["session_id"]
    res = parse(finalize_ingredient_session({"session_id": sid}))
    check("empty finalize did not commit the dish",
          res.get("committed_to_dish") is False, f"got: {res}")
    check("empty finalize surfaces a warning", "warning" in res, f"got: {res}")
    precious = next((d for d in _repos_mod.dish_repo.load() if d.name == "precious"), None)
    check("recipe preserved after empty finalize",
          precious is not None and len(precious.ingredients) == 2,
          f"got: {precious and precious.ingredients}")


def test_dii_init_resolves_aliases():
    print("\n-- DII init canonicalizes ingredient names --")
    _clear_aliases()
    # Retire "al_dii_old" in favour of "al_dii_new" before the session exists.
    merge_ingredient_alias({"from_name": "al_dii_old", "to_name": "al_dii_new"})

    state = parse(init_ingredient_session({
        "dish_name": "Alias DII Dish",
        "ingredients": ["al_dii_old", "al_dii_keep"],
        "is_essential": [True, True],
        "pre_select_top_n": 2,
    }))
    check("session stores the canonical spelling",
          state["essential_ingredients"] == ["al_dii_new", "al_dii_keep"],
          f"got {state['essential_ingredients']}")

    # The whole point: what gets committed must not resurrect the retired name.
    parse(finalize_ingredient_session({"session_id": state["session_id"]}))
    recipe = parse(get_dish_recipe({"dish_name": "Alias DII Dish"}))
    check("catalog receives the canonical name",
          "al_dii_new" in recipe["essential"] and "al_dii_old" not in recipe["essential"],
          f"got {recipe}")
    fridge = _repos_mod.fridge_repo.load()
    check("fridge receives the canonical name",
          "al_dii_new" in fridge and "al_dii_old" not in fridge,
          f"got {sorted(fridge)}")


def test_dii_remove_resolves_aliases():
    print("\n-- DII remove canonicalizes ingredient names --")
    _clear_aliases()
    merge_ingredient_alias({"from_name": "al_rm_old", "to_name": "al_rm_new"})

    state = parse(init_ingredient_session({
        "dish_name": "Alias DII Remove",
        "ingredients": ["al_rm_base"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    sid = state["session_id"]

    added = parse(dii_add_manual({"session_id": sid, "ingredient": "al_rm_old"}))
    check("add_manual canonicalizes",
          "al_rm_new" in added["essential_ingredients"], f"got {added}")

    # Removing by the spelling the user typed has to find the canonical entry,
    # or an ingredient added this way could never be taken back out.
    removed = parse(dii_remove_ingredient({"session_id": sid, "ingredient": "al_rm_old"}))
    check("remove by the retired spelling still removes it",
          "al_rm_new" not in removed["essential_ingredients"], f"got {removed}")
    check("removal is not reported as a no-op",
          removed.get("no_change") is not True, f"got {removed}")


def test_dii_corrupt_session_backup_is_swept():
    print("\n-- DII survives a malformed session backup file --")
    sessions = _TMP_DATA_DIR / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    # Valid JSON of the wrong shape. Reading last_activity off it raised
    # AttributeError out of the orphan sweep, which took down every DII tool —
    # including the sweep that should have removed the file.
    junk = sessions / "mm_junk_backup.json"
    junk.write_text("[]", encoding="utf-8")

    store = _dii_mod._store
    store._last_cleanup_monotonic = 0.0  # defeat the debounce

    state = parse(init_ingredient_session({
        "dish_name": "Junk Backup Dish",
        "ingredients": ["jb_one"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    check("DII still works with a malformed backup present",
          "error" not in state, f"got {state}")

    store._last_cleanup_monotonic = 0.0
    read_back = parse(dii_get_state({"session_id": state["session_id"]}))
    check("reads still work", "error" not in read_back, f"got {read_back}")
    check("the malformed backup is swept away", not junk.exists())


def test_update_fridge_add_clamps_to_max():
    print("\n-- update_fridge_inventory add respects the portion ceiling --")
    cap = _handlers_common.MAX_PORTION_COUNT
    update_fridge_inventory({"action": "set", "ingredients": {"clamp_me": cap}})
    update_fridge_inventory({"action": "add", "ingredients": {"clamp_me": cap}})
    fridge = _repos_mod.fridge_repo.load()
    check("a running total cannot exceed MAX_PORTION_COUNT",
          fridge.get("clamp_me") == cap, f"got {fridge.get('clamp_me')}")


def test_update_fridge_expiry_on_staple():
    print("\n-- update_fridge_inventory records an expiry on a pantry staple --")
    update_fridge_inventory({"action": "set", "ingredients": {"staple_oil": None}})
    msg = update_fridge_inventory({"action": "add", "ingredients": {
        "staple_oil": {"count": 1, "expires_on": "2026-12-01"},
    }})
    entries = _repos_mod.fridge_repo.load_entries()
    check("the date is stored rather than discarded",
          entries.get("staple_oil", {}).get("expires_on") == "2026-12-01",
          f"got {entries.get('staple_oil')}")
    check("it stays a staple", entries.get("staple_oil", {}).get("count") is None,
          f"got {entries.get('staple_oil')}")
    check("the message reports the expiry", "Expiry recorded" in msg, f"got {msg}")

    # A staple with no date supplied is still the old no-op.
    msg2 = update_fridge_inventory({"action": "add", "ingredients": {"staple_oil": 2}})
    check("a plain add onto a staple is still a no-op",
          "already a pantry staple" in msg2, f"got {msg2}")


def test_merge_alias_clamps_out_of_band_count():
    print("\n-- merge_ingredient_alias clamps a passthrough count --")
    _clear_aliases()
    cap = _handlers_common.MAX_PORTION_COUNT
    # Only reachable by hand-editing, but the merge used to copy it verbatim
    # because only the summing branch clamped.
    _repos_mod.fridge_repo.save_entries(
        {"oob_from": {"count": 5000, "expires_on": None}}
    )
    res = parse(merge_ingredient_alias({"from_name": "oob_from", "to_name": "oob_to"}))
    check("the merged count is clamped", res.get("resulting_count") == cap, f"got {res}")


def test_init_session_rejects_bad_pre_select():
    print("\n-- init_ingredient_session validates pre_select_top_n --")
    base = {
        "dish_name": "Pre Select Dish",
        "ingredients": ["ps_a", "ps_b", "ps_c", "ps_d"],
        "is_essential": [True, True, True, True],
    }
    for bad in ("garbage", 3.9, True):
        res = parse(init_ingredient_session({**base, "pre_select_top_n": bad}))
        check(f"pre_select_top_n={bad!r} rejected",
              "error" in res and "integer" in res["error"], f"got {res}")

    res = parse(init_ingredient_session({**base, "pre_select_top_n": 2}))
    check("a valid value is still honoured",
          res.get("essential_ingredients") == ["ps_a", "ps_b"], f"got {res}")
    res = parse(init_ingredient_session(base))
    check("an omitted value still defaults to 3",
          res.get("essential_ingredients") == ["ps_a", "ps_b", "ps_c"], f"got {res}")


def test_history_unreadable_degrades_and_reports():
    print("\n-- unreadable history.json: suggestions degrade, reporting errors --")
    path = _TMP_DATA_DIR / "history.json"
    original = path.read_text(encoding="utf-8")
    path.chmod(0o000)
    try:
        # Root ignores the mode bits, so only assert when the chmod took.
        try:
            path.read_text(encoding="utf-8")
            enforced = False
        except OSError:
            enforced = True

        if enforced:
            suggestions = parse(get_meal_suggestions({}))
            check("get_meal_suggestions degrades instead of erroring",
                  isinstance(suggestions, list), f"got {suggestions}")
            listed = parse(list_cooking_history({}))
            check("list_cooking_history still surfaces the problem",
                  "error" in listed, f"got {listed}")
            check("the envelope names the file, not its path",
                  "/" not in listed.get("error", "/"), f"got {listed}")
        else:
            check("history permission test skipped (running as root)", True)
    finally:
        path.chmod(0o644)
        path.write_text(original, encoding="utf-8")


def test_dii_store_ttl_and_recovery():
    print("\n-- DII store: TTL expiry, crash recovery, traversal guard --")
    store_mod = importlib.import_module(".src.dii.store", _PLUGIN_DIR.name)
    session_mod = importlib.import_module(".src.dii.session", _PLUGIN_DIR.name)
    tmp = Path(tempfile.mkdtemp(prefix="store_ttl_"))
    try:
        store = store_mod.IngredientSessionStore(session_dir=tmp)
        fresh = session_mod.DIISession(
            session_id="alpha", dish_name="d",
            created_at=session_mod.now_iso(), last_activity=session_mod.now_iso())
        store.put(fresh)
        # (a) crash recovery: a brand-new store rehydrates from the backup file.
        reloaded = store_mod.IngredientSessionStore(session_dir=tmp).get("alpha")
        check("crash-recovery reloads a live session", reloaded is not None)
        # (b) expired session is purged from memory and disk.
        old = "2000-01-01T00:00:00+00:00"
        stale = session_mod.DIISession(
            session_id="beta", dish_name="d", created_at=old, last_activity=old)
        store.put(stale)
        check("expired session not served", store.get("beta") is None)
        check("expired backup deleted", not (tmp / "beta.json").exists())
        # (c) path-traversal id rejected before any filesystem access.
        try:
            store.get("../../etc/passwd")
            check("traversal id rejected", False, "should have raised ValueError")
        except ValueError:
            check("traversal id rejected", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dii_session_lock_is_exclusive():
    print("\n-- DII store: per-session lock survives a concurrent cleanup --")
    import threading
    store_mod = importlib.import_module(".src.dii.store", _PLUGIN_DIR.name)
    session_mod = importlib.import_module(".src.dii.session", _PLUGIN_DIR.name)
    tmp = Path(tempfile.mkdtemp(prefix="store_lock_"))
    try:
        # cleanup_interval_seconds=0 makes every call sweep, which is what used
        # to evict a lock out from under the thread holding it — after which the
        # next caller got a fresh mutex and both ran the critical section.
        store = store_mod.IngredientSessionStore(session_dir=tmp,
                                                 cleanup_interval_seconds=0)
        session = session_mod.DIISession(
            session_id="locked", dish_name="d",
            created_at=session_mod.now_iso(), last_activity=session_mod.now_iso())
        store.put(session)

        inside, overlaps = [], []
        done = threading.Event()

        def worker(tag):
            for _ in range(100):
                with store.session_lock("locked"):
                    inside.append(tag)
                    if len(inside) > 1:
                        overlaps.append(tuple(inside))
                    inside.remove(tag)

        def sweeper():
            while not done.is_set():
                store.cleanup_expired()
                store.get("locked")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        sweep = threading.Thread(target=sweeper, daemon=True)
        sweep.start()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        done.set()

        check("no two threads inside the critical section",
              overlaps == [], f"got {overlaps[:3]}")
        check("lock map self-prunes when idle", store._locks == {}, f"got {store._locks}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dii_finalize_reports_fridge_additions():
    print("\n-- DII: finalize reports commit vs. how much changed --")
    update_fridge_inventory({"action": "set", "ingredients": {"already_here": 2}})
    state = parse(init_ingredient_session({
        "dish_name": "Ya En Nevera",
        "ingredients": ["already_here"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    res = parse(finalize_ingredient_session({"session_id": state["session_id"]}))
    # The commit happened in full; nothing needed adding. Reporting False here
    # used to read as a failure to the caller.
    check("commit reported as done even with nothing to add",
          res["committed_to_fridge"] is True, f"got {res}")
    check("items-added count carries the 'what changed' signal",
          res["fridge_items_added"] == 0, f"got {res}")
    check("existing count untouched",
          _repos_mod.fridge_repo.load().get("already_here") == 2)

    state2 = parse(init_ingredient_session({
        "dish_name": "Nueva Nevera",
        "ingredients": ["brand_new"],
        "is_essential": [True],
        "pre_select_top_n": 1,
    }))
    res2 = parse(finalize_ingredient_session({"session_id": state2["session_id"]}))
    check("fresh ingredient counted", res2["fridge_items_added"] == 1, f"got {res2}")


def test_dii_session_id_traversal_rejected():
    print("\n-- security: session_id path traversal cannot touch other files --")
    (_TMP_DATA_DIR / "dishes.json").write_text(
        json.dumps({"dishes": [{"name": "safe", "ingredients": {"a": True}}]}),
        encoding="utf-8")
    res = parse(dii_get_state({"session_id": "../dishes"}))
    check("traversing session_id returns an error", "error" in res, f"got: {res}")
    check("catalog file untouched by traversal read",
          (_TMP_DATA_DIR / "dishes.json").exists())
    res2 = parse(init_ingredient_session({
        "dish_name": "x", "ingredients": ["a"], "is_essential": [True],
        "session_id": "../evil",
    }))
    check("traversing session_id on init rejected", "error" in res2, f"got: {res2}")
    check("no file written outside sessions/",
          not (_TMP_DATA_DIR / "evil.json").exists())


def test_dish_load_preserves_malformed():
    print("\n-- data integrity: unparseable dish entry preserved across writes --")
    (_TMP_DATA_DIR / "dishes.json").write_text(json.dumps({"dishes": [
        {"name": "keeper", "ingredients": {"a": True}},
        {"name": "victim", "ingredients": {"b": True}},
        {"name": "legacy", "ingredients": {"c": "yes"}},  # non-bool -> unparseable
    ]}), encoding="utf-8")
    res = parse(delete_dish({"dish_name": "victim"}))
    check("deleted the targeted dish",
          isinstance(res, str) and "deleted" in res.lower(), f"got: {res}")
    raw = json.loads((_TMP_DATA_DIR / "dishes.json").read_text())
    names = [d["name"] for d in raw["dishes"]]
    check("unrelated unparseable entry preserved", "legacy" in names, f"got: {names}")
    check("valid untargeted dish preserved", "keeper" in names, f"got: {names}")
    check("targeted dish removed", "victim" not in names, f"got: {names}")

    # Adding a valid dish whose name collides with the preserved malformed row
    # must NOT create a permanent duplicate-named ghost: the malformed twin is
    # dropped in favour of the live dish.
    add_dish({"name": "legacy", "ingredients": {"real": True}})
    raw2 = json.loads((_TMP_DATA_DIR / "dishes.json").read_text())
    legacy_rows = [d for d in raw2["dishes"] if d.get("name") == "legacy"]
    check("no duplicate-named ghost after re-adding the name",
          len(legacy_rows) == 1 and legacy_rows[0]["ingredients"] == {"real": True},
          f"got: {legacy_rows}")


# ---------------------------------------------------------------------------
# Tool discovery and plugin wiring
# ---------------------------------------------------------------------------

def _public_handler_modules() -> set[str]:
    """Module names under src/handlers/ that iter_tools() should pick up."""
    handlers_dir = _PLUGIN_DIR / "src" / "handlers"
    return {
        p.stem for p in handlers_dir.glob("*.py")
        if not p.stem.startswith("_")
    }


def test_iter_tools_discovers_every_handler():
    print("\n-- iter_tools (auto-discovery) --")
    tools = list(_handlers_pkg.iter_tools())
    modules = _public_handler_modules()

    # Count equality is the point: a module that fails to import, or that lost
    # one of NAME/SCHEMA/HANDLER, is dropped with only a log line otherwise.
    check("one tool per public handler module",
          len(tools) == len(modules),
          f"{len(tools)} tools vs {len(modules)} modules: "
          f"{sorted(modules - {n for n, _, _ in tools})}")

    names = [name for name, _, _ in tools]
    check("every NAME is a non-empty string",
          all(isinstance(n, str) and n.strip() for n in names))
    check("every NAME is unique", len(set(names)) == len(names), f"got {names}")
    check("module names match tool names", set(names) == modules,
          f"symmetric difference: {set(names) ^ modules}")

    check("every SCHEMA is a dict", all(isinstance(s, dict) for _, s, _ in tools))
    bad_desc = [
        n for n, s, _ in tools
        if not isinstance(s.get("description"), str) or not s["description"].strip()
    ]
    check("every SCHEMA has a non-empty description", bad_desc == [], f"got {bad_desc}")
    check("every HANDLER is callable", all(callable(h) for _, _, h in tools))
    check("iteration order is alphabetical", names == sorted(names), f"got {names}")


def test_plugin_yaml_matches_registered_tools():
    print("\n-- plugin.yaml / iter_tools sync --")
    # plugin.yaml is documented as manually synced with src/handlers/, so drift
    # is a test failure rather than something discovered at load time. Parsed
    # with the stdlib: the tools list is a simple block sequence and the repo
    # has no runtime dependency on PyYAML.
    text = (_PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
    declared: list[str] = []
    in_list = False
    for line in text.splitlines():
        if line.startswith("provides_tools:"):
            in_list = True
            continue
        if in_list:
            stripped = line.strip()
            if stripped.startswith("- "):
                declared.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("#"):
                break  # next top-level key ends the sequence

    check("the tools list was actually parsed", len(declared) > 0, f"got {declared}")
    registered = {name for name, _, _ in _handlers_pkg.iter_tools()}
    check("plugin.yaml declares exactly the registered tools",
          set(declared) == registered,
          f"only in yaml: {sorted(set(declared) - registered)}; "
          f"only registered: {sorted(registered - set(declared))}")
    check("no duplicate entries in plugin.yaml",
          len(declared) == len(set(declared)), f"got {declared}")


class _FakeCtx:
    """Minimal stand-in for the Hermes plugin context."""

    def __init__(self):
        self.registered: list[tuple] = []
        self.injected: list[str] = []

    def register_tool(self, name, plugin, schema, handler):
        self.registered.append((name, plugin, schema, handler))

    def inject_message(self, text):
        self.injected.append(text)


def test_register_wires_every_tool():
    print("\n-- register() (plugin entry point) --")
    # register(data_dir=…) reconfigures the repository and DII singletons
    # globally, so this must restore _TMP_DATA_DIR afterwards or every test
    # that runs after it reads the wrong directory. It is placed late in
    # main() for the same reason.
    assert _TMP_DATA_DIR is not None
    other = Path(tempfile.mkdtemp(prefix="meal_manager_register_"))
    try:
        ctx = _FakeCtx()
        _pkg.register(ctx, data_dir=other)

        expected = [name for name, _, _ in _handlers_pkg.iter_tools()]
        got = [name for name, _, _, _ in ctx.registered]
        check("one register_tool call per discovered tool",
              got == expected, f"got {got}")
        check("every registration names the plugin",
              all(plugin == "meal_manager" for _, plugin, _, _ in ctx.registered))
        check("schemas and handlers are passed through",
              all(isinstance(s, dict) and callable(h)
                  for _, _, s, h in ctx.registered))

        skill_text = (_PLUGIN_DIR / "skill.md").read_text(encoding="utf-8")
        check("skill.md was injected exactly once", len(ctx.injected) == 1)
        check("the injected text is skill.md",
              ctx.injected == [skill_text] if ctx.injected else False)

        check("data_dir redirected the dish repository",
              _repos_mod.dish_repo.path == other / "dishes.json",
              f"got {_repos_mod.dish_repo.path}")
        check("data_dir redirected the DII session directory",
              _dii_mod._store.session_dir == other / "sessions",
              f"got {_dii_mod._store.session_dir}")
    finally:
        _repos_mod.configure(_TMP_DATA_DIR)
        _dii_mod.configure(_TMP_DATA_DIR / "sessions")
        shutil.rmtree(other, ignore_errors=True)

    check("configuration restored for the tests that follow",
          _repos_mod.dish_repo.path == _TMP_DATA_DIR / "dishes.json",
          f"got {_repos_mod.dish_repo.path}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    _setup_tmp_data()
    try:
        run(test_list_fridge)
        # These two run against the untouched seed fridge: the fridge tests
        # below add 'pollo', which would make Arroz con Pollo cookable, and
        # would also overwrite the legacy list-shaped fixture file.
        run(test_fridge_legacy_list_migrates)
        run(test_get_missing_for_dish)
        run(test_update_fridge_add)
        run(test_update_fridge_add_duplicate)
        run(test_update_fridge_remove_ignores_counts)
        run(test_update_fridge_remove)
        run(test_get_meal_suggestions)
        run(test_get_quick_shopping_list)
        run(test_get_quick_shopping_list_max_missing)
        run(test_register_cooked_meal)
        run(test_register_cooked_meal_bogus)
        run(test_register_cooked_meal_rollback)
        run(test_delete_history_entry)
        run(test_delete_history_entry_bogus)
        run(test_add_dish_dict)
        run(test_add_dish_list)
        run(test_add_dish_duplicate)
        run(test_add_dish_invalid_inputs)
        run(test_edit_dish)
        run(test_edit_dish_bogus)
        run(test_delete_dish)
        run(test_delete_dish_bogus)
        run(test_add_dishes_batch)
        run(test_clear_fridge)
        run(test_clear_fridge_already_empty)

        # Portion counts. These run on the emptied fridge and set up their own
        # state, so they cannot perturb the assertions above.
        run(test_fridge_counts_and_staples)
        run(test_cook_decrements_instead_of_deleting)
        run(test_register_cooked_meal_backdated)
        run(test_register_cooked_meal_backdate_preserves_newer)

        # DII
        run(test_dii_full_lifecycle)
        run(test_dii_clear_all)
        run(test_dii_expired_session)
        run(test_dii_finalize_twice)
        run(test_dii_finalize_options)
        run(test_dii_finalize_rollback)
        run(test_dii_get_state)
        run(test_dii_add_manual_empty)

        # Regression tests for the review fixes. The state-preserving ones run
        # first; the two that overwrite dishes.json wholesale run last so they
        # cannot perturb the catalog the earlier assertions depend on.
        run(test_missing_required_arg_message)
        run(test_unknown_argument_rejected)
        run(test_history_event_log_on_disk)
        run(test_history_rollback_hard_deletes_the_event)
        run(test_delete_history_entry_releases_the_cooldown)
        run(test_list_cooking_history)
        run(test_list_cooking_history_validation)
        run(test_list_cooking_history_surfaces_corruption)
        run(test_dish_instructions_roundtrip)
        run(test_edit_dish_preserves_instructions)
        run(test_dish_instructions_errors)
        run(test_add_dish_with_instructions)
        run(test_add_dishes_batch_partial_failure)
        run(test_dii_remove_optional_no_recalc)
        run(test_edit_dish_empty_rejected)
        run(test_dii_finalize_empty_selection_no_wipe)
        run(test_dii_store_ttl_and_recovery)
        run(test_dii_session_lock_is_exclusive)
        run(test_dii_finalize_reports_fridge_additions)

        # Online weight tuning (self-contained; runs late so it cannot perturb
        # the fridge/catalog state the earlier assertions depend on).
        run(test_online_weight_tuning)

        # Ingredient expiry. Self-contained: uses its own exp_* keys.
        run(test_fridge_expiry_end_to_end)
        run(test_fridge_expiry_validation)

        # Ingredient aliases. These register a persistent alias map that the
        # tool boundary consults on every later call, so they run late and
        # clear the map when they are done.
        run(test_merge_ingredient_alias_catalog_only)
        run(test_merge_ingredient_alias_fridge_counts)
        run(test_merge_ingredient_alias_essential_wins)
        run(test_merge_ingredient_alias_boundary_resolution)
        run(test_merge_ingredient_alias_unlocks_a_dish)
        run(test_merge_ingredient_alias_errors)

        # Regression tests for the code-review findings.
        run(test_dii_init_resolves_aliases)
        run(test_dii_remove_resolves_aliases)
        run(test_dii_corrupt_session_backup_is_swept)
        run(test_update_fridge_add_clamps_to_max)
        run(test_update_fridge_expiry_on_staple)
        run(test_merge_alias_clamps_out_of_band_count)
        run(test_init_session_rejects_bad_pre_select)
        run(test_history_unreadable_degrades_and_reports)

        # Tool discovery and plugin wiring. Read-only against the catalog, but
        # test_register_wires_every_tool reconfigures the repository and DII
        # singletons globally and restores them in its own finally: — so it
        # runs late, where a slip would damage the least.
        run(test_iter_tools_discovers_every_handler)
        run(test_plugin_yaml_matches_registered_tools)
        run(test_register_wires_every_tool)

        # These overwrite dishes.json wholesale — keep them last.
        run(test_dii_session_id_traversal_rejected)
        run(test_dish_load_preserves_malformed)

    finally:
        _teardown_tmp_data()

    print(f"\n{'='*40}")
    print(f"  {_passed} passed, {_failed} failed")
    print(f"{'='*40}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
