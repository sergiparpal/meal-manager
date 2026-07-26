"""JSON-file-backed implementation of HistoryRepository."""

import json
import threading
from datetime import date
from pathlib import Path

from .. import atomic_write_json


def _is_later(candidate: str, reference: str) -> bool:
    """True when *candidate* is a strictly later date than *reference*.

    False on any parse failure, so an unreadable stored value never blocks a
    write — a corrupt entry should be replaced, not defended.
    """
    try:
        return date.fromisoformat(candidate) > date.fromisoformat(reference)
    except (TypeError, ValueError):
        return False


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
            if key not in normalized:
                normalized[key] = date_str
                continue
            # Compare as actual dates, not lexicographically: raw string order
            # is wrong for non-zero-padded values (e.g. '2026-7-9' vs
            # '2026-12-09'). On any parse ambiguity, keep the existing value.
            try:
                if date.fromisoformat(date_str) > date.fromisoformat(normalized[key]):
                    normalized[key] = date_str
            except ValueError:
                continue
        return normalized

    def set_entry(
        self,
        dish_name: str,
        date_str: str,
        *,
        only_if_newer: bool = False,
    ) -> str | None:
        """Store or replace a history entry. Returns the previous value (or None).

        History keeps a single date per dish — the last time it was cooked — so
        a plain write is destructive when the incoming date is older than what
        is already stored. With *only_if_newer*, a strictly more recent existing
        entry is kept and no write happens: recording a forgotten meal from last
        month must not erase a cook from this morning and hand the dish back to
        the suggestion engine inside its cooldown window.

        The previous value is returned either way. A caller rolling back with
        :meth:`revert_entry` stays correct when the write was skipped, because
        the stored value will not match the expected one.
        """
        with self._lock:
            history = self.load()
            key = dish_name.strip().lower()
            previous = history.get(key)
            value = date_str if isinstance(date_str, str) else date_str.isoformat()
            if only_if_newer and previous is not None and _is_later(previous, value):
                return previous
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
