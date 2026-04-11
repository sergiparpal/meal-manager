"""Tool handlers for the meal_manager plugin.

Every handler follows the signature ``def handler(args: dict, **kwargs) -> str``
and returns a ``json.dumps()`` string.
"""

import json
import uuid
from datetime import date

from .src.storage import load_dishes, save_dishes, dishes_lock
from .src.history import load_history, register_cooked_dish, remove_history_entry, history_lock
from .src.dish import Dish
from .src.suggestion import suggest_dishes
from .src.shopping import suggest_quick_shopping
from .src.fridge import load_fridge, save_fridge, fridge_lock
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


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

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

def get_meal_suggestions(args: dict, **kwargs) -> str:
    try:
        dishes = load_dishes()
        fridge = set(load_fridge())
        days = _days_since_last_cook()

        ranking = suggest_dishes(dishes, fridge, days)
        result = [
            {"dish": dish.name, "score": round(score, 2)}
            for dish, score in ranking
        ]
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def get_quick_shopping_list(args: dict, **kwargs) -> str:
    try:
        dishes = load_dishes()
        fridge = set(load_fridge())
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
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def update_fridge_inventory(args: dict, **kwargs) -> str:
    try:
        action = args["action"]
        ingredients = args["ingredients"]

        if action not in ("add", "remove"):
            raise ValueError(f"action must be 'add' or 'remove', got '{action}'")

        ingredients = list(dict.fromkeys(
            ing for raw in ingredients
            if (ing := raw.strip().lower())
        ))

        if not ingredients:
            return json.dumps("No changes — no valid ingredients provided.", ensure_ascii=False)

        names = ", ".join(ingredients)

        with fridge_lock:
            fridge = load_fridge()

            if action == "add":
                added = [ing for ing in ingredients if ing not in fridge]
                fridge.extend(added)
                save_fridge(fridge)
                if not added:
                    msg = f"No changes — {names} already in the fridge."
                else:
                    msg = f"Successfully added {', '.join(added)} to the fridge."
                return json.dumps(msg, ensure_ascii=False)

            # action == "remove"
            to_remove = set(ingredients)
            removed = [ing for ing in ingredients if ing in fridge]
            fridge = [ing for ing in fridge if ing not in to_remove]
            save_fridge(fridge)

        if not removed:
            msg = f"No changes — {names} not found in the fridge."
        else:
            msg = f"Successfully removed {', '.join(removed)} from the fridge."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def register_cooked_meal(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        name = dish_name.strip().lower()

        # Snapshot the catalog under lock so validation and ingredient
        # lookup see a consistent state.
        with dishes_lock:
            dishes = load_dishes()
            dish = next((p for p in dishes if p.name.strip().lower() == name), None)

        if dish is None:
            return json.dumps(f"Error: '{dish_name}' is not in the recipe catalog.", ensure_ascii=False)

        today = date.today()
        register_cooked_dish(name, today.isoformat())

        essentials = [ing for ing, imp in dish.ingredients.items() if imp]

        with fridge_lock:
            fridge = load_fridge()
            removed = [ing for ing in essentials if ing in fridge]
            if removed:
                fridge = [ing for ing in fridge if ing not in removed]
                save_fridge(fridge)

        removed_msg = f" Removed from fridge: {', '.join(removed)}." if removed else ""
        msg = f"Registered '{dish_name}' as cooked on {today.isoformat()}.{removed_msg}"
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def delete_history_entry(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        name = dish_name.strip().lower()
        if remove_history_entry(name):
            msg = f"Removed '{name}' from cooking history."
        else:
            msg = f"Error: '{dish_name}' not found in cooking history."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def list_fridge(args: dict, **kwargs) -> str:
    try:
        result = load_fridge()
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


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
        return {ing.strip().lower(): True for ing in ingredients if isinstance(ing, str) and ing.strip()}
    if isinstance(ingredients, dict):
        return {k.strip().lower(): v for k, v in ingredients.items()}
    raise ValueError(f"ingredients must be a dict or list, got {type(ingredients).__name__}")


def add_dish(args: dict, **kwargs) -> str:
    try:
        name = args["name"]
        ingredients = _normalize_ingredients(args["ingredients"])
        normalized = name.strip().lower()

        with dishes_lock:
            dishes = load_dishes()
            if any(p.name.strip().lower() == normalized for p in dishes):
                return json.dumps(f"Error: a dish called '{normalized}' already exists in the catalog.", ensure_ascii=False)

            new_dish = Dish(name=normalized, prep_time=0)
            for ing, essential in ingredients.items():
                new_dish.add_ingredient(ing, essential)
            dishes.append(new_dish)
            save_dishes(dishes)

        n_ess = sum(1 for v in new_dish.ingredients.values() if v)
        n_opt = len(new_dish.ingredients) - n_ess
        msg = f"Added '{normalized}' to the catalog ({n_ess} essential, {n_opt} optional ingredients)."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def delete_dish(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        name = dish_name.strip().lower()

        with dishes_lock:
            dishes = load_dishes()
            remaining = [p for p in dishes if p.name.strip().lower() != name]
            if len(remaining) == len(dishes):
                return json.dumps(f"Error: '{dish_name}' not found in the catalog.", ensure_ascii=False)
            save_dishes(remaining)

        msg = f"Deleted '{name}' from the catalog."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def edit_dish(args: dict, **kwargs) -> str:
    try:
        dish_name = args["dish_name"]
        ingredients = args["ingredients"]
        name = dish_name.strip().lower()

        with dishes_lock:
            dishes = load_dishes()
            dish = next((p for p in dishes if p.name.strip().lower() == name), None)
            if dish is None:
                return json.dumps(f"Error: '{dish_name}' not found in the catalog.", ensure_ascii=False)

            dish.ingredients = {
                Dish.normalize_ingredient(k): v for k, v in ingredients.items()
            }
            save_dishes(dishes)

        n_ess = sum(1 for v in dish.ingredients.values() if v)
        n_opt = len(dish.ingredients) - n_ess
        msg = f"Updated '{name}' ingredients ({n_ess} essential, {n_opt} optional)."
        return json.dumps(msg, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def add_dishes_batch(args: dict, **kwargs) -> str:
    try:
        dishes_input = args["dishes"]

        with dishes_lock:
            dishes = load_dishes()
            existing = {p.name.strip().lower() for p in dishes}

            added = []
            skipped = []
            for entry in dishes_input:
                name = entry["name"].strip().lower()
                if name in existing:
                    skipped.append(name)
                    continue
                ingredients = _normalize_ingredients(entry["ingredients"])
                new_dish = Dish(name=name, prep_time=0)
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
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


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
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Dynamic Ingredient Interface (DII) handlers
# ---------------------------------------------------------------------------


def init_ingredient_session(args: dict, **kwargs) -> str:
    try:
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
            return json.dumps({"error": "ingredients and is_essential must be arrays"}, ensure_ascii=False)

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

        session = create_session(
            session_id=uuid.uuid4().hex[:16],
            dish_name=args["dish_name"],
            ranked_ingredients=ranked,
            pre_select_top_n=pre_select,
        )
        return json.dumps(dii_get_state_impl(session.session_id), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def dii_add_suggested(args: dict, **kwargs) -> str:
    try:
        result = dii_add_suggested_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def dii_skip_suggested(args: dict, **kwargs) -> str:
    try:
        result = dii_skip_suggested_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def dii_remove_ingredient(args: dict, **kwargs) -> str:
    try:
        result = dii_remove_ingredient_impl(args["session_id"], args["ingredient"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def dii_add_manual(args: dict, **kwargs) -> str:
    try:
        ingredient = args["ingredient"].strip()
        if not ingredient:
            return json.dumps({"error": "Ingredient name cannot be empty"}, ensure_ascii=False)
        result = dii_add_manual_impl(
            args["session_id"],
            ingredient,
            args.get("is_essential", True),
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def dii_clear_all(args: dict, **kwargs) -> str:
    try:
        result = dii_clear_all_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def finalize_ingredient_session(args: dict, **kwargs) -> str:
    try:
        result = dii_finalize_session_impl(
            args["session_id"],
            commit_to_fridge=args.get("commit_to_fridge", True),
            commit_to_dish=args.get("commit_to_dish", True),
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def dii_get_state(args: dict, **kwargs) -> str:
    """Get current DII session state without modifying it."""
    try:
        result = dii_get_state_impl(args["session_id"])
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
