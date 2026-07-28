"""Tool: merge_ingredient_alias — collapse two spellings of one ingredient."""

from .. import data_lock
from ..repositories import alias_repo, dish_repo, fridge_repo
from ._common import (
    MAX_PORTION_COUNT,
    normalize_ingredient_name,
    require_arg,
    tool_handler,
)

NAME = "merge_ingredient_alias"

SCHEMA = {
    "description": (
        "Declare that two ingredient names mean the same thing and merge them. "
        "Rewrites every recipe and the fridge to use the canonical name, then "
        "remembers the alias so future input canonicalizes itself. Use when "
        "the user says two entries are the same ('tomates and tomate are the "
        "same thing'), or when you notice near-duplicate spellings in the "
        "fridge or catalog. Where a recipe lists both, essential wins over "
        "optional; where the fridge holds both, portion counts are added and a "
        "pantry staple wins over any count."
    ),
    "type": "object",
    "properties": {
        "from_name": {
            "type": "string",
            "description": "the duplicate spelling to retire",
        },
        "to_name": {
            "type": "string",
            "description": "the canonical spelling to keep",
        },
    },
    "required": ["from_name", "to_name"],
}


def _merge_expiry(from_expiry, to_expiry):
    """Earliest known date wins; an absent date means unknown, not "never".

    Merging through the count-only view dropped the retired name's date
    entirely, so collapsing the only stocked spelling onto a canonical name
    that was not in the fridge silently lost an expiry the user had recorded.
    Canonical ISO dates sort chronologically, so ``min`` is the earliest — the
    conservative choice, since the merged entry should warn on whichever batch
    goes off first.
    """
    known = [value for value in (from_expiry, to_expiry) if value is not None]
    return min(known) if known else None


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    # Normalize before entering the data-lock window: this reads the alias map,
    # and the window should cover only the mutations. Resolving `to_name` here
    # also means merging onto an already-aliased name lands on its canonical
    # form.
    from_name = normalize_ingredient_name(require_arg(args, "from_name"))
    to_name = normalize_ingredient_name(require_arg(args, "to_name"))

    if from_name == to_name:
        raise ValueError(
            f"'{from_name}' is already the canonical name — nothing to merge."
        )

    dishes_updated = []
    fridge_merged = False
    resulting_count = None
    resulting_expiry = None

    # One exclusive window over the catalog, the fridge and the alias map. The
    # lock is the same reentrant object for all three, so nesting is free — and
    # a merge that rewrote the catalog, then let another process interleave
    # before the fridge caught up, was observable as half-merged data.
    with data_lock:
        dishes = dish_repo.load()
        for dish in dishes:
            if from_name not in dish.ingredients:
                continue
            merged = dish.ingredients.pop(from_name)
            if to_name in dish.ingredients:
                # Essential wins. Demoting an essential to optional would let
                # can_cook_with approve a dish the user cannot actually make.
                dish.ingredients[to_name] = dish.ingredients[to_name] or merged
            else:
                dish.ingredients[to_name] = merged
            dishes_updated.append(dish.name)
        if dishes_updated:
            dish_repo.save(dishes)

        # The entries view, not the count-only one: the merge has to decide what
        # happens to both expiry dates rather than discard them by omission.
        entries = fridge_repo.load_entries()
        if from_name in entries:
            from_entry = entries.pop(from_name)
            to_entry = entries.get(to_name)
            from_count = from_entry["count"]
            if to_entry is not None:
                to_count = to_entry["count"]
                if from_count is None or to_count is None:
                    resulting_count = None  # a staple never runs out
                else:
                    resulting_count = from_count + to_count
            else:
                resulting_count = from_count
            # Clamp once, on the way out. Doing it only in the summing branch
            # let a single hand-edited out-of-band count survive the merge.
            if resulting_count is not None:
                resulting_count = min(resulting_count, MAX_PORTION_COUNT)
            resulting_expiry = _merge_expiry(
                from_entry["expires_on"],
                to_entry["expires_on"] if to_entry is not None else None,
            )
            entries[to_name] = {
                "count": resulting_count,
                "expires_on": resulting_expiry,
            }
            fridge_repo.save_entries(entries)
            fridge_merged = True
        elif to_name in entries:
            resulting_count = entries[to_name]["count"]
            resulting_expiry = entries[to_name]["expires_on"]

        # Recorded last on purpose. If a step above fails, the alias is absent
        # and the whole operation is safely repeatable; recording it first would
        # canonicalize `from_name` away and turn the retry into a no-op that
        # silently leaves half-merged data behind.
        alias_repo.add(from_name, to_name)

    return {
        "from": from_name,
        "to": to_name,
        "dishes_updated": sorted(set(dishes_updated)),
        "fridge_merged": fridge_merged,
        "resulting_count": resulting_count,
        "resulting_expiry": resulting_expiry,
    }
