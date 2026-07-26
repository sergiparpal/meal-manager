# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `AGENTS.md` before starting — it contains additional repository-specific guidance for agentic coding work that should be consulted alongside this file.

## Project Overview

A meal planning and fridge inventory manager structured as a Hermes plugin. The entry point is `__init__.py:register(ctx)`, which auto-discovers the twenty-one tool handlers under `src/handlers/` and installs the skill. All state is persisted in JSON files under `data/`.

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

- **`_common.py`** — Shared helpers: `tool_handler` decorator (the canonical wrapper for every handler), `require_arg` (explicit "required argument" error instead of a bare `KeyError`), `maybe_parse_json_arg` (coerces JSON-string arguments that some LLMs emit), `normalize_dish_name`, `normalize_ingredient_name`, `normalize_ingredients`, `normalize_ingredient_counts` (the fridge-side mirror of `normalize_ingredients`: accepts `["a", "b"]` or `{"a": 3, "salt": null}` and yields `{name: count}`), `days_since_last_cook`, plus the input-limit constants (`MAX_NAME_LEN`, `MAX_INGREDIENTS`, `MAX_BATCH_SIZE`, `MAX_FRIDGE_UPDATE`, `MAX_PORTION_COUNT`). Both `normalize_dish_name` and `normalize_ingredient_name` delegate to a single `_normalize_label(value, *, label)` helper so the rules (non-empty, max length) live in one place.

### Domain modules (`src/`)

- **`dish.py`** — `Dish` dataclass: recipe model with `ingredients` dict mapping name → `bool` (True = essential, False = optional). `__post_init__` enforces the invariant that `Dish.name` is always stored stripped and lowercased — every construction path (direct, `from_dict`, dataclass `replace`) goes through it, so consumers can compare `dish.name` by equality without re-normalizing. `can_cook_with()` checks if all essential ingredients are available. Serialization uses English keys (`name`, `ingredients`). Legacy data files may contain `prep_time` which is silently ignored on load.
- **`suggestion.py`** — Scoring engine. `calculate_score()` blends an ingredient-match term with a recency term. Essentials are **not** part of the score: they are a gate, already enforced by `can_cook_with` (and by the shopping simulation), so scoring them again would only add a constant. The match term is the number of *optional* ingredients actually in stock, capped at `OPTIONAL_CAP` (3) and normalized — an absolute count, not an intra-dish ratio, so declaring an optional you have raises the score and declaring one you lack is free. Recency is normalized over 14 days. Dishes cooked < 2 days ago score 0. The blend weight between the two terms is the learner's deployed `w` (`match_weight`/`time_weight`), defaulting to 0.6/0.4. `suggest_dishes()` filters to cookable dishes and ranks by score.
- **`shopping.py`** — `suggest_quick_shopping()` finds dishes missing at most `max_missing` essential ingredients (default 1), simulates having all of them, scores the result, and credits every missing essential of the near-miss dish. Returns `(ingredient, dish_names, max_score, unlocks_count, still_missing)` tuples sorted by **reach first** (`unlocks_count` descending), then score, then ingredient name for deterministic ties. `still_missing` is the smallest basket size that unlocks a dish through that ingredient, so callers can distinguish a true one-item unlock from part of a larger basket.
- **`tuning.py`** — Online self-tuning of the availability/recency blend. Pure functions only (no I/O, no locking, no randomness): `initialize_state`/`validate_state` manage the `data/tuning.json` shape; `compute_rewards` replays a cook decision against the pre-cook snapshot and rewards every availability-weight candidate `w` by how highly it ranked the cooked dish, returning `None` for events that carry no signal about `w` (the dish was dropped from every ranking, or the reward vector is uniform within `MIN_REWARD_SPREAD` — applying either would only discount accumulated mass by `GAMMA`); `apply_update` applies the discounted (`GAMMA`) reward/count update; `select_deployed` picks the deployed `w` (cold-start anchor below `MIN_OBSERVATIONS`, then argmax-within-`BAND` gated by `HYSTERESIS_MARGIN`); `deployed_weights` is the safe reader. Hyperparameters are module constants. `suggest_dishes` accepts `match_weight`/`time_weight`, so the deployed blend feeds straight in.

### Persistence layer (`src/repositories/`)

All file-backed state lives behind repository singletons defined in `src/repositories/__init__.py` (`dish_repo`, `fridge_repo`, `history_repo`, `tuning_repo`). Consumers depend on the `Protocol` types in `base.py`, not on the concrete `Json*Repository` classes — this is the seam that lets tests swap implementations without monkey-patching module-level functions.

