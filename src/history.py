import json
import threading
from pathlib import Path

from . import atomic_write_json

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_PATH = BASE_DIR / "data" / "historial.json"

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


def register_cooked_dish(dish_name, date_str):
    with history_lock:
        history = load_history()
        history[dish_name.strip().lower()] = date_str if isinstance(date_str, str) else date_str.isoformat()
        atomic_write_json(HISTORY_PATH, history)


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
