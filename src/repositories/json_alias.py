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
import threading
from pathlib import Path

from .. import atomic_write_json

logger = logging.getLogger(__name__)


class JsonAliasRepository:
    """Stores ingredient aliases as a flat ``{alias: canonical}`` JSON object."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> dict[str, str]:
        """Load the alias map; a missing or unreadable file yields ``{}``.

        Reads are lock-free, matching the other repositories: writes land via
        atomic replacement, so a reader sees either the old map or the new one.
        """
        if not self.path.exists():
            return {}
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

    def save(self, mapping: dict) -> None:
        atomic_write_json(self.path, mapping)

    def resolve(self, name: str) -> str:
        """Return the canonical spelling of *name*, or *name* itself.

        A single hop, never a loop. :meth:`add` guarantees that no alias ever
        points at another alias, so a chain cannot form — and a loop here would
        hang on a hand-edited file that contains a cycle.
        """
        return self.load().get(name, name)

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