The data directory is injectable via `src.repositories.configure(data_dir)` — this mutates the existing singletons' `path` attributes in place so modules that already imported `dish_repo` / `fridge_repo` / `history_repo` / `tuning_repo` keep a valid reference. The default (when `configure` is never called) is `<plugin_root>/data/`.

- **`base.py`** — `DishRepository`, `FridgeRepository`, `HistoryRepository`, `TuningRepository` Protocols.
- **`json_dish.py`** — `JsonDishRepository` (`<data_dir>/dishes.json`, wraps the `{"dishes": [...]}` envelope). Owns its own `lock` for load-modify-save sequences. `restore(dish)` is the delta-rollback for delete.
- **`json_fridge.py`** — `JsonFridgeRepository` (`<data_dir>/fridge.json`, a `{name: count}` object, lowercased on load). `None` = pantry staple (unlimited, never decremented), `0` = known to be out of stock, `n > 0` = approximately `n` dish-portions. Legacy flat-list files are migrated in memory on load (each name becomes one portion) and written back in the new shape on the next save, so no migration step is needed. `load_set()` returns only the *usable* names — this is the seam that keeps the scoring core unaware of counts. `remove_items(items)` is the delta-rollback for finalize; `consume(names)` / `restore_counts(previous)` are the decrement/rollback pair used by the cook handler.
- **`json_history.py`** — `JsonHistoryRepository` (`<data_dir>/history.json`, dish name → ISO date). Encapsulates its own lock; `set_entry` returns the previous value for compare-and-swap rollback via `revert_entry`.
- **`json_tuning.py`** — `JsonTuningRepository` (`<data_dir>/tuning.json`, the online-learner state). Owns its own `lock` for the cook handler's load-modify-save sequence. `load()` never raises: a missing/corrupt/schema-invalid file yields a fresh `tuning.initialize_state()`.

### DII (`src/dii/`)

- **`session.py`** — `DIISession` dataclass plus ISO-time helpers and `to_dict`/`from_dict` serialization. Pure data; no I/O.
- **`store.py`** — `IngredientSessionStore`: in-memory session map mirrored to `data/sessions/` for crash recovery, with TTL cleanup (30 min) debounced by monotonic clock. Owns the global lock and the per-session lock map.
- **`engine.py`** — Pure mutations on a `DIISession` (build, add/skip/remove/add_manual/clear/mark_finalized). No I/O, no locking — those concerns live in the store and the public API. The "essential XOR optional" rule is enforced in a single `_select(session, name, *, essential)` helper used by every code path that adds an ingredient to a selected list. `build_session` is the orchestrator: validation, normalization, session construction, pre-selection, and queue seeding each live in their own named helper.
- **`presenter.py`** — Builds the LLM-facing response shape (`next_actions`, `instructions`). Decoupled from the engine so the agent UX can change without touching state logic.
- **`finalizer.py`** — Commits a session via injected `dish_repo` + `fridge_repo`, with delta-rollback of the fridge if the dish save fails.
- **`__init__.py`** — Public API: composes the store, engine, presenter, and finalizer into the eight functions consumed by the DII handler modules. Holds the default `IngredientSessionStore` singleton. Also exposes `configure(session_dir)` so hosts and tests can redirect the on-disk session backup directory in place.

### Data files (`data/`)

- `dishes.json` — Recipe catalog. Wraps dishes in `{"dishes": [...]}`; each dish has `name` and `ingredients` (name → bool).
- `fridge.json` — Fridge inventory: an object mapping ingredient name → portion count, where `null` means a pantry staple (unlimited) and `0` means known to be out of stock. Legacy flat-array files are migrated automatically on first load.
- `history.json` — Cooking history (dish name → ISO date string).
- `tuning.json` — (created lazily on the first learning event) Online-learner state for the suggestion blend: candidate grid, discounted reward/count sums (`S`/`C`), `observations`, and the `deployed_match_weight` / `deployed_time_weight`. Missing/corrupt files fall back to a fresh initialized state.
- `sessions/` — (created lazily) Per-session DII JSON backups for crash recovery. Files are named `{session_id}.json` and auto-cleaned after 30 minutes.

## Key Design Decisions

