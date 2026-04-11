import json
import os
import tempfile
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FRIDGE_PATH = BASE_DIR / "data" / "nevera.json"

fridge_lock = threading.Lock()


def load_fridge() -> list[str]:
    """Load the current fridge inventory from nevera.json.

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
    """Persist the fridge inventory to nevera.json atomically.

    Args:
        ingredients: The full list of ingredient names to save.
    """
    FRIDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(FRIDGE_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ingredients, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(FRIDGE_PATH))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
