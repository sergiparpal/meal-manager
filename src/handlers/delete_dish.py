"""Tool: delete_dish — remove a recipe from the catalog."""

import logging

from ..repositories import dish_repo, history_repo
from ._common import normalize_dish_name, tool_handler

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


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    raw_name = args["dish_name"]
    name = normalize_dish_name(raw_name)

    with dish_repo.lock:
        dishes = dish_repo.load()
        deleted = next((d for d in dishes if d.name == name), None)
        if deleted is None:
            raise LookupError(f"'{raw_name}' not found in the catalog.")
        remaining = [d for d in dishes if d.name != name]
        dish_repo.save(remaining)

    try:
        history_repo.remove_entry(name)
    except Exception:
        try:
            dish_repo.restore(deleted)
        except Exception:
            logger.exception("delete_dish rollback failed")
        raise

    return f"Deleted '{name}' from the catalog."
