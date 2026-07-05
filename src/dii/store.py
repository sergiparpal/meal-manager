"""IngredientSessionStore — in-memory session map with JSON snapshots and TTL.

Owns all state and locking. The engine and the public API treat this as the
single source of truth for active sessions; the JSON files under
``data/sessions/`` exist only as crash-recovery backups.
"""

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import atomic_write_json
from .session import DIISession, from_dict, parse_iso_to_aware, to_dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

SESSION_TTL_MINUTES = 30
CLEANUP_INTERVAL_SECONDS = 60
DEFAULT_SESSION_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sessions"
ORPHAN_SCAN_LIMIT = 100

# Session ids become filenames (``<id>.json``), so they must be a strict,
# path-safe charset. Without this, an id like ``../dishes`` would resolve
# outside the sessions directory and let a read/write/unlink hit an arbitrary
# JSON file (e.g. deleting the dish catalog).
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_session_id(session_id: str) -> str:
    """Return *session_id* if it is a path-safe token, else raise ValueError."""
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(
            "Invalid session_id: must be 1-64 chars of letters, digits, '-' or '_'"
        )
    return session_id


class IngredientSessionStore:
    """Thread-safe in-memory store with disk mirror and lazy TTL cleanup."""

    def __init__(
        self,
        *,
        ttl_minutes: int = SESSION_TTL_MINUTES,
        cleanup_interval_seconds: int = CLEANUP_INTERVAL_SECONDS,
        session_dir: Path = DEFAULT_SESSION_DIR,
    ) -> None:
        self.ttl_minutes = ttl_minutes
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.session_dir = Path(session_dir)
        self._sessions: dict[str, DIISession] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
        self._last_cleanup_monotonic: float = 0.0

    # -----------------------------------------------------------------
    # Locking
    # -----------------------------------------------------------------

    def get_lock(self, session_id: str) -> threading.Lock:
        """Return (or create) the per-session lock."""
        with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = threading.Lock()
            return self._locks[session_id]

    # -----------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------

    def get(self, session_id: str) -> DIISession | None:
        """Retrieve session from memory, falling back to disk."""
        validate_session_id(session_id)
        self.cleanup_expired()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.ttl_minutes)
        with self._global_lock:
            session = self._sessions.get(session_id)
            # The memory path must apply the same TTL as the disk path: cleanup
            # is debounced, so an expired session can still be resident. Without
            # this check get() would serve a session the disk loader rejects.
            if session is not None and parse_iso_to_aware(session.last_activity) < cutoff:
                self._sessions.pop(session_id, None)
                self._locks.pop(session_id, None)
                self._delete_file(session_id)
                session = None
            if session is None:
                session = self._load_from_disk(session_id)
                if session is not None:
                    self._sessions[session_id] = session
        return session

    def put(self, session: DIISession, *, allow_overwrite: bool = False) -> None:
        validate_session_id(session.session_id)
        with self._global_lock:
            if session.session_id in self._sessions and not allow_overwrite:
                raise ValueError(f"Session ID collision: {session.session_id}")
            self._sessions[session.session_id] = session
        self.persist(session)

    def remove(self, session_id: str) -> None:
        with self._global_lock:
            self._sessions.pop(session_id, None)
            self._locks.pop(session_id, None)
            # Delete the file inside the lock so a concurrent get cannot
            # resurrect a just-purged session from disk.
            self._delete_file(session_id)

    def _session_path(self, session_id: str) -> Path:
        """Validated ``<session_dir>/<id>.json`` — the only place ids become paths."""
        validate_session_id(session_id)
        return self.session_dir / f"{session_id}.json"

    def persist(self, session: DIISession) -> None:
        """Write session to its JSON backup file atomically.

        No-op when the session is no longer the live mapping for its id (it was
        removed or replaced by a reset). This keeps the on-disk backup in step
        with memory: a mutation's trailing persist can't resurrect a session a
        concurrent remove/TTL-cleanup just deleted, and a reset can't be
        overwritten by an in-flight mutation of the old session object.
        """
        path = self._session_path(session.session_id)
        with self._global_lock:
            if self._sessions.get(session.session_id) is not session:
                return
            # Session backups are ephemeral crash-recovery state, so skip the
            # directory fsync to keep this lock-held critical section short.
            atomic_write_json(path, to_dict(session), indent=None, fsync_dir=False)

    # -----------------------------------------------------------------
    # Persistence helpers
    # -----------------------------------------------------------------

    def _load_from_disk(self, session_id: str) -> DIISession | None:
        """Restore a session from its JSON backup, rejecting expired files."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            path.unlink(missing_ok=True)  # genuinely corrupt backup
            return None
        except OSError:
            # Transient read error (EINTR/EACCES/…) — never destroy a file we
            # merely failed to read; atomic writes guarantee no torn content.
            logger.warning("transient read error loading session %s", session_id)
            return None
        try:
            session = from_dict(data)
        except (KeyError, TypeError, ValueError):
            path.unlink(missing_ok=True)  # malformed session backup
            return None
        if session.session_id != session_id:
            # Content doesn't match the requested id — don't trust or delete it.
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.ttl_minutes)
        if parse_iso_to_aware(session.last_activity) < cutoff:
            path.unlink(missing_ok=True)
            return None
        return session

    def _delete_file(self, session_id: str) -> None:
        self._session_path(session_id).unlink(missing_ok=True)

    # -----------------------------------------------------------------
    # GC
    # -----------------------------------------------------------------

    def cleanup_expired(self) -> None:
        """Purge sessions older than TTL from memory and disk.

        Debounced via the monotonic clock so wall-clock jumps cannot stop it
        firing.
        """
        now_mono = time.monotonic()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.ttl_minutes)

        with self._global_lock:
            if (
                self._last_cleanup_monotonic
                and (now_mono - self._last_cleanup_monotonic) < self.cleanup_interval_seconds
            ):
                return
            self._last_cleanup_monotonic = now_mono

            expired = [
                sid for sid, s in self._sessions.items()
                if parse_iso_to_aware(s.last_activity) < cutoff
            ]
            for sid in expired:
                self._sessions.pop(sid, None)
                self._locks.pop(sid, None)
                self._delete_file(sid)

            # Clean orphaned locks (e.g. from lookups on invalid session IDs).
            for sid in [s for s in self._locks if s not in self._sessions]:
                del self._locks[sid]

        # Also clean orphaned files on disk (cap iterations to avoid slow scans).
        if self.session_dir.exists():
            for i, fpath in enumerate(self.session_dir.glob("*.json")):
                if i >= ORPHAN_SCAN_LIMIT:
                    break
                try:
                    data = json.loads(fpath.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, ValueError):
                    fpath.unlink(missing_ok=True)  # corrupt file
                    continue
                except OSError:
                    continue  # transient read error — leave the file intact
                last = parse_iso_to_aware(data.get("last_activity"))
                if last < cutoff:
                    fpath.unlink(missing_ok=True)
