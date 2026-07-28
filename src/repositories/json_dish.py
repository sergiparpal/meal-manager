"""JSON-file-backed implementation of DishRepository."""

import json
import logging
from pathlib import Path

from .. import atomic_write_json, data_lock
from ..dish import Dish

logger = logging.getLogger(__name__)


class JsonDishRepository:
    """Stores the dish catalog as ``{"dishes": [...]}`` in a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # Shared with every other repository — see ``src/filelock.py``.
        self.lock = data_lock
        # Raw rows the most recent parse could not read, kept so ``save`` can
        # round-trip them without re-reading and re-parsing the whole catalog.
        # ``None`` means "not known yet" and makes ``save`` go back to disk.
        self._malformed: list | None = None

    def _parse(self) -> tuple[list[Dish], list]:
        """Split the file into parsed dishes and the raw rows that failed.

        One pass over the file yields both halves. ``load`` skips entries
        ``Dish.from_dict`` rejects, so a naive ``save(load())`` would erase
        them permanently; keeping the rejects here lets ``save`` write them back
        verbatim.
        """
        if not self.path.exists():
            return [], []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning("Failed to load %s: %s", self.path.name, exc)
            return [], []
        if not isinstance(data, dict):
            logger.warning(
                "Ignoring %s with unexpected top-level type: %s",
                self.path.name,
                type(data).__name__,
            )
            return [], []
        raw_dishes = data.get("dishes", [])
        if not isinstance(raw_dishes, list):
            logger.warning(
                "Ignoring %s with non-list dishes field: %r",
                self.path.name,
                raw_dishes,
            )
            return [], []
        parsed: list[Dish] = []
        malformed: list = []
        for index, entry in enumerate(raw_dishes):
            try:
                parsed.append(Dish.from_dict(entry))
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "Skipping malformed dish entry at index %s: %r (%s)",
                    index,
                    entry,
                    exc,
                )
                malformed.append(entry)
        return parsed, malformed

    def load(self) -> list[Dish]:
        dishes, malformed = self._parse()
        self._malformed = malformed
        return dishes

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
        # Every caller does load-modify-save under ``self.lock``, so the rows the
        # preceding load rejected are still what is on disk. Fall back to a fresh
        # read only if this instance has not parsed the file yet.
        known = self._malformed if self._malformed is not None else self._parse()[1]
        preserved = [
            entry for entry in known
            if self._entry_name(entry) not in saved_names
        ]
        data = {"dishes": [dish.to_dict() for dish in dishes] + preserved}
        atomic_write_json(self.path, data)
        # The file now holds exactly ``preserved`` as its unparseable rows.
        self._malformed = preserved

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
