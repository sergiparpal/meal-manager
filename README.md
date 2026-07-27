# Meal Manager

An intelligent meal planning and fridge inventory management system structured as an official Hermes plugin. It helps users decide what to cook for dinner and what to buy at the grocery store by analyzing their current fridge contents, recipe catalog, and cooking history.

An AI assistant invokes the twenty-six tool handlers registered via `__init__.py:register(ctx)` to deliver personalized dinner suggestions, generate optimized shopping lists, manage fridge inventory, manage the recipe catalog, track cooked meals, and interactively build ingredient lists via the Dynamic Ingredient Interface (DII) — all with zero external dependencies.

---

## Design Philosophy: A Deterministic Core with a Conversational Shell

Traditional meal-planning apps fail in two ways. Some turn the user into a data-entry clerk, demanding constant manual input until the user abandons the system. Others hand so much control to an AI that behavior becomes unpredictable — suggestions change meaning between sessions, state drifts quietly, and users lose the trust that makes the tool useful.

meal-manager resolves this by separating concerns cleanly. The LLM acts as a **semantic translator** at the boundary: it interprets natural-language intent ("we had carbonara tonight", "add lasagna to my recipes") and maps it onto a typed, validated tool call. The plugin's core is a **deterministic state machine** — scoring, inventory updates, recipe storage, DII session transitions, and persistence are all pure, testable Python code with explicit constants and no model round-trips.

The result is a system that offers the user the freedom of conversation while guaranteeing the consistency of code. Ambiguity is resolved once, at the edge. Every decision past that edge is reproducible, auditable, and cheap.

**The LLM is a Translator, Not a Judge.** The model interprets user intent and maps it onto a tool schema. It does not rank meals, decide whether an ingredient is essential, or track session state — those belong to deterministic Python modules. This line stays fixed when the underlying model changes, the prompt drifts, or the user rephrases the same request two different ways.

**Ambiguity Stops at the Schema.** Free-text input is welcome in conversation; past the tool boundary, every argument is typed, normalized, and explicit. Schemas refuse fuzzy values — the LLM must commit to a concrete `dish_name`, a concrete `action` enum, a concrete `is_essential` boolean. The cost of interpretation is paid once, at parse time, and never re-paid by downstream logic. The database stays clean by construction, not by convention.

**Reproducibility as User Trust.** Given identical fridge contents, recipe catalog, cooking history, and tuning state, the plugin always produces identical suggestions in identical order. The scoring model itself — essentials act as a gate (a dish is either cookable or it is not), and the ingredient signal is the count of optional ingredients in stock capped at `OPTIONAL_CAP` — along with the 2-day cooldown and the 14-day recency cap, are explicit constants and control flow in source, not emergent model output. The match/recency blend starts at 60/40 and self-adjusts *slowly and deterministically* as meals are cooked: a bounded online learner (`src/tuning.py`) nudges the availability weight one small, hysteresis-gated step per cook, never randomly and always within a fixed band. Suggestions therefore remain reproducible **given the state files** — the learned weight lives in `data/tuning.json` alongside the rest, every state transition can be replayed, and the current blend is inspectable at any time via `get_tuning_state`.

**Tokens Are a Cost, Not a Feature.** Work the code can do does not belong in the prompt. Ranking, session state, ingredient normalization, and persistence run in microseconds without a model round-trip. The result is a plugin that is cheap to run, fast to respond, testable without mocking an LLM, and structurally incapable of hallucinating itself into an inconsistent state.

---

## Features

