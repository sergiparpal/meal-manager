"""Tool: merge_ingredient_alias — collapse two spellings of one ingredient."""

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


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    # Normalize before taking any lock — this reads the alias map, and the
    # lock order is alias -> dish -> fridge. Resolving `to_name` here also
    # means merging onto an already-aliased name lands on its canonical form.
    from_name = normalize_ingredient_name(require_arg(args, "from_name"))
    to_name = normalize_ingredient_name(require_arg(args, "to_name"))

    if from_name == to_name:
        raise ValueError(
            f"'{from_name}' is already the canonical name — nothing to merge."
        )

    dishes_updated = []
    with dish_repo.lock:
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

    fridge_merged = False
    resulting_count = None
    with fridge_repo.lock:
        fridge = fridge_repo.load()
        if from_name in fridge:
            from_count = fridge.pop(from_name)
            if to_name in fridge:
                to_count = fridge[to_name]
                if from_count is None or to_count is None:
                    resulting_count = None  # a staple never runs out
                else:
                    resulting_count = min(from_count + to_count, MAX_PORTION_COUNT)
            else:
                resulting_count = from_count
            fridge[to_name] = resulting_count
            fridge_repo.save(fridge)
            fridge_merged = True
        elif to_name in fridge:
            resulting_count = fridge[to_name]

    # Recorded last on purpose. If a step above fails, the alias is absent and
    # the whole operation is safely repeatable; recording it first would
    # canonicalize `from_name` away and turn the retry into a no-op that
    # silently leaves half-merged data behind.
    alias_repo.add(from_name, to_name)

    return {
        "from": from_name,
        "to": to_name,
        "dishes_updated": sorted(set(dishes_updated)),
        "fridge_merged": fridge_merged,
        "resulting_count": resulting_count,
    }
