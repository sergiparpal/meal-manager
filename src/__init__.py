"""meal_manager.src -- domain modules package."""

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, data, *, indent: int | None = 2,
                      fsync_dir: bool = True) -> None:
    """Write JSON atomically via temp file + os.replace.

    ``fsync_dir`` also fsyncs the parent directory so the rename is crash-durable
    for the canonical data files. Callers writing ephemeral, reconstructable
    files (e.g. DII session backups, which are held under a lock during the
    write) may pass ``fsync_dir=False`` to keep the critical section short.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
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
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
