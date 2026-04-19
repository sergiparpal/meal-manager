"""Pure operations on DIISession state.

Each function takes a session, mutates it in place, and returns small status
tuples to the caller. No I/O, no locking — those concerns live in the store
and the public API layer.
"""

from typing import cast

from ..dish import Dish
from .session import DIISession, now_iso


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _touch(session: DIISession) -> None:
    session.last_activity = now_iso()


def _advance_queue(session: DIISession) -> None:
    """Pop the next item from hidden_queue into current_suggestion."""
    if session.hidden_queue:
        session.current_suggestion = session.hidden_queue.pop(0)
    else:
        session.current_suggestion = None


def _select(session: DIISession, name: str, *, essential: bool) -> None:
    """Place ``name`` in the chosen list, removing it from the other if present.

    The essential and optional lists are mutually exclusive. This helper is
    the single source of that invariant — every code path that adds an
    ingredient to a selected list must go through here.
    """
    target, other = (
        (session.essential_ingredients, session.optional_ingredients)
        if essential
        else (session.optional_ingredients, session.essential_ingredients)
    )
    if name in other:
        other.remove(name)
    if name not in target:
        target.append(name)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def build_session(
    session_id: str,
    dish_name: str,
    ranked_ingredients: list[dict],
    pre_select_top_n: int = 3,
) -> DIISession:
    """Construct and pre-populate a fresh DIISession from raw inputs.

    The top *pre_select_top_n* ingredients are auto-selected into the
    essential/optional lists. The next one becomes ``current_suggestion`` and
    the rest go into ``hidden_queue``.
    """
    _validate_pre_select(pre_select_top_n)
    cleaned = _normalize_ranked(ranked_ingredients)
    session = _new_session(session_id, dish_name)
    _apply_pre_selection(session, cleaned[:pre_select_top_n])
    _seed_queue(session, cleaned[pre_select_top_n:])
    return session


def _validate_pre_select(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("pre_select_top_n must be an integer")
    if value < 0:
        raise ValueError("pre_select_top_n must be >= 0")


def _new_session(session_id: str, dish_name: str) -> DIISession:
    normalized = Dish.normalize_name(dish_name)
    if not normalized:
        raise ValueError("Dish name cannot be empty")
    now = now_iso()
    return DIISession(
        session_id=session_id,
        dish_name=normalized,
        created_at=now,
        last_activity=now,
    )


def _normalize_ranked(ranked_ingredients: list[dict]) -> list[dict]:
    """Validate, normalize, and dedupe a ranked-ingredients list.

    Raises ``ValueError`` on shape errors; silently drops duplicates by
    normalized ingredient name (first occurrence wins).
    """
    if not isinstance(ranked_ingredients, list):
        raise ValueError("ranked_ingredients must be a list")

    seen: set[str] = set()
    cleaned: list[dict] = []
    for item in ranked_ingredients:
        normalized = _normalize_ranked_item(item)
        if normalized["ingredient"] in seen:
            continue
        seen.add(normalized["ingredient"])
        cleaned.append(normalized)
    return cleaned


def _normalize_ranked_item(item: object) -> dict:
    if not isinstance(item, dict):
        raise ValueError("ranked_ingredients must contain objects")
    if "ingredient" not in item:
        raise ValueError("ranked_ingredients items must include ingredient")
    item_dict = cast(dict[str, object], item)

    name = Dish.normalize_ingredient(item_dict["ingredient"])
    if not name:
        raise ValueError("ingredient name cannot be empty")
    item_dict["ingredient"] = name

    is_essential = item_dict.get("is_essential", True)
    if not isinstance(is_essential, bool):
        raise ValueError("is_essential must be a boolean")
    item_dict["is_essential"] = is_essential

    return item_dict


def _apply_pre_selection(session: DIISession, pre_selected: list[dict]) -> None:
    for item in pre_selected:
        _select(session, item["ingredient"], essential=item.get("is_essential", True))


def _seed_queue(session: DIISession, remaining: list[dict]) -> None:
    session.hidden_queue = remaining[1:]
    session.current_suggestion = remaining[0] if remaining else None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def add_suggested(session: DIISession) -> bool:
    """Accept the current suggestion. Returns False if there is nothing shown."""
    if session.current_suggestion is None:
        return False
    item = session.current_suggestion
    _select(session, item["ingredient"], essential=item.get("is_essential", True))
    _advance_queue(session)
    _touch(session)
    return True


def skip_suggested(session: DIISession) -> None:
    _advance_queue(session)
    _touch(session)


def remove(session: DIISession, ingredient: str) -> tuple[bool, bool]:
    """Remove an ingredient. Returns ``(changed, recalculation_needed)``."""
    name = Dish.normalize_ingredient(ingredient)
    if not name:
        raise ValueError("Ingredient name cannot be empty")
    if name in session.essential_ingredients:
        session.essential_ingredients.remove(name)
        session.pending_recalculation = True
        _touch(session)
        return True, True
    if name in session.optional_ingredients:
        session.optional_ingredients.remove(name)
        _touch(session)
        return True, False
    return False, False


def add_manual(
    session: DIISession,
    ingredient: str,
    is_essential: bool = True,
) -> tuple[bool, str | None]:
    """Add a user-typed ingredient. Returns ``(changed, error_message)``.

    Empty input returns ``(False, "...")`` rather than raising so the public
    API can attach the message to a no-change response.
    """
    if not isinstance(is_essential, bool):
        raise ValueError("is_essential must be a boolean")
    name = Dish.normalize_ingredient(ingredient)
    if not name:
        return False, "Ingredient name cannot be empty"

    _select(session, name, essential=is_essential)

    # Drop the same name from the funnel so it isn't suggested again.
    session.hidden_queue = [
        item for item in session.hidden_queue
        if item["ingredient"] != name
    ]
    if (
        session.current_suggestion is not None
        and session.current_suggestion["ingredient"] == name
    ):
        _advance_queue(session)

    _touch(session)
    return True, None


def clear_all(session: DIISession) -> None:
    session.essential_ingredients.clear()
    session.optional_ingredients.clear()
    session.pending_recalculation = True
    _touch(session)


def mark_finalized(session: DIISession) -> None:
    session.finalized = True
    session.pending_recalculation = False
    _touch(session)
