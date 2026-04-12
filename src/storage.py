import json
import logging
import threading
from pathlib import Path

from . import atomic_write_json
from .dish import Dish

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

BASE_DIR = Path(__file__).resolve().parent.parent
JSON_PATH = BASE_DIR / "data" / "dishes.json"

dishes_lock = threading.Lock()


def load_dishes():
    if not JSON_PATH.exists():
        return []
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to load dishes.json: %s", exc)
        return []
    if not isinstance(data, dict):
        logger.warning(
            "Ignoring dishes.json with unexpected top-level type: %s",
            type(data).__name__,
        )
        return []
    raw_dishes = data.get("dishes", [])
    if not isinstance(raw_dishes, list):
        logger.warning("Ignoring dishes.json with non-list dishes field: %r", raw_dishes)
        return []
    result = []
    for index, p in enumerate(raw_dishes):
        try:
            result.append(Dish.from_dict(p))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Skipping malformed dish entry at index %s: %r (%s)",
                index,
                p,
                exc,
            )
            continue
    return result


def save_dishes(dishes):
    data = {"dishes": [p.to_dict() for p in dishes]}
    atomic_write_json(JSON_PATH, data)


def restore_dish(dish: Dish) -> bool:
    """Re-add *dish* if a same-named entry is no longer in the catalog.

    Used as a delta-rollback for delete_dish: only restores the deleted dish
    if a concurrent writer hasn't already replaced it.
    """
    name_lower = dish.name.strip().lower()
    with dishes_lock:
        dishes = load_dishes()
        if any(d.name.strip().lower() == name_lower for d in dishes):
            return False
        dishes.append(dish)
        save_dishes(dishes)
        return True
