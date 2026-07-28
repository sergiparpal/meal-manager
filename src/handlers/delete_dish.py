"""Tool: delete_dish — remove a recipe from the catalog."""

import logging

from .. import data_lock
from ..repositories import dish_repo, history_repo
from ._common import normalize_dish_name, require_arg, tool_handler

logger = logging.getLogger(__name__)

NAME = "delete_dish"

SCHEMA = {
    "description": (
        "Remove a recipe from the catalog. Use when the user wants to "
        "delete a dish they no longer cook or that was added by mistake."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name to delete from catalog",
        },
    },
    "required": ["dish_name"],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    raw_name = require_arg(args, "dish_name")
    name = normalize_dish_name(raw_name)

    # Catalog and history in one exclusive window (the same reentrant lock backs
    # both repositories), so nothing can observe a dish deleted whose cooks are
    # still counting toward the cooldown, and the rollback below runs with no
    # concurrent writer able to interleave.
    with data_lock:
        dishes = dish_repo.load()
        deleted = next((d for d in dishes if d.name == name), None)
        if deleted is None:
            raise LookupError(f"'{raw_name}' not found in the catalog.")
        remaining = [d for d in dishes if d.name != name]
        dish_repo.save(remaining)

        try:
            # The dish is gone, so its cooks must stop gating suggestions — but
            # retract rather than erase: the log still records they happened.
            history_repo.retract_all_for_dish(name)
        except Exception:
            try:
                dish_repo.restore(deleted)
            except Exception:
                logger.exception("delete_dish rollback failed")
            raise

    return f"Deleted '{name}' from the catalog."