- **Smart Meal Suggestions** — Ranks every dish in the catalog using a weighted scoring algorithm that combines ingredient availability with cooking recency (starting at a 60/40 blend). Availability is measured over *optional* ingredients only: essentials are a gate, since a dish missing one is not offered at all. Dishes cooked fewer than 2 days ago are automatically excluded.
- **Adaptive Suggestion Weights** — The availability/recency blend self-adjusts with use. Each cooked meal feeds a bounded, deterministic online learner (no background job, no randomness) that nudges the weighting toward whatever has been ranking your actual choices best. The current blend and learning status are inspectable at any time via `get_tuning_state`, and a fresh install behaves exactly like the classic 60/40 blend until enough meals accumulate.
- **Unlock-Ranked Shopping List** — Identifies ingredients that, once purchased, unlock entirely new dishes, ranked by the size of the smallest basket that actually gets you to a meal, then by how many dishes each ingredient reaches, then by projected score. Defaults to single-ingredient unlocks; raise `max_missing` to 2-3 when the fridge is nearly empty and no one-item unlock exists.
- **What a Dish Still Needs** — `get_missing_for_dish` answers "can I make this tonight?" for a named dish, splitting what is missing into blocking essentials and score-only optionals.
- **Fridge Inventory Management** — Add, remove, or set ingredients as you shop or cook, tracked as approximate portion counts rather than an all-or-nothing list. Pantry staples (salt, oil, spices) are marked unlimited and never run out. Ingredient and dish names are normalized to lowercase for consistent matching.
- **Cooking History Tracking** — Logs cooked meals with ISO dates, including backdated ones, as an append-only event log. The one-date-per-dish view the suggestion engine uses is computed from that log, so backdating cannot rewind the cooldown on something you made this morning — recording a forgotten meal from last month simply adds an older event that the projection ignores. `list_cooking_history` answers "when did I last cook this?" and "how often do I make it?", and taking an entry back retracts it rather than destroying it, so the record of what you actually cooked stays intact. History keys are normalized to lowercase on load, so comparisons are case-insensitive.
- **Portion Accounting on Cook** — When a meal is registered as cooked, one portion of each essential ingredient is consumed from the fridge. An ingredient you had plenty of stays available; one that runs out is remembered as out of stock rather than silently deleted.
- **Essential vs. Optional Ingredients** — Recipes distinguish between must-have ingredients (required to cook) and nice-to-have ingredients (boost the suggestion score but are not blocking).
- **Cooking Instructions** — Recipes can carry free-form cooking steps alongside their ingredients. `set_dish_instructions` records or clears them, `get_dish_recipe` reads the whole recipe back, and editing a dish's ingredients leaves the steps untouched.
- **Ingredient Aliases** — "tomato", "tomatoes" and "roma tomato" stop being three different things. `merge_ingredient_alias` rewrites the catalog and fridge once to use a single canonical name, then remembers the alias so anything you type later canonicalizes itself. Where a recipe listed both spellings, essential wins over optional; where the fridge held both, the counts add up.
- **Expiry Awareness** — Fridge entries can carry a `expires_on` date. `list_fridge` reports what is expiring within three days and what has already passed. Expired items are flagged, never removed — the date is your estimate, not ground truth, and deleting your food is not a call the tool gets to make.
- **Dynamic Ingredient Interface (DII)** — Interactive, stateful ingredient selection via plain text conversation. A "probability funnel" reveals ranked ingredient suggestions one at a time. The agent interprets free-text user responses (e.g. "yes", "skip", "add X") to drive add/skip/remove/manual-add controls. Removing an essential ingredient triggers a recalculation signal so the agent can re-evaluate suggestions.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Dependencies | None (standard library only) |
| Data Storage | Local JSON files (`data/`) |
| Architecture | Official Hermes plugin (`plugin.yaml` + `register(ctx)`) |
| Data Modeling | Python `dataclasses` |

---

## Getting Started

### Prerequisites

- **Python 3.12** or newer installed on your system.
- No package manager or virtual environment is required — the project has zero external dependencies.

### Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/sergiparpal/meal-manager.git
   cd meal-manager
   ```

2. **Verify your Python version:**

   ```bash
   python3 --version   # Should be 3.12+
   ```

3. **Run the tests** to verify everything works:

   ```bash
   python3 test_unit.py
   python3 test_integration.py
   ```

No build step, dependency installation, or configuration is needed. Data files under `data/` are created lazily by the tools when first needed.

---

## Usage

### As a Hermes Agent User

Once the plugin is installed in your Hermes agent, you never invoke any tool yourself. You talk to the agent in natural language and it translates your intent into the right tool calls. There are no commands to memorize — say what you mean and the agent will handle the bookkeeping.

Example phrases and what the agent will do behind the scenes:

**Deciding what to cook**

- *"What should I cook tonight?"* — ranks your cookable dishes and proposes the best one.
- *"We had carbonara."* — records the meal, applies the 2-day cooldown, and removes its essential ingredients from the fridge automatically.

**Shopping**

- *"I'm heading to the grocery store, what should I buy?"* — lists the ingredients that unlock the most dishes, highest-leverage first.
- *"I bought onions, peppers, and chicken."* — updates the fridge and proposes new meal ideas with what you have now.
- *"We ran out of milk."* — marks it out of stock in the fridge inventory.
- *"Can I make lasagne tonight?"* — reports exactly what that dish is still missing.

**Managing the fridge**

- *"What do I have in the fridge?"* — returns the current inventory.
- *"Empty the fridge, I'm going on vacation."* — clears all fridge contents.

**Teaching new recipes**

- *"I usually make potato omelette."* — the agent infers ingredients from culinary knowledge, shows them for your confirmation, then saves the recipe.
- *"Add lasagna, cannelloni, and paella to my recipes."* — adds several dishes in a single pass.
- *"Carbonara doesn't carry cream, fix the recipe."* — replaces the ingredient list of an existing dish.
- *"Delete the chicken curry recipe."* — removes it from the catalog.

**Correcting mistakes**

- *"I didn't actually cook that yesterday."* — removes the meal from history so it can be suggested again without waiting for the cooldown.

**Interactive ingredient picking (DII)**

When you add a new dish without listing its ingredients, the agent starts a step-by-step session. It proposes one ingredient at a time and you reply in plain text:

> **Agent:** I suggest **parmesan cheese** (optional). Add it, skip it, or something else?
>
> **You:** skip — add pepper instead
>
> **Agent:** Added pepper. Next suggestion: **garlic** (optional)…

Reply naturally — *"yes"*, *"skip"*, *"remove X"*, *"also add Y"*, or *"done"* when finished. There's no menu to navigate.

**First time?** If your catalog is empty or has fewer than five dishes, the agent will proactively offer to help populate it — just tell it what you usually cook and it will infer ingredients, confirm them with you, and save everything in one batch.

### As a Hermes Plugin

The plugin is loaded by a Hermes agent via the `register(ctx)` entry point in `__init__.py`. It registers twenty-six tools:

| Tool | Purpose |
|---|---|
| `get_meal_suggestions` | Returns a ranked list of dishes you can cook right now |
| `get_quick_shopping_list` | Returns purchases that unlock new dishes, cheapest real unlock first |
| `get_missing_for_dish` | Reports what one named dish is still missing, split into essentials and optionals |
| `get_tuning_state` | Reports the current self-adjusted availability/recency blend and learning status |
| `update_fridge_inventory` | Adds, removes, or sets fridge ingredients and their portion counts |
| `register_cooked_meal` | Logs a dish as cooked (today or a given date) and consumes one portion of each essential |
| `delete_history_entry` | Undo for `register_cooked_meal` — retracts the most recent cook of a dish |
| `list_cooking_history` | Lists recorded cook events, newest first — "when did I last cook X?" |
| `list_fridge` | Returns the current fridge contents with portion counts, expiry dates, and what needs using up |
| `add_dish` | Adds a new recipe to the catalog |
| `add_dishes_batch` | Adds multiple recipes in a single call |
| `delete_dish` | Removes a recipe from the catalog |
| `edit_dish` | Replaces the ingredients of an existing dish |
| `set_dish_instructions` | Sets or clears the cooking steps for a dish |
| `get_dish_recipe` | Returns a dish's full recipe: essentials, optionals, and instructions |
| `merge_ingredient_alias` | Merges two spellings of one ingredient across the catalog and fridge |
| `list_ingredient_aliases` | Lists the alias mappings recorded so far |
| `clear_fridge` | Empties the fridge completely |
| `init_ingredient_session` | Start a DII session with ranked ingredient suggestions |
| `dii_add_suggested` | Accept the current ingredient suggestion and reveal the next |
| `dii_skip_suggested` | Skip the current suggestion and reveal the next |
| `dii_remove_ingredient` | Remove an ingredient (signals recalculation if essential) |
| `dii_add_manual` | Manually add a user-typed ingredient |
| `dii_clear_all` | Clear all selected ingredients from the session |
| `finalize_ingredient_session` | Commit session results to fridge and/or dish catalog |
| `dii_get_state` | Get current DII session state without modifying it |

All handlers follow the signature `def handler(args: dict, **kwargs) -> str` and return JSON strings.

See [`skill.md`](skill.md) for detailed instructions on when and how an AI assistant should invoke each tool.

### Interactive Examples

Each tool lives in its own module under `src/handlers/` and exposes a `HANDLER` callable. Since the package uses relative imports, standalone invocation requires bootstrapping it via `importlib`:

```bash
# Get dinner suggestions based on current fridge contents
python3 -c "
import sys, importlib, pathlib
sys.path.insert(0, str(pathlib.Path('.').resolve().parent))
m = importlib.import_module('.src.handlers.get_meal_suggestions', pathlib.Path('.').resolve().name)
print(m.HANDLER({}))
"
```

Swap `get_meal_suggestions` for any other module under `src/handlers/`, for example:

- `update_fridge_inventory.HANDLER({'action': 'add', 'ingredients': ['chicken', 'rice']})`
- `update_fridge_inventory.HANDLER({'action': 'set', 'ingredients': {'milk': {'count': 2, 'expires_on': '2026-08-01'}}})`
- `get_quick_shopping_list.HANDLER({})`
- `register_cooked_meal.HANDLER({'dish_name': 'rice with chicken'})`
- `set_dish_instructions.HANDLER({'dish_name': 'rice with chicken', 'instructions': 'Brown the chicken, add rice, simmer 20 min.'})`
- `get_dish_recipe.HANDLER({'dish_name': 'rice with chicken'})`
- `list_cooking_history.HANDLER({'dish_name': 'rice with chicken'})`
- `merge_ingredient_alias.HANDLER({'from_name': 'tomatoes', 'to_name': 'tomato'})`

### Running the Integration Test

```bash
python3 test_integration.py
```

This script creates a throw-away temp directory, points the repositories and DII session store at it via `configure()`, seeds its own fixtures, and exercises all twenty-six tools end-to-end. The real `data/` files are never touched — the temp directory is deleted on teardown.

For the fastest feedback on pure domain logic, run `python3 test_unit.py`. It covers the dataclass, scoring, shopping, weight-tuning, cooking-event, alias, expiry, and ingredient-normalization helpers without touching `data/`.

### Continuous Integration

Both scripts also run in GitHub Actions ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)) on every push to `main`, on every pull request, and on manual dispatch. The job runs on `ubuntu-latest` across a Python **3.12, 3.13, and 3.14** matrix — the project declares 3.12+, so the whole supported range is tested rather than just the floor, which is free to do with no dependencies to install. Each leg runs `test_unit.py` followed by `test_integration.py`, and `fail-fast` is off so one failing version does not hide the others.

---

## Project Structure

```
meal-manager/
├── src/
│   ├── __init__.py            # Package marker + atomic_write_json helper
│   ├── dish.py                # Dish dataclass — recipe model (essential/optional ingredients)
│   ├── suggestion.py          # Scoring engine — ranks dishes by availability + recency
│   ├── shopping.py            # Shopping suggestions — near-miss unlock logic, cheapest basket first
│   ├── tuning.py              # Online learner — self-adjusts the availability/recency blend
│   ├── handlers/              # One module per registered tool (NAME, SCHEMA, HANDLER)
│   │   ├── __init__.py                     # iter_tools() walks the package and yields each triple
│   │   ├── _common.py                      # Shared helpers (tool_handler decorator, normalization, input limits)
│   │   ├── get_meal_suggestions.py         # Rank cookable dishes by availability and recency
│   │   ├── get_quick_shopping_list.py      # Purchases that unlock new dishes, cheapest basket first
│   │   ├── get_missing_for_dish.py         # What one named dish is still missing
│   │   ├── get_tuning_state.py             # Read-only report of the self-adjusted suggestion weights
│   │   ├── update_fridge_inventory.py      # Add, remove, or set fridge ingredients and portion counts
│   │   ├── register_cooked_meal.py         # Log a dish as cooked and consume one portion of each essential
│   │   ├── delete_history_entry.py         # Undo a cooked-meal entry from history
│   │   ├── list_fridge.py                  # Return the current fridge contents with portion counts
│   │   ├── add_dish.py                     # Add a new recipe to the catalog
│   │   ├── add_dishes_batch.py             # Add multiple recipes in a single call
│   │   ├── delete_dish.py                  # Remove a recipe from the catalog
│   │   ├── edit_dish.py                    # Replace the ingredient list of an existing recipe
│   │   ├── clear_fridge.py                 # Empty the fridge inventory
│   │   ├── init_ingredient_session.py      # Start a DII session with ranked suggestions
│   │   ├── dii_add_suggested.py            # Accept the current DII suggestion and reveal the next
│   │   ├── dii_skip_suggested.py           # Skip the current DII suggestion and reveal the next
│   │   ├── dii_remove_ingredient.py        # Remove a DII ingredient (flags recalc if essential)
│   │   ├── dii_add_manual.py               # Add a user-typed ingredient to the DII session
│   │   ├── dii_clear_all.py                # Clear all selected ingredients in the DII session
│   │   ├── dii_get_state.py                # Read-only DII session state query
│   │   └── finalize_ingredient_session.py  # Commit the DII session to fridge and/or dish catalog
│   ├── repositories/          # Persistence layer behind Protocol seams
│   │   ├── __init__.py        # Singletons + configure(data_dir)
│   │   ├── base.py            # DishRepository / FridgeRepository / HistoryRepository / TuningRepository
│   │   ├── json_dish.py       # Recipe catalog persistence (data/dishes.json)
│   │   ├── json_fridge.py     # Fridge inventory persistence (data/fridge.json)
│   │   ├── json_history.py    # Cooking history persistence (data/history.json)
│   │   └── json_tuning.py     # Online-learner state persistence (data/tuning.json)
│   └── dii/                   # Dynamic Ingredient Interface
│       ├── __init__.py        # Public API + configure(session_dir)
│       ├── session.py         # DIISession dataclass + serialization
│       ├── store.py           # In-memory map mirrored to data/sessions/ with TTL
│       ├── engine.py          # Pure mutations on a DIISession
│       ├── presenter.py       # LLM-facing response shape
│       └── finalizer.py       # Commits a session via injected repositories
├── data/
│   ├── dishes.json            # Recipe catalog (dishes with ingredients)
│   ├── fridge.json            # Fridge inventory (ingredient → portion count; null = staple)
│   ├── history.json           # Cooking history (dish name → last-cooked ISO date)
│   ├── tuning.json            # (created lazily) Online-learner state for the suggestion blend
│   └── sessions/              # (created lazily) DII session backups for crash recovery
├── .github/
│   └── workflows/
│       └── tests.yml          # CI — runs both test scripts on push, PR, and manual dispatch
├── plugin.yaml                # Hermes plugin manifest (name, version, provided tools)
├── __init__.py                # Plugin entry point — register(ctx, *, data_dir=None)
├── test_unit.py               # Unit tests for domain logic modules
├── test_integration.py        # Integration smoke test
├── skill.md                   # Prompt instructions defining when/how to call each tool
├── AGENTS.md                  # Repository guidance for agentic coding work
├── CLAUDE.md                  # Development guidelines for Claude Code
├── LICENSE                    # GPLv3 license text
└── README.md                  # This file — project overview and usage guide
```

### Data Format Reference

**`data/dishes.json`** — Recipe catalog:

```json
{
  "dishes": [
    {
      "name": "rice with chicken",
      "ingredients": {
        "rice": true,
        "chicken": true,
        "peppers": false
      },
      "instructions": "Brown the chicken, add the rice, simmer 20 minutes."
    }
  ]
}
```

- `true` = essential ingredient (must be in the fridge to cook the dish). Essentials are a gate, not a score: a dish missing one is never suggested, so they contribute nothing to the ranking of the dishes that *are* offered.
- `false` = optional ingredient. Each optional you actually have in the fridge raises the dish's score, up to `OPTIONAL_CAP` (3) of them; declaring an optional you lack costs nothing. Describing a recipe more thoroughly can therefore only help it, never hurt it.
- `instructions` is optional free-form text, capped at 20,000 characters. The key is written only when instructions are actually set, so a catalog without them round-trips byte-identically. Clearing them (passing `null` or a blank string) removes the key rather than storing an empty string.
- Legacy `prep_time` fields are ignored on load and are not written back.

**`data/fridge.json`** — Fridge inventory, as ingredient name → portion count:

```json
{"potatoes": 2, "eggs": 6, "olive oil": null, "rice": 0,
 "milk": {"count": 2, "expires_on": "2026-08-01"}}
