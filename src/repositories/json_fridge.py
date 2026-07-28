"""JSON-file-backed implementation of FridgeRepository."""

import json
import logging
import math
from datetime import date
from pathlib import Path

from .. import atomic_write_json, data_lock

logger = logging.getLogger(__name__)

STAPLE = None  # sentinel count meaning "pantry staple, never runs out"

# How many days ahead counts as "use this soon".
EXPIRING_SOON_DAYS = 3

_MISSING = object()


def is_available(count) -> bool:
    """True when an ingredient can be used: staples always, others when > 0."""
    return count is STAPLE or count > 0


def consume_one(count):
    """Decrement one portion. Staples are untouched; counts never go negative."""
    if count is STAPLE:
        return STAPLE
    return max(0, count - 1)


def expiry_status(expires_on, today: date | None = None):
    """Classify a stored expiry date: expired / expiring_soon / fresh / None.

    ``None`` in means ``None`` out — most ingredients carry no date, and that is
    not the same as "fresh". An unparseable date is treated as no date rather
    than as an error: the value came off disk, where it may have been typed by
    hand.
    """
    if expires_on is None:
        return None
    if not isinstance(expires_on, date):
        try:
            expires_on = date.fromisoformat(expires_on)
        except (TypeError, ValueError):
            return None
    days = (expires_on - (today or date.today())).days
    if days < 0:
        return "expired"
    if days <= EXPIRING_SOON_DAYS:
        return "expiring_soon"
    return "fresh"


def _parse_count(raw_count, *, name: str, source: str):
    """Coerce a stored count, or ``_MISSING`` when it is unusable."""
    if raw_count is None:
        return STAPLE
    if isinstance(raw_count, bool):
        return _MISSING  # JSON true/false is not a count
    if isinstance(raw_count, (int, float)):
        # Python's json module accepts the non-standard NaN/Infinity literals,
        # and both blow up int(): NaN raises ValueError, Infinity raises
        # OverflowError. That happens outside the parse guard in the caller, so
        # without this check one hand-edited value turns every fridge-backed
        # tool into an error envelope.
        if isinstance(raw_count, float) and not math.isfinite(raw_count):
            logger.warning("Ignoring non-finite count for %r in %s", name, source)
            return _MISSING
        return max(0, int(raw_count))
    logger.warning("Ignoring non-numeric count for %r in %s", name, source)
    return _MISSING


