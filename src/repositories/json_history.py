"""JSON-file-backed implementation of HistoryRepository.

Storage is an append-only event log::

    {"schema_version": 2, "events": [{...}, ...]}

``load()`` projects that log down to the one-date-per-dish mapping the rest of
the package consumes. Because the projection takes the *maximum* ``cooked_on``
per dish, recording a forgotten meal from last month cannot displace a cook
from this morning — the bug the old single-value model needed an
``only_if_newer`` flag to work around is now impossible by construction.
"""

import json
import logging
import threading
import uuid
from datetime import date
from pathlib import Path

from .. import atomic_write_json
from ..dish import Dish
from ..history_event import CookingEvent, new_event_id, utc_now_iso

logger = logging.getLogger(__name__)

HISTORY_SCHEMA_VERSION = 2

# Fixed namespace for deriving ids when migrating a legacy ``{dish: date}``
# file. Migration runs in memory on every load until the first write, so the
# ids must be a pure function of the entry — a random id would mint a fresh
# event on every load and duplicate the row on the next write.
_LEGACY_ID_NAMESPACE = uuid.UUID("6f6d2f0b-8a3d-4c3a-9a1e-0d9f5a6b7c8d")


class HistoryDataError(ValueError):
    """Stored cooking history could not be read as a valid event log."""


