"""Repositories — composition root for the persistence layer.

Exposes the protocol classes (for type hints) and a default singleton per
repository (for the application). Consumers import from here:

    from .src.repositories import dish_repo, fridge_repo, history_repo

or, when typing matters:

    from .src.repositories import DishRepository
    def my_service(repo: DishRepository): ...

The default singletons point at ``<plugin_root>/data/`` on import. Callers
that need a different location (tests pointing at a tmp path, or a host
placing plugin data elsewhere) invoke :func:`configure` to redirect the
singletons. ``configure`` mutates the existing singletons in place so any
module that already imported ``dish_repo`` / ``fridge_repo`` / ``history_repo``
keeps a valid reference.
"""

from pathlib import Path

from .base import DishRepository, FridgeRepository, HistoryRepository
from .json_dish import JsonDishRepository
from .json_fridge import JsonFridgeRepository
from .json_history import JsonHistoryRepository

# ---------------------------------------------------------------------------
# Default singletons
# ---------------------------------------------------------------------------
# The default path matches the legacy layout (`<plugin_root>/data/`) so
# existing data files are picked up without migration. ``configure`` swaps
# the path on each singleton for callers that want isolation.

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

dish_repo: DishRepository = JsonDishRepository(_DEFAULT_DATA_DIR / "dishes.json")
fridge_repo: FridgeRepository = JsonFridgeRepository(_DEFAULT_DATA_DIR / "fridge.json")
history_repo: HistoryRepository = JsonHistoryRepository(_DEFAULT_DATA_DIR / "history.json")


def configure(data_dir) -> None:
    """Redirect the default repositories at ``data_dir``.

    Mutates ``dish_repo.path``, ``fridge_repo.path`` and ``history_repo.path``
    in place so consumers that already captured the singleton bindings
    (handlers under ``src/handlers/`` all do) continue to work without a
    reload. Typical callers:

    * the top-level ``register(ctx, data_dir=…)`` when a Hermes host wants
      the plugin to read/write under a custom location;
    * tests pointing at a ``tempfile.mkdtemp()`` path for isolation.
    """
    data_dir = Path(data_dir)
    dish_repo.path = data_dir / "dishes.json"
    fridge_repo.path = data_dir / "fridge.json"
    history_repo.path = data_dir / "history.json"


__all__ = [
    "DishRepository",
    "FridgeRepository",
    "HistoryRepository",
    "JsonDishRepository",
    "JsonFridgeRepository",
    "JsonHistoryRepository",
    "configure",
    "dish_repo",
    "fridge_repo",
    "history_repo",
]