class JsonFridgeRepository:
    """Stores the fridge inventory as a JSON object of ``{name: value}``.

    A value is either a bare count (``null`` = pantry staple, ``0`` = known out
    of stock, ``n`` = roughly ``n`` dishes' worth) or an object carrying an
    expiry alongside it::

        {"milk": {"count": 2, "expires_on": "2026-08-01"}, "salt": null, "onion": 3}

    The object form is purely additive: entries without an expiry are still
    written as bare scalars, so an existing file round-trips with no diff.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # Shared with every other repository — see ``src/filelock.py``.
        self.lock = data_lock

    def load(self) -> dict:
        """Load the inventory as ``{name: count}``; ``None`` means staple.

        Expiry is stripped here — this is the shape the scoring path and every
        existing caller consume, and it has not changed. Use
        :meth:`load_entries` when the expiry matters.
        """
        return {name: entry["count"] for name, entry in self.load_entries().items()}

    def load_entries(self) -> dict:
        """Load the inventory as ``{name: {"count": …, "expires_on": … | None}}``.

        Accepts the legacy flat-list shape and migrates it in memory (each name
        becomes one portion). The current shape is written back on the next
        save, so no explicit migration step is needed.
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
            return {
                name: {"count": 1, "expires_on": None}
                for name in dict.fromkeys(items)
            }

        if not isinstance(data, dict):
            logger.warning(
                "Ignoring %s with unexpected top-level type: %s",
                self.path.name,
                type(data).__name__,
            )
            return {}

        result: dict = {}
        for raw_name, raw_value in data.items():
            if not isinstance(raw_name, str):
                continue
            name = raw_name.strip().lower()
            if not name:
                continue

            if isinstance(raw_value, dict):
                raw_count = raw_value.get("count", 1)
                expires_on = self._parse_expiry(raw_value.get("expires_on"), name)
            else:
                raw_count = raw_value
                expires_on = None

            count = _parse_count(raw_count, name=name, source=self.path.name)
            if count is _MISSING:
                continue
            result[name] = {"count": count, "expires_on": expires_on}
        return result

    def _parse_expiry(self, raw, name: str):
        if raw is None:
            return None
        try:
            return date.fromisoformat(raw).isoformat()
        except (TypeError, ValueError):
            # Keep the ingredient, drop the date. Losing a known food item
            # because its date was mistyped is the worse outcome.
            logger.warning(
                "Ignoring unreadable expires_on %r for %r in %s",
                raw,
                name,
                self.path.name,
            )
            return None

    def save_entries(self, entries: dict) -> None:
        """Write ``{name: {"count": …, "expires_on": …}}`` in the compact form.

        An entry with no expiry is written as a bare scalar rather than
        ``{"count": n, "expires_on": null}``, so adding this feature does not
        rewrite every row of an existing file.
        """
        data = {}
        for name, entry in entries.items():
            expires_on = entry.get("expires_on")
            count = entry.get("count")
            if expires_on is None:
                data[name] = count
            else:
                data[name] = {"count": count, "expires_on": expires_on}
        atomic_write_json(self.path, data)

    def load_set(self) -> set[str]:
        """Usable ingredients only — zero-count entries are not available."""
        return {name for name, count in self.load().items() if is_available(count)}

    def save(self, ingredients: dict) -> None:
        """Persist ``{name: count}``, keeping any expiry already on file.

        The count-only view is what most callers deal in, and writing it back
        verbatim would silently erase every ``expires_on``. Names absent from
        *ingredients* are removed; names present keep their stored date.

        The read and the write are one load-modify-save window, so they belong
        inside the lock. It is reentrant, so callers that already hold it
        (``remove_items``, ``consume``, ``restore_counts``) are unaffected.
        """
        with self.lock:
            known = self.load_entries()
            self.save_entries({
                name: {
                    "count": count,
                    "expires_on": known.get(name, {}).get("expires_on"),
                }
                for name, count in ingredients.items()
            })

    def remove_items(self, items: list[str]) -> None:
        """Atomically drop specific keys if present.

        Used by delta-rollback paths so an aborted operation only undoes its
        own additions and does not clobber concurrent writes.
        """
        if not items:
            return
        to_remove = set(items)
        with self.lock:
            entries = self.load_entries()
            remaining = {k: v for k, v in entries.items() if k not in to_remove}
            if remaining != entries:
                self.save_entries(remaining)

    def consume(self, names: list[str]) -> dict:
        """Consume one portion of each name present and available.

        Returns ``{name: previous_count}`` for the entries actually changed, so
        the caller can roll back with :meth:`restore_counts`. Staples and
        already-zero entries are not changed and are not reported.
        """
        if not names:
            return {}
        with self.lock:
            entries = self.load_entries()
            previous: dict = {}
            for name in names:
                entry = entries.get(name)
                if entry is None:
                    continue
                count = entry["count"]
                new_count = consume_one(count)
                if new_count != count:
                    previous[name] = count
                    entry["count"] = new_count
            if previous:
                self.save_entries(entries)
            return previous

    def restore_counts(self, previous: dict) -> None:
        """Re-apply counts captured by :meth:`consume` (rollback path)."""
        if not previous:
            return
        with self.lock:
            entries = self.load_entries()
            for name, count in previous.items():
                entry = entries.setdefault(name, {"count": count, "expires_on": None})
                entry["count"] = count
            self.save_entries(entries)
