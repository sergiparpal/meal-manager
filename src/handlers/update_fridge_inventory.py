"""Tool: update_fridge_inventory — add or remove fridge ingredients."""

from ..repositories import fridge_repo
from ._common import (
    MAX_FRIDGE_UPDATE,
    normalize_ingredient_name,
    tool_handler,
)

NAME = "update_fridge_inventory"

SCHEMA = {
    "description": (
        "Add or remove ingredients from the fridge inventory. Use when the "
        "user mentions buying groceries, restocking, or when ingredients "
        "have run out."
    ),
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["add", "remove"],
            "description": "add or remove ingredients",
        },
        "ingredients": {
            "type": "array",
            "items": {"type": "string"},
            "description": "list of ingredient names",
        },
    },
    "required": ["action", "ingredients"],
}


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    action = args["action"]
    raw_items = args["ingredients"]

    if action not in ("add", "remove"):
        raise ValueError(f"action must be 'add' or 'remove', got '{action}'")
    if not isinstance(raw_items, list):
        raise ValueError("ingredients must be an array")
    if len(raw_items) > MAX_FRIDGE_UPDATE:
        raise ValueError(f"Too many ingredients (max {MAX_FRIDGE_UPDATE})")

    items = list(dict.fromkeys(normalize_ingredient_name(raw) for raw in raw_items))
    if not items:
        return "No changes — no valid ingredients provided."

    names = ", ".join(items)

    with fridge_repo.lock:
        fridge = fridge_repo.load()

        if action == "add":
            added = [ing for ing in items if ing not in fridge]
            already = [ing for ing in items if ing in fridge]
            if added:
                fridge.extend(added)
                fridge_repo.save(fridge)
                if already:
                    return (
                        f"Added {', '.join(added)} to the fridge. "
                        f"Already present: {', '.join(already)}."
                    )
                return f"Successfully added {', '.join(added)} to the fridge."
            return f"No changes — {names} already in the fridge."

        # action == "remove"
        to_remove = set(items)
        removed = [ing for ing in items if ing in fridge]
        not_found = [ing for ing in items if ing not in fridge]
        if removed:
            fridge = [ing for ing in fridge if ing not in to_remove]
            fridge_repo.save(fridge)
            if not_found:
                return (
                    f"Removed {', '.join(removed)} from the fridge. "
                    f"Not found: {', '.join(not_found)}."
                )
            return f"Successfully removed {', '.join(removed)} from the fridge."
        return f"No changes — {names} not found in the fridge."
