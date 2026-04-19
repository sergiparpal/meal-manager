"""Handler package — one module per registered tool.

Each public submodule (i.e. anything that does not start with ``_``) exports
three module-level attributes:

    NAME    : str           — tool name passed to ctx.register_tool
    SCHEMA  : dict          — JSON-schema dict (with top-level ``description``)
    HANDLER : Callable      — handler function ``(args: dict, **kwargs) -> str``

``iter_tools()`` walks the package via ``pkgutil.iter_modules`` and yields
``(NAME, SCHEMA, HANDLER)`` for each module that satisfies that contract.
This eliminates the need for a hand-maintained registry — adding a new tool
is just dropping a new module into this directory.
"""

import importlib
import pkgutil
from typing import Callable, Iterator

Tool = tuple[str, dict, Callable[..., str]]


def iter_tools() -> Iterator[Tool]:
    """Yield ``(NAME, SCHEMA, HANDLER)`` for every handler module.

    Iteration order is alphabetical by module name, which keeps registration
    deterministic across runs.
    """
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f".{info.name}", __name__)
        try:
            name = module.NAME
            schema = module.SCHEMA
            handler = module.HANDLER
        except AttributeError:
            continue
        yield name, schema, handler


__all__ = ["iter_tools", "Tool"]
