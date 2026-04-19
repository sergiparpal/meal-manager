"""LLM-facing response formatter for DII sessions.

Lives outside the engine so the agent UX (next_actions, instructions) can
evolve without touching state-mutation logic. The shape returned here is the
public contract consumed by ``tools.py`` and the integration tests.
"""

from .session import DIISession


def to_response(session: DIISession, *, recalculation_needed: bool = False) -> dict:
    """Build the public response dict for a session.

    Includes ``next_actions`` and a free-text ``instructions`` field so the
    LLM can drive the conversation without external tooling lookups.
    """
    is_finalized = session.finalized
    awaiting_recalc = session.pending_recalculation
    suggestion = session.current_suggestion
    has_suggestion = suggestion is not None
    queue_empty = len(session.hidden_queue) == 0 and not has_suggestion

    if is_finalized:
        next_actions: list[str] = []
        instructions = (
            f"Session finalized for '{session.dish_name}'. "
            "No more actions available."
        )
    elif awaiting_recalc:
        next_actions = [
            "init_ingredient_session",
            "dii_add_manual",
            "dii_remove_ingredient",
            "dii_clear_all",
            "finalize_ingredient_session",
        ]
        instructions = (
            f"The session needs recalculation. Call init_ingredient_session "
            f"again with a new ranked list for '{session.dish_name}' AND pass "
            f"this same session_id ('{session.session_id}') so the session is "
            f"reset in place. You can also add/remove ingredients manually or "
            f"finalize as-is."
        )
    elif suggestion is not None:
        ing_name = suggestion.get("ingredient", "?")
        is_ess = "essential" if suggestion.get("is_essential", True) else "optional"
        next_actions = [
            "dii_add_suggested",
            "dii_skip_suggested",
            "dii_remove_ingredient",
            "dii_add_manual",
            "finalize_ingredient_session",
        ]
        instructions = (
            f"Current suggestion: '{ing_name}' ({is_ess}). "
            f"Ask the user whether to add it, skip it, or type another ingredient."
        )
    elif queue_empty:
        next_actions = ["dii_add_manual", "finalize_ingredient_session"]
        instructions = (
            "No more suggestions. You can add ingredients manually or "
            "finalize the session."
        )
    else:
        next_actions = ["dii_add_manual", "finalize_ingredient_session"]
        instructions = "Unexpected state. Consider finalizing or restarting the session."

    return {
        "session_id": session.session_id,
        "dish_name": session.dish_name,
        "essential_ingredients": session.essential_ingredients,
        "optional_ingredients": session.optional_ingredients,
        "current_suggestion": session.current_suggestion,
        "queue_remaining": len(session.hidden_queue),
        "queue_exhausted": queue_empty,
        "recalculation_needed": recalculation_needed,
        "pending_recalculation": awaiting_recalc,
        "finalized": is_finalized,
        "next_actions": next_actions,
        "instructions": instructions,
    }
