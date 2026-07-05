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

    def _read_malformed(self) -> list:
        """Return the raw dish entries currently on disk that ``load`` cannot parse.

        ``load`` skips entries ``Dish.from_dict`` rejects, so a naive
        ``save(load())`` would permanently erase them. Callers always hold
        ``self.lock`` across load-modify-save, so re-reading the file here (the
        file is unchanged under the lock) lets ``save`` round-trip those rows
        verbatim instead of dropping them.
        """
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError):
            return []
        if not isinstance(data, dict):
            return []
        raw_dishes = data.get("dishes", [])
        if not isinstance(raw_dishes, list):
            return []
        malformed = []
        for entry in raw_dishes:
            try:
                Dish.from_dict(entry)
            except (AttributeError, KeyError, TypeError, ValueError):
                malformed.append(entry)
        return malformed

    @staticmethod
    def _entry_name(entry) -> str | None:
        """Normalized name of a raw dish entry, or None if it has no usable name."""
        try:
            return Dish.normalize_name(entry["name"])
        except (TypeError, KeyError, ValueError):
            return None

    def save(self, dishes: list[Dish]) -> None:
        # Preserve any unparseable entries already on disk so an unrelated write
        # never silently deletes a legacy/hand-edited row it couldn't load. Drop
        # any preserved row whose name collides with a dish being saved, so a
        # live dish can't spawn a permanent, un-removable duplicate-named ghost.
        saved_names = {dish.name for dish in dishes}
        preserved = [
            entry for entry in self._read_malformed()
            if self._entry_name(entry) not in saved_names
        ]
        data = {"dishes": [dish.to_dict() for dish in dishes] + preserved}
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
