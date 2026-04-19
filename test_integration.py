"""Integration smoke test for all 19 meal_manager tools.

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

# ---------------------------------------------------------------------------
# Tmp data directory lifecycle
# ---------------------------------------------------------------------------

_DATA_FILES = ["dishes.json", "fridge.json", "history.json"]
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

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_fridge():
    print("\n-- list_fridge --")
    result = parse(list_fridge({}))
    check("returns a list", isinstance(result, list))
    check("contains seeded items", "arroz" in result and "patatas" in result)
    check("has exactly 2 items", len(result) == 2, f"got {len(result)}")


def test_update_fridge_add():
    print("\n-- update_fridge_inventory (add) --")
    result = parse(update_fridge_inventory({"action": "add", "ingredients": ["pollo", "huevos"]}))
    check("returns success string", isinstance(result, str) and "error" not in result.lower())

    fridge = parse(list_fridge({}))
    check("pollo added", "pollo" in fridge)
    check("huevos added", "huevos" in fridge)
    check("originals preserved", "arroz" in fridge and "patatas" in fridge)


def test_update_fridge_add_duplicate():
    print("\n-- update_fridge_inventory (add duplicate) --")
    result = parse(update_fridge_inventory({"action": "add", "ingredients": ["pollo"]}))
    check("no-op for duplicates", isinstance(result, str) and "no change" in result.lower())


def test_update_fridge_remove():
    print("\n-- update_fridge_inventory (remove) --")
    result = parse(update_fridge_inventory({"action": "remove", "ingredients": ["huevos"]}))
    check("returns success string", isinstance(result, str) and "removed" in result.lower())

    fridge = parse(list_fridge({}))
    check("huevos removed", "huevos" not in fridge)


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


def test_register_cooked_meal():
    print("\n-- register_cooked_meal --")
    result = parse(register_cooked_meal({"dish_name": "arroz con pollo"}))
    check("success message", isinstance(result, str) and "registered" in result.lower(),
          f"got: {result}")
    check("removes essentials from fridge",
          "arroz" not in parse(list_fridge({})) and "pollo" not in parse(list_fridge({})))


def test_register_cooked_meal_bogus():
    print("\n-- register_cooked_meal (nonexistent dish) --")
    result = parse(register_cooked_meal({"dish_name": "Plato Inventado"}))
    check("returns error", isinstance(result, dict) and "error" in result, f"got: {result}")


def test_register_cooked_meal_rollback():
    print("\n-- register_cooked_meal (rollback) --")
    before = _repos_mod.history_repo.load()

    original_save = _repos_mod.fridge_repo.save
    try:
        def fail_save(_fridge):
            raise RuntimeError("boom")

        _repos_mod.fridge_repo.save = fail_save
        result = parse(register_cooked_meal({"dish_name": "tortilla de patatas"}))
        check("returns error on fridge failure", isinstance(result, dict) and "error" in result)
        check("history restored after failure", _repos_mod.history_repo.load() == before)
    finally:
        _repos_mod.fridge_repo.save = original_save


def test_delete_history_entry():
    print("\n-- delete_history_entry --")
    result = parse(delete_history_entry({"dish_name": "arroz con pollo"}))
    check("success message", isinstance(result, str) and "removed" in result.lower())


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
    check("fridge is empty", len(fridge) == 0, f"got {fridge}")


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
    fridge = parse(list_fridge({}))
    check("harina in fridge after finalize", "harina" in fridge)
    check("tomate in fridge after finalize", "tomate" in fridge)
    check("queso de cabra in fridge after finalize", "queso de cabra" in fridge)


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

    parse(finalize_ingredient_session({"session_id": sid}))
    # After H1 fix, finalized sessions are cleaned up from memory and disk,
    # so a second finalize correctly reports "session not found".
    state2 = parse(finalize_ingredient_session({"session_id": sid}))
    check("second finalize returns session-not-found error",
          "error" in state2 and "not found" in state2["error"].lower(),
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
# Runner
# ---------------------------------------------------------------------------

def main():
    _setup_tmp_data()
    try:
        test_list_fridge()
        test_update_fridge_add()
        test_update_fridge_add_duplicate()
        test_update_fridge_remove()
        test_get_meal_suggestions()
        test_get_quick_shopping_list()
        test_register_cooked_meal()
        test_register_cooked_meal_bogus()
        test_register_cooked_meal_rollback()
        test_delete_history_entry()
        test_delete_history_entry_bogus()
        test_add_dish_dict()
        test_add_dish_list()
        test_add_dish_duplicate()
        test_add_dish_invalid_inputs()
        test_edit_dish()
        test_edit_dish_bogus()
        test_delete_dish()
        test_delete_dish_bogus()
        test_add_dishes_batch()
        test_clear_fridge()
        test_clear_fridge_already_empty()

        # DII
        test_dii_full_lifecycle()
        test_dii_clear_all()
        test_dii_expired_session()
        test_dii_finalize_twice()
        test_dii_finalize_options()
        test_dii_finalize_rollback()
        test_dii_get_state()
        test_dii_add_manual_empty()

    finally:
        _teardown_tmp_data()

    print(f"\n{'='*40}")
    print(f"  {_passed} passed, {_failed} failed")
    print(f"{'='*40}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
