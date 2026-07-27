"""Cooking history event model.

Pure data, no I/O — the persistence side lives in
``src/repositories/json_history.py``.

History is an append-only log of cook events. The single-date-per-dish view
the rest of the package consumes is a *projection* over this log, computed on
read, which is why an older event can never displace a newer one.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .dish import Dish

ID_PREFIX = "cook_"


def new_event_id() -> str:
    """Fresh identifier for a newly recorded cook."""
    return f"{ID_PREFIX}{uuid.uuid4().hex}"


def utc_now_iso() -> str:
    """Current UTC time as a timezone-aware ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _parse_aware_datetime(value, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO 8601 datetime string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {label} {value!r}: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


@dataclass
class CookingEvent:
    """One recorded cook of one dish.

    ``dish_name`` is a *snapshot* of the name at cook time. Renaming a dish in
    the catalog does not rewrite history, so a rename splits a dish's record
    into two names rather than silently rewriting the past.

    ``retracted_at`` marks an event the user took back. Retraction is not
    deletion: the row stays in the log and remains visible through
    ``list_cooking_history``, it just stops counting toward the projection.
    """

    id: str
    dish_name: str
    cooked_on: str
    recorded_at: str
    backfilled: bool = False
    retracted_at: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.startswith(ID_PREFIX):
            raise ValueError(f"event id must be a string starting with {ID_PREFIX!r}")
        if self.id == ID_PREFIX:
            raise ValueError("event id cannot be empty")

        self.dish_name = Dish.normalize_name(self.dish_name)
        if not self.dish_name:
            raise ValueError("dish name cannot be empty")

        if not isinstance(self.cooked_on, str):
            raise ValueError("cooked_on must be an ISO date string (YYYY-MM-DD)")
        try:
            # Store the canonical form so string equality and date comparison
            # never disagree about the same day.
            self.cooked_on = date.fromisoformat(self.cooked_on).isoformat()
        except ValueError as exc:
            raise ValueError(f"invalid cooked_on {self.cooked_on!r}: {exc}") from exc

        self.recorded_at = _parse_aware_datetime(self.recorded_at, label="recorded_at")

        if not isinstance(self.backfilled, bool):
            raise ValueError("backfilled must be a boolean")

        if self.retracted_at is not None:
            self.retracted_at = _parse_aware_datetime(
                self.retracted_at, label="retracted_at"
            )

    @property
    def active(self) -> bool:
        return self.retracted_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dish_name": self.dish_name,
            "cooked_on": self.cooked_on,
            "recorded_at": self.recorded_at,
            "backfilled": self.backfilled,
            "retracted_at": self.retracted_at,
        }

    @classmethod
    def from_dict(cls, data) -> "CookingEvent":
        """Strict inverse of :meth:`to_dict`.

        Unknown and missing keys both raise: this is the read path for stored
        data we wrote ourselves, so a shape we do not recognize is corruption
        to surface, not something to absorb with defaults.
        """
        if not isinstance(data, dict):
            raise ValueError("cooking event must be an object")
        expected = {
            "id",
            "dish_name",
            "cooked_on",
            "recorded_at",
            "backfilled",
            "retracted_at",
        }
        missing = expected - set(data)
        if missing:
            raise ValueError(f"cooking event is missing keys: {sorted(missing)}")
        unknown = set(data) - expected
        if unknown:
            raise ValueError(f"cooking event has unknown keys: {sorted(unknown)}")
        return cls(
            id=data["id"],
            dish_name=data["dish_name"],
            cooked_on=data["cooked_on"],
            recorded_at=data["recorded_at"],
            backfilled=data["backfilled"],
            retracted_at=data["retracted_at"],
        )