```

- `n > 0` = approximately `n` dishes' worth on hand. Cooking a dish consumes one portion of each of its essentials.
- `null` = pantry staple: unlimited, never decremented (salt, oil, spices).
- `0` = known to be out of stock. Kept deliberately — "ran out" is more informative than "never had it", and `list_fridge` reports these separately under `out_of_stock`.
- An entry may instead be an object carrying an expiry date alongside the count. Entries with no expiry stay bare scalars, so adding this feature does not rewrite files that do not use it. An unreadable date costs the date, not the ingredient.

> **Format change.** `fridge.json` was previously a flat array of names (`["potatoes", "eggs", "rice"]`). Existing files are migrated automatically the first time they are loaded — each name becomes one portion — and rewritten in the new shape on the next save. No manual migration step is required, and every shape is accepted indefinitely.

**`data/history.json`** — Cooking history, as an append-only event log:

```json
{
  "schema_version": 2,
  "events": [
    {
      "id": "cook_9f2c1e...",
      "dish_name": "rice with chicken",
      "cooked_on": "2026-04-02",
      "recorded_at": "2026-04-02T19:14:03+00:00",
      "backfilled": false,
      "retracted_at": null
    }
  ]
}
```

- The one-date-per-dish view the suggestion engine consumes is a *projection*: the latest `cooked_on` per dish, with retracted events excluded. Because it takes a maximum, an older event can never displace a newer one.
- `backfilled` marks a cook recorded after the fact. Backdated cooks still consume from the fridge but skip the learning update, since the decision they replay never happened.
- `retracted_at` marks an entry the user took back. The row survives and stays visible through `list_cooking_history`; it just stops counting. Only a rolled-back cook — one whose fridge consumption failed — is hard-deleted, because it never happened at all.

> **Format change.** `history.json` was previously a flat `{"dish name": "2026-04-02"}` object. Existing files are migrated in memory on load (one event per entry, with ids derived deterministically so re-migrating never duplicates a row) and rewritten in the new shape on the next write.

**`data/aliases.json`** — Ingredient aliases (created lazily on the first merge):

```json
{"tomatoes": "tomato", "roma tomato": "tomato"}
```

- A flat `alias → canonical` map, consulted at the tool boundary so input spelled the old way lands on the canonical name. No alias ever points at another alias, so resolution is a single hop.

**`data/tuning.json`** — Online-learner state for the availability/recency blend (created lazily on the first learning event):

```json
{
  "version": 2,
  "candidates": [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80],
  "S": {"0.60": 6.0, "...": "discounted reward sum per candidate"},
  "C": {"0.60": 10.0, "...": "discounted observation count per candidate"},
  "observations": 0,
  "deployed_match_weight": 0.60,
  "deployed_time_weight": 0.40
}
```

- `deployed_match_weight` / `deployed_time_weight` are the currently deployed availability/recency weights (they sum to 1.0).
- A missing or corrupt file falls back to a fresh initialized state, reproducing the classic 60/40 blend.
- The state carries a `version`. When the scoring geometry changes, the version is bumped and any file written under the old geometry is discarded on load — accumulated reward mass from a different score model is not comparable. The learner simply restarts from the 60/40 anchor.

---

## Contributing

Contributions are welcome. To get started:

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/my-feature`).
3. Make your changes and verify them with `python3 test_unit.py` and `python3 test_integration.py`.
4. Commit your changes and open a Pull Request. CI runs both scripts on the pull request automatically.

Please ensure all ingredient and dish names follow the lowercase/stripped normalization convention used throughout the codebase.

---

## License

This project is licensed under the **GNU General Public License v3.0**.

You may copy, distribute and modify the software as long as you track changes/dates in source files. Any modifications to or software including (via compiler) GPL-licensed code must also be made available under the GPL along with build & install instructions.

See the [LICENSE](LICENSE) file for the full license text.
