"""meal_manager – Hermes plugin entry point."""

import logging
from pathlib import Path

from .src.dii import configure as _configure_dii
from .src.handlers import iter_tools
from .src.repositories import configure as _configure_repos

# Library convention: install a NullHandler on the package root so callers
# without logging configured don't see "No handlers could be found" warnings.
# Submodules just call ``logging.getLogger(__name__)`` and inherit this.
logging.getLogger(__name__).addHandler(logging.NullHandler())


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

    for name, schema, handler in iter_tools():
        ctx.register_tool(name, "meal_manager", schema, handler)

    skill_path = Path(__file__).parent / "skill.md"
    ctx.inject_message(skill_path.read_text(encoding="utf-8"))
