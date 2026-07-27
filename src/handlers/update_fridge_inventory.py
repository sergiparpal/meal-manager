"""Tool: update_fridge_inventory — add, remove, or set fridge portion counts."""

from ..repositories import fridge_repo
from ._common import (
    MAX_FRIDGE_UPDATE,
    MAX_PORTION_COUNT,
    normalize_ingredient_entries,
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
                "mark a pantry staple that never runs out (salt, oil, spices). "
                "To record an expiry date, map the name to an object instead: "
                '{\"milk\": {\"count\": 2, \"expires_on\": \"2026-08-01\"}}. '
                "Omitting expires_on leaves any stored date alone; passing null "
                "clears it."
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


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    action = require_arg(args, "action")
    raw_items = require_arg(args, "ingredients")

    if action not in ("add", "remove", "set"):
        raise ValueError(f"action must be 'add', 'remove' or 'set', got '{action}'")

    if action == "remove":
        # Removal deletes the entry outright, so a count attached to the name is
        # meaningless here and must not be validated against MAX_PORTION_COUNT.
        return _remove(normalize_ingredient_names(raw_items))

    specs = normalize_ingredient_entries(raw_items)
    if len(specs) > MAX_FRIDGE_UPDATE:
        raise ValueError(f"Too many ingredients (max {MAX_FRIDGE_UPDATE})")
    if not specs:
        return "No changes — no valid ingredients provided."

    with fridge_repo.lock:
        entries = fridge_repo.load_entries()

        changes = []
        unchanged = []
        dated = []
        for ing, spec in specs.items():
            count = spec["count"]
            existing = entries.get(ing)
            before = existing["count"] if existing is not None else 0
            has_expiry = "expires_on" in spec

            if action == "set":
                new_count = count
            elif count is None:
                new_count = None            # promote to pantry staple
            elif before is None:
                # Already unlimited, so the count cannot go up. An expiry sent
                # alongside it is still a real change, though, and dropping it
                # here silently discarded a date the user had just given us.
                if not has_expiry:
                    unchanged.append(ing)
                    continue
                new_count = None
                dated.append(ing)
            else:
                # The input count is capped, but the running total was not, so
                # two adds of the maximum stored well past it.
                new_count = min(before + count, MAX_PORTION_COUNT)

            # An omitted expires_on leaves whatever is stored alone, so a
            # routine restock does not quietly erase a date the user gave us.
            if has_expiry:
                expires_on = spec["expires_on"]
            else:
                expires_on = existing["expires_on"] if existing is not None else None

            entries[ing] = {"count": new_count, "expires_on": expires_on}
            if ing not in dated:
                changes.append((ing, before, new_count))

        if changes or dated:
            fridge_repo.save_entries(entries)

    parts = []
    if changes:
        detail = ", ".join(f"{ing} ({_fmt(before)} -> {_fmt(after)})"
                           for ing, before, after in sorted(changes))
        verb = "Set" if action == "set" else "Added"
        parts.append(f"{verb} in the fridge: {detail}.")
    if dated:
        # Reported separately: the count genuinely did not move, so folding
        # these into the "(before -> after)" detail would read as a no-op.
        parts.append(f"Expiry recorded for: {', '.join(sorted(dated))}.")
    if unchanged:
        already = f"{', '.join(sorted(unchanged))} already a pantry staple."
        parts.append(f"No changes — {already}" if not parts
                     else f"Already a pantry staple: {', '.join(sorted(unchanged))}.")
    return " ".join(parts)
