import json
import threading
from pathlib import Path

from . import atomic_write_json

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_PATH = BASE_DIR / "data" / "history.json"

history_lock = threading.Lock()


def load_history():
    if not HISTORY_PATH.exists():
        return {}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    # Normalize keys to lowercase; keep the most recent date for duplicates
    normalized = {}
    for name, date_str in raw.items():
        if not isinstance(name, str) or not isinstance(date_str, str):
            continue
        key = name.strip().lower()
        if key not in normalized or date_str > normalized[key]:
            normalized[key] = date_str
    return normalized


def set_history_entry(dish_name, date_str):
    """Store or replace a cooking-history entry and return the previous value."""
    with history_lock:
        history = load_history()
        key = dish_name.strip().lower()
        previous = history.get(key)
        history[key] = date_str if isinstance(date_str, str) else date_str.isoformat()
        atomic_write_json(HISTORY_PATH, history)
        return previous


def remove_history_entry(dish_name: str) -> bool:
    """Remove a dish entry from the cooking history.

    Args:
        dish_name: The dish name to remove.

    Returns:
        True if the entry was found and removed, False if not found.
    """
    with history_lock:
        history = load_history()
        key = dish_name.strip().lower()
        if key not in history:
            return False
        del history[key]
        atomic_write_json(HISTORY_PATH, history)
        return True


def revert_history_entry(dish_name: str, expected_value: str, previous_value: str | None) -> bool:
    """Compare-and-swap rollback for set_history_entry.

    If the current entry equals *expected_value*, restore *previous_value*
    (or delete the key if previous was None). If the current value diverged
    (a concurrent writer changed it), leave it alone and return False.
    """
    with history_lock:
        history = load_history()
        key = dish_name.strip().lower()
        if history.get(key) != expected_value:
            return False
        if previous_value is None:
            history.pop(key, None)
        else:
            history[key] = previous_value
        atomic_write_json(HISTORY_PATH, history)
        return True
