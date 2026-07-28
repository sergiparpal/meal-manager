"""Dynamic Ingredient Interface — public API.

Composes the session store, pure engine, presenter, and finalizer into the
eight functions consumed by the DII handler modules under ``src/handlers/``.
Persistence is injected via the shared repository singletons so this layer
never touches files directly.
"""

import logging
from contextlib import contextmanager
from pathlib import Path

from ..repositories import dish_repo, fridge_repo
from . import engine
from .finalizer import commit as _commit
from .presenter import to_response as _to_response
from .session import DIISession
from .store import IngredientSessionStore

# Deliberate re-export, not dead code: init_ingredient_session imports
# validate_session_id from here. The redundant alias is the explicit form that
# says so.
from .store import validate_session_id as validate_session_id

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


@contextmanager
def _locked(session_id: str, *, active_only: bool = False):
    """Lock a session, then validate it, yielding the live object.

    Validating *inside* the lock is what guarantees the session stays live and
    unfinalized for the whole mutation, so it is the only check that carries
    weight. There used to be a second, identical check before the lock, on the
    grounds that it kept a bad id out of the lock map — but every DII call then
    paid for two full ``_store.get()`` round-trips (global lock, TTL sweep,
    possibly a disk read), and ``session_lock`` only ever mints a refcounted
    dict entry that deletes itself when its last holder leaves. Validating the
    id *format* up front is the part worth keeping, and it is a regex.
    """
    require = _require_active_session if active_only else _require_session
    with _store.session_lock(validate_session_id(session_id)):
        yield require(session_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    with _locked(session_id) as session:
        return _to_response(session)


def add_suggested_ingredient(session_id: str) -> dict:
    """Accept the current suggestion and advance the queue."""
    with _locked(session_id, active_only=True) as session:
        if not engine.add_suggested(session):
            resp = _to_response(session)
            resp["no_change"] = True
            return resp
        _store.persist(session)
        return _to_response(session)


def skip_suggested_ingredient(session_id: str) -> dict:
    """Skip the current suggestion without adding it."""
    with _locked(session_id, active_only=True) as session:
        engine.skip_suggested(session)
        _store.persist(session)
        return _to_response(session)


def remove_ingredient(session_id: str, ingredient: str) -> dict:
    """Remove an ingredient. Signals recalculation if it was essential."""
    with _locked(session_id) as session:
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
    with _locked(session_id) as session:
        engine.add_manual(session, ingredient, is_essential)
        _store.persist(session)
        return _to_response(session)


def clear_all_ingredients(session_id: str) -> dict:
    """Remove all selected ingredients. Signals recalculation."""
    with _locked(session_id) as session:
        cleared = engine.clear_all(session)
        _store.persist(session)
        return _to_response(session, recalculation_needed=cleared)


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

    # One lookup, taken under the lock — the pre-lock probe this used to do was
    # a second full ``_store.get()`` whose answer the locked one re-derived.
    with _store.session_lock(validate_session_id(session_id)):
        session = _store.get(session_id)
        if session is None:
            raise ValueError(f"Session not found or expired: {session_id}")

        # Idempotent finalization
        if session.finalized:
            resp = _to_response(session)
            resp["warning"] = "Session was already finalized"
            return resp

        has_selection = bool(
            session.essential_ingredients or session.optional_ingredients
        )

        committed_fridge, committed_dish, fridge_items_added = _commit(
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
        resp["fridge_items_added"] = fridge_items_added
        if commit_to_dish and not committed_dish and not has_selection:
            resp["warning"] = (
                "No ingredients were selected; the dish catalog was not modified."
            )

        # Persist the finalized flag rather than deleting the session, so a
        # repeat finalize hits the idempotency guard above (and reports the
        # "already finalized" warning) instead of a misleading "not found",
        # and a crash-recovery reload cannot re-commit. TTL cleanup reclaims
        # the inert finalized session in the background.
        try:
            _store.persist(session)
        except Exception:
            logger.exception("finalize_session persist failed")

        return resp