class JsonHistoryRepository:
    """Stores cooking history as an append-only log of :class:`CookingEvent`.

    The repository owns its own lock; callers do not acquire it.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    # -- reading ------------------------------------------------------------

    def load_events(self, *, strict: bool = False) -> list[CookingEvent]:
        """Return every stored event, oldest first, migrating legacy files.

        Never writes: a legacy file is migrated in memory and only rewritten in
        the v2 shape by the next mutating call, mirroring how the legacy
        flat-list ``fridge.json`` is handled.

        With *strict*, corrupt storage raises :class:`HistoryDataError` instead
        of yielding an empty log — a caller reporting history to the user must
        not render "you have never cooked anything" over an unreadable file.
        """
        try:
            return self._parse()
        except HistoryDataError:
            if strict:
                raise
            logger.warning("Ignoring unreadable %s", self.path.name)
            return []

    def load(self) -> dict[str, str]:
        """Project the log to ``{dish_name: latest_cooked_on}``.

        Retracted events are excluded. This is the contract the scoring path
        and ``days_since_last_cook`` depend on and it has not changed.
        """
        projected: dict[str, str] = {}
        for event in self.load_events():
            if not event.active:
                continue
            current = projected.get(event.dish_name)
            # Compare as dates, never lexicographically.
            if current is None or (
                date.fromisoformat(event.cooked_on) > date.fromisoformat(current)
            ):
                projected[event.dish_name] = event.cooked_on
        return projected

    # -- writing ------------------------------------------------------------

    def append_event(
        self,
        dish_name: str,
        cooked_on,
        *,
        backfilled: bool = False,
    ) -> CookingEvent:
        """Record a cook and return the stored event."""
        value = cooked_on if isinstance(cooked_on, str) else cooked_on.isoformat()
        with self._lock:
            events = self.load_events()
            event = CookingEvent(
                id=new_event_id(),
                dish_name=dish_name,
                cooked_on=value,
                recorded_at=utc_now_iso(),
                backfilled=bool(backfilled),
            )
            events.append(event)
            self._save(events)
            return event

    def retract_event(self, event_id: str) -> CookingEvent | None:
        """Mark an active event as taken back. Returns it, or None if absent."""
        with self._lock:
            events = self.load_events()
            for event in events:
                if event.id == event_id and event.active:
                    event.retracted_at = utc_now_iso()
                    self._save(events)
                    return event
            return None

    def retract_latest_for_dish(self, dish_name: str) -> CookingEvent | None:
        """Retract the most recent active cook of *dish_name*.

        "Most recent" is by ``cooked_on``, not by insertion order: this backs
        the undo tool, whose promise is to release the recency cooldown, and
        only the event the projection actually uses can do that.
        """
        key = Dish.normalize_name(dish_name)
        with self._lock:
            events = self.load_events()
            target = None
            for event in events:
                if event.dish_name != key or not event.active:
                    continue
                if target is None or (
                    date.fromisoformat(event.cooked_on)
                    >= date.fromisoformat(target.cooked_on)
                ):
                    target = event
            if target is None:
                return None
            target.retracted_at = utc_now_iso()
            self._save(events)
            return target

    def retract_all_for_dish(self, dish_name: str) -> list[CookingEvent]:
        """Retract every active cook of *dish_name*. Returns what was retracted.

        Used when a dish leaves the catalog: its cooks must stop counting
        toward the projection, but the log still records that they happened.
        """
        key = Dish.normalize_name(dish_name)
        with self._lock:
            events = self.load_events()
            retracted_at = utc_now_iso()
            retracted = [
                event for event in events if event.dish_name == key and event.active
            ]
            if not retracted:
                return []
            for event in retracted:
                event.retracted_at = retracted_at
            self._save(events)
            return retracted

    def delete_event(self, event_id: str) -> bool:
        """Remove an event outright. Returns True if it was present.

        The rollback path, and only that: a cook whose fridge consumption failed
        never happened, so it must leave no trace. Everything a user takes back
        goes through retraction instead, which preserves the row.
        """
        with self._lock:
            events = self.load_events()
            remaining = [event for event in events if event.id != event_id]
            if len(remaining) == len(events):
                return False
            self._save(remaining)
            return True

    # -- internals ----------------------------------------------------------

    def _save(self, events: list[CookingEvent]) -> None:
        atomic_write_json(
            self.path,
            {
                "schema_version": HISTORY_SCHEMA_VERSION,
                "events": [event.to_dict() for event in events],
            },
        )

    def _parse(self) -> list[CookingEvent]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HistoryDataError(
                f"{self.path.name} is not valid JSON"
            ) from exc
        return self._migrate(raw)

    def _migrate(self, raw) -> list[CookingEvent]:
        if not isinstance(raw, dict):
            raise HistoryDataError(
                f"{self.path.name} has an unexpected top-level type: "
                f"{type(raw).__name__}"
            )

        if "schema_version" in raw:
            version = raw.get("schema_version")
            if version != HISTORY_SCHEMA_VERSION:
                raise HistoryDataError(
                    f"{self.path.name} has unsupported schema_version {version!r}"
                )
            events = raw.get("events")
            if not isinstance(events, list):
                raise HistoryDataError(
                    f"{self.path.name} has a non-list 'events' field"
                )
            try:
                return [CookingEvent.from_dict(entry) for entry in events]
            except ValueError as exc:
                raise HistoryDataError(
                    f"{self.path.name} contains an invalid event: {exc}"
                ) from exc

        return self._from_legacy(raw)

    def _from_legacy(self, raw: dict) -> list[CookingEvent]:
        """Synthesize one event per entry of a legacy ``{dish: date}`` file."""
        recorded_at = utc_now_iso()
        events: list[CookingEvent] = []
        for name, date_str in raw.items():
            if not isinstance(name, str) or not isinstance(date_str, str):
                continue
            key = name.strip().lower()
            if not key:
                continue
            try:
                cooked_on = date.fromisoformat(date_str).isoformat()
            except ValueError:
                # The old loader kept these but nothing could use them —
                # ``days_since_last_cook`` skipped them with the same warning.
                logger.warning(
                    "Skipping legacy history entry %r with unreadable date %r",
                    key,
                    date_str,
                )
                continue
            event_id = "cook_" + uuid.uuid5(
                _LEGACY_ID_NAMESPACE, f"{key}|{cooked_on}"
            ).hex
            events.append(
                CookingEvent(
                    id=event_id,
                    dish_name=key,
                    cooked_on=cooked_on,
                    recorded_at=recorded_at,
                    backfilled=False,
                )
            )
        return events
