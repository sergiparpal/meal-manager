"""JSON-file-backed implementation of FridgeRepository."""

import json
import threading
from pathlib import Path

from .. import atomic_write_json


class JsonFridgeRepository:
    """Stores the fridge inventory as a flat JSON list of strings."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> list[str]:
        """Load the inventory. Returns ``[]`` for missing or invalid files."""
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        items = [ing.strip().lower() for ing in data if isinstance(ing, str)]
        return list(dict.fromkeys(items))

    def load_set(self) -> set[str]:
        """Load the inventory as a set for O(1) membership tests."""
        return set(self.load())

    def save(self, ingredients: list[str]) -> None:
        atomic_write_json(self.path, ingredients)

    def remove_items(self, items: list[str]) -> None:
        """Atomically remove specific items if present.

        Used by delta-rollback paths so an aborted operation only undoes its
        own additions and does not clobber concurrent writes.
        """
        if not items:
            return
        to_remove = set(items)
        with self.lock:
            fridge = self.load()
            new_fridge = [ing for ing in fridge if ing not in to_remove]
            if new_fridge != fridge:
                self.save(new_fridge)
