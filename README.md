# Meal Manager

An intelligent meal planning and fridge inventory management system structured as an official Hermes plugin. It helps users decide what to cook for dinner and what to buy at the grocery store by analyzing their current fridge contents, recipe catalog, and cooking history.

An AI assistant invokes the nineteen tool handlers registered via `__init__.py:register(ctx)` to deliver personalized dinner suggestions, generate optimized shopping lists, manage fridge inventory, manage the recipe catalog, track cooked meals, and interactively build ingredient lists via the Dynamic Ingredient Interface (DII) — all with zero external dependencies.

---

## Design Philosophy: A Deterministic Core with a Conversational Shell

Traditional meal-planning apps fail in two ways. Some turn the user into a data-entry clerk, demanding constant manual input until the user abandons the system. Others hand so much control to an AI that behavior becomes unpredictable — suggestions change meaning between sessions, state drifts quietly, and users lose the trust that makes the tool useful.

meal-manager resolves this by separating concerns cleanly. The LLM acts as a **semantic translator** at the boundary: it interprets natural-language intent ("we had carbonara tonight", "add lasagna to my recipes") and maps it onto a typed, validated tool call. The plugin's core is a **deterministic state machine** — scoring, inventory updates, recipe storage, DII session transitions, and persistence are all pure, testable Python code with explicit constants and no model round-trips.

The result is a system that offers the user the freedom of conversation while guaranteeing the consistency of code. Ambiguity is resolved once, at the edge. Every decision past that edge is reproducible, auditable, and cheap.

**The LLM is a Translator, Not a Judge.** The model interprets user intent and maps it onto a tool schema. It does not rank meals, decide whether an ingredient is essential, or track session state — those belong to deterministic Python modules. This line stays fixed when the underlying model changes, the prompt drifts, or the user rephrases the same request two different ways.

**Ambiguity Stops at the Schema.** Free-text input is welcome in conversation; past the tool boundary, every argument is typed, normalized, and explicit. Schemas refuse fuzzy values — the LLM must commit to a concrete `dish_name`, a concrete `action` enum, a concrete `is_essential` boolean. The cost of interpretation is paid once, at parse time, and never re-paid by downstream logic. The database stays clean by construction, not by convention.

**Reproducibility as User Trust.** Given identical fridge contents, recipe catalog, and cooking history, the plugin always produces identical suggestions in identical order. The 60/40 match/recency blend, the 80/20 essential/optional weighting, the 2-day cooldown, and the 14-day recency cap are explicit constants in source — not emergent model output. Users can predict the system because the system predicts itself; every state transition can be replayed from the JSON files under `data/`.

**Tokens Are a Cost, Not a Feature.** Work the code can do does not belong in the prompt. Ranking, session state, ingredient normalization, and persistence run in microseconds without a model round-trip. The result is a plugin that is cheap to run, fast to respond, testable without mocking an LLM, and structurally incapable of hallucinating itself into an inconsistent state.

---

## Features

- **Smart Meal Suggestions** — Ranks every dish in the catalog using a weighted scoring algorithm that combines ingredient availability (60%) with cooking recency (40%). Dishes cooked fewer than 2 days ago are automatically excluded.
- **One-Ingredient Shopping List** — Identifies single ingredients that, once purchased, unlock entirely new dishes. Prioritized by the projected score of the unlocked meal.
- **Fridge Inventory Management** — Add or remove ingredients as you shop or cook. Ingredient and dish names are normalized to lowercase for consistent matching.
- **Cooking History Tracking** — Logs cooked meals with ISO dates. History keys are normalized to lowercase on load, so comparisons are case-insensitive.
- **Auto-Cleanup on Cook** — When a meal is registered as cooked, its essential ingredients are automatically removed from the fridge inventory.
- **Essential vs. Optional Ingredients** — Recipes distinguish between must-have ingredients (required to cook) and nice-to-have ingredients (boost the suggestion score but are not blocking).
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

- *"I'm heading to the grocery store, what should I buy?"* — lists single ingredients that, once purchased, unlock the best dishes.
- *"I bought onions, peppers, and chicken."* — updates the fridge and proposes new meal ideas with what you have now.
- *"We ran out of milk."* — removes it from the fridge inventory.

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

The plugin is loaded by a Hermes agent via the `register(ctx)` entry point in `__init__.py`. It registers nineteen tools:

| Tool | Purpose |
|---|---|
| `get_meal_suggestions` | Returns a ranked list of dishes you can cook right now |
| `get_quick_shopping_list` | Returns single-ingredient purchases that unlock new dishes |
| `update_fridge_inventory` | Adds or removes ingredients from the fridge |
| `register_cooked_meal` | Logs a dish as cooked today and removes its essential ingredients |
| `delete_history_entry` | Undo for `register_cooked_meal` — removes a dish from history |
| `list_fridge` | Returns the current fridge contents |
| `add_dish` | Adds a new recipe to the catalog |
| `add_dishes_batch` | Adds multiple recipes in a single call |
| `delete_dish` | Removes a recipe from the catalog |
| `edit_dish` | Replaces the ingredients of an existing dish |
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
- `get_quick_shopping_list.HANDLER({})`
- `register_cooked_meal.HANDLER({'dish_name': 'rice with chicken'})`

