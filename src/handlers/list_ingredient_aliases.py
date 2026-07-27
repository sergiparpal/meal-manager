"""Tool: list_ingredient_aliases — show recorded ingredient alias mappings."""

from ..repositories import alias_repo
from ._common import tool_handler

NAME = "list_ingredient_aliases"

SCHEMA = {
    "description": (
        "List the ingredient aliases recorded by merge_ingredient_alias, as "
        "{alias: canonical_name}. Use when the user asks which spellings have "
        "been merged, or to check whether a name is already canonicalized "
        "before merging it again."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}


@tool_handler(NAME, SCHEMA)
def HANDLER(args: dict, **kwargs):
    aliases = alias_repo.load()
    return {
        "aliases": {alias: aliases[alias] for alias in sorted(aliases)},
        "count": len(aliases),
    }
