"""meal_manager – Hermes plugin entry point."""

import logging
from pathlib import Path

from .src.dii import configure as _configure_dii
from .src.handlers import iter_tools
from .src.repositories import configure as _configure_repos

# Library convention: install a NullHandler on the package root so callers
# without logging configured don't see "No handlers could be found" warnings.
# Submodules just call ``logging.getLogger(__name__)`` and inherit this.
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Hermes namespaces plugin skills, so the agent sees ``meal_manager:assistant``.
# The description is all the system prompt's skill index shows for it, and
# recent Hermes releases clip it to 60 characters.
SKILL_NAME = "assistant"
SKILL_DESCRIPTION = "What to cook, recipes, fridge and grocery shopping"

# Hermes v0.22.5 files plugin skills under a "plugin" category, so some models
# ask for ``plugin:meal_manager:assistant``, get "not found" and answer without
# the skill. The agent reads a tool's description before calling it, so every
# description ends by naming the skill exactly.
SKILL_POINTER = (
    " Usage guidance for all meal_manager tools is in the skill "
    f"meal_manager:{SKILL_NAME}: if it isn't loaded yet in this conversation, "
    "load it first, by exactly that name (no plugin: prefix)."
)


def register(ctx, *, data_dir: Path | str | None = None):
    """Register all meal_manager tools and the skill with the Hermes context.

    Parameters
    ----------
    ctx:
        Hermes plugin context.
    data_dir:
        Optional override for the plugin's persistence root. When provided,
        repositories read/write under ``data_dir`` and DII session backups
        live under ``data_dir/sessions``. When omitted, the plugin keeps
        using ``<plugin_root>/data/`` (the default baked into the
        repository and DII packages).
    """
    if data_dir is not None:
        data_dir = Path(data_dir)
        _configure_repos(data_dir)
        _configure_dii(data_dir / "sessions")

    # Not ``ctx.inject_message``: it queues a message into a live session, and
    # during plugin discovery there is none, so it returned False and the
    # skill never reached the model.
    register_skill = getattr(ctx, "register_skill", None)

    for name, schema, handler in iter_tools():
        # Point at the skill only where the host can register it, and on a
        # copy, so the handler module's SCHEMA keeps its own description.
        if register_skill is not None:
            schema = {**schema, "description": schema["description"] + SKILL_POINTER}
        ctx.register_tool(name, "meal_manager", schema, handler)

    if register_skill is None:
        logger.warning(
            "This Hermes version has no ctx.register_skill; "
            "skill.md was not registered"
        )
        return
    register_skill(
        SKILL_NAME,
        Path(__file__).parent / "skill.md",
        description=SKILL_DESCRIPTION,
    )
