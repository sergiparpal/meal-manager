"""Tool: register_cooked_meal — record cook event and consume essentials."""

import logging
from datetime import date

from .. import data_lock, tuning
from ..repositories import dish_repo, fridge_repo, history_repo, tuning_repo
from ._common import (
    days_since_last_cook,
    normalize_dish_name,
    require_arg,
    tool_handler,
)

logger = logging.getLogger(__name__)

NAME = "register_cooked_meal"


SCHEMA = {
    "description": (
        "Register that a specific dish was cooked. Records it in the cooking "
        "history so the suggestion engine avoids recommending it again too "
        "soon. Also consumes one portion of each essential ingredient from the "
        "fridge (pantry staples are left untouched). Defaults to today; pass "
        "'date' to record a past meal."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name from the catalog",
        },
        "date": {
            "type": "string",
            "description": (
                "ISO date (YYYY-MM-DD) the meal was cooked. Defaults to today. "
                "Use when the user is recording a past meal."
            ),
        },
    },
    "required": ["dish_name"],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    raw_name = require_arg(args, "dish_name")
    name = normalize_dish_name(raw_name)

    # Validate the date before entering the lock window — it needs no stored
    # state, and a rejected argument should not queue behind another process.
    raw_date = args.get("date")
    if raw_date is None:
        cooked_on = date.today()
        backdated = False
    else:
        if not isinstance(raw_date, str):
            raise ValueError("date must be an ISO string (YYYY-MM-DD)")
        try:
            cooked_on = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError(f"invalid date {raw_date!r}: {exc}") from exc
        if cooked_on > date.today():
            raise ValueError("date cannot be in the future")
        backdated = cooked_on != date.today()
    cooked_iso = cooked_on.isoformat()

    # This handler touches four repositories, and the compensation below only
    # makes sense if nothing can observe the state between them. One window
    # over the whole data directory gives that: the lock is a single reentrant
    # object shared by every repository, so the nested acquisitions inside
    # ``append_event`` / ``consume`` / the tuning block cost nothing. Before,
    # this ran as four independent windows and another process could see a cook
    # recorded whose ingredients had not been consumed yet.
    with data_lock:
        dishes = dish_repo.load()
        dish = next((d for d in dishes if d.name == name), None)
        if dish is None:
            raise LookupError(f"'{raw_name}' is not in the recipe catalog.")

        # Snapshot the decision state as it was at the moment the user chose to
        # cook — before history and fridge are mutated below. The learning
        # update at the end replays the ranking against this snapshot.
        fridge_snapshot = fridge_repo.load_set()
        days_snapshot = days_since_last_cook()

        # Read the projection before appending: this is what the response
        # compares against to tell the user whether their cooldown moved.
        projected_before = history_repo.load().get(name)
        event = history_repo.append_event(name, cooked_iso, backfilled=backdated)
        superseded = projected_before is not None and (
            date.fromisoformat(projected_before) > cooked_on
        )

        essentials = [
            ing for ing, is_essential in dish.ingredients.items() if is_essential
        ]

        try:
            consumed = fridge_repo.consume(essentials)
        except Exception:
            try:
                # Hard delete, not a retraction: a cook that was rolled back
                # never happened, so it must leave no trace in the log.
                history_repo.delete_event(event.id)
            except Exception:
                logger.exception("register_cooked_meal rollback failed")
            raise

        # Best-effort online weight tuning. This must never fail or roll back
        # the cook registration: any error here is logged and swallowed.
        #
        # Skipped for backdated cooks: the snapshot above reflects today's
        # fridge and history, not the state at the time the meal was actually
        # cooked, so replaying it would teach the learner from a decision that
        # never happened.
        if not backdated:
            try:
                state = tuning_repo.load()
                rewards = tuning.compute_rewards(
                    name, dishes, fridge_snapshot, days_snapshot, state["candidates"]
                )
                if rewards is not None:
                    state = tuning.apply_update(state, rewards)
                    state = tuning.select_deployed(state)
                    tuning_repo.save(state)
            except Exception:
                logger.exception("weight tuning update failed (non-critical)")

    if consumed:
        parts = []
        for ing, before in sorted(consumed.items()):
            after = max(0, before - 1)
            parts.append(f"{ing} ({before} -> {after})")
        removed_msg = f" Consumed from fridge: {', '.join(parts)}."
    else:
        removed_msg = ""

    if superseded:
        # The event was still recorded — the log keeps everything. What is
        # unchanged is the projection, and with it the cooldown.
        history_msg = (
            f" Cooking history still shows {projected_before}, which is more recent,"
            " so the recency cooldown is unchanged."
        )
    else:
        history_msg = ""
    return (
        f"Registered '{dish.name}' as cooked on {cooked_iso}.{removed_msg}{history_msg}"
    )
