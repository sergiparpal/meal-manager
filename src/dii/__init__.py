"""Dynamic Ingredient Interface — public API.

Composes the session store, pure engine, presenter, and finalizer into the
eight functions consumed by ``tools.py``. Persistence is injected via the
shared repository singletons so this layer never touches files directly.
"""

import logging
from pathlib import Path

from ..repositories import dish_repo, fridge_repo
from . import engine
from .finalizer import commit as _commit
from .presenter import to_response as _to_response
from .session import DIISession
from .store import IngredientSessionStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default singleton store
# ---------------------------------------------------------------------------
# Module-level so the public API stays a free-function surface. ``configure``
# below lets tests or hosts redirect the on-disk session backup directory
# without reloading this module.

_store = IngredientSessionStore()


def configure(session_dir) -> None:
    """Redirect the default DII session store at ``session_dir``.

    Mutates ``_store.session_dir`` in place so callers that already hold a
    reference to the store (or imported symbols from this module) keep
    working. Typically invoked by the top-level ``register`` with
    ``<data_dir>/sessions`` or by tests with a tmp path.
    """
    _store.session_dir = Path(session_dir)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_session(session_id: str) -> DIISession:
    session = _store.get(session_id)
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_session(session_id: str) -> DIISession | None:
    """Retrieve a session from memory or disk. Returns None if missing/expired."""
    return _store.get(session_id)


def create_session(
    session_id: str,
    dish_name: str,
    ranked_ingredients: list[dict],
    pre_select_top_n: int = 3,
    *,
    reuse_existing: bool = False,
) -> DIISession:
    """Initialize a DII session, optionally resetting an existing id in place."""
    _store.cleanup_expired()
    session = engine.build_session(
        session_id, dish_name, ranked_ingredients, pre_select_top_n
    )
    _store.put(session, allow_overwrite=reuse_existing)
    return session


def get_session_state(session_id: str) -> dict:
    """Return public session state as a JSON-serializable dict."""
    # Validate first so we don't create a per-session lock for a non-existent
    # id (otherwise the lock map accumulates orphan entries).
    _require_session(session_id)
    with _store.get_lock(session_id):
        session = _require_session(session_id)
        return _to_response(session)


def add_suggested_ingredient(session_id: str) -> dict:
    """Accept the current suggestion and advance the queue."""
    _require_active_session(session_id)
    with _store.get_lock(session_id):
        session = _require_active_session(session_id)
        if not engine.add_suggested(session):
            resp = _to_response(session)
            resp["no_change"] = True
            return resp
        _store.persist(session)
        return _to_response(session)


def skip_suggested_ingredient(session_id: str) -> dict:
    """Skip the current suggestion without adding it."""
    _require_active_session(session_id)
    with _store.get_lock(session_id):
        session = _require_active_session(session_id)
        engine.skip_suggested(session)
        _store.persist(session)
        return _to_response(session)


def remove_ingredient(session_id: str, ingredient: str) -> dict:
    """Remove an ingredient. Signals recalculation if it was essential."""
    _require_session(session_id)
    with _store.get_lock(session_id):
        session = _require_session(session_id)
        changed, recalc = engine.remove(session, ingredient)
        if not changed:
            resp = _to_response(session)
            resp["no_change"] = True
            return resp
        _store.persist(session)
        return _to_response(session, recalculation_needed=recalc)


def add_manual_ingredient(
    session_id: str,
    ingredient: str,
    is_essential: bool = True,
) -> dict:
    """Add a user-typed ingredient not from the funnel."""
    _require_session(session_id)
    with _store.get_lock(session_id):
        session = _require_session(session_id)
        changed, err = engine.add_manual(session, ingredient, is_essential)
        if not changed:
            resp = _to_response(session)
            resp["no_change"] = True
            if err:
                resp["error"] = err
            return resp
        _store.persist(session)
        return _to_response(session)


def clear_all_ingredients(session_id: str) -> dict:
    """Remove all selected ingredients. Signals recalculation."""
    _require_session(session_id)
    with _store.get_lock(session_id):
        session = _require_session(session_id)
        engine.clear_all(session)
        _store.persist(session)
        return _to_response(session, recalculation_needed=True)


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

    if _store.get(session_id) is None:
        raise ValueError(f"Session not found or expired: {session_id}")
    with _store.get_lock(session_id):
        session = _store.get(session_id)
        if session is None:
            raise ValueError(f"Session not found or expired: {session_id}")

        # Idempotent finalization
        if session.finalized:
            resp = _to_response(session)
            resp["warning"] = "Session was already finalized"
            return resp

        committed_fridge, committed_dish = _commit(
            session,
            commit_to_fridge=commit_to_fridge,
            commit_to_dish=commit_to_dish,
            dish_repo=dish_repo,
            fridge_repo=fridge_repo,
        )

        engine.mark_finalized(session)

        resp = _to_response(session)
        resp["committed_to_fridge"] = committed_fridge
        resp["committed_to_dish"] = committed_dish

        # Clean up: remove from memory and disk to prevent unbounded growth.
        try:
            _store.remove(session_id)
        except Exception:
            logger.exception("finalize_session cleanup failed")

        return resp
