# AGENTS.md

Repository guidance for agentic coding work in `meal-manager`.

This repo is a Hermes plugin that manages meals, fridge inventory, recipe data,
and Dynamic Ingredient Interface (DII) sessions. It uses only the Python
standard library and persists state in JSON files under `data/`.

## Fast Facts

- Python 3.12+.
- No third-party dependencies.
- No build step is configured.
- No lint step is configured.
- Tests are plain Python scripts, not pytest/unittest cases.
- Keep the plugin entry point, schemas, handlers, and skill file aligned.
- Relative imports are required inside the package.
- Preserve the existing JSON data formats and tool names.

## Core Commands

- Run the integration smoke test:

```bash
python3 test_hermes.py
```

- Run the unit test script for domain logic:

```bash
python3 test_unit.py
```

- Run a single unit test function directly:

```bash
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); m = importlib.import_module('.test_unit', pathlib.Path('.').resolve().name); m.test_calculate_score_basic()"
```

- Run a single integration-style test function with explicit setup and restore:

```bash
python3 - <<'PY'
import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path('.').resolve().parent))
m = importlib.import_module('.test_hermes', pathlib.Path('.').resolve().name)
m._backup()
m._seed()
try:
    m.test_list_fridge()
finally:
    m._restore()
PY
```

- Run one tool interactively:

```bash
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); t = importlib.import_module('.tools', pathlib.Path('.').resolve().name); print(t.get_meal_suggestions({}))"
```

- Prefer the smallest relevant script or direct function call instead of the
  full integration suite when you only changed a narrow area.

## Imports

- Use relative imports inside the package, for example `from .src.storage import load_dishes`.
- Do not switch to absolute `src.*` imports; Hermes loads the plugin as a
  package, and relative imports are the safe form.
- Keep standard library imports first, then local imports.
- Avoid import cycles; if a helper is shared, move it to a lower-level module.

## Formatting

- Follow the existing Python style rather than introducing a new formatter.
- Use 4-space indentation.
- Prefer double quotes for strings.
- Keep lines reasonably short and wrap long expressions or dict literals.
- Use blank lines to separate logical sections.
- Long modules often use `# ---------------------------------------------------------------------------`
  section dividers; keep that pattern when it helps readability.
- Keep comments sparse and only add them for non-obvious behavior.

## Naming

- Use `snake_case` for functions, variables, and module-level helpers.
- Use `UpperCamelCase` for classes and dataclasses.
- Use `UPPER_SNAKE_CASE` for constants.
- Prefix private helpers with `_`.
- Keep tool handler names stable and descriptive, matching the schema names.
- Preserve public API names unless there is a concrete reason to change them.

## Types

- Type hints are used selectively, not everywhere.
- When adding or changing public functions, add hints if they clarify intent.
- Prefer concrete collection types like `list[str]`, `dict[str, int]`, and
  `set[str]` where the type matters.
- Keep annotations simple; avoid heavy type machinery unless needed.
- Maintain compatibility with Python 3.12 syntax.

## Error Handling

- Validate user-supplied input at the tool boundary.
- Raise `ValueError` for invalid lower-level arguments when that keeps the logic clear.
- Public tool handlers should catch exceptions, log them with `logger.exception(...)`, and return a JSON error payload.
- Do not let stack traces escape a handler function.
- Return JSON strings from tool handlers, not raw Python objects.
- Use `ensure_ascii=False` when serializing user-facing JSON so accented text stays readable.

## Persistence

- Use `atomic_write_json` from `src/__init__.py` for every JSON write.
- Keep persisted file formats stable.
- Create parent directories lazily when needed, not at import time.
- Treat missing or malformed JSON files as empty state unless the caller needs an explicit error.
- Use UTF-8 for all file I/O.
- Do not store transient scratch data in `data/` unless the feature explicitly needs persistence.

## Concurrency

- File-backed stores use module-level `threading.Lock` instances.
- Hold the appropriate lock around load-modify-save sequences.
- DII sessions also use per-session locks plus a global lock for session maps.
- Do not bypass the locking helpers when changing persistence behavior.
- Read-only suggestion queries are intentionally lock-free because they rely on atomic file replacement.

## Domain Rules

- Ingredient and dish names are normalized with `strip().lower()` semantics.
- `Dish.ingredients` maps ingredient name to `bool`.
- `True` means essential.
- `False` means optional.
- Dishes cooked fewer than 2 days ago are excluded from suggestions.
- `register_cooked_meal` removes essential ingredients from the fridge after recording the meal.
- Quick shopping suggestions only surface dishes missing exactly one essential ingredient.
- DII sessions reveal suggestions one at a time through the probability funnel.
- Removing an essential ingredient in a DII session should signal that recalculation is needed.

## Editing Rules

- Make the smallest correct change.
- Avoid broad refactors unrelated to the task.
- Do not rename persisted keys, tool names, or schema constants without updating every consumer.
- Keep `__init__.py` as the registration layer and `tools.py` as the handler layer.
- Do not edit live `data/` files unless the task explicitly requires it.
- If you touch persistence or DII, run both test scripts before finishing.
- If you touch a single pure function, the targeted unit test is usually enough.
- Leave unrelated worktree changes alone; do not revert or overwrite them.

## Testing

- `test_unit.py` covers pure logic in `src/dish.py`, `src/suggestion.py`, `src/shopping.py`, and `_normalize_ingredients`.
- `test_hermes.py` is the end-to-end smoke test for all tool handlers.
- The integration script backs up `data/`, seeds deterministic fixtures, and restores the original files afterward.
- It intentionally exercises error cases and may print stack traces for expected failures.
- For a single integration scenario, call the helper setup functions around one `test_*` function.
- Prefer the narrowest test that covers the changed code path.

## Tool And Schema Notes

- Keep `schemas.py` descriptions in sync with handler behavior.
- Keep `plugin.yaml` aligned with the registered tool list.
- Keep `skill.md` aligned with DII behavior and user-facing interaction flow.
- Use `README.md` as the source of truth for the high-level project summary and examples.

## Editor Rules

- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` files are present in this repository snapshot.
- `CLAUDE.md` contains additional repo-specific guidance and should stay consistent with this file.
