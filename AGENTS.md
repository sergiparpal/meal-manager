# AGENTS.md

Repository guidance for agentic coding work in `meal-manager`.

Read `CLAUDE.md` before starting — it contains additional repository-specific guidance that should be consulted alongside this file and kept consistent with it.

This repo is a Hermes plugin that manages meals, fridge inventory, recipe data,
and Dynamic Ingredient Interface (DII) sessions. It uses only the Python
standard library and persists state in JSON files under `data/`.

## Fast Facts

- Python 3.12+.
- No third-party **runtime** dependencies. The plugin imports nothing outside the standard library, and nothing under `src/` or `__init__.py` may import a development tool. **Development/CI** tooling does exist and is pinned: `mypy==2.3.0`, `coverage==7.15.0`, and `ruff` (configured in `pyproject.toml`).
- No build step is configured. `pyproject.toml` holds tool configuration only — deliberately no `[build-system]` table and no `[project]` metadata, because this plugin is loaded by path as `hermes_plugins.meal_manager` rather than installed as a distribution.
- Lint is configured (`ruff`, narrow `F,B,I` selection) but is deliberately **not** a CI gate.
- Tests are plain Python scripts with assertions, not a pytest/unittest harness. Register every test function in `main()` via `run(test_fn)`, never as a bare call: `run` records a raised exception as a failure so one mistake cannot abort every test after it.
- CI (`.github/workflows/tests.yml`) runs on push to `main`, on pull requests, and on manual dispatch: a `tests` job (both scripts across Python 3.12/3.13/3.14), a `types` job (mypy), and a `coverage` job (`--fail-under=91`, a ratchet — raise it when coverage rises, never lower it to make a build pass). Any new job must be added to `ci-complete`'s `needs:` list; that job is the single required status check for the branch ruleset and it fails if a needed job is skipped, cancelled or failed. GitHub Actions are pinned to full commit SHAs with a trailing `# vX.Y.Z` comment. The `tests` job ends by verifying the suites left the checkout untouched: no `data/` under the repo root and a clean `git status`. Both are needed — `data/` is gitignored, so the porcelain check alone would not notice it appearing, and a fresh checkout has none, so its mere existence is the failure.
- Both suites also run before every commit via `.githooks/pre-commit`, which each clone activates once with `git config core.hooksPath .githooks`. Stdlib-only and quiet unless something fails; it deliberately skips `mypy` and `coverage`, which need an install a fresh checkout does not have. `git commit --no-verify` skips it and gets you nowhere, because `main` still requires `ci-complete`. A group of checks at the end of `test_unit.py` holds the hook and the workflow to what they claim — executable bit, both suites in both places, the declared Python floor present *in the matrix* (not merely somewhere in the file), every action pinned to a SHA, every job in `ci-complete`'s `needs:`. Every one of those failures is a silent one, which is why they are tested rather than trusted.
- Tools are auto-discovered: each module under `src/handlers/` exports `NAME`, `SCHEMA`, `HANDLER` and is picked up by `iter_tools()`. There is no central registry to keep in sync.
- Relative imports are required inside the package.
- Preserve the existing JSON data formats and tool names. Every format change on record follows the same courtesy — the loader accepts the old shape, migrates it in memory, and rewrites it on the next save, so no user ever runs a migration step:
  - `fridge.json`: flat array of names → `{name: count}` object (`null` = pantry staple, `0` = out of stock) → values may also be `{"count": n, "expires_on": "YYYY-MM-DD"}`. Entries without an expiry are still written as bare scalars.
  - `history.json`: `{dish: date}` → `{"schema_version": 2, "events": [...]}`, an append-only log. Legacy ids are derived with `uuid5` so re-migrating is idempotent.
  - `dishes.json`: dishes may carry `instructions`; the key is emitted only when set, so untouched catalogs do not churn.

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
- Raise `ValueError` (or `LookupError` for not-found cases) inside handlers — do not catch and reformat. The `@tool_handler(NAME, SCHEMA)` decorator from `src/handlers/_common.py` is mandatory on every public handler; it logs the exception via `logger.exception` and converts it into the unified `{"error": ...}` JSON envelope.
- Always pass `SCHEMA` to the decorator. It derives the allowed argument keys from `SCHEMA["properties"]`, so an unknown key is rejected instead of silently ignored. If a handler needs to read a key, that key belongs in the schema — the schema is the tool's public interface and should be honest. `extra_args={...}` exists for keys that must stay undocumented; comment why.
- The envelope message is sanitized by `_safe_error_message`. `ValueError` and `LookupError` pass through verbatim (handlers write them for the user); `OSError` and `json.JSONDecodeError` are replaced with fixed text because they carry filesystem paths and file contents; anything else becomes "An internal error occurred". `JSONDecodeError` subclasses `ValueError`, so it must be tested first. Full detail always still reaches the log.
- Handlers return plain Python objects (dict, list, str). The decorator handles `json.dumps(..., ensure_ascii=False)` for both success and error paths.
- Do not let stack traces escape a handler function — the decorator's outer `try/except` is the single guarantee of that.
- Internal helpers and engine-layer code may raise freely; the decorator at the boundary is the catch-all.

