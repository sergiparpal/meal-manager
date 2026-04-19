# AGENTS.md

Repository guidance for agentic coding work in `meal-manager`.

Read `CLAUDE.md` before starting — it contains additional repository-specific guidance that should be consulted alongside this file and kept consistent with it.

This repo is a Hermes plugin that manages meals, fridge inventory, recipe data,
and Dynamic Ingredient Interface (DII) sessions. It uses only the Python
standard library and persists state in JSON files under `data/`.

## Fast Facts

- Python 3.12+.
- No third-party dependencies.
- No build step is configured.
- No lint step is configured.
- Tests are plain Python scripts with assertions, not a pytest/unittest harness.
- Tools are auto-discovered: each module under `src/handlers/` exports `NAME`, `SCHEMA`, `HANDLER` and is picked up by `iter_tools()`. There is no central registry to keep in sync.
- Relative imports are required inside the package.
- Preserve the existing JSON data formats and tool names.

## Core Commands

- Run the integration smoke test:

```bash
python3 test_integration.py
```

- Run the unit test script for domain logic:

```bash
python3 test_unit.py
```

- Run a single unit test function directly:

```bash
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); m = importlib.import_module('.test_unit', pathlib.Path('.').resolve().name); m.test_calculate_score_basic()"
```

- Run a single integration-style test function with explicit setup and teardown:

```bash
python3 - <<'PY'
import importlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path('.').resolve().parent))
m = importlib.import_module('.test_integration', pathlib.Path('.').resolve().name)
m._setup_tmp_data()
try:
    m.test_list_fridge()
finally:
    m._teardown_tmp_data()
PY
```

`_setup_tmp_data` creates a `tempfile.mkdtemp()` directory, points the repository and DII singletons at it via `configure()`, and seeds deterministic JSON fixtures. `_teardown_tmp_data` deletes the directory. The live `data/` under the repo root is never read or written. `_backup` / `_restore` still exist as compatibility aliases for older recipes.

- Run one tool interactively:

```bash
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); m = importlib.import_module('.src.handlers.get_meal_suggestions', pathlib.Path('.').resolve().name); print(m.HANDLER({}))"
```

- Prefer the smallest relevant script or direct function call instead of the
  full integration suite when you only changed a narrow area.

## Imports

- Use relative imports inside the package, for example `from .src.repositories import dish_repo`.
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
- Prefix private helpers with `_`. Modules under `src/handlers/` that start with `_` (e.g. `_common.py`) are skipped by the auto-discovery walker.
- Keep tool handler module names equal to the registered `NAME` constant (e.g. `src/handlers/add_dish.py` exports `NAME = "add_dish"`).
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
- Raise `ValueError` (or `LookupError` for not-found cases) inside handlers — do not catch and reformat. The `@tool_handler(NAME)` decorator from `src/handlers/_common.py` is mandatory on every public handler; it logs the exception via `logger.exception` and converts it into the unified `{"error": str(exc)}` JSON envelope.
- Handlers return plain Python objects (dict, list, str). The decorator handles `json.dumps(..., ensure_ascii=False)` for both success and error paths.
- Do not let stack traces escape a handler function — the decorator's outer `try/except` is the single guarantee of that.
- Internal helpers and engine-layer code may raise freely; the decorator at the boundary is the catch-all.

## Persistence

- Use `atomic_write_json` from `src/__init__.py` for every JSON write.
- Keep persisted file formats stable.
- Create parent directories lazily when needed, not at import time.
- Treat missing or malformed JSON files as empty state unless the caller needs an explicit error.
- Use UTF-8 for all file I/O.
- Do not store transient scratch data in `data/` unless the feature explicitly needs persistence.
- The data directory is injectable. `src/repositories/__init__.py:configure(data_dir)` and `src/dii/__init__.py:configure(session_dir)` redirect the singletons in place; the top-level `register(ctx, *, data_dir=None)` wires both. Tests should never hit the real `data/` — use a tmp dir via `_setup_tmp_data` / `configure`.

## Concurrency

- File-backed stores use module-level `threading.Lock` instances.
- Hold the appropriate lock around load-modify-save sequences.
- DII sessions also use per-session locks plus a global lock for session maps.
- Do not bypass the locking helpers when changing persistence behavior.
- Read-only suggestion queries are intentionally lock-free because they rely on atomic file replacement.

## Domain Rules

- Ingredient and dish names are normalized with `strip().lower()` semantics. The normalization rule lives in `Dish._clean(value, *, label)` and is applied via `Dish.normalize_name` / `Dish.normalize_ingredient` (and the `_common.normalize_*` wrappers that add length validation).
- `Dish.__post_init__` enforces that `Dish.name` is always stored normalized, so downstream consumers compare `dish.name == name` directly — do not add defensive `.strip().lower()` at call sites.
- Cooking history keys are normalized to lowercase on load, so `history.json` comparisons are case-insensitive.
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
- Do not rename persisted keys or tool `NAME` constants without updating every consumer (handler module name, `plugin.yaml`, `skill.md`, tests).
- Keep top-level `__init__.py` minimal — it should only walk `src/handlers/` and inject the skill. Tool definitions belong in their own modules under `src/handlers/`.
- Do not edit live `data/` files unless the task explicitly requires it.
- If you touch persistence or DII, run both test scripts before finishing.
- If you touch a single pure function, the targeted unit test is usually enough.
- Leave unrelated worktree changes alone; do not revert or overwrite them.

## Testing

- `test_unit.py` covers pure logic in `src/dish.py`, `src/suggestion.py`, `src/shopping.py`, and `_normalize_ingredients`.
- `test_integration.py` is the end-to-end smoke test for all tool handlers.
- The integration script creates a throw-away tmp directory, points the repositories and DII session store at it via `configure()`, seeds deterministic fixtures, and removes the directory when finished. The real `data/` files are never touched.
- It intentionally exercises error cases and may print stack traces for expected failures.
- For a single integration scenario, call `_setup_tmp_data` / `_teardown_tmp_data` around one `test_*` function.
- Prefer the narrowest test that covers the changed code path.

## Tool And Schema Notes

- Keep each handler module's `SCHEMA["description"]` in sync with the actual handler behavior — schema and code live side by side.
- Keep `plugin.yaml` aligned with the modules under `src/handlers/` (the auto-registration is the source of truth for what is registered, but `plugin.yaml` is read by Hermes for discovery).
- Keep `skill.md` aligned with DII behavior and user-facing interaction flow.
- Use `README.md` as the source of truth for the high-level project summary and examples.

## Editor Rules

- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` files are present in this repository snapshot.
- `CLAUDE.md` contains additional repo-specific guidance and must be read before starting any work alongside this file; the two should stay consistent.
