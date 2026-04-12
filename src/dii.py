"""Dynamic Ingredient Interface (DII) — stateful session engine.

Manages interactive ingredient-selection sessions where a ranked list of
ingredients is revealed one at a time (the "probability funnel").  Sessions
live in memory with optional JSON backup for crash recovery.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from . import atomic_write_json
from .dish import Dish
from .fridge import load_fridge, save_fridge, fridge_lock, remove_items_from_fridge
from .storage import load_dishes, save_dishes, dishes_lock

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SESSION_TTL_MINUTES = 30
_CLEANUP_INTERVAL_SECONDS = 60
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SESSION_DIR = _DATA_DIR / "sessions"
# Sentinel used when last_activity is missing or malformed — guaranteed to
# be older than any real TTL window.
_EPOCH_SENTINEL_ISO = "1970-01-01T00:00:00+00:00"


def _parse_iso_to_aware(value: str | None) -> datetime:
    """Parse an ISO timestamp into a UTC-aware datetime.

    Falls back to the epoch sentinel for empty/invalid input so the cleanup
    loop can never crash on a malformed last_activity field. Naive timestamps
    written by older code paths are assumed UTC.
    """
    if not value:
        return datetime.fromisoformat(_EPOCH_SENTINEL_ISO)
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.fromisoformat(_EPOCH_SENTINEL_ISO)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------


@dataclass
class DIISession:
    session_id: str
    dish_name: str
    essential_ingredients: list[str] = field(default_factory=list)
    optional_ingredients: list[str] = field(default_factory=list)
    hidden_queue: list[dict] = field(default_factory=list)
    current_suggestion: dict | None = None
    created_at: str = _EPOCH_SENTINEL_ISO
    last_activity: str = _EPOCH_SENTINEL_ISO
    finalized: bool = False
    pending_recalculation: bool = False


# ---------------------------------------------------------------------------
# In-memory store & locking
# ---------------------------------------------------------------------------

_sessions: dict[str, DIISession] = {}
_session_locks: dict[str, threading.Lock] = {}
_global_lock = threading.Lock()  # protects _sessions and _session_locks dicts
_last_cleanup_monotonic: float = 0.0

# ---------------------------------------------------------------------------
# Lock helpers
# ---------------------------------------------------------------------------


def _get_lock(session_id: str) -> threading.Lock:
    """Return (or create) the per-session lock."""
    with _global_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _persist_session(session: DIISession) -> None:
    """Write session to data/sessions/{id}.json atomically."""
    path = _SESSION_DIR / f"{session.session_id}.json"
    atomic_write_json(path, _session_to_full_dict(session), indent=None)


def _load_session_from_disk(session_id: str) -> DIISession | None:
    """Attempt to restore a session from its JSON backup.

    Rejects (and removes) sessions whose ``last_activity`` is older than the
    TTL window — otherwise a stale file would resurrect a session that the
    in-memory cleanup already purged.
    """
    path = _SESSION_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        path.unlink(missing_ok=True)
        return None
    try:
        session = _dict_to_session(data)
    except Exception:
        path.unlink(missing_ok=True)
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_SESSION_TTL_MINUTES)
    if _parse_iso_to_aware(session.last_activity) < cutoff:
        path.unlink(missing_ok=True)
        return None
    return session


def _delete_session_file(session_id: str) -> None:
    path = _SESSION_DIR / f"{session_id}.json"
    path.unlink(missing_ok=True)


def _cleanup_expired(ttl_minutes: int = _SESSION_TTL_MINUTES) -> None:
    """Purge sessions older than TTL from memory and disk.

    Debounced via monotonic clock so wall-clock jumps cannot stop it firing.
    """
    global _last_cleanup_monotonic
    now_mono = time.monotonic()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)

    with _global_lock:
        if _last_cleanup_monotonic and (now_mono - _last_cleanup_monotonic) < _CLEANUP_INTERVAL_SECONDS:
            return
        _last_cleanup_monotonic = now_mono

        expired = [
            sid for sid, s in _sessions.items()
            if _parse_iso_to_aware(s.last_activity) < cutoff
        ]
        for sid in expired:
            _sessions.pop(sid, None)
            _session_locks.pop(sid, None)
            # Delete the file inside the lock so a concurrent get_session
            # cannot resurrect a just-purged session from disk.
            _delete_session_file(sid)

        # Clean orphaned locks (e.g. from lookups on invalid session IDs)
        for sid in [s for s in _session_locks if s not in _sessions]:
            del _session_locks[sid]

    # Also clean orphaned files on disk (cap iterations to avoid slow scans)
    if _SESSION_DIR.exists():
        for i, fpath in enumerate(_SESSION_DIR.glob("*.json")):
            if i >= 100:
                break
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                last = _parse_iso_to_aware(data.get("last_activity"))
                if last < cutoff:
                    fpath.unlink(missing_ok=True)
            except Exception:
                fpath.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _session_to_full_dict(session: DIISession) -> dict:
    """Full serialization including hidden_queue (for persistence)."""
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


def _dict_to_session(data: dict) -> DIISession:
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


def _session_to_response(session: DIISession, *, recalculation_needed: bool = False) -> dict:
    """Public-facing response dict (hides queue contents).
    
    Includes next_actions and instructions to guide the LLM through the DII flow
    without external tooling dependencies.
    """
    # Determine state
    is_finalized = session.finalized
    awaiting_recalc = session.pending_recalculation
    has_suggestion = session.current_suggestion is not None
    queue_empty = len(session.hidden_queue) == 0 and not has_suggestion
    
    # Build next_actions based on state
    if is_finalized:
        next_actions = []
        instructions = f"Session finalized for '{session.dish_name}'. No more actions available."
    elif awaiting_recalc:
        next_actions = ["init_ingredient_session", "dii_add_manual", "dii_remove_ingredient", "dii_clear_all", "finalize_ingredient_session"]
        instructions = (
            f"The session needs recalculation. Call init_ingredient_session again "
            f"with a new ranked list for '{session.dish_name}' AND pass this same "
            f"session_id ('{session.session_id}') so the session is reset in place. "
            f"You can also add/remove ingredients manually or finalize as-is."
        )
    elif has_suggestion:
        assert session.current_suggestion is not None
        suggestion = session.current_suggestion
        ing_name = suggestion.get("ingredient", "?")
        is_ess = "essential" if suggestion.get("is_essential", True) else "optional"
        next_actions = ["dii_add_suggested", "dii_skip_suggested", "dii_remove_ingredient", "dii_add_manual", "finalize_ingredient_session"]
        instructions = (
            f"Current suggestion: '{ing_name}' ({is_ess}). "
            f"Ask the user whether to add it, skip it, or type another ingredient."
        )
    elif queue_empty:
        next_actions = ["dii_add_manual", "finalize_ingredient_session"]
        instructions = (
            f"No more suggestions. You can add ingredients manually or finalize the session."
        )
    else:
        next_actions = ["dii_add_manual", "finalize_ingredient_session"]
        instructions = f"Unexpected state. Consider finalizing or restarting the session."
    
    return {
        "session_id": session.session_id,
        "dish_name": session.dish_name,
        "essential_ingredients": session.essential_ingredients,
        "optional_ingredients": session.optional_ingredients,
        "current_suggestion": session.current_suggestion,
        "queue_remaining": len(session.hidden_queue),
        "queue_exhausted": queue_empty,
        "recalculation_needed": recalculation_needed,
        "pending_recalculation": awaiting_recalc,
        "finalized": is_finalized,
        "next_actions": next_actions,
        "instructions": instructions,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _touch(session: DIISession) -> None:
    session.last_activity = _now_iso()


def _advance_queue(session: DIISession) -> None:
    """Pop the next item from hidden_queue into current_suggestion."""
    if session.hidden_queue:
        session.current_suggestion = session.hidden_queue.pop(0)
    else:
        session.current_suggestion = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_session(session_id: str) -> DIISession | None:
    """Retrieve session from memory, falling back to disk."""
    _cleanup_expired()
    with _global_lock:
        session = _sessions.get(session_id)
        if session is None:
            session = _load_session_from_disk(session_id)
            if session is not None:
                _sessions[session_id] = session
    return session


def _require_session(session_id: str) -> DIISession:
    session = get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found or expired: {session_id}")
    if session.finalized:
        raise ValueError(f"Session already finalized: {session_id}")
    return session


def _require_active_session(session_id: str) -> DIISession:
    """Like _require_session but also rejects sessions awaiting recalculation."""
    session = _require_session(session_id)
    if session.pending_recalculation:
        raise ValueError(
            f"Session {session_id} is awaiting recalculation — mutations blocked"
        )
    return session


def create_session(
    session_id: str,
    dish_name: str,
    ranked_ingredients: list[dict],
    pre_select_top_n: int = 3,
    *,
    reuse_existing: bool = False,
) -> DIISession:
    """Initialize a DII session.

    The top *pre_select_top_n* ingredients are auto-selected into the
    essential/optional lists.  The next one becomes ``current_suggestion``
    and the rest go into ``hidden_queue``.

    When *reuse_existing* is True, any existing session with this id is
    replaced in place — used by the recalculation flow so the agent can keep
    the same session_id after the LLM regenerates the ranked list.
    """
    _cleanup_expired()

    now = _now_iso()
    normalized_dish_name = Dish.normalize_name(dish_name)
    if not normalized_dish_name:
        raise ValueError("Dish name cannot be empty")
    if not isinstance(pre_select_top_n, int) or isinstance(pre_select_top_n, bool):
        raise ValueError("pre_select_top_n must be an integer")
    if pre_select_top_n < 0:
        raise ValueError("pre_select_top_n must be >= 0")

    session = DIISession(
        session_id=session_id,
        dish_name=normalized_dish_name,
        created_at=now,
        last_activity=now,
    )

    # Validate, normalize, and deduplicate ranked ingredients
    if not isinstance(ranked_ingredients, list):
        raise ValueError("ranked_ingredients must be a list")
    seen: set[str] = set()
    cleaned: list[dict] = []
    for item in ranked_ingredients:
        if not isinstance(item, dict):
            raise ValueError("ranked_ingredients must contain objects")
        if "ingredient" not in item:
            raise ValueError("ranked_ingredients items must include ingredient")
        item_dict = cast(dict[str, object], item)
        name = Dish.normalize_ingredient(item_dict["ingredient"])
        if not name:
            raise ValueError("ingredient name cannot be empty")
        if name in seen:
            continue
        item_dict["ingredient"] = name
        # Coerce confidence to float in [0, 1], default 0.5
        conf_value = item_dict.get("confidence", 0.5)
        if isinstance(conf_value, (int, float, str)):
            try:
                conf = float(cast(float | int | str, conf_value))
            except (TypeError, ValueError):
                conf = 0.5
        else:
            conf = 0.5
        item_dict["confidence"] = max(0.0, min(1.0, conf))
        # Coerce is_essential to bool, default True
        is_essential = item_dict.get("is_essential", True)
        if not isinstance(is_essential, bool):
            raise ValueError("is_essential must be a boolean")
        item_dict["is_essential"] = is_essential
        seen.add(name)
        cleaned.append(item_dict)

    pre_selected = cleaned[:pre_select_top_n]
    remaining = cleaned[pre_select_top_n:]

    for item in pre_selected:
        name = item["ingredient"]
        if item.get("is_essential", True):
            if name not in session.essential_ingredients:
                session.essential_ingredients.append(name)
        else:
            if name not in session.optional_ingredients:
                session.optional_ingredients.append(name)

    session.hidden_queue = remaining[1:]
    session.current_suggestion = remaining[0] if remaining else None

    with _global_lock:
        if session_id in _sessions and not reuse_existing:
            raise ValueError(f"Session ID collision: {session_id}")
        _sessions[session_id] = session
    _persist_session(session)
    return session


def get_session_state(session_id: str) -> dict:
    """Return public session state as a JSON-serializable dict."""
    # Validate first so we don't create a per-session lock for a non-existent
    # id (otherwise _session_locks accumulates orphan entries).
    _require_session(session_id)
    with _get_lock(session_id):
        session = _require_session(session_id)
        return _session_to_response(session)


def add_suggested_ingredient(session_id: str) -> dict:
    """Accept the current suggestion, advance the queue."""
    _require_active_session(session_id)
    with _get_lock(session_id):
        session = _require_active_session(session_id)

        if session.current_suggestion is None:
            resp = _session_to_response(session)
            resp["no_change"] = True
            return resp

        item = session.current_suggestion
        name = item["ingredient"]
        if item.get("is_essential", True):
            if name not in session.essential_ingredients:
                session.essential_ingredients.append(name)
        else:
            if name not in session.optional_ingredients:
                session.optional_ingredients.append(name)

        _advance_queue(session)
        _touch(session)
        _persist_session(session)
        return _session_to_response(session)


def skip_suggested_ingredient(session_id: str) -> dict:
    """Skip the current suggestion without adding it."""
    _require_active_session(session_id)
    with _get_lock(session_id):
        session = _require_active_session(session_id)
        _advance_queue(session)
        _touch(session)
        _persist_session(session)
        return _session_to_response(session)


def remove_ingredient(session_id: str, ingredient: str) -> dict:
    """Remove an ingredient. Signals recalculation if it was essential."""
    _require_session(session_id)
    with _get_lock(session_id):
        session = _require_session(session_id)
        name = Dish.normalize_ingredient(ingredient)
        if not name:
            raise ValueError("Ingredient name cannot be empty")
        recalc = False

        if name in session.essential_ingredients:
            session.essential_ingredients.remove(name)
            recalc = True
            session.pending_recalculation = True
        elif name in session.optional_ingredients:
            session.optional_ingredients.remove(name)
        else:
            resp = _session_to_response(session)
            resp["no_change"] = True
            return resp

        _touch(session)
        _persist_session(session)
        return _session_to_response(session, recalculation_needed=recalc)


def add_manual_ingredient(session_id: str, ingredient: str, is_essential: bool = True) -> dict:
    """Add a user-typed ingredient not from the funnel."""
    _require_session(session_id)
    with _get_lock(session_id):
        session = _require_session(session_id)
        if not isinstance(is_essential, bool):
            raise ValueError("is_essential must be a boolean")
        name = Dish.normalize_ingredient(ingredient)

        if not name:
            resp = _session_to_response(session)
            resp["no_change"] = True
            resp["error"] = "Ingredient name cannot be empty"
            return resp

        # Move between categories if already present in the opposite one
        if is_essential:
            if name in session.optional_ingredients:
                session.optional_ingredients.remove(name)
            if name not in session.essential_ingredients:
                session.essential_ingredients.append(name)
        else:
            if name in session.essential_ingredients:
                session.essential_ingredients.remove(name)
            if name not in session.optional_ingredients:
                session.optional_ingredients.append(name)

        # Remove from hidden queue to avoid redundant suggestions later
        session.hidden_queue = [
            item for item in session.hidden_queue
            if item["ingredient"] != name
        ]
        if session.current_suggestion and session.current_suggestion["ingredient"] == name:
            _advance_queue(session)

        _touch(session)
        _persist_session(session)
        return _session_to_response(session)


def clear_all_ingredients(session_id: str) -> dict:
    """Remove all selected ingredients. Signals recalculation."""
    _require_session(session_id)
    with _get_lock(session_id):
        session = _require_session(session_id)
        session.essential_ingredients.clear()
        session.optional_ingredients.clear()
        session.pending_recalculation = True
        _touch(session)
        _persist_session(session)
        return _session_to_response(session, recalculation_needed=True)


def finalize_session(
    session_id: str,
    commit_to_fridge: bool = True,
    commit_to_dish: bool = True,
) -> dict:
    """Commit session results to fridge and/or dish catalog."""
    if not isinstance(commit_to_fridge, bool):
        raise ValueError("commit_to_fridge must be a boolean")
    if not isinstance(commit_to_dish, bool):
        raise ValueError("commit_to_dish must be a boolean")

    if get_session(session_id) is None:
        raise ValueError(f"Session not found or expired: {session_id}")
    with _get_lock(session_id):
        session = get_session(session_id)
        if session is None:
            raise ValueError(f"Session not found or expired: {session_id}")

        # Idempotent finalization
        if session.finalized:
            resp = _session_to_response(session)
            resp["warning"] = "Session was already finalized"
            return resp

        all_ingredients = session.essential_ingredients + session.optional_ingredients

        committed_fridge = False
        committed_dish = False
        added_to_fridge: list[str] = []

        if commit_to_fridge and all_ingredients:
            with fridge_lock:
                fridge = load_fridge()
                added_to_fridge = [ing for ing in all_ingredients if ing not in fridge]
                if added_to_fridge:
                    fridge.extend(added_to_fridge)
                    save_fridge(fridge)
                committed_fridge = bool(added_to_fridge)

        try:
            if commit_to_dish:
                with dishes_lock:
                    dishes = load_dishes()
                    ingredient_map = {}
                    for ing in session.essential_ingredients:
                        ingredient_map[ing] = True
                    for ing in session.optional_ingredients:
                        ingredient_map[ing] = False

                    existing = next(
                        (d for d in dishes if d.name.strip().lower() == session.dish_name),
                        None,
                    )
                    if existing is not None:
                        existing.ingredients = ingredient_map
                    else:
                        new_dish = Dish(name=session.dish_name)
                        for ing, essential in ingredient_map.items():
                            new_dish.add_ingredient(ing, essential)
                        dishes.append(new_dish)
                    save_dishes(dishes)
                    committed_dish = True
        except Exception:
            # Delta rollback: only remove the items we actually added so we
            # don't clobber concurrent fridge writes.
            if added_to_fridge:
                try:
                    remove_items_from_fridge(added_to_fridge)
                except Exception:
                    logger.exception("finalize_session fridge rollback failed")
            raise

        session.finalized = True
        session.pending_recalculation = False
        _touch(session)

        resp = _session_to_response(session)
        resp["committed_to_fridge"] = committed_fridge
        resp["committed_to_dish"] = committed_dish

        # Clean up: remove from memory and disk to prevent unbounded growth (H1).
        try:
            with _global_lock:
                _sessions.pop(session_id, None)
                _session_locks.pop(session_id, None)
            _delete_session_file(session_id)
        except Exception:
            logger.exception("finalize_session cleanup failed")

        return resp
