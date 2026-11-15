"""meal_manager.src -- domain modules package."""

import contextlib
import json
import logging
import os
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .filelock import DataDirLock, DataLockTimeout, data_lock

__all__ = ["DataDirLock", "DataLockTimeout", "atomic_write_json", "data_lock", "unreadable_json"]

logger = logging.getLogger(__name__)

# Temp files created below. The prefix is what makes the stale sweep safe: it
# only ever removes files this module created.
_TMP_PREFIX = ".mm-tmp-"
_TMP_SUFFIX = ".tmp"

# Mode for a target that does not exist yet. ``mkstemp`` hands back 0600 and
# ``os.replace`` carries that onto the target, so without an explicit mode
# every data file silently narrowed to owner-only on its first write here.
_DEFAULT_FILE_MODE = 0o644

# A temp file older than this was left behind by a write that died before its
# ``os.replace``. Generous on purpose: a slow write in another process must
# never look stale.
_STALE_TMP_SECONDS = 3600

# A data file that cannot be read is moved aside under this name before a write
# replaces it: ``dishes.json.unreadable-20261115T134409Z``.
_UNREADABLE_INFIX = ".unreadable-"


def _apply_target_mode(fd: int, path: Path) -> None:
    """Give the temp file the permissions of the file it is about to replace."""
    try:
        mode = stat.S_IMODE(os.stat(str(path)).st_mode)
    except OSError:
        mode = _DEFAULT_FILE_MODE
    # Best-effort: fchmod is unavailable on some platforms, and a mode we
    # cannot set is not worth failing an otherwise good write over.
    with contextlib.suppress(OSError, AttributeError, NotImplementedError):
        os.fchmod(fd, mode)


def _sweep_stale_temps(directory: Path) -> None:
    """Delete temp files orphaned by a write that never reached ``os.replace``.

    Nothing else scans the data directory, so without this a single kill mid
    write leaves a file behind forever. Only files this module created
    (``_TMP_PREFIX``) and only ones older than ``_STALE_TMP_SECONDS`` are
    touched, so a write in flight in another process is never disturbed.
    """
    cutoff = time.time() - _STALE_TMP_SECONDS
    try:
        candidates = list(directory.glob(f"{_TMP_PREFIX}*{_TMP_SUFFIX}"))
    except OSError:
        return
    for candidate in candidates:
        with contextlib.suppress(OSError):
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink()


def unreadable_json(path: Path) -> bool:
    """True when *path* exists but does not hold valid JSON.

    The repositories read such a file as empty, so that one damaged file does
    not take every tool down with it. This is how the tools that list it can
    still say why the list is empty. A file that cannot be opened at all
    (permissions) is not "unreadable" here: there is nothing to move aside.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return False
    try:
        json.loads(raw.decode("utf-8"))
    except ValueError:  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        return True
    return False


def _keep_unreadable(path: Path) -> Path | None:
    """Move a damaged *path* aside before a write replaces it, and return where.

    Reading a damaged file as empty is what keeps the plugin usable, but it
    meant the next save wrote the empty view over the file and whatever it held
    was gone for good. Nothing reads the copy back; it is there to recover by hand.
    """
    if not unreadable_json(path):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kept = path.with_name(f"{path.name}{_UNREADABLE_INFIX}{stamp}")
    suffix = 1
    while kept.exists():
        kept = path.with_name(f"{path.name}{_UNREADABLE_INFIX}{stamp}-{suffix}")
        suffix += 1
    os.replace(str(path), str(kept))
    logger.warning("%s could not be read; kept it as %s before writing a new one",
                   path.name, kept.name)
    return kept


def atomic_write_json(path: Path, data, *, indent: int | None = 2,
                      fsync_dir: bool = True, keep_unreadable: bool = True) -> None:
    """Write JSON atomically via temp file + os.replace.

    ``fsync_dir`` also fsyncs the parent directory so the rename is crash-durable
    for the canonical data files. Callers writing ephemeral, reconstructable
    files (e.g. DII session backups, which are held under a lock during the
    write) may pass ``fsync_dir=False`` to keep the critical section short.

    ``keep_unreadable`` moves a target that holds no valid JSON aside, as
    ``<name>.unreadable-<UTC time>``, instead of writing over it. If that move
    fails, the write fails too and the target is left as it was. The same
    reconstructable files may pass ``False``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=_TMP_PREFIX,
                               suffix=_TMP_SUFFIX)
    try:
        _apply_target_mode(fd, path)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        if keep_unreadable:
            _keep_unreadable(path)
        os.replace(tmp, str(path))
        # Also fsync the parent directory so the rename itself is durable:
        # on many filesystems the directory entry is not persisted until the
        # directory is synced, so a crash right after os.replace could
        # otherwise revert to the pre-write file. Best-effort — some platforms
        # (notably Windows) do not support directory fsync.
        if fsync_dir:
            try:
                dir_fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    # After the write, never before: the failure path above stays as short as
    # it was, and a successful write is the natural moment to notice debris.
    _sweep_stale_temps(path.parent)
