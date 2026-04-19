# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `AGENTS.md` before starting — it contains additional repository-specific guidance for agentic coding work that should be consulted alongside this file.

## Project Overview

A meal planning and fridge inventory manager structured as a Hermes plugin. The entry point is `__init__.py:register(ctx)`, which auto-discovers the nineteen tool handlers under `src/handlers/` and installs the skill. All state is persisted in JSON files under `data/`.

Python 3.12+, no external dependencies (stdlib only).

## Commands

```bash
# Run the unit test script for pure domain logic
python3 test_unit.py

# Run the integration smoke test
python3 test_integration.py

# Run a single tool interactively (parent dir must be on sys.path for relative imports)
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); m = importlib.import_module('.src.handlers.get_meal_suggestions', pathlib.Path('.').resolve().name); print(m.HANDLER({}))"
```

There is no build step or linter. `test_integration.py` and `test_unit.py` are plain Python scripts with assertions, not a pytest/unittest harness.

## Architecture

### Plugin wiring layer (top-level files)

- **`__init__.py`** — `register(ctx, *, data_dir=None)` walks `src/handlers/` via `iter_tools()` and registers each `(NAME, SCHEMA, HANDLER)` triple, then injects `skill.md` into the Hermes context. There is no central handler list to maintain — adding a new tool is a matter of dropping a new module into `src/handlers/`. If the host supplies a `data_dir`, `register` calls `src.repositories.configure(data_dir)` and `src.dii.configure(data_dir / "sessions")` so all persistence is redirected to that location.
- **`plugin.yaml`** — Declares the plugin name (`meal_manager`) and lists provided tools (kept manually in sync with the modules under `src/handlers/`).
- **`skill.md`** — LLM-facing instructions for when/how to invoke each tool. The DII section instructs the agent to drive ingredient selection via plain text conversation, interpreting free-text user responses to call the appropriate DII tool.

### Handlers (`src/handlers/`)

One module per registered tool. Each public submodule (anything not prefixed with `_`) exports three module-level attributes:

- `NAME: str` — tool name passed to `ctx.register_tool`.
- `SCHEMA: dict` — JSON schema with a top-level `description`.
- `HANDLER: Callable[[dict, ...], str]` — handler function. Decorated with `@tool_handler(NAME)` from `_common.py`, the body returns a plain Python object (dict, list, str, …) and raises on validation/business errors. The decorator centralizes JSON serialization (`json.dumps(..., ensure_ascii=False)`) and error handling: any exception is logged via `logger.exception` and surfaced as the unified `{"error": str(exc)}` envelope.

`src/handlers/__init__.py:iter_tools()` walks the package via `pkgutil.iter_modules`, importing each non-underscore module and yielding its `(NAME, SCHEMA, HANDLER)` triple in alphabetical order. Modules starting with `_` (like `_common.py`) are skipped.

- **`_common.py`** — Shared helpers: `tool_handler` decorator (the canonical wrapper for every handler), `err()` legacy shim, `normalize_dish_name`, `normalize_ingredient_name`, `normalize_ingredients`, `days_since_last_cook`, plus the input-limit constants (`MAX_NAME_LEN`, `MAX_INGREDIENTS`, `MAX_BATCH_SIZE`, `MAX_FRIDGE_UPDATE`). Both `normalize_dish_name` and `normalize_ingredient_name` delegate to a single `_normalize_label(value, *, label)` helper so the rules (non-empty, max length) live in one place.

### Domain modules (`src/`)

- **`dish.py`** — `Dish` dataclass: recipe model with `ingredients` dict mapping name → `bool` (True = essential, False = optional). `__post_init__` enforces the invariant that `Dish.name` is always stored stripped and lowercased — every construction path (direct, `from_dict`, dataclass `replace`) goes through it, so consumers can compare `dish.name` by equality without re-normalizing. `can_cook_with()` checks if all essential ingredients are available. Serialization uses English keys (`name`, `ingredients`). Legacy data files may contain `prep_time` which is silently ignored on load.
- **`suggestion.py`** — Scoring engine. `calculate_score()` blends ingredient match (60%) with recency (40%). Within ingredient match, essentials count 80% and optionals 20%. Recency is normalized over 14 days. Dishes cooked < 2 days ago score 0. `suggest_dishes()` filters to cookable dishes and ranks by score.
- **`shopping.py`** — `suggest_quick_shopping()` finds dishes missing exactly one essential ingredient, simulates having it, scores the result, and groups by missing ingredient. Returns `(ingredient, dish_names, max_score)` tuples sorted by score.

### Persistence layer (`src/repositories/`)

All file-backed state lives behind repository singletons defined in `src/repositories/__init__.py` (`dish_repo`, `fridge_repo`, `history_repo`). Consumers depend on the `Protocol` types in `base.py`, not on the concrete `Json*Repository` classes — this is the seam that lets tests swap implementations without monkey-patching module-level functions.

The data directory is injectable via `src.repositories.configure(data_dir)` — this mutates the existing singletons' `path` attributes in place so modules that already imported `dish_repo` / `fridge_repo` / `history_repo` keep a valid reference. The default (when `configure` is never called) is `<plugin_root>/data/`.

