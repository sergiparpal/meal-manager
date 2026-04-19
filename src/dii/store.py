"""IngredientSessionStore — in-memory session map with JSON snapshots and TTL.

Owns all state and locking. The engine and the public API treat this as the
single source of truth for active sessions; the JSON files under
``data/sessions/`` exist only as crash-recovery backups.
"""

import json
import logging
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
        self.cleanup_expired()
        with self._global_lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = self._load_from_disk(session_id)
                if session is not None:
                    self._sessions[session_id] = session
        return session

    def put(self, session: DIISession, *, allow_overwrite: bool = False) -> None:
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

    def persist(self, session: DIISession) -> None:
        """Write session to its JSON backup file atomically."""
        path = self.session_dir / f"{session.session_id}.json"
        atomic_write_json(path, to_dict(session), indent=None)

    # -----------------------------------------------------------------
    # Persistence helpers
    # -----------------------------------------------------------------

    def _load_from_disk(self, session_id: str) -> DIISession | None:
        """Restore a session from its JSON backup, rejecting expired files."""
        path = self.session_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            path.unlink(missing_ok=True)
            return None
        try:
            session = from_dict(data)
        except Exception:
            path.unlink(missing_ok=True)
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.ttl_minutes)
        if parse_iso_to_aware(session.last_activity) < cutoff:
            path.unlink(missing_ok=True)
            return None
        return session

    def _delete_file(self, session_id: str) -> None:
        path = self.session_dir / f"{session_id}.json"
        path.unlink(missing_ok=True)

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
                    last = parse_iso_to_aware(data.get("last_activity"))
                    if last < cutoff:
                        fpath.unlink(missing_ok=True)
                except Exception:
                    fpath.unlink(missing_ok=True)
