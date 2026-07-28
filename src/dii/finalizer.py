"""Commit a session to the fridge and recipe catalog with delta rollback.

Repositories are injected so the public API layer owns wiring; the finalizer
itself doesn't know how persistence is implemented.
"""

import logging

from ..dish import Dish
from ..repositories import DishRepository, FridgeRepository
from .session import DIISession

logger = logging.getLogger(__name__)


def commit(
    session: DIISession,
    *,
    commit_to_fridge: bool,
    commit_to_dish: bool,
    dish_repo: DishRepository,
    fridge_repo: FridgeRepository,
) -> tuple[bool, bool, int]:
    """Apply commit policy, returning ``(fridge, dish, items_added_to_fridge)``.

    ``committed_fridge`` reports whether the fridge commit was carried out, not
    whether it happened to change anything: a session whose ingredients were all
    already stocked has been committed just as fully as one that added three,
    and reporting False there reads as a failure. The count carries the "how
    much actually changed" signal instead.

    On a dish-write failure, rolls back only the items this call appended to
    the fridge — never clobbers concurrent writers.
    """
    # Essential wins where a name appears in both lists. The engine keeps them
    # mutually exclusive, but a session restored from a hand-edited backup need
    # not be, and a dict union resolved that collision the other way — silently
    # demoting an essential so ``can_cook_with`` would approve a dish the user
    # cannot make. Same rule, same reason, as ``merge_ingredient_alias``.
    ingredient_map: dict[str, bool] = dict.fromkeys(
        session.essential_ingredients, True
    )
    for ing in session.optional_ingredients:
        ingredient_map.setdefault(ing, False)
    all_ingredients = list(ingredient_map)
    committed_fridge = False
    committed_dish = False

    # One lock is held across the whole commit so that, on a dish-write failure,
    # the rollback undoes exactly this call's fridge additions with no concurrent
    # writer able to interleave (which a release-then-remove rollback could
    # otherwise clobber).
    #
    # ``dish_repo.lock`` and ``fridge_repo.lock`` are the *same object* — every
    # repository shares the one reentrant ``DataDirLock`` over the whole data
    # directory (see ``src/filelock.py``), so this nests one lock rather than
    # ordering two. Both are named anyway to say which repositories the critical
    # section covers, and so the code stays correct if the lock is ever split
    # per file. If it is split, this is the site that fixes the acquisition
    # order for the rest of the package.
    with dish_repo.lock, fridge_repo.lock:
        added_to_fridge: list[str] = []
        if commit_to_fridge and all_ingredients:
            fridge = fridge_repo.load()
            added_to_fridge = [ing for ing in all_ingredients if ing not in fridge]
            if added_to_fridge:
                for ing in added_to_fridge:
                    fridge[ing] = 1
                fridge_repo.save(fridge)
        committed_fridge = bool(commit_to_fridge and all_ingredients)

        try:
            # An empty selection would wipe an existing recipe to zero
            # ingredients (or create a meaningless empty dish), so never write
            # the catalog unless there is at least one ingredient to commit.
            if commit_to_dish and ingredient_map:
                dishes = dish_repo.load()
                existing = next(
                    (d for d in dishes if d.name == session.dish_name),
                    None,
                )
                if existing is not None:
                    # Already validated: every name came through
                    # Dish.normalize_ingredient and every flag through the
                    # engine's boolean check, so this assignment cannot
                    # reintroduce the shapes Dish.__post_init__ rejects.
                    existing.ingredients = ingredient_map
                else:
                    new_dish = Dish(name=session.dish_name)
                    for ing, essential in ingredient_map.items():
                        new_dish.add_ingredient(ing, essential)
                    dishes.append(new_dish)
                dish_repo.save(dishes)
                committed_dish = True
        except Exception:
            if added_to_fridge:
                try:
                    # ``remove_items`` is the delta rollback: it drops exactly
                    # these keys. The previous load-filter-save rewrote the whole
                    # inventory from a snapshot, which only stayed correct
                    # because it ran under this lock.
                    fridge_repo.remove_items(added_to_fridge)
                except Exception:
                    logger.exception("finalize_session fridge rollback failed")
            raise

    return committed_fridge, committed_dish, len(added_to_fridge)