- **`base.py`** — `DishRepository`, `FridgeRepository`, `HistoryRepository` Protocols.
- **`json_dish.py`** — `JsonDishRepository` (`<data_dir>/dishes.json`, wraps the `{"dishes": [...]}` envelope). Owns its own `lock` for load-modify-save sequences. `restore(dish)` is the delta-rollback for delete.
- **`json_fridge.py`** — `JsonFridgeRepository` (`<data_dir>/fridge.json`, flat list, dedup + lowercase on load). `remove_items(items)` is the delta-rollback for finalize.
- **`json_history.py`** — `JsonHistoryRepository` (`<data_dir>/history.json`, dish name → ISO date). Encapsulates its own lock; `set_entry` returns the previous value for compare-and-swap rollback via `revert_entry`.

### DII (`src/dii/`)

- **`session.py`** — `DIISession` dataclass plus ISO-time helpers and `to_dict`/`from_dict` serialization. Pure data; no I/O.
- **`store.py`** — `IngredientSessionStore`: in-memory session map mirrored to `data/sessions/` for crash recovery, with TTL cleanup (30 min) debounced by monotonic clock. Owns the global lock and the per-session lock map.
- **`engine.py`** — Pure mutations on a `DIISession` (build, add/skip/remove/add_manual/clear/mark_finalized). No I/O, no locking — those concerns live in the store and the public API. The "essential XOR optional" rule is enforced in a single `_select(session, name, *, essential)` helper used by every code path that adds an ingredient to a selected list. `build_session` is the orchestrator: validation, normalization, session construction, pre-selection, and queue seeding each live in their own named helper.
- **`presenter.py`** — Builds the LLM-facing response shape (`next_actions`, `instructions`). Decoupled from the engine so the agent UX can change without touching state logic.
- **`finalizer.py`** — Commits a session via injected `dish_repo` + `fridge_repo`, with delta-rollback of the fridge if the dish save fails.
- **`__init__.py`** — Public API: composes the store, engine, presenter, and finalizer into the eight functions consumed by the DII handler modules. Holds the default `IngredientSessionStore` singleton. Also exposes `configure(session_dir)` so hosts and tests can redirect the on-disk session backup directory in place.

### Data files (`data/`)

- `dishes.json` — Recipe catalog. Wraps dishes in `{"dishes": [...]}`; each dish has `name` and `ingredients` (name → bool).
- `fridge.json` — Fridge inventory (flat array of ingredient strings).
- `history.json` — Cooking history (dish name → ISO date string).
- `sessions/` — (created lazily) Per-session DII JSON backups for crash recovery. Files are named `{session_id}.json` and auto-cleaned after 30 minutes.

## Key Design Decisions

- **Essential vs optional ingredients**: In `Dish.ingredients`, `True` = essential (must have to cook), `False` = optional (improves score but not required).
- **Recency cooldown**: Dishes cooked fewer than 2 days ago are always excluded (score forced to 0).
- **Auto-removal on cook**: `register_cooked_meal` removes essential ingredients from the fridge after recording the meal.
- **Single-ingredient unlock**: Shopping suggestions only surface dishes exactly one essential ingredient away from being cookable.
- **Names are normalized once at the boundary; downstream code trusts the invariant.** Ingredient names go through `Dish.normalize_ingredient` / `_common.normalize_ingredient_name`; dish names go through `Dish.normalize_name` / `_common.normalize_dish_name`. `Dish.__post_init__` enforces that `Dish.name` is always stored normalized, so consumers compare `dish.name == name` directly — they do not re-`strip().lower()`.
- **JSON keys are in English** (`name`, `ingredients`, `dishes`) matching the Python code.
- **DII probability funnel**: Sessions hold a hidden queue of ranked ingredients. Only one suggestion is revealed at a time. The LLM provides the ranked list; the tool layer manages the reveal-one-at-a-time state.
- **DII user interaction via conversation**: The DII flow uses plain text conversation — the agent presents one suggestion at a time and interprets the user's free-text response (e.g. "yes", "skip", "add X") to call the appropriate DII tool. The DII tools are platform-agnostic; `skill.md` defines the conversational presentation strategy.
- **Recalculation signal**: When an essential ingredient is removed from a DII session, the tool returns `recalculation_needed: true`. The LLM decides whether to regenerate the ranked list — the tool layer never calls the LLM itself.
- **DII session lifecycle**: `init_ingredient_session` → manipulate via add/skip/remove/manual/clear tools → `finalize_ingredient_session` commits to fridge and/or dish catalog. Sessions are in-memory with optional JSON persistence under `data/sessions/`.
- **Relative imports throughout**: All internal imports use relative form (e.g. `from .src.repositories import dish_repo`, `from .dish import ...`) because Hermes loads the plugin as `hermes_plugins.meal_manager`. Absolute imports like `from src.xxx` would fail at runtime. The test files (`test_integration.py` and `test_unit.py`) bootstrap the package via `importlib` to make relative imports work when running standalone.
- **Injectable data directory**: `src/repositories/__init__.py:configure(data_dir)` and `src/dii/__init__.py:configure(session_dir)` mutate the singleton `path`/`session_dir` attributes in place. The top-level `register(ctx, *, data_dir=None)` wires both. `test_integration.py` uses this to point the whole plugin at a `tempfile.mkdtemp()` directory, so the real `data/` is never touched during tests and no backup/restore dance is needed.
