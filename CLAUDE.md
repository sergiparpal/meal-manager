# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `AGENTS.md` before starting — it contains additional repository-specific guidance for agentic coding work that should be consulted alongside this file.

## Project Overview

A meal planning and fridge inventory manager structured as a Hermes plugin. The entry point is `__init__.py:register(ctx)`, which registers nineteen tools and installs the skill. All state is persisted in JSON files under `data/`.

Python 3.12+, no external dependencies (stdlib only).

## Commands

```bash
# Run the integration smoke test
python3 test_integration_smoke.py

# Run a single tool interactively (parent dir must be on sys.path for relative imports)
python3 -c "import sys, importlib, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve().parent)); t = importlib.import_module('.tools', pathlib.Path('.').resolve().name); print(t.get_meal_suggestions({}))"
```

There is no build step or linter. `test_integration_smoke.py` and `test_unit.py` are plain Python scripts with assertions, not a pytest/unittest harness.

## Architecture

### Plugin wiring layer (top-level files)

- **`__init__.py`** — `register(ctx)` wires all nineteen tools (schema from `schemas.py`, handler from `tools.py`) and installs `skill.md` into the Hermes context.
- **`schemas.py`** — Named constants (e.g. `GET_MEAL_SUGGESTIONS_SCHEMA`) holding the JSON schema for each tool.
- **`tools.py`** — Nineteen handler functions, each `def handler(args: dict, **kwargs) -> str` returning `json.dumps()`. All wrap their body in try/except returning `{"error": "..."}` on failure. Exceptions are logged via the `logging` module before being returned.
- **`plugin.yaml`** — Declares the plugin name (`meal_manager`) and lists provided tools.
- **`skill.md`** — LLM-facing instructions for when/how to invoke each tool. The DII section instructs the agent to drive ingredient selection via plain text conversation, interpreting free-text user responses to call the appropriate DII tool.

### Domain modules (`src/`)

- **`dish.py`** — `Dish` dataclass: recipe model with `ingredients` dict mapping name → `bool` (True = essential, False = optional). `can_cook_with()` checks if all essential ingredients are available. Serialization uses English keys (`name`, `ingredients`). Legacy data files may contain `prep_time` which is silently ignored on load.
- **`suggestion.py`** — Scoring engine. `calculate_score()` blends ingredient match (60%) with recency (40%). Within ingredient match, essentials count 80% and optionals 20%. Recency is normalized over 14 days. Dishes cooked < 2 days ago score 0. `suggest_dishes()` filters to cookable dishes and ranks by score.
- **`shopping.py`** — `suggest_quick_shopping()` finds dishes missing exactly one essential ingredient, simulates having it, scores the result, and groups by missing ingredient. Returns `(ingredient, dish_names, max_score)` tuples sorted by score.
- **`history.py`** — Cooking history persistence (`data/history.json`). Maps dish name → last-cooked ISO date. Keys are normalized to lowercase on load.
- **`storage.py`** — Recipe catalog persistence (`data/dishes.json`). `load_dishes()` / `save_dishes()` handle the `{"dishes": [...]}` wrapper.
- **`fridge.py`** — Fridge persistence (`data/fridge.json`). Simple list of lowercase ingredient strings, deduplicated on load.
- **`dii.py`** — Dynamic Ingredient Interface session engine. Manages stateful ingredient-selection sessions with a "probability funnel" (ranked suggestions revealed one at a time). `DIISession` dataclass holds per-session state in memory (`_sessions` dict) with optional JSON backup under `data/sessions/`. Sessions expire after 30 minutes. Integrates with `fridge.py` and `storage.py` on finalization.

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
- **All ingredient names are normalized to lowercase/stripped** throughout the codebase. Dish names are also lowercased for comparison.
- **JSON keys are in English** (`name`, `ingredients`, `dishes`) matching the Python code.
- **DII probability funnel**: Sessions hold a hidden queue of ranked ingredients. Only one suggestion is revealed at a time. The LLM provides the ranked list; the tool layer manages the reveal-one-at-a-time state.
- **DII user interaction via conversation**: The DII flow uses plain text conversation — the agent presents one suggestion at a time and interprets the user's free-text response (e.g. "sí", "pasa", "añade X") to call the appropriate DII tool. The DII tools are platform-agnostic; `skill.md` defines the conversational presentation strategy.
- **Recalculation signal**: When an essential ingredient is removed from a DII session, the tool returns `recalculation_needed: true`. The LLM decides whether to regenerate the ranked list — the tool layer never calls the LLM itself.
- **DII session lifecycle**: `init_ingredient_session` → manipulate via add/skip/remove/manual/clear tools → `finalize_ingredient_session` commits to fridge and/or dish catalog. Sessions are in-memory with optional JSON persistence under `data/sessions/`.
- **Relative imports throughout**: All internal imports use relative form (e.g. `from .src.storage import ...`, `from .dish import ...`) because Hermes loads the plugin as `hermes_plugins.meal_manager`. Absolute imports like `from src.xxx` would fail at runtime. The test file (`test_integration_smoke.py`) bootstraps the package via `importlib` to make relative imports work when running standalone.
