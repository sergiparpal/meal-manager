"""Tool: register_cooked_meal — record cook event and consume essentials."""

import logging
from datetime import date

from .. import tuning
from ..repositories import dish_repo, fridge_repo, history_repo, tuning_repo
from ._common import (
    days_since_last_cook,
    normalize_dish_name,
    require_arg,
    tool_handler,
)

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
    raw_name = require_arg(args, "dish_name")
    name = normalize_dish_name(raw_name)

    with dish_repo.lock:
        dishes = dish_repo.load()
        dish = next((d for d in dishes if d.name == name), None)

    if dish is None:
        raise LookupError(f"'{raw_name}' is not in the recipe catalog.")

    # Snapshot the decision state as it was at the moment the user chose to
    # cook — before history and fridge are mutated below. The learning update
    # at the end of the handler replays the ranking against this snapshot.
    fridge_snapshot = fridge_repo.load_set()
    days_snapshot = days_since_last_cook()

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

    # Best-effort online weight tuning. This must never fail or roll back the
    # cook registration: any error here is logged and swallowed.
    try:
        with tuning_repo.lock:
            state = tuning_repo.load()
            rewards = tuning.compute_rewards(
                name, dishes, fridge_snapshot, days_snapshot, state["candidates"]
            )
            if rewards is not None:
                state = tuning.apply_update(state, rewards)
                state = tuning.select_deployed(state)
                tuning_repo.save(state)
    except Exception:
        logger.exception("weight tuning update failed (non-critical)")

    removed_msg = f" Removed from fridge: {', '.join(removed)}." if removed else ""
    return f"Registered '{dish.name}' as cooked on {today_iso}.{removed_msg}"
