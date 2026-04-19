"""DIISession dataclass plus timestamp and serialization helpers.

Pure data: no I/O, no locking. Both the store (for persistence) and the
engine (for state mutations) depend on this module.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


# Sentinel used when last_activity is missing or malformed — guaranteed to
# be older than any real TTL window.
EPOCH_SENTINEL_ISO = "1970-01-01T00:00:00+00:00"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso_to_aware(value: str | None) -> datetime:
    """Parse an ISO timestamp into a UTC-aware datetime.

    Falls back to the epoch sentinel for empty/invalid input so the cleanup
    loop can never crash on a malformed last_activity field. Naive timestamps
    written by older code paths are assumed UTC.
    """
    if not value:
        return datetime.fromisoformat(EPOCH_SENTINEL_ISO)
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.fromisoformat(EPOCH_SENTINEL_ISO)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class DIISession:
    session_id: str
    dish_name: str
    essential_ingredients: list[str] = field(default_factory=list)
    optional_ingredients: list[str] = field(default_factory=list)
    hidden_queue: list[dict] = field(default_factory=list)
    current_suggestion: dict | None = None
    created_at: str = EPOCH_SENTINEL_ISO
    last_activity: str = EPOCH_SENTINEL_ISO
    finalized: bool = False
    pending_recalculation: bool = False


def to_dict(session: DIISession) -> dict:
    """Full serialization including hidden_queue (used for persistence)."""
    return {
        "session_id": session.session_id,
        "dish_name": session.dish_name,
        "essential_ingredients": session.essential_ingredients,
        "optional_ingredients": session.optional_ingredients,
        "hidden_queue": session.hidden_queue,
        "current_suggestion": session.current_suggestion,
        "created_at": session.created_at,
        "last_activity": session.last_activity,
        "finalized": session.finalized,
        "pending_recalculation": session.pending_recalculation,
    }


def from_dict(data: dict) -> DIISession:
    return DIISession(
        session_id=data["session_id"],
        dish_name=data["dish_name"],
        essential_ingredients=data.get("essential_ingredients", []),
        optional_ingredients=data.get("optional_ingredients", []),
        hidden_queue=data.get("hidden_queue", []),
        current_suggestion=data.get("current_suggestion"),
        created_at=data.get("created_at", ""),
        last_activity=data.get("last_activity", ""),
        finalized=data.get("finalized", False),
        pending_recalculation=data.get("pending_recalculation", False),
    )
