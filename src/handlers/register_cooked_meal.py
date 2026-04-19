"""Tool: register_cooked_meal — record cook event and consume essentials."""

import logging
from datetime import date

from ..repositories import dish_repo, fridge_repo, history_repo
from ._common import normalize_dish_name, tool_handler

logger = logging.getLogger(__name__)

NAME = "register_cooked_meal"

SCHEMA = {
    "description": (
        "Register that a specific dish was cooked today. Records it in the "
        "cooking history so the suggestion engine avoids recommending it "
        "again too soon. Also auto-removes essential ingredients from the "
        "fridge."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name from the catalog",
        },
    },
    "required": ["dish_name"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    raw_name = args["dish_name"]
    name = normalize_dish_name(raw_name)

    with dish_repo.lock:
        dishes = dish_repo.load()
        dish = next((d for d in dishes if d.name == name), None)

    if dish is None:
        raise LookupError(f"'{raw_name}' is not in the recipe catalog.")

    today_iso = date.today().isoformat()
    previous_history = history_repo.set_entry(name, today_iso)

    essentials = [ing for ing, is_essential in dish.ingredients.items() if is_essential]

    try:
        with fridge_repo.lock:
            fridge = fridge_repo.load()
            removed = [ing for ing in essentials if ing in fridge]
            if removed:
                fridge = [ing for ing in fridge if ing not in removed]
                fridge_repo.save(fridge)
    except Exception:
        try:
            history_repo.revert_entry(name, today_iso, previous_history)
        except Exception:
            logger.exception("register_cooked_meal rollback failed")
        raise

    removed_msg = f" Removed from fridge: {', '.join(removed)}." if removed else ""
    return f"Registered '{dish.name}' as cooked on {today_iso}.{removed_msg}"
