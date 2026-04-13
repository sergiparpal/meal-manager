# Meal Manager

An intelligent meal planning and fridge inventory management system structured as an official Hermes plugin. It helps users decide what to cook for dinner and what to buy at the grocery store by analyzing their current fridge contents, recipe catalog, and cooking history.

An AI assistant invokes the nineteen tool handlers registered via `__init__.py:register(ctx)` to deliver personalized dinner suggestions, generate optimized shopping lists, manage fridge inventory, manage the recipe catalog, track cooked meals, and interactively build ingredient lists via the Dynamic Ingredient Interface (DII) — all with zero external dependencies.

---

## Design Philosophy: Solving Friction

Traditional fridge inventory apps fail because they turn the user into a data entry clerk. Tracking every ingredient or recording every meal requires constant manual input. The cost (immediate effort) outweighs the reward (better meal planning), and users abandon the system.

This plugin solves that by introducing an AI agent as an intermediary. The user never interacts with the database directly — the agent manages the plugin on their behalf.

**Interface abstraction via natural language.** Tools like `update_fridge_inventory` or `register_cooked_meal` are triggered by the agent interpreting conversation ("I bought onions", "we had carbonara tonight"), not by the user clicking anything.

**Proactive action chaining.** The agent closes the loop automatically: buying ingredients triggers meal suggestions; confirming a dish registers it as cooked and removes its essentials from the fridge. No follow-up input needed.

**Culinary inference offloads cataloging.** The agent uses its own knowledge to infer ingredients from dish names — the user says "I usually make tortilla" and the agent populates the recipe. No manual ingredient lists required.

**Ambiguity absorption.** Spelling variance, synonyms, and vague commands ("skip", "add X", "pasa") are resolved by the agent before reaching the plugin. The database stays clean while the user stays in conversation mode.

The result: the plugin shifts the bookkeeping burden from the human to the LLM, removing the friction points that cause inventory systems to fail.

---

## Features

- **Smart Meal Suggestions** — Ranks every dish in the catalog using a weighted scoring algorithm that combines ingredient availability (60%) with cooking recency (40%). Dishes cooked fewer than 2 days ago are automatically excluded.
- **One-Ingredient Shopping List** — Identifies single ingredients that, once purchased, unlock entirely new dishes. Prioritized by the projected score of the unlocked meal.
- **Fridge Inventory Management** — Add or remove ingredients as you shop or cook. Ingredient and dish names are normalized to lowercase for consistent matching.
- **Cooking History Tracking** — Logs cooked meals with ISO dates. History keys are normalized to lowercase on load, so comparisons are case-insensitive.
- **Auto-Cleanup on Cook** — When a meal is registered as cooked, its essential ingredients are automatically removed from the fridge inventory.
- **Essential vs. Optional Ingredients** — Recipes distinguish between must-have ingredients (required to cook) and nice-to-have ingredients (boost the suggestion score but are not blocking).
- **Dynamic Ingredient Interface (DII)** — Interactive, stateful ingredient selection via plain text conversation. A "probability funnel" reveals ranked ingredient suggestions one at a time. The agent interprets free-text user responses (e.g. "sí", "pasa", "añade X") to drive add/skip/remove/manual-add controls. Removing an essential ingredient triggers a recalculation signal so the agent can re-evaluate suggestions.

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

Since the module uses relative imports, standalone invocation requires bootstrapping the package via `importlib`. A helper one-liner:

```bash
# Get dinner suggestions based on current fridge contents
python3 -c "
import sys, importlib, pathlib
sys.path.insert(0, str(pathlib.Path('.').resolve().parent))
t = importlib.import_module('.tools', pathlib.Path('.').resolve().name)
print(t.get_meal_suggestions({}))
"
```

Replace `get_meal_suggestions({})` with any other tool call, e.g.:

- `t.update_fridge_inventory({'action': 'add', 'ingredients': ['chicken', 'rice']})`
- `t.get_quick_shopping_list({})`
- `t.register_cooked_meal({'dish_name': 'rice with chicken'})`

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
│   ├── __init__.py        # Package marker
│   ├── dish.py            # Dish dataclass — recipe model (essential/optional ingredients)
│   ├── suggestion.py      # Scoring engine — ranks dishes by availability + recency
│   ├── shopping.py        # Shopping suggestions — single-ingredient unlock logic
│   ├── history.py         # Cooking history persistence (data/history.json)
│   ├── storage.py         # Recipe catalog persistence (data/dishes.json)
│   ├── fridge.py          # Fridge inventory persistence (data/fridge.json)
│   └── dii.py             # Dynamic Ingredient Interface — stateful session engine
├── data/
│   ├── dishes.json        # Recipe catalog (dishes with ingredients)
│   ├── fridge.json        # Current fridge inventory (list of ingredients)
│   ├── history.json       # Cooking history (dish name → last-cooked ISO date)
│   └── sessions/          # (created lazily) DII session backups for crash recovery
├── plugin.yaml            # Hermes plugin manifest (name + provided tools)
├── __init__.py            # Plugin entry point — register(ctx) wires tools + skill
├── schemas.py             # JSON schemas for all nineteen tools (named constants)
├── tools.py               # Handler functions (args dict → JSON string)
├── test_unit.py           # Unit tests for domain logic modules
├── test_integration.py    # Integration smoke test
├── skill.md               # Prompt instructions defining when/how to call each tool
├── AGENTS.md              # Repository guidance for agentic coding work
├── CLAUDE.md              # Development guidelines for Claude Code
├── LICENSE                # GPLv3 license text
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
