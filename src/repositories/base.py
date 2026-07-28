"""Repository protocols — the persistence boundary the rest of the package
depends on. Concrete implementations live in sibling ``json_*`` modules.

These are structural ``Protocol``s (not ABCs), so any class that exposes the
listed attributes/methods satisfies the contract — no inheritance needed.
This keeps the door open for in-memory test doubles or alternate backends
without coupling them to a specific base class.
"""

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from ..dish import Dish

# The concrete lock is the single shared ``DataDirLock`` from ``src/filelock.py``
# — one advisory lock over the whole data directory, not one per file. Callers
# only ever use it as a context manager, so that is all the protocols promise.
# Declared read-only (a property rather than a bare attribute) because a
# mutable protocol attribute is invariant, which would admit only something
# that is exactly an ``AbstractContextManager``; nothing reassigns ``.lock``.
#
# ``path`` is a plain attribute because ``configure()`` reassigns it in place —
# that is the documented seam hosts and tests use to redirect persistence.


class DishRepository(Protocol):
    """Persistence boundary for the dish catalog."""

    path: Path

    @property
    def lock(self) -> AbstractContextManager: ...

    def load(self) -> list[Dish]: ...
    def save(self, dishes: list[Dish]) -> None: ...
    def restore(self, dish: Dish) -> bool: ...


class FridgeRepository(Protocol):
    """Persistence boundary for the fridge inventory.

    Inventory is ``{name: count}`` where ``None`` means "pantry staple,
    unlimited" and ``0`` means "known to be out of stock". ``load_set`` returns
    only the usable names, which is what the scoring layer consumes.

    An entry may also carry an expiry date. ``load``/``save`` keep the
    count-only view unchanged for the callers that only care about portions;
    ``load_entries``/``save_entries`` are the richer pair that sees
    ``{"count": …, "expires_on": …}``.
    """

    path: Path

    @property
    def lock(self) -> AbstractContextManager: ...

    def load(self) -> dict: ...
    def load_entries(self) -> dict: ...
    def load_set(self) -> set[str]: ...
    def save(self, ingredients: dict) -> None: ...
    def save_entries(self, entries: dict) -> None: ...
    def remove_items(self, items: list[str]) -> None: ...
    def consume(self, names: list[str]) -> dict: ...
    def restore_counts(self, previous: dict) -> None: ...


class HistoryRepository(Protocol):
    """Persistence boundary for cooking history.

    History is an append-only log of :class:`CookingEvent`, projected on read
    to one date per dish (``{normalized dish name: ISO date string}``) — the
    shape the scoring path consumes. Because the projection takes the latest
    ``cooked_on`` per dish, an older event can never displace a newer one.

    Retraction (``retract_event`` / ``retract_latest_for_dish``) is the user's
    undo: the row survives and stays readable, it just stops counting toward
    the projection. ``delete_event`` is the hard delete reserved for rollback,
    where a cook that failed halfway must leave no trace at all.

    The repository owns its own locking — callers do not hold it.
    """

    path: Path

    def load(self) -> dict[str, str]: ...
    def load_events(self, *, strict: bool = False) -> list: ...
    def append_event(
        self,
        dish_name: str,
        cooked_on,
        *,
        backfilled: bool = False,
    ): ...
    def retract_event(self, event_id: str): ...
    def retract_latest_for_dish(self, dish_name: str): ...
    def retract_all_for_dish(self, dish_name: str) -> list: ...
    def delete_event(self, event_id: str) -> bool: ...


class AliasRepository(Protocol):
    """Persistence boundary for ingredient aliases.

    A flat ``{alias: canonical}`` map consulted at the tool boundary so that
    input spelled a second way canonicalizes itself. ``add`` maintains the
    invariant that no alias points at another alias, which is what lets
    ``resolve`` be a single hop rather than a walk.
    """

    path: Path

    @property
    def lock(self) -> AbstractContextManager: ...

    def load(self) -> dict[str, str]: ...
    def save(self, mapping: dict) -> None: ...
    def resolve(self, name: str) -> str: ...
    def add(self, alias: str, canonical: str) -> None: ...


class TuningRepository(Protocol):
    """Persistence boundary for the online suggestion-weight learner.

    State is a single JSON object (candidate grid, discounted reward/count
    sums, observation counter, deployed weights). ``load`` never raises —
    a missing or corrupt file yields a fresh initialized state. The lock is
    exposed so the cook handler can wrap the load-modify-save sequence.
    """

    path: Path

    @property
    def lock(self) -> AbstractContextManager: ...

    def load(self) -> dict: ...
    def save(self, state: dict) -> None: ...