## Persistence

- Use `atomic_write_json` from `src/__init__.py` for every JSON write.
- Keep persisted file formats stable.
- Create parent directories lazily when needed, not at import time.
- Treat missing or malformed JSON files as empty state unless the caller needs an explicit error. "Malformed" includes valid JSON of the wrong *shape* — check `isinstance` before reading attributes off parsed data. A DII session backup containing an array raised `AttributeError` out of the orphan sweep and took down every DII tool, including the sweep that would have cleaned it up.
- Use UTF-8 for all file I/O.
- Do not store transient scratch data in `data/` unless the feature explicitly needs persistence.
- The data directory is injectable. `src/repositories/__init__.py:configure(data_dir)` and `src/dii/__init__.py:configure(session_dir)` redirect the singletons in place; the top-level `register(ctx, *, data_dir=None)` wires both. Tests should never hit the real `data/` — use a tmp dir via `_setup_tmp_data` / `configure`.

## Concurrency

- **All five file-backed stores share one lock object**: the `data_lock` singleton from `src/filelock.py`, an advisory `fcntl.flock` over `<data_dir>/.lock` that covers the whole data directory. It is assigned to the same attribute each repository already exposed (`self.lock` on the dish, fridge, alias, and tuning repos; `self._lock` on the history repo), so every existing call site is unchanged. It is reentrant, cross-process, and degrades to in-process-only where `fcntl` is unavailable.
- Hold the appropriate lock around load-modify-save sequences. A bare load-modify-save is a bug even when each half is individually atomic.
- **There is one lock, not five.** `dish_repo.lock`, `fridge_repo.lock`, `alias_repo.lock`, `tuning_repo.lock` and the history repository's private `_lock` are all the *same* reentrant `DataDirLock` object over the whole data directory. Nesting them is free and cannot deadlock, and the nominal `alias -> dish -> fridge` order documents intent only — it is not a live constraint. Keep writing it that way so the code survives any future move back to per-file locks (`src/dii/finalizer.py` is the site that would fix the order), but do not reason about deadlock risk that does not exist.
- **Multi-repository mutations take one explicit window.** Acquiring per repository still produces *independent* windows, so a handler that touches several must wrap its whole sequence in `with data_lock:` — `register_cooked_meal`, `merge_ingredient_alias` and `delete_dish` all do. Their compensation logic stays (an in-window step can still fail), but no other process can observe the half-applied state between steps. Normalize arguments *before* the window so it covers only the mutations.
- **Acquisition can time out.** `DataDirLock` polls a non-blocking `flock` up to `LOCK_TIMEOUT_SECONDS` and then raises `DataLockTimeout`. It is a `TimeoutError` (hence an `OSError`), so `_safe_error_message` tests for it *before* the generic `OSError` branch; anything added to that function must preserve that ordering.
- **Normalize arguments before acquiring any repository lock.** `_common.normalize_ingredient_name` reads the alias map, so normalizing inside a `dish_repo.lock` / `fridge_repo.lock` block inverts the documented order. Every handler normalizes first, then locks.
- DII sessions also use per-session locks plus a global lock for session maps. Always take a session lock through the `IngredientSessionStore.session_lock(session_id)` context manager, which reference-counts holders and prunes the entry itself. Never delete from `_locks` anywhere else: removing a lock does not release it, so a holder mid-critical-section and the next caller end up on different mutexes.
- Do not bypass the locking helpers when changing persistence behavior.
- Read-only suggestion queries are intentionally lock-free because they rely on atomic file replacement.

## Domain Rules

