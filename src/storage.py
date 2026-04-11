import json
import os
import tempfile
import threading
from pathlib import Path
from .dish import Dish

BASE_DIR = Path(__file__).resolve().parent.parent
JSON_PATH = BASE_DIR / "data" / "platos.json"

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
    return [Dish.from_dict(p) for p in data.get("platos", [])]


def save_dishes(dishes):
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"platos": [p.to_dict() for p in dishes]}
    fd, tmp = tempfile.mkstemp(dir=str(JSON_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(JSON_PATH))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
