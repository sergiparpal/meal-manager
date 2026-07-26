"""Tool: update_fridge_inventory — add, remove, or set fridge portion counts."""

from ..repositories import fridge_repo
from ._common import (
    MAX_FRIDGE_UPDATE,
    normalize_ingredient_counts,
    normalize_ingredient_names,
    require_arg,
    tool_handler,
)

NAME = "update_fridge_inventory"

SCHEMA = {
    "description": (
        "Add, remove, or set ingredients in the fridge inventory. The fridge "
        "tracks approximate portion counts — how many dishes' worth of an "
        "ingredient is on hand. Use when the user mentions buying groceries, "
        "restocking, running out, or correcting an estimate."
    ),
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["add", "remove", "set"],
            "description": (
                "'add' increases the portion count (creating the entry if new), "
                "'remove' deletes the ingredient entirely, 'set' overwrites the "
                "count — use 'set' to re-inventory after the estimates drift."
            ),
        },
        "ingredients": {
            "description": (
                "Either a list of names (each counts as one portion) or an "
                "object mapping name -> portion count. Use null as the count to "
                "mark a pantry staple that never runs out (salt, oil, spices)."
            ),
            "oneOf": [
                {"type": "array", "items": {"type": "string"}},
                {"type": "object"},
            ],
        },
    },
    "required": ["action", "ingredients"],
}


def _fmt(value):
    return "staple" if value is None else str(value)


def _remove(names: list[str]) -> str:
    if len(names) > MAX_FRIDGE_UPDATE:
        raise ValueError(f"Too many ingredients (max {MAX_FRIDGE_UPDATE})")
    if not names:
        return "No changes — no valid ingredients provided."

    with fridge_repo.lock:
        fridge = fridge_repo.load()
        removed = [ing for ing in names if ing in fridge]
        not_found = [ing for ing in names if ing not in fridge]
        if not removed:
            return f"No changes — {', '.join(names)} not found in the fridge."
        for ing in removed:
            del fridge[ing]
        fridge_repo.save(fridge)

    msg = f"Removed {', '.join(sorted(removed))} from the fridge."
    if not_found:
        msg += f" Not found: {', '.join(sorted(not_found))}."
    return msg


@tool_handler(NAME)
def HANDLER(args: dict, **kwargs):
    action = require_arg(args, "action")
    raw_items = require_arg(args, "ingredients")

    if action not in ("add", "remove", "set"):
        raise ValueError(f"action must be 'add', 'remove' or 'set', got '{action}'")

    if action == "remove":
        # Removal deletes the entry outright, so a count attached to the name is
        # meaningless here and must not be validated against MAX_PORTION_COUNT.
        return _remove(normalize_ingredient_names(raw_items))

    counts = normalize_ingredient_counts(raw_items)
    if len(counts) > MAX_FRIDGE_UPDATE:
        raise ValueError(f"Too many ingredients (max {MAX_FRIDGE_UPDATE})")
    if not counts:
        return "No changes — no valid ingredients provided."

    with fridge_repo.lock:
        fridge = fridge_repo.load()

        changes = []
        unchanged = []
        for ing, count in counts.items():
            before = fridge.get(ing, 0)
            if action == "set":
                fridge[ing] = count
            elif count is None:
                fridge[ing] = None          # promote to pantry staple
            elif fridge.get(ing, 0) is None:
                unchanged.append(ing)       # already unlimited; nothing to add
                continue
            else:
                fridge[ing] = before + count
            changes.append((ing, before, fridge[ing]))

        if changes:
            fridge_repo.save(fridge)

    if not changes:
        return f"No changes — {', '.join(sorted(unchanged))} already a pantry staple."

    detail = ", ".join(f"{ing} ({_fmt(before)} -> {_fmt(after)})"
                       for ing, before, after in sorted(changes))
    verb = "Set" if action == "set" else "Added"
    msg = f"{verb} in the fridge: {detail}."
    if unchanged:
        msg += f" Already a pantry staple: {', '.join(sorted(unchanged))}."
    return msg
