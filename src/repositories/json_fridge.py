"""JSON-file-backed implementation of FridgeRepository."""

import json
import logging
import math
import threading
from pathlib import Path

from .. import atomic_write_json

logger = logging.getLogger(__name__)

STAPLE = None  # sentinel count meaning "pantry staple, never runs out"


def is_available(count) -> bool:
    """True when an ingredient can be used: staples always, others when > 0."""
    return count is STAPLE or count > 0


def consume_one(count):
    """Decrement one portion. Staples are untouched; counts never go negative."""
    if count is STAPLE:
        return STAPLE
    return max(0, count - 1)


class JsonFridgeRepository:
    """Stores the fridge inventory as a JSON object of ``{name: count}``."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> dict:
        """Load the inventory as ``{name: count}``; ``None`` means staple.

        Accepts the legacy flat-list shape and migrates it in memory (each name
        becomes one portion). The new shape is written back on the next save, so
        no explicit migration step is needed.
        """
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to load %s: %s", self.path.name, exc)
            return {}

        if isinstance(data, list):
            # Legacy shape: a flat list of names, each meaning "one portion".
            items = [ing.strip().lower() for ing in data if isinstance(ing, str)]
            return {name: 1 for name in dict.fromkeys(items)}

        if not isinstance(data, dict):
            logger.warning(
                "Ignoring %s with unexpected top-level type: %s",
                self.path.name,
                type(data).__name__,
            )
            return {}

        result: dict = {}
        for raw_name, raw_count in data.items():
            if not isinstance(raw_name, str):
                continue
            name = raw_name.strip().lower()
            if not name:
                continue
            if raw_count is None:
                result[name] = STAPLE
            elif isinstance(raw_count, bool):
                continue  # JSON true/false is not a count
            elif isinstance(raw_count, (int, float)):
                # Python's json module accepts the non-standard NaN/Infinity
                # literals, and both blow up int(): NaN raises ValueError,
                # Infinity raises OverflowError. That happens outside the parse
                # guard above, so without this check one hand-edited value turns
                # every fridge-backed tool into an error envelope.
                if isinstance(raw_count, float) and not math.isfinite(raw_count):
                    logger.warning(
                        "Ignoring non-finite count for %r in %s", name, self.path.name
                    )
                    continue
                result[name] = max(0, int(raw_count))
            else:
                logger.warning(
                    "Ignoring non-numeric count for %r in %s", name, self.path.name
                )
        return result

    def load_set(self) -> set[str]:
        """Usable ingredients only — zero-count entries are not available."""
        return {name for name, count in self.load().items() if is_available(count)}

    def save(self, ingredients: dict) -> None:
        atomic_write_json(self.path, ingredients)

    def remove_items(self, items: list[str]) -> None:
        """Atomically drop specific keys if present.

        Used by delta-rollback paths so an aborted operation only undoes its
        own additions and does not clobber concurrent writes.
        """
        if not items:
            return
        to_remove = set(items)
        with self.lock:
            fridge = self.load()
            new_fridge = {k: v for k, v in fridge.items() if k not in to_remove}
            if new_fridge != fridge:
                self.save(new_fridge)

    def consume(self, names: list[str]) -> dict:
        """Consume one portion of each name present and available.

        Returns ``{name: previous_count}`` for the entries actually changed, so
        the caller can roll back with :meth:`restore_counts`. Staples and
        already-zero entries are not changed and are not reported.
        """
        if not names:
            return {}
        with self.lock:
            fridge = self.load()
            previous: dict = {}
            for name in names:
                if name not in fridge:
                    continue
                count = fridge[name]
                new_count = consume_one(count)
                if new_count != count:
                    previous[name] = count
                    fridge[name] = new_count
            if previous:
                self.save(fridge)
            return previous

    def restore_counts(self, previous: dict) -> None:
        """Re-apply counts captured by :meth:`consume` (rollback path)."""
        if not previous:
            return
        with self.lock:
            fridge = self.load()
            fridge.update(previous)
            self.save(fridge)
