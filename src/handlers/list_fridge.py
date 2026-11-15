"""Tool: list_fridge — return current fridge contents."""

from datetime import date

from .. import unreadable_json
from ..repositories import fridge_repo
from ..repositories.json_fridge import EXPIRING_SOON_DAYS, expiry_status
from ._common import tool_handler

NAME = "list_fridge"

DAMAGED_WARNING = (
    "The saved fridge file (fridge.json) is damaged and could not be read, so "
    "the fridge shows as empty even if the user has food recorded. Tell the "
    "user. Saving to the fridge now first keeps the damaged file aside, as "
    "fridge.json.unreadable-<time>, so what it held is not lost."
)

SCHEMA = {
    "description": (
        "Return the current contents of the fridge as "
        "{in_stock: {ingredient: portion_count}, out_of_stock: [ingredient]}. "
        "A portion count of null means a pantry staple that never runs out "
        "(salt, oil, spices); a number is roughly how many dishes' worth is on "
        "hand. 'out_of_stock' lists ingredients the user is known to have run "
        "out of, which is more informative than never having had them. "
        "Ingredients with a recorded expiry also appear in 'expiry' with their "
        "date and status, and are collected into 'expiring_soon' (within "
        f"{EXPIRING_SOON_DAYS} days) and 'expired'. Expired items are still "
        "listed as in stock — the date is the user's estimate, not ground "
        "truth, so flag them and let the user decide. Use when the user asks "
        "what they have in the fridge or what needs using up. If the saved "
        "file is damaged, the fridge is empty and a 'warning' says so: tell "
        "the user, and don't say their fridge is empty."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    entries = fridge_repo.load_entries()
    today = date.today()

    expiry = {}
    expiring_soon = []
    expired = []
    for name, entry in sorted(entries.items()):
        status = expiry_status(entry["expires_on"], today)
        if status is None:
            continue
        expiry[name] = {"expires_on": entry["expires_on"], "status": status}
        if status == "expiring_soon":
            expiring_soon.append(name)
        elif status == "expired":
            expired.append(name)

    result = {
        "in_stock": {
            name: entry["count"]
            for name, entry in sorted(entries.items())
            if entry["count"] is None or entry["count"] > 0
        },
        "out_of_stock": sorted(
            name for name, entry in entries.items() if entry["count"] == 0
        ),
        "expiry": expiry,
        "expiring_soon": expiring_soon,
        "expired": expired,
    }
    if unreadable_json(fridge_repo.path):
        # The repository reads a damaged file as an empty fridge; say so, or the
        # agent reports an empty fridge as fact (the same gap as in list_dishes).
        result["warning"] = DAMAGED_WARNING
    return result
