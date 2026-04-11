"""Integration smoke test for all 19 meal_manager tools.

Backs up data files before running and restores them afterwards so the test
is idempotent and never pollutes live data.

Usage:
    python3 test_hermes.py
"""

import importlib
import json
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: make relative imports work when running standalone.
# We import the plugin directory as a package so that internal relative
# imports (e.g. ``from .src.storage import ...``) resolve correctly.
# ---------------------------------------------------------------------------

_PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_PLUGIN_DIR.parent))
_pkg = importlib.import_module(_PLUGIN_DIR.name)

# ---------------------------------------------------------------------------
# Data backup / restore
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parent / "data"
_BACKUP_DIR = _DATA_DIR / "_test_backup"
_DATA_FILES = ["dishes.json", "fridge.json", "history.json"]


def _backup():
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for name in _DATA_FILES:
        src = _DATA_DIR / name
        if src.exists():
            shutil.copy2(src, _BACKUP_DIR / name)
    # Also back up sessions dir
    sessions = _DATA_DIR / "sessions"
    backup_sessions = _BACKUP_DIR / "sessions"
    if sessions.exists():
        if backup_sessions.exists():
            shutil.rmtree(backup_sessions)
        shutil.copytree(sessions, backup_sessions)


def _restore():
    for name in _DATA_FILES:
        backup = _BACKUP_DIR / name
        if backup.exists():
            shutil.copy2(backup, _DATA_DIR / name)
    # Restore sessions dir
    sessions = _DATA_DIR / "sessions"
    backup_sessions = _BACKUP_DIR / "sessions"
    if sessions.exists():
        shutil.rmtree(sessions)
    if backup_sessions.exists():
        shutil.copytree(backup_sessions, sessions)
    shutil.rmtree(_BACKUP_DIR)


# ---------------------------------------------------------------------------
# Seed data for a clean test environment
# ---------------------------------------------------------------------------

def _seed():
    """Write known initial state so tests are deterministic."""
    (_DATA_DIR / "dishes.json").write_text(json.dumps({
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

    (_DATA_DIR / "fridge.json").write_text(
        json.dumps(["arroz", "patatas"], ensure_ascii=False), encoding="utf-8"
    )

    (_DATA_DIR / "history.json").write_text(
        json.dumps({"tortilla de patatas": "2026-03-20"}, ensure_ascii=False),
        encoding="utf-8",
    )

    # Clean sessions
    sessions = _DATA_DIR / "sessions"
    if sessions.exists():
        shutil.rmtree(sessions)


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


def parse(raw: str) -> dict | list | str:
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Import tools (after path setup)
# ---------------------------------------------------------------------------

_tools = importlib.import_module(".tools", _PLUGIN_DIR.name)

get_meal_suggestions = _tools.get_meal_suggestions
get_quick_shopping_list = _tools.get_quick_shopping_list
update_fridge_inventory = _tools.update_fridge_inventory
register_cooked_meal = _tools.register_cooked_meal
delete_history_entry = _tools.delete_history_entry
list_fridge = _tools.list_fridge
add_dish = _tools.add_dish
add_dishes_batch = _tools.add_dishes_batch
delete_dish = _tools.delete_dish
edit_dish = _tools.edit_dish
clear_fridge = _tools.clear_fridge
init_ingredient_session = _tools.init_ingredient_session
dii_add_suggested = _tools.dii_add_suggested
dii_skip_suggested = _tools.dii_skip_suggested
dii_remove_ingredient = _tools.dii_remove_ingredient
dii_add_manual = _tools.dii_add_manual
dii_clear_all = _tools.dii_clear_all
finalize_ingredient_session = _tools.finalize_ingredient_session
dii_get_state = _tools.dii_get_state

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
    check("returns error", isinstance(result, str) and "error" in result.lower())


def test_delete_history_entry():
    print("\n-- delete_history_entry --")
    result = parse(delete_history_entry({"dish_name": "arroz con pollo"}))
    check("success message", isinstance(result, str) and "removed" in result.lower())


def test_delete_history_entry_bogus():
    print("\n-- delete_history_entry (nonexistent) --")
    result = parse(delete_history_entry({"dish_name": "nada"}))
    check("returns error", isinstance(result, str) and "error" in result.lower())


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
    check("returns error for duplicate", isinstance(result, str) and "error" in result.lower())


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
    check("returns error", isinstance(result, str) and "error" in result.lower())


def test_delete_dish():
    print("\n-- delete_dish --")
    result = parse(delete_dish({"dish_name": "Pasta Sencilla"}))
    check("success message", isinstance(result, str) and "deleted" in result.lower())


def test_delete_dish_bogus():
    print("\n-- delete_dish (nonexistent) --")
    result = parse(delete_dish({"dish_name": "Nada"}))
    check("returns error", isinstance(result, str) and "error" in result.lower())


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

    # 7. Re-init (simulating agent recalculation) -- reuse session by creating new one
    state = parse(init_ingredient_session({
        "dish_name": "Pizza Margherita",
        "ingredients": ["harina", "tomate", "queso de cabra"],
        "is_essential": [True, True, True],
        "pre_select_top_n": 3,
    }))
    sid2 = state["session_id"]
    check("new session for recalculation", sid2 != sid)
    check("queso de cabra pre-selected", "queso de cabra" in state["essential_ingredients"])

    # 8. Finalize
    state = parse(finalize_ingredient_session({"session_id": sid2}))
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
    _backup()
    try:
        _seed()

        test_list_fridge()
        test_update_fridge_add()
        test_update_fridge_add_duplicate()
        test_update_fridge_remove()
        test_get_meal_suggestions()
        test_get_quick_shopping_list()
        test_register_cooked_meal()
        test_register_cooked_meal_bogus()
        test_delete_history_entry()
        test_delete_history_entry_bogus()
        test_add_dish_dict()
        test_add_dish_list()
        test_add_dish_duplicate()
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
        test_dii_get_state()
        test_dii_add_manual_empty()

    finally:
        _restore()

    print(f"\n{'='*40}")
    print(f"  {_passed} passed, {_failed} failed")
    print(f"{'='*40}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
