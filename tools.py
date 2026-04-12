"""Tool handlers for the meal_manager plugin.

Every handler follows the signature ``def handler(args: dict, **kwargs) -> str``
and returns a ``json.dumps()`` string.  Nineteen handlers total.
"""

import json
import logging
import uuid
from datetime import date

from .src.storage import load_dishes, save_dishes, dishes_lock, restore_dish
from .src.history import (
    load_history,
    set_history_entry,
    remove_history_entry,
    revert_history_entry,
)
from .src.dish import Dish
from .src.suggestion import suggest_dishes
from .src.shopping import suggest_quick_shopping
from .src.fridge import (
    load_fridge,
    save_fridge,
    fridge_lock,
    load_fridge_set,
    remove_items_from_fridge,
)
from .src.dii import (
    create_session,
    add_suggested_ingredient as dii_add_suggested_impl,
    skip_suggested_ingredient as dii_skip_suggested_impl,
    remove_ingredient as dii_remove_ingredient_impl,
    add_manual_ingredient as dii_add_manual_impl,
    clear_all_ingredients as dii_clear_all_impl,
    finalize_session as dii_finalize_session_impl,
    get_session_state as dii_get_state_impl,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Input limits (safety net for LLM-generated arguments)
# ---------------------------------------------------------------------------

_MAX_NAME_LEN = 200
_MAX_INGREDIENTS = 100
_MAX_BATCH_SIZE = 50
_MAX_FRIDGE_UPDATE = 200


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _err(msg: str) -> str:
    """Build a consistent JSON error response."""
    return json.dumps({"error": msg}, ensure_ascii=False)


def _normalize_dish_name(name: str) -> str:
    normalized = Dish.normalize_name(name)
    if not normalized:
        raise ValueError("Dish name cannot be empty")
    if len(normalized) > _MAX_NAME_LEN:
        raise ValueError(f"Dish name too long (max {_MAX_NAME_LEN} chars)")
    return normalized


def _normalize_ingredient_name(name: str) -> str:
    normalized = Dish.normalize_ingredient(name)
    if not normalized:
        raise ValueError("Ingredient name cannot be empty")
    if len(normalized) > _MAX_NAME_LEN:
        raise ValueError(f"Ingredient name too long (max {_MAX_NAME_LEN} chars)")
    return normalized


def _days_since_last_cook() -> dict[str, int]:
    """Build a mapping of dish name -> days since it was last cooked."""
    history = load_history()
    today = date.today()
    result = {}
    for name, date_str in history.items():
        try:
            days = (today - date.fromisoformat(date_str)).days
        except ValueError:
            continue
        result[name.strip().lower()] = max(days, 0)
    return result


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
# Read-only handlers (get_meal_suggestions, get_quick_shopping_list) are
# lock-free.  Consistent snapshots are guaranteed by atomic_write_json
# using os.replace under the hood.


def get_meal_suggestions(args: dict, **kwargs) -> str:
    try:
        dishes = load_dishes()
        fridge = load_fridge_set()
        days = _days_since_last_cook()

        ranking = suggest_dishes(dishes, fridge, days)
        result = [
            {"dish": dish.name, "score": round(score, 2)}
            for dish, score in ranking
        ]
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("get_meal_suggestions failed")
        return _err(str(exc))


def get_quick_shopping_list(args: dict, **kwargs) -> str:
    try:
        dishes = load_dishes()
        fridge = load_fridge_set()
        days = _days_since_last_cook()

        shopping = suggest_quick_shopping(dishes, fridge, days)
        result = [
            {
                "missing_ingredient": ingredient,
                "unlocks_dishes": dishes_str,
                "score": round(score, 2),
            }
            for ingredient, dishes_str, score in shopping
        ]
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("get_quick_shopping_list failed")
        return _err(str(exc))


def update_fridge_inventory(args: dict, **kwargs) -> str:
    try:
        action = args["action"]
        ingredients = args["ingredients"]

        if action not in ("add", "remove"):
            raise ValueError(f"action must be 'add' or 'remove', got '{action}'")

        if not isinstance(ingredients, list):
            raise ValueError("ingredients must be an array")

        if len(ingredients) > _MAX_FRIDGE_UPDATE:
            raise ValueError(f"Too many ingredients (max {_MAX_FRIDGE_UPDATE})")

        ingredients = list(dict.fromkeys(
            _normalize_ingredient_name(raw)
            for raw in ingredients
        ))

        if not ingredients:
            return json.dumps("No changes — no valid ingredients provided.", ensure_ascii=False)

        names = ", ".join(ingredients)

        with fridge_lock:
            fridge = load_fridge()

            if action == "add":
                added = [ing for ing in ingredients if ing not in fridge]
                already = [ing for ing in ingredients if ing in fridge]
                if added:
                    fridge.extend(added)
                    save_fridge(fridge)
                    if already:
                        msg = (
                            f"Added {', '.join(added)} to the fridge. "
                            f"Already present: {', '.join(already)}."
                        )
                    else:
                        msg = f"Successfully added {', '.join(added)} to the fridge."
                else:
                    msg = f"No changes — {names} already in the fridge."
            else:
                to_remove = set(ingredients)
                removed = [ing for ing in ingredients if ing in fridge]
                not_found = [ing for ing in ingredients if ing not in fridge]
                if removed:
                    fridge = [ing for ing in fridge if ing not in to_remove]
                    save_fridge(fridge)
                    if not_found:
                        msg = (
                            f"Removed {', '.join(removed)} from the fridge. "
                            f"Not found: {', '.join(not_found)}."
                        )
                    else:
                        msg = f"Successfully removed {', '.join(removed)} from the fridge."
                else:
                    msg = f"No changes — {names} not found in the fridge."

        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        logger.exception("update_fridge_inventory failed")
        return _err(str(exc))


def register_cooked_meal(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        name = _normalize_dish_name(dish_name)

        # Snapshot the catalog under lock so validation and ingredient
        # lookup see a consistent state.
        with dishes_lock:
            dishes = load_dishes()
            dish = next((p for p in dishes if p.name.strip().lower() == name), None)

        if dish is None:
            return json.dumps(f"Error: '{dish_name}' is not in the recipe catalog.", ensure_ascii=False)

        today = date.today()
        today_iso = today.isoformat()
        previous_history = set_history_entry(name, today_iso)

        essentials = [ing for ing, imp in dish.ingredients.items() if imp]

        try:
            with fridge_lock:
                fridge = load_fridge()
                removed = [ing for ing in essentials if ing in fridge]
                if removed:
                    fridge = [ing for ing in fridge if ing not in removed]
                    save_fridge(fridge)
        except Exception:
            # Delta rollback: only revert if our history write is still
            # current; never overwrite a concurrent writer's value.
            try:
                revert_history_entry(name, today_iso, previous_history)
            except Exception:
                logger.exception("register_cooked_meal rollback failed")
            raise

        removed_msg = f" Removed from fridge: {', '.join(removed)}." if removed else ""
        msg = f"Registered '{dish.name}' as cooked on {today_iso}.{removed_msg}"
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        logger.exception("register_cooked_meal failed")
        return _err(str(exc))


def delete_history_entry(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        name = _normalize_dish_name(dish_name)
        if remove_history_entry(name):
            msg = f"Removed '{name}' from cooking history."
        else:
            msg = f"Error: '{dish_name}' not found in cooking history."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        logger.exception("delete_history_entry failed")
        return _err(str(exc))


def list_fridge(args: dict, **kwargs) -> str:
    try:
        result = load_fridge()
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("list_fridge failed")
        return _err(str(exc))


def _normalize_ingredients(ingredients) -> dict:
    """Accept ingredients as dict {name: bool} or list [name, ...] (all essential).
    Also handles JSON strings (some LLMs serialize the argument).
    Raises ValueError if the input cannot be parsed."""
    if isinstance(ingredients, str):
        try:
            ingredients = json.loads(ingredients)
        except json.JSONDecodeError:
            raise ValueError(f"Cannot parse ingredients string: {ingredients!r}")
    if isinstance(ingredients, list):
        result = {}
        for ing in ingredients:
            result[_normalize_ingredient_name(ing)] = True
    elif isinstance(ingredients, dict):
        result = {}
        for key, value in ingredients.items():
            if not isinstance(value, bool):
                raise ValueError(f"ingredient '{key}' must be true or false")
            result[_normalize_ingredient_name(key)] = value
    else:
        raise ValueError(f"ingredients must be a dict or list, got {type(ingredients).__name__}")
    if len(result) > _MAX_INGREDIENTS:
        raise ValueError(f"Too many ingredients (max {_MAX_INGREDIENTS})")
    return result


def add_dish(args: dict, **kwargs) -> str:
    try:
        name = args["name"]
        ingredients = _normalize_ingredients(args["ingredients"])
        normalized = _normalize_dish_name(name)

        with dishes_lock:
            dishes = load_dishes()
            if any(p.name.strip().lower() == normalized for p in dishes):
                return json.dumps(f"Error: a dish called '{normalized}' already exists in the catalog.", ensure_ascii=False)

            new_dish = Dish(name=normalized)
            for ing, essential in ingredients.items():
                new_dish.add_ingredient(ing, essential)
            dishes.append(new_dish)
            save_dishes(dishes)

        n_ess = sum(1 for v in new_dish.ingredients.values() if v)
        n_opt = len(new_dish.ingredients) - n_ess
        msg = f"Added '{normalized}' to the catalog ({n_ess} essential, {n_opt} optional ingredients)."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        logger.exception("add_dish failed")
        return _err(str(exc))


def delete_dish(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        name = _normalize_dish_name(dish_name)

        with dishes_lock:
            dishes = load_dishes()
            deleted = next((p for p in dishes if p.name.strip().lower() == name), None)
            if deleted is None:
                return json.dumps(f"Error: '{dish_name}' not found in the catalog.", ensure_ascii=False)
            remaining = [p for p in dishes if p.name.strip().lower() != name]
            save_dishes(remaining)

        # Clean up orphaned history entry for the deleted dish.
        try:
            remove_history_entry(name)
        except Exception:
            # Delta rollback: re-add only if no concurrent writer has put a
            # same-named dish back.
            try:
                restore_dish(deleted)
            except Exception:
                logger.exception("delete_dish rollback failed")
            raise

        msg = f"Deleted '{name}' from the catalog."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        logger.exception("delete_dish failed")
        return _err(str(exc))


def edit_dish(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        ingredients = _normalize_ingredients(args["ingredients"])
        name = _normalize_dish_name(dish_name)

        with dishes_lock:
            dishes = load_dishes()
            dish = next((p for p in dishes if p.name.strip().lower() == name), None)
            if dish is None:
                return json.dumps(f"Error: '{dish_name}' not found in the catalog.", ensure_ascii=False)

            dish.ingredients = ingredients
            save_dishes(dishes)

        n_ess = sum(1 for v in dish.ingredients.values() if v)
        n_opt = len(dish.ingredients) - n_ess
        msg = f"Updated '{name}' ingredients ({n_ess} essential, {n_opt} optional)."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        logger.exception("edit_dish failed")
        return _err(str(exc))


def add_dishes_batch(args: dict, **kwargs) -> str:
    try:
        dishes_input = args["dishes"]
        if not isinstance(dishes_input, list):
            raise ValueError("dishes must be an array")
        if len(dishes_input) > _MAX_BATCH_SIZE:
            raise ValueError(f"Too many dishes in batch (max {_MAX_BATCH_SIZE})")

        with dishes_lock:
            dishes = load_dishes()
            existing = {p.name.strip().lower() for p in dishes}

            added = []
            skipped = []
            for entry in dishes_input:
                if not isinstance(entry, dict):
                    raise ValueError("each dish must be an object")
                name = _normalize_dish_name(entry["name"])
                if name in existing:
                    skipped.append(name)
                    continue
                ingredients = _normalize_ingredients(entry["ingredients"])
                new_dish = Dish(name=name)
                for ing, essential in ingredients.items():
                    new_dish.add_ingredient(ing, essential)
                dishes.append(new_dish)
                existing.add(name)
                added.append(name)

            if added:
                save_dishes(dishes)

        result = {"added": added, "skipped": skipped}
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("add_dishes_batch failed")
        return _err(str(exc))


def clear_fridge(args: dict, **kwargs) -> str:
    try:
        with fridge_lock:
            fridge = load_fridge()
            count = len(fridge)
            save_fridge([])

        if count == 0:
            msg = "The fridge was already empty."
        else:
            msg = f"Cleared the fridge ({count} ingredient{'s' if count != 1 else ''} removed)."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        logger.exception("clear_fridge failed")
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Dynamic Ingredient Interface (DII) handlers
# ---------------------------------------------------------------------------


def init_ingredient_session(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        dish_name = _normalize_dish_name(dish_name)

        ingredients = args["ingredients"]
        is_essential = args["is_essential"]

        # Parse JSON strings if passed as strings (some LLMs do this)
        if isinstance(ingredients, str):
            try:
                ingredients = json.loads(ingredients)
            except json.JSONDecodeError:
                pass
        if isinstance(is_essential, str):
            try:
                is_essential = json.loads(is_essential)
            except json.JSONDecodeError:
                pass

        # Ensure they are lists
        if not isinstance(ingredients, list) or not isinstance(is_essential, list):
            return _err("ingredients and is_essential must be arrays")

        # Validate parallel arrays have the same length
        if len(ingredients) != len(is_essential):
            return _err(
                f"ingredients ({len(ingredients)}) and is_essential "
                f"({len(is_essential)}) must have the same length"
            )

        if len(ingredients) > _MAX_INGREDIENTS:
            return _err(f"Too many ingredients (max {_MAX_INGREDIENTS})")

        for ing in ingredients:
            _normalize_ingredient_name(ing)
        for flag in is_essential:
            if not isinstance(flag, bool):
                return _err("is_essential must contain boolean values")

        # Convert flat parallel arrays to internal format
        ranked = [
            {"ingredient": ing, "is_essential": ess, "confidence": 0.5}
            for ing, ess in zip(ingredients, is_essential)
        ]

        # Coerce pre_select_top_n to int with default
        pre_select = args.get("pre_select_top_n", 3)
        try:
            pre_select = int(pre_select)
        except (TypeError, ValueError):
            pre_select = 3
        if pre_select < 0:
            return _err("pre_select_top_n must be >= 0")

        # Recalculation path: caller passes the existing session_id to reset
        # it in place. Otherwise generate a fresh id.
        provided_id = args.get("session_id")
        if provided_id is not None:
            if not isinstance(provided_id, str) or not provided_id.strip():
                return _err("session_id must be a non-empty string when provided")
            session_id = provided_id.strip()
            reuse = True
        else:
            session_id = uuid.uuid4().hex[:16]
            reuse = False

        session = create_session(
            session_id=session_id,
            dish_name=dish_name,
            ranked_ingredients=ranked,
            pre_select_top_n=pre_select,
            reuse_existing=reuse,
        )
        return json.dumps(dii_get_state_impl(session.session_id), ensure_ascii=False)
    except Exception as exc:
        logger.exception("init_ingredient_session failed")
        return _err(str(exc))


def dii_add_suggested(args: dict, **kwargs) -> str:
    try:
        result = dii_add_suggested_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("dii_add_suggested failed")
        return _err(str(exc))


def dii_skip_suggested(args: dict, **kwargs) -> str:
    try:
        result = dii_skip_suggested_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("dii_skip_suggested failed")
        return _err(str(exc))


def dii_remove_ingredient(args: dict, **kwargs) -> str:
    try:
        result = dii_remove_ingredient_impl(args["session_id"], args["ingredient"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("dii_remove_ingredient failed")
        return _err(str(exc))


def dii_add_manual(args: dict, **kwargs) -> str:
    try:
        ingredient = _normalize_ingredient_name(args["ingredient"])
        is_essential = args.get("is_essential", True)
        if not isinstance(is_essential, bool):
            raise ValueError("is_essential must be a boolean")
        result = dii_add_manual_impl(
            args["session_id"],
            ingredient,
            is_essential,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("dii_add_manual failed")
        return _err(str(exc))


def dii_clear_all(args: dict, **kwargs) -> str:
    try:
        result = dii_clear_all_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("dii_clear_all failed")
        return _err(str(exc))


def finalize_ingredient_session(args: dict, **kwargs) -> str:
    try:
        commit_to_fridge = args.get("commit_to_fridge", True)
        commit_to_dish = args.get("commit_to_dish", True)
        if not isinstance(commit_to_fridge, bool):
            raise ValueError("commit_to_fridge must be a boolean")
        if not isinstance(commit_to_dish, bool):
            raise ValueError("commit_to_dish must be a boolean")
        result = dii_finalize_session_impl(
            args["session_id"],
            commit_to_fridge=commit_to_fridge,
            commit_to_dish=commit_to_dish,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("finalize_ingredient_session failed")
        return _err(str(exc))


def dii_get_state(args: dict, **kwargs) -> str:
    """Get current DII session state without modifying it."""
    try:
        result = dii_get_state_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        logger.exception("dii_get_state failed")
        return _err(str(exc))
