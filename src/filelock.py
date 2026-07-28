"""Cross-process advisory lock over the plugin's data directory.

The repositories serialize with threading locks, which only bind one process.
Two processes running load-modify-save against the same JSON file lose an update
silently: atomic_write_json prevents a torn file, not a clobbered one. This adds
an advisory file lock so the load-modify-save window is exclusive across
processes too.

One lock covers the whole data directory rather than one lock per file. A
per-file lock would require a global acquisition order across five repositories,
and handlers that touch several (register_cooked_meal touches four) would become
a deadlock source. The directory lock is coarse, but it also gives those handlers
the cross-repository atomicity they never had.
"""

import contextlib
import logging
import os
import threading
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# How long to wait for another process to release the data directory before
# giving up. Every operation here is milliseconds of work, so anything near
# this bound means the other holder is wedged, not busy.
LOCK_TIMEOUT_SECONDS = 30.0
_LOCK_POLL_SECONDS = 0.05


class DataLockTimeout(TimeoutError):
    """The data directory stayed locked by another process past the timeout.

    A ``TimeoutError`` (and so an ``OSError``) so generic I/O error handling
    still catches it, but a distinct type so the handler layer can surface the
    real reason instead of the generic storage message. The message is written
    for the user and deliberately carries no filesystem path.
    """


class DataDirLock:
    """Reentrant, thread-safe, cross-process lock over one directory.

    Reentrancy matters: repository methods nest (``save`` calls ``load_entries``)
    and handlers hold one repository's lock while calling into another. Since
    every repository shares this one object, a non-reentrant lock would deadlock
    on the first nested call.

    Degrades to a pure in-process lock where ``fcntl`` is unavailable (Windows),
    matching the existing best-effort posture of ``atomic_write_json``'s
    directory fsync.
    """

    def __init__(self, path, *, timeout_seconds: float = LOCK_TIMEOUT_SECONDS) -> None:
        self._path = Path(path)
        self._rlock = threading.RLock()
        self._depth = 0
        self._fd: int | None = None
        self.timeout_seconds = timeout_seconds

    @property
    def path(self) -> Path:
        return self._path

    def configure(self, path) -> None:
        """Point the lock at a new file. Not permitted while held."""
        with self._rlock:
            if self._depth:
                raise RuntimeError("cannot reconfigure a held DataDirLock")
            self._path = Path(path)

    def __enter__(self):
        self._rlock.acquire()
        self._depth += 1
        if self._depth == 1:
            try:
                self._acquire_file_lock()
            except BaseException:
                self._depth -= 1
                self._rlock.release()
                raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._depth == 1:
                self._release_file_lock()
        finally:
            self._depth -= 1
            self._rlock.release()

    def _acquire_file_lock(self) -> None:
        # The lock file is opened per critical section and closed on release.
        # A long-lived fd would go stale across ``configure``; reopening costs
        # one syscall pair per operation, which is nothing at this scale.
        if fcntl is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            self._flock_until(fd)
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd

    def _flock_until(self, fd: int) -> None:
        """Block for the lock, but give up rather than hang forever.

        A blocking ``LOCK_EX`` has no upper bound, so one wedged holder froze
        every tool in the plugin with nothing to report to the user. Polling a
        non-blocking acquire turns that into an error the handler layer can
        explain.
        """
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise DataLockTimeout(
                        "The meal data is busy — another operation has been "
                        "holding it too long. Try again in a moment."
                    ) from None
                time.sleep(_LOCK_POLL_SECONDS)

    def _release_file_lock(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            logger.warning("failed to release data lock", exc_info=True)
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)


# ``src/filelock.py`` -> ``.parent`` is ``src/`` -> ``.parent`` is the plugin
# root, so this matches ``_DEFAULT_DATA_DIR`` in ``src/repositories/__init__``.
_DEFAULT_LOCK_PATH = Path(__file__).resolve().parent.parent / "data" / ".lock"

data_lock = DataDirLock(_DEFAULT_LOCK_PATH)
