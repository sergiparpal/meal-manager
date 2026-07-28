"""JSON-file-backed implementation of AliasRepository.

The alias map records that one ingredient spelling *is* another: ``{"tomates":
"tomate"}``. It is consulted at the tool boundary
(``_common.normalize_ingredient_name``) so future input canonicalizes itself,
while the one-shot merge in ``merge_ingredient_alias`` rewrites the data that
already exists. Deliberately not a read-time projection over the catalog and
fridge: rewriting once is cheaper than resolving forever, and it leaves the
stored data honest about what the user has.
"""

import json
import logging
from pathlib import Path

from .. import atomic_write_json, data_lock

logger = logging.getLogger(__name__)


class JsonAliasRepository:
    """Stores ingredient aliases as a flat ``{alias: canonical}`` JSON object."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # Shared with every other repository — see ``src/filelock.py``.
        self.lock = data_lock
        # (file identity, parsed mapping) for the most recent successful read.
        # ``resolve`` runs once per ingredient name at the tool boundary, so
        # re-reading and re-parsing the file each time turned a single
        # 100-ingredient ``add_dish`` into 100 opens and 100 JSON parses.
        self._cache: tuple[tuple, dict[str, str]] | None = None

    def _identity(self):
        """Stat fingerprint of the file, or ``None`` when it is not there.

        ``atomic_write_json`` replaces the file rather than rewriting it in
        place, and the replacement is created while the old one still exists,
        so the inode is guaranteed to differ across writes. That is a stronger
        signal than mtime alone, whose filesystem resolution is coarse enough
        (a timer tick) for two quick writes to share a timestamp. ``configure``
        retargets ``path``, so the path belongs in the key too.
        """
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (str(self.path), stat.st_ino, stat.st_mtime_ns, stat.st_size)

    def _mapping(self) -> dict[str, str]:
        """Shared view of the alias map. Callers must not mutate the result."""
        identity = self._identity()
        if identity is None:
            self._cache = None
            return {}
        cached = self._cache
        if cached is not None and cached[0] == identity:
            return cached[1]
        mapping = self._parse()
        # One attribute store, so a concurrent reader sees either the previous
        # tuple or the new one — never a half-updated pair.
        self._cache = (identity, mapping)
        return mapping

    def _parse(self) -> dict[str, str]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning("Failed to load %s: %s", self.path.name, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning(
                "Ignoring %s with unexpected top-level type: %s",
                self.path.name,
                type(data).__name__,
            )
            return {}

        mapping: dict[str, str] = {}
        for raw_alias, raw_canonical in data.items():
            if not isinstance(raw_alias, str) or not isinstance(raw_canonical, str):
                continue
            alias = raw_alias.strip().lower()
            canonical = raw_canonical.strip().lower()
            if not alias or not canonical or alias == canonical:
                continue
            mapping[alias] = canonical
        return mapping

    def load(self) -> dict[str, str]:
        """Load the alias map; a missing or unreadable file yields ``{}``.

        Reads are lock-free, matching the other repositories: writes land via
        atomic replacement, so a reader sees either the old map or the new one.

        Returns a fresh copy every call — ``add`` mutates what it gets back,
        and the mapping behind :meth:`_mapping` is shared.
        """
        return dict(self._mapping())

    def save(self, mapping: dict) -> None:
        atomic_write_json(self.path, mapping)
        # The stat fingerprint would catch this on its own, but dropping the
        # cache here makes writes through the repository exact rather than
        # merely near-certain.
        self._cache = None

    def resolve(self, name: str) -> str:
        """Return the canonical spelling of *name*, or *name* itself.

        A single hop, never a loop. :meth:`add` guarantees that no alias ever
        points at another alias, so a chain cannot form — and a loop here would
        hang on a hand-edited file that contains a cycle.
        """
        return self._mapping().get(name, name)

    def add(self, alias: str, canonical: str) -> None:
        """Record that *alias* means *canonical*, keeping the map chain-free."""
        if alias == canonical:
            raise ValueError("an ingredient cannot be an alias of itself")
        with self.lock:
            mapping = self.load()
            # Anything that pointed at `alias` must be re-pointed, or the
            # single-hop resolve would stop one link short of the truth.
            for key, target in list(mapping.items()):
                if target == alias:
                    mapping[key] = canonical
            mapping[alias] = canonical
            # `canonical` is a root now, so it must not also be an alias key.
            mapping.pop(canonical, None)
            self.save(mapping)
