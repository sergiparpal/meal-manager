"""Tool: list_cooking_history — read the cooking history event log."""

from ..repositories import HistoryDataError, history_repo
from ._common import normalize_dish_name, tool_handler

NAME = "list_cooking_history"

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100

DAMAGED_WARNING = (
    "The cooking history file (history.json) is damaged and could not be "
    "read, so this list is empty even if the user has cooked before. Tell "
    "the user. Registering a meal starts a new history and keeps the damaged "
    "file aside, as history.json.unreadable-<time>."
)

SCHEMA = {
    "description": (
        "List recorded cooking events, most recent first. This is the tool for "
        "'when did I last cook X?' and 'how often do I make Y?'. Each row has "
        "the dish name, the date it was cooked, when it was recorded, whether "
        "it was backfilled (recorded after the fact), and its status — "
        "'retracted' rows were taken back by the user and no longer count "
        "toward the recency cooldown, but are still on record. Cooks recorded "
        "since the plugin started noting it also list what they took from the "
        "fridge, as 'consumed'. If the history "
        "file is damaged, the list is empty and a 'warning' says so: tell the "
        "user, and don't say they have never cooked anything."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "only return events for this dish",
        },
        "include_retracted": {
            "type": "boolean",
            "description": "include events the user took back (default true)",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_LIMIT,
            "description": f"maximum rows to return (1-{MAX_LIMIT}, default {DEFAULT_LIMIT})",
        },
    },
    "required": [],
}


def _coerce_limit(value) -> int:
    if value is None:
        return DEFAULT_LIMIT
    # isinstance(True, int) is True in Python, so a bare bool check has to come
    # first or limit=true would silently become limit=1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    if not 1 <= value <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return value


def _coerce_include_retracted(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, bool):
        raise ValueError("include_retracted must be true or false")
    return value


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    limit = _coerce_limit(args.get("limit"))
    include_retracted = _coerce_include_retracted(args.get("include_retracted"))

    raw_name = args.get("dish_name")
    dish_filter = normalize_dish_name(raw_name) if raw_name is not None else None

    # strict=True on purpose: an unreadable file must not come back as a bare
    # empty list, which reads as "you have never cooked anything". A damaged
    # file says why in a warning, as list_dishes and list_fridge do; it used to
    # be an error, which logged a traceback for what is a data problem. A file
    # that cannot be opened at all is still an error.
    try:
        events = history_repo.load_events(strict=True)
    except HistoryDataError:
        if not history_repo.damaged():
            raise
        return {"events": [], "count": 0, "truncated": False, "warning": DAMAGED_WARNING}

    rows = []
    for event in reversed(events):
        if dish_filter is not None and event.dish_name != dish_filter:
            continue
        if not include_retracted and not event.active:
            continue
        row = event.to_dict()
        row["status"] = "active" if event.active else "retracted"
        rows.append(row)
        # Read one past the limit so "truncated" is a fact rather than a guess
        # when the log happens to hold exactly `limit` matching rows.
        if len(rows) > limit:
            break

    truncated = len(rows) > limit
    return {
        "events": rows[:limit],
        "count": min(len(rows), limit),
        "truncated": truncated,
    }