### Running the Integration Test

```bash
python3 test_integration.py
```

This script seeds its own test data, exercises all nineteen tools end-to-end, and restores the original data files afterwards.

For the fastest feedback on pure domain logic, run `python3 test_unit.py`. It covers the dataclass, scoring, shopping, and ingredient-normalization helpers without touching `data/`.

---

## Project Structure

```
meal-manager/
├── src/
│   ├── __init__.py            # Package marker + atomic_write_json helper
│   ├── dish.py                # Dish dataclass — recipe model (essential/optional ingredients)
│   ├── suggestion.py          # Scoring engine — ranks dishes by availability + recency
│   ├── shopping.py            # Shopping suggestions — single-ingredient unlock logic
│   ├── handlers/              # One module per registered tool (NAME, SCHEMA, HANDLER)
│   │   ├── __init__.py        # iter_tools() walks the package and yields each triple
│   │   ├── _common.py         # Shared helpers (err, normalization, input limits)
│   │   ├── get_meal_suggestions.py
│   │   ├── get_quick_shopping_list.py
│   │   ├── update_fridge_inventory.py
│   │   ├── register_cooked_meal.py
│   │   ├── delete_history_entry.py
│   │   ├── list_fridge.py
│   │   ├── add_dish.py
│   │   ├── add_dishes_batch.py
│   │   ├── delete_dish.py
│   │   ├── edit_dish.py
│   │   ├── clear_fridge.py
│   │   ├── init_ingredient_session.py
│   │   ├── dii_add_suggested.py
│   │   ├── dii_skip_suggested.py
│   │   ├── dii_remove_ingredient.py
│   │   ├── dii_add_manual.py
│   │   ├── dii_clear_all.py
│   │   ├── dii_get_state.py
│   │   └── finalize_ingredient_session.py
│   ├── repositories/          # Persistence layer behind Protocol seams
│   │   ├── __init__.py        # Singletons + configure(data_dir)
│   │   ├── base.py            # DishRepository / FridgeRepository / HistoryRepository
│   │   ├── json_dish.py       # Recipe catalog persistence (data/dishes.json)
│   │   ├── json_fridge.py     # Fridge inventory persistence (data/fridge.json)
│   │   └── json_history.py    # Cooking history persistence (data/history.json)
│   └── dii/                   # Dynamic Ingredient Interface
│       ├── __init__.py        # Public API + configure(session_dir)
│       ├── session.py         # DIISession dataclass + serialization
│       ├── store.py           # In-memory map mirrored to data/sessions/ with TTL
│       ├── engine.py          # Pure mutations on a DIISession
│       ├── presenter.py       # LLM-facing response shape
│       └── finalizer.py       # Commits a session via injected repositories
├── data/
│   ├── dishes.json            # Recipe catalog (dishes with ingredients)
│   ├── fridge.json            # Current fridge inventory (list of ingredients)
│   ├── history.json           # Cooking history (dish name → last-cooked ISO date)
│   └── sessions/              # (created lazily) DII session backups for crash recovery
├── plugin.yaml                # Hermes plugin manifest (name + provided tools)
├── __init__.py                # Plugin entry point — register(ctx, *, data_dir=None)
├── test_unit.py               # Unit tests for domain logic modules
├── test_integration.py        # Integration smoke test
├── skill.md                   # Prompt instructions defining when/how to call each tool
├── AGENTS.md                  # Repository guidance for agentic coding work
├── CLAUDE.md                  # Development guidelines for Claude Code
├── LICENSE                    # GPLv3 license text
└── README.md
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
      }
    }
  ]
}
```

- `true` = essential ingredient (must be in the fridge to cook the dish)
- `false` = optional ingredient (improves the suggestion score but is not required)
- Legacy `prep_time` fields are ignored on load and are not written back.

**`data/fridge.json`** — Fridge inventory:

```json
["potatoes", "eggs", "rice"]
```

**`data/history.json`** — Cooking history:

```json
{"rice with chicken": "2026-04-02"}
```

---

## Contributing

Contributions are welcome. To get started:

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/my-feature`).
3. Make your changes and verify them with `python3 test_unit.py` and `python3 test_integration.py`.
4. Commit your changes and open a Pull Request.

Please ensure all ingredient and dish names follow the lowercase/stripped normalization convention used throughout the codebase.

---

## License

This project is licensed under the **GNU General Public License v3.0**.

You may copy, distribute and modify the software as long as you track changes/dates in source files. Any modifications to or software including (via compiler) GPL-licensed code must also be made available under the GPL along with build & install instructions.

See the [LICENSE](LICENSE) file for the full license text.