- **Essential vs optional ingredients**: In `Dish.ingredients`, `True` = essential (must have to cook), `False` = optional (improves score but not required).
- **Adaptive suggestion weights**: The availability/recency blend is no longer a fixed source constant — a bounded online learner (`src/tuning.py`, state in `data/tuning.json`) nudges the availability weight `w` (recency is always `1 - w`) one step per cooked meal, full-information and event-driven (no daemon, no randomness). This softens the deterministic-core promise **by design and with maintainer approval**: output stays deterministic *given* `tuning.json`, the weight is bounded to `BAND`, slow-moving (discounted, hysteresis-gated, cold-start-anchored), and auditable via the read-only `get_tuning_state` tool. A fresh/missing `tuning.json` reproduces the historical 0.6/0.4 blend until `MIN_OBSERVATIONS` cooks accumulate.
- **Essentials gate, optionals score**: `calculate_score` never scores essentials. Both production callers guarantee complete essentials before calling (`suggest_dishes` pre-filters with `can_cook_with`; `suggest_quick_shopping` simulates the missing ones), so an essential term would be a constant `1.0` with no discriminating power. The match signal is the capped *count* of optionals in stock. A count rather than a ratio is deliberate: under a ratio, declaring no optionals scored identically to having them all, so describing a recipe more carefully lowered its score — an inverted incentive that degraded the catalog over time.
- **Recency cooldown**: Dishes cooked fewer than 2 days ago are always excluded (score forced to 0).
- **Auto-removal on cook**: `register_cooked_meal` consumes one portion of each essential ingredient from the fridge after recording the meal. Pantry staples are untouched and counts floor at 0 rather than being deleted.
- **Portion counts, not quantities**: The fridge stores approximate dish-portions, and one cooked dish consumes one portion of each essential. This is deliberately approximate — real dishes use differing amounts — but it is strictly better than the previous all-or-nothing deletion, and it avoids forcing the user to enter grams. The `set` action on `update_fridge_inventory` exists so drift can be corrected cheaply; per-dish ingredient quantities are explicitly out of scope.
- **Pantry staples are unlimited**: A `null` count marks an ingredient that never runs out (salt, oil, spices). Staples always count as available and are never decremented by a cook, so the user is not asked to re-stock things they always have.
- **Backdated cooks skip learning**: `register_cooked_meal` accepts an optional `date`. The fridge is still consumed (the ingredients really were used, and the fridge reflects the present), but the tuning update is skipped — the learner replays the decision against a snapshot of *today's* fridge and history, which does not correspond to the backdated moment.
- **Near-miss unlock**: Shopping suggestions surface dishes at most `max_missing` essential ingredients away from cookable (default 1). Raising it is what makes the tool answer usefully on a near-empty fridge, where single-ingredient unlocks do not exist. Results rank by reach before score.
- **Names are normalized once at the boundary; downstream code trusts the invariant.** Ingredient names go through `Dish.normalize_ingredient` / `_common.normalize_ingredient_name`; dish names go through `Dish.normalize_name` / `_common.normalize_dish_name`. `Dish.__post_init__` enforces that `Dish.name` is always stored normalized, so consumers compare `dish.name == name` directly — they do not re-`strip().lower()`.
- **JSON keys are in English** (`name`, `ingredients`, `dishes`) matching the Python code.
- **DII probability funnel**: Sessions hold a hidden queue of ranked ingredients. Only one suggestion is revealed at a time. The LLM provides the ranked list; the tool layer manages the reveal-one-at-a-time state.
- **DII user interaction via conversation**: The DII flow uses plain text conversation — the agent presents one suggestion at a time and interprets the user's free-text response (e.g. "yes", "skip", "add X") to call the appropriate DII tool. The DII tools are platform-agnostic; `skill.md` defines the conversational presentation strategy.
- **Recalculation signal**: When an essential ingredient is removed from a DII session, the tool returns `recalculation_needed: true`. The LLM decides whether to regenerate the ranked list — the tool layer never calls the LLM itself.
- **DII session lifecycle**: `init_ingredient_session` → manipulate via add/skip/remove/manual/clear tools → `finalize_ingredient_session` commits to fridge and/or dish catalog. Sessions are in-memory with optional JSON persistence under `data/sessions/`.
- **Relative imports throughout**: All internal imports use relative form (e.g. `from .src.repositories import dish_repo`, `from .dish import ...`) because Hermes loads the plugin as `hermes_plugins.meal_manager`. Absolute imports like `from src.xxx` would fail at runtime. The test files (`test_integration.py` and `test_unit.py`) bootstrap the package via `importlib` to make relative imports work when running standalone.
- **Injectable data directory**: `src/repositories/__init__.py:configure(data_dir)` and `src/dii/__init__.py:configure(session_dir)` mutate the singleton `path`/`session_dir` attributes in place. The top-level `register(ctx, *, data_dir=None)` wires both. `test_integration.py` uses this to point the whole plugin at a `tempfile.mkdtemp()` directory, so the real `data/` is never touched during tests and no backup/restore dance is needed.