- Ingredient and dish names are normalized with `strip().lower()` semantics. The rule lives in the module-level `dish.clean_label(value, *, label)` and is applied via `Dish.normalize_name` / `Dish.normalize_ingredient` (and the `_common.normalize_*` wrappers that add the non-empty and length checks). It is public and lives outside the `Dish` class on purpose: the tool boundary needs the same rule, and `_common._normalize_label` reaching into a `Dish._clean` was the only place one layer touched another's private API.
- `Dish.__post_init__` enforces that `Dish.name` is always stored normalized, so downstream consumers compare `dish.name == name` directly — do not add defensive `.strip().lower()` at call sites.
- Cooking history keys are normalized to lowercase on load, so `history.json` comparisons are case-insensitive.
- `Dish.ingredients` maps ingredient name to `bool`.
- `True` means essential.
- `False` means optional.
- Dishes cooked fewer than 2 days ago are excluded from suggestions.
- Scoring never rewards essentials — they are a gate enforced by `can_cook_with`. The match term is the count of *optional* ingredients in stock, capped at `OPTIONAL_CAP`.
- The fridge stores portion counts: `None` = pantry staple (unlimited), `0` = known out of stock, `n > 0` = roughly `n` dishes' worth. `MAX_PORTION_COUNT` bounds the stored value, not merely the argument, so every path that produces a count (`add`'s running total, an alias merge) clamps to it.
- `register_cooked_meal` consumes one portion of each essential ingredient after recording the meal; staples are untouched and counts floor at 0 rather than being deleted. It accepts an optional ISO `date` for backdated cooks, which skip the learning update.
- Cooking history is an append-only event log, projected to one date per dish on read. `history_repo.load()` returns the latest `cooked_on` per dish with retracted events excluded, so backdating a forgotten meal cannot rewind a more recent cook — that is a property of the model now, not a flag on the write.
- Retraction and deletion are different operations. `delete_history_entry` retracts (the row survives, visible through `list_cooking_history`, and stops counting toward the projection); `register_cooked_meal`'s rollback path calls `delete_event` (hard delete, because a cook that failed halfway never happened); `delete_dish` retracts every event for the dish it removes.
- Ingredient aliases canonicalize input at the tool boundary only. `_common.normalize_ingredient_name` resolves them; `Dish.normalize_ingredient` deliberately does not, so the domain layer stays pure and I/O-free. Do not "fix" that asymmetry.
- On an alias merge, essential wins over optional in a recipe, and in the fridge a pantry staple wins over any count while two counts sum. The result is clamped to `MAX_PORTION_COUNT` on the way out, so a hand-edited out-of-band count is normalized rather than copied through.
- Alias resolution is the whole tool boundary's job, DII handlers included: `init_ingredient_session` builds sessions from canonical names and `dii_remove_ingredient` resolves before looking one up. Validating a name and then using the raw one leaves the DII path blind to aliases.
- Fridge entries may carry `expires_on`. Expired items stay available and are only flagged — the date is the user's estimate, not ground truth. The tool boundary is strict about the date format; the loader is forgiving and drops an unreadable date rather than the ingredient.
- `Dish.instructions` is optional free-form text capped at `MAX_INSTRUCTIONS_LENGTH`; blank normalizes to `None` so "cleared" and "never set" stay a single state.
- Colliding normalized names in a dict argument are rejected, not silently merged — the values can disagree. List arguments still collapse repeats. `Dish.from_dict` stays permissive so existing catalog rows keep loading.
- Quick shopping suggestions surface dishes missing at most `max_missing` essential ingredients (default 1), ranked by smallest basket (`still_missing`) first, then reach, then score. Reach-first alone promoted ingredients that unlock nothing on their own once `max_missing > 1`.
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

- `test_unit.py` covers pure logic in `src/dish.py`, `src/suggestion.py`, `src/shopping.py`, `src/tuning.py`, `src/history_event.py`, and the `normalize_*` / argument-validation / error-sanitization helpers in `src/handlers/_common.py`. It also covers the repository behavior that needs no tool boundary — fridge portion counts (including non-finite values and the expiry grammar), the history event log (projection, migration idempotence, retract vs delete, corruption), and the alias map — against a tmp path, not the real `data/`.
- `test_integration.py` is the end-to-end smoke test for all tool handlers.
- The integration script creates a throw-away tmp directory, points the repositories and DII session store at it via `configure()`, seeds deterministic fixtures, and removes the directory when finished. The real `data/` files are never touched.
- It intentionally exercises error cases and may print stack traces for expected failures.
- For a single integration scenario, call `_setup_tmp_data` / `_teardown_tmp_data` around one `test_*` function.
- Prefer the narrowest test that covers the changed code path.
- `.github/workflows/tests.yml` runs `test_unit.py` then `test_integration.py` on Python 3.12, 3.13, and 3.14 / `ubuntu-latest`. Both must exit zero, so a script that only *prints* a failure without asserting will pass CI — assert, don't print.

## Tool And Schema Notes

- Keep each handler module's `SCHEMA["description"]` in sync with the actual handler behavior — schema and code live side by side.
- Keep `plugin.yaml` aligned with the modules under `src/handlers/` (the auto-registration is the source of truth for what is registered, but `plugin.yaml` is read by Hermes for discovery).
- Keep `skill.md` aligned with DII behavior and user-facing interaction flow.
- Use `README.md` as the source of truth for the high-level project summary and examples.

## Editor Rules

- No `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` files are present in this repository snapshot.
- `CLAUDE.md` contains additional repo-specific guidance and must be read before starting any work alongside this file; the two should stay consistent.
