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
) -> tuple[bool, bool]:
    """Apply commit policy and return ``(committed_fridge, committed_dish)``.

    On a dish-write failure, rolls back only the items this call appended to
    the fridge — never clobbers concurrent writers.
    """
    all_ingredients = session.essential_ingredients + session.optional_ingredients
    committed_fridge = False
    committed_dish = False
    added_to_fridge: list[str] = []

    if commit_to_fridge and all_ingredients:
        with fridge_repo.lock:
            fridge = fridge_repo.load()
            added_to_fridge = [ing for ing in all_ingredients if ing not in fridge]
            if added_to_fridge:
                fridge.extend(added_to_fridge)
                fridge_repo.save(fridge)
            committed_fridge = bool(added_to_fridge)

    try:
        if commit_to_dish:
            with dish_repo.lock:
                dishes = dish_repo.load()
                ingredient_map: dict[str, bool] = (
                    {ing: True for ing in session.essential_ingredients}
                    | {ing: False for ing in session.optional_ingredients}
                )

                existing = next(
                    (d for d in dishes if d.name == session.dish_name),
                    None,
                )
                if existing is not None:
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
                fridge_repo.remove_items(added_to_fridge)
            except Exception:
                logger.exception("finalize_session fridge rollback failed")
        raise

    return committed_fridge, committed_dish
