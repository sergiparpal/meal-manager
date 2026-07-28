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


def _clean_names(raw, *, label: str) -> list[str]:
    """Normalize a stored ingredient list, dropping repeats (first wins)."""
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    names: list[str] = []
    for value in raw:
        if not isinstance(value, str):
            raise ValueError(f"{label} must contain strings")
        name = value.strip().lower()
        if not name:
            raise ValueError(f"{label} cannot contain an empty name")
        if name not in names:
            names.append(name)
    return names


def _clean_queue_item(raw) -> dict:
    """Normalize one funnel entry, guaranteeing the keys the engine indexes.

    ``engine.add_manual`` and ``engine.add_suggested`` read ``item["ingredient"]``
    directly. Restoring a backup without checking meant a hand-edited or
    older-format file could hand them an entry with no such key, and the bare
    KeyError surfaced to the user as ``{"error": "'ingredient'"}``.
    """
    if not isinstance(raw, dict):
        raise ValueError("queue entries must be objects")
    ingredient = raw.get("ingredient")
    if not isinstance(ingredient, str) or not ingredient.strip():
        raise ValueError("queue entries must carry a non-empty 'ingredient'")
    is_essential = raw.get("is_essential", True)
    if not isinstance(is_essential, bool):
        raise ValueError("queue entry 'is_essential' must be a boolean")
    return {
        **raw,
        "ingredient": ingredient.strip().lower(),
        "is_essential": is_essential,
    }


def _clean_flag(raw, *, label: str) -> bool:
    if not isinstance(raw, bool):
        raise ValueError(f"{label} must be a boolean")
    return raw


def from_dict(data: dict) -> DIISession:
    """Rebuild a session from its JSON backup, validating as it goes.

    Restoring blindly let a hand-edited or older-format backup carry the same
    ingredient in *both* selected lists, and the finalizer's map union then
    resolved the collision as optional — demoting an essential and letting
    ``can_cook_with`` approve a dish the user cannot actually make. The lists
    are mutually exclusive by design, so the collision is resolved here the
    same way ``merge_ingredient_alias`` resolves it: essential wins.

    Raising is the intended outcome for a shape we cannot trust — the store
    treats it as a corrupt backup and removes the file.
    """
    if not isinstance(data, dict):
        raise ValueError("session backup must be an object")

    session_id = data["session_id"]
    dish_name = data["dish_name"]
    if not isinstance(session_id, str) or not isinstance(dish_name, str):
        raise ValueError("session_id and dish_name must be strings")

    essential = _clean_names(
        data.get("essential_ingredients", []), label="essential_ingredients"
    )
    optional = [
        name
        for name in _clean_names(
            data.get("optional_ingredients", []), label="optional_ingredients"
        )
        if name not in essential
    ]

    raw_queue = data.get("hidden_queue", [])
    if not isinstance(raw_queue, list):
        raise ValueError("hidden_queue must be a list")

    raw_suggestion = data.get("current_suggestion")

    return DIISession(
        session_id=session_id,
        dish_name=dish_name.strip().lower(),
        essential_ingredients=essential,
        optional_ingredients=optional,
        hidden_queue=[_clean_queue_item(item) for item in raw_queue],
        current_suggestion=(
            None if raw_suggestion is None else _clean_queue_item(raw_suggestion)
        ),
        created_at=data.get("created_at", ""),
        last_activity=data.get("last_activity", ""),
        finalized=_clean_flag(data.get("finalized", False), label="finalized"),
        pending_recalculation=_clean_flag(
            data.get("pending_recalculation", False), label="pending_recalculation"
        ),
    )
