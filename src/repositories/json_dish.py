"""JSON-file-backed implementation of DishRepository."""

import json
import logging
import threading
from pathlib import Path

from .. import atomic_write_json
from ..dish import Dish

logger = logging.getLogger(__name__)


class JsonDishRepository:
    """Stores the dish catalog as ``{"dishes": [...]}`` in a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> list[Dish]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load %s: %s", self.path.name, exc)
            return []
        if not isinstance(data, dict):
            logger.warning(
                "Ignoring %s with unexpected top-level type: %s",
                self.path.name,
                type(data).__name__,
            )
            return []
        raw_dishes = data.get("dishes", [])
        if not isinstance(raw_dishes, list):
            logger.warning(
                "Ignoring %s with non-list dishes field: %r",
                self.path.name,
                raw_dishes,
            )
            return []
        result: list[Dish] = []
        for index, entry in enumerate(raw_dishes):
            try:
                result.append(Dish.from_dict(entry))
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "Skipping malformed dish entry at index %s: %r (%s)",
                    index,
                    entry,
                    exc,
                )
                continue
        return result

    def save(self, dishes: list[Dish]) -> None:
        data = {"dishes": [dish.to_dict() for dish in dishes]}
        atomic_write_json(self.path, data)

    def restore(self, dish: Dish) -> bool:
        """Re-add *dish* if a same-named entry is no longer in the catalog.

        Used as a delta-rollback for delete: only restores the deleted dish if
        a concurrent writer hasn't already replaced it.
        """
        with self.lock:
            dishes = self.load()
            if any(d.name == dish.name for d in dishes):
                return False
            dishes.append(dish)
            self.save(dishes)
            return True
