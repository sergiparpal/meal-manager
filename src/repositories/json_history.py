"""JSON-file-backed implementation of HistoryRepository."""

import json
import threading
from pathlib import Path

from .. import atomic_write_json


class JsonHistoryRepository:
    """Stores cooking history as ``{dish_name: ISO_date_string}`` in JSON.

    Keys are normalized to lowercase on load. The repository owns its own
    lock; callers do not need to acquire it for individual operations.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        # Normalize keys to lowercase; keep the most recent date for duplicates.
        normalized: dict[str, str] = {}
        for name, date_str in raw.items():
            if not isinstance(name, str) or not isinstance(date_str, str):
                continue
            key = name.strip().lower()
            if key not in normalized or date_str > normalized[key]:
                normalized[key] = date_str
        return normalized

    def set_entry(self, dish_name: str, date_str: str) -> str | None:
        """Store or replace a history entry. Returns the previous value (or None)."""
        with self._lock:
            history = self.load()
            key = dish_name.strip().lower()
            previous = history.get(key)
            value = date_str if isinstance(date_str, str) else date_str.isoformat()
            history[key] = value
            atomic_write_json(self.path, history)
            return previous

    def remove_entry(self, dish_name: str) -> bool:
        """Remove a dish entry. Returns True if it was present."""
        with self._lock:
            history = self.load()
            key = dish_name.strip().lower()
            if key not in history:
                return False
            del history[key]
            atomic_write_json(self.path, history)
            return True

    def revert_entry(
        self,
        dish_name: str,
        expected_value: str,
        previous_value: str | None,
    ) -> bool:
        """Compare-and-swap rollback for set_entry.

        If the current entry equals *expected_value*, restore *previous_value*
        (or delete the key if previous was None). If a concurrent writer has
        diverged from *expected_value*, leave the entry alone and return False.
        """
        with self._lock:
            history = self.load()
            key = dish_name.strip().lower()
            if history.get(key) != expected_value:
                return False
            if previous_value is None:
                history.pop(key, None)
            else:
                history[key] = previous_value
            atomic_write_json(self.path, history)
            return True
