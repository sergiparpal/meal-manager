import json
import threading
from pathlib import Path

from . import atomic_write_json
from .dish import Dish

BASE_DIR = Path(__file__).resolve().parent.parent
JSON_PATH = BASE_DIR / "data" / "dishes.json"

dishes_lock = threading.Lock()


def load_dishes():
    if not JSON_PATH.exists():
        return []
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    result = []
    for p in data.get("dishes", []):
        try:
            result.append(Dish.from_dict(p))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return result


def save_dishes(dishes):
    data = {"dishes": [p.to_dict() for p in dishes]}
    atomic_write_json(JSON_PATH, data)
