"""Tool: delete_history_entry — undo a cook registration."""

import logging

from .. import data_lock
from ..repositories import fridge_repo, history_repo
from ._common import MAX_PORTION_COUNT, normalize_dish_name, require_arg, tool_handler

logger = logging.getLogger(__name__)

NAME = "delete_history_entry"

SCHEMA = {
    "description": (
        "Retract the most recent cook of a dish. This is the undo for "
        "register_cooked_meal: use it when the user registered a meal by "
        "mistake or wants to reset the recency cooldown for a dish. It takes "
        "back one cook, not the dish's whole history — earlier cooks stay on "
        "record, and the retracted one remains visible through "
        "list_cooking_history. Call it again to take back the one before it. "
        "Pass restore_fridge when the meal didn't happen, to put back in the "
        "fridge what that cook used."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name whose latest cook should be retracted",
        },
        "restore_fridge": {
            "type": "boolean",
            "description": (
                "true when the meal didn't actually happen: also puts back the "
                "fridge portions that cook used. Leave it out when the user did "
                "cook it and only wants the dish suggested again sooner."
            ),
        },
    },
    "required": ["dish_name"],
}


def _describe_restored(restored: dict) -> str:
    parts = []
    for ing, before in sorted(restored.items()):
        if before is None:
            parts.append(f"{ing} (not in the fridge -> 1)")
        else:
            parts.append(f"{ing} ({before} -> {before + 1})")
    return ", ".join(parts)


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    raw_name = require_arg(args, "dish_name")
    name = normalize_dish_name(raw_name)
    restore = args.get("restore_fridge", False)
    if not isinstance(restore, bool):
        raise ValueError("restore_fridge must be true or false")

    # With restore_fridge this touches two repositories, so one window covers
    # both, as in register_cooked_meal: nothing can observe a cook taken back
    # whose portions are not back yet.
    with data_lock:
        event = history_repo.retract_latest_for_dish(name)
        if event is None:
            if history_repo.damaged():
                # Otherwise the user hears that the cook was never recorded,
                # when it may well be in the file that could not be read.
                raise LookupError(
                    "The cooking history file (history.json) is damaged and could "
                    f"not be read, so there is no cook of '{name}' to take back. "
                    "Tell the user."
                )
            raise LookupError(f"'{raw_name}' not found in cooking history.")

        restored: dict = {}
        if restore and event.consumed:
            try:
                restored = fridge_repo.restore(event.consumed, max_count=MAX_PORTION_COUNT)
            except Exception:
                # A take-back whose fridge half failed did not happen: the cook
                # must keep counting, as before.
                try:
                    history_repo.reinstate_event(event.id)
                except Exception:
                    logger.exception("delete_history_entry rollback failed")
                raise

    message = (
        f"Retracted the cook of '{name}' recorded for {event.cooked_on}. "
        "It no longer counts toward the recency cooldown."
    )
    if not restore:
        return message
    if event.consumed is None:
        return message + (
            " Nothing was put back in the fridge: this cook was recorded before"
            " the plugin noted what each cook used."
        )
    if not event.consumed:
        return message + (
            " That cook used no fridge portions, so there was nothing to put back."
        )
    if not restored:
        return message + (
            " Nothing was put back: what that cook used is now a pantry staple"
            " or already at the maximum count."
        )
    return message + f" Put back in the fridge: {_describe_restored(restored)}."
