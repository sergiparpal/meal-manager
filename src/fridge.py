import json
import threading
from pathlib import Path

from . import atomic_write_json

BASE_DIR = Path(__file__).resolve().parent.parent
FRIDGE_PATH = BASE_DIR / "data" / "fridge.json"

fridge_lock = threading.Lock()


def load_fridge() -> list[str]:
    """Load the current fridge inventory from fridge.json.

    Returns:
        A list of ingredient name strings. Returns an empty list if the
        file does not exist or contains invalid data.
    """
    if not FRIDGE_PATH.exists():
        return []
    try:
        with open(FRIDGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    items = [ing.strip().lower() for ing in data if isinstance(ing, str)]
    return list(dict.fromkeys(items))


def save_fridge(ingredients: list[str]) -> None:
    """Persist the fridge inventory to fridge.json atomically.

    Args:
        ingredients: The full list of ingredient names to save.
    """
    atomic_write_json(FRIDGE_PATH, ingredients)


def load_fridge_set() -> set[str]:
    """Load the fridge inventory as a set for O(1) membership tests."""
    return set(load_fridge())


def remove_items_from_fridge(items: list[str]) -> None:
    """Atomically remove specific items from the fridge if present.

    Used by delta-rollback paths so an aborted operation only undoes its own
    additions and doesn't clobber concurrent writes.
    """
    if not items:
        return
    to_remove = set(items)
    with fridge_lock:
        fridge = load_fridge()
        new_fridge = [ing for ing in fridge if ing not in to_remove]
        if new_fridge != fridge:
            save_fridge(new_fridge)
