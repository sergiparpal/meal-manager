"""Repository protocols — the persistence boundary the rest of the package
depends on. Concrete implementations live in sibling ``json_*`` modules.

These are structural ``Protocol``s (not ABCs), so any class that exposes the
listed attributes/methods satisfies the contract — no inheritance needed.
This keeps the door open for in-memory test doubles or alternate backends
without coupling them to a specific base class.
"""

import threading
from typing import Protocol

from ..dish import Dish


class DishRepository(Protocol):
    """Persistence boundary for the dish catalog."""

    lock: threading.Lock

    def load(self) -> list[Dish]: ...
    def save(self, dishes: list[Dish]) -> None: ...
    def restore(self, dish: Dish) -> bool: ...


class FridgeRepository(Protocol):
    """Persistence boundary for the fridge inventory."""

    lock: threading.Lock

    def load(self) -> list[str]: ...
    def load_set(self) -> set[str]: ...
    def save(self, ingredients: list[str]) -> None: ...
    def remove_items(self, items: list[str]) -> None: ...


class HistoryRepository(Protocol):
    """Persistence boundary for cooking history.

    History is keyed by normalized dish name and value is an ISO date string.
    The repository owns its own locking — callers do not hold it.
    """

    def load(self) -> dict[str, str]: ...
    def set_entry(self, dish_name: str, date_str: str) -> str | None: ...
    def remove_entry(self, dish_name: str) -> bool: ...
    def revert_entry(
        self,
        dish_name: str,
        expected_value: str,
        previous_value: str | None,
    ) -> bool: ...


class TuningRepository(Protocol):
    """Persistence boundary for the online suggestion-weight learner.

    State is a single JSON object (candidate grid, discounted reward/count
    sums, observation counter, deployed weights). ``load`` never raises —
    a missing or corrupt file yields a fresh initialized state. The lock is
    exposed so the cook handler can wrap the load-modify-save sequence.
    """

    lock: threading.Lock

    def load(self) -> dict: ...
    def save(self, state: dict) -> None: ...
