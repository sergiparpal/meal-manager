# Gestor de Cenas Mejorado

An intelligent meal planning and fridge inventory management system structured as an official Hermes plugin. It helps users decide what to cook for dinner and what to buy at the grocery store by analyzing their current fridge contents, recipe catalog, and cooking history.

An AI assistant invokes the eighteen tool handlers registered via `__init__.py:register(ctx)` to deliver personalized dinner suggestions, generate optimized shopping lists, manage fridge inventory, manage the recipe catalog, track cooked meals, and interactively build ingredient lists via the Dynamic Ingredient Interface (DII) — all with zero external dependencies.

---

## Features

- **Smart Meal Suggestions** — Ranks every dish in the catalog using a weighted scoring algorithm that combines ingredient availability (60%) with cooking recency (40%). Dishes cooked fewer than 2 days ago are automatically excluded.
- **One-Ingredient Shopping List** — Identifies single ingredients that, once purchased, unlock entirely new dishes. Prioritized by the projected score of the unlocked meal.
- **Fridge Inventory Management** — Add or remove ingredients as you shop or cook. All names are normalized to lowercase for consistent matching.
- **Cooking History Tracking** — Logs cooked meals with ISO dates so the suggestion engine avoids repetitive recommendations.
- **Auto-Cleanup on Cook** — When a meal is registered as cooked, its essential ingredients are automatically removed from the fridge inventory.
- **Essential vs. Optional Ingredients** — Recipes distinguish between must-have ingredients (required to cook) and nice-to-have ingredients (boost the suggestion score but are not blocking).
- **Dynamic Ingredient Interface (DII)** — Interactive, stateful ingredient selection using Hermes' native `clarify` tool for step-by-step user interaction. A "probability funnel" reveals ranked ingredient suggestions one at a time, with add/skip/remove/manual-add controls presented as interactive options. Removing an essential ingredient triggers a recalculation signal so the agent can re-evaluate suggestions.

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
   git clone <repository-url>
   cd gestor-cenas-mejorado
   ```

2. **Verify your Python version:**

   ```bash
   python3 --version   # Should be 3.12+
   ```

3. **Check that the data files exist:**

   ```bash
   ls data/
   # Expected: platos.json  nevera.json  historial.json
   ```

No build step, dependency installation, or configuration is needed. The project is ready to use immediately after cloning.

---

## Usage

### As a Hermes Plugin

The plugin is loaded by a Hermes agent via the `register(ctx)` entry point in `__init__.py`. It registers eighteen tools:

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

All handlers follow the signature `def handler(args: dict, **kwargs) -> str` and return JSON strings.

See [`skill.md`](skill.md) for detailed instructions on when and how an AI assistant should invoke each tool.

### Interactive Examples

**Get dinner suggestions based on current fridge contents:**

```bash
python3 -c "from tools import get_meal_suggestions; print(get_meal_suggestions({}))"
```

**Add ingredients after a grocery run:**

```bash
python3 -c "from tools import update_fridge_inventory; print(update_fridge_inventory({'action': 'add', 'ingredients': ['huevos', 'arroz', 'pollo']}))"
```

**See what one ingredient could unlock:**

```bash
python3 -c "from tools import get_quick_shopping_list; print(get_quick_shopping_list({}))"
```

**Register a cooked meal:**

```bash
python3 -c "from tools import register_cooked_meal; print(register_cooked_meal({'dish_name': 'arroz con pollo'}))"
```

### Running the Integration Test

```bash
python3 test_hermes.py
```

This script exercises the core tools end-to-end against the live data files and prints the results to stdout.

---

## Project Structure

```
gestor-cenas-mejorado/
├── plugin.yaml            # Hermes plugin manifest (name + provided tools)
├── __init__.py            # Plugin entry point — register(ctx) wires tools + skill
├── schemas.py             # JSON schemas for all eighteen tools (named constants)
├── tools.py               # Handler functions (args dict → JSON string)
├── skill.md               # Prompt instructions defining when/how to call each tool
├── CLAUDE.md              # Development guidelines for Claude Code
├── src/
│   ├── __init__.py
│   ├── dish.py            # Dish dataclass — recipe model (essential/optional ingredients)
│   ├── suggestion.py      # Scoring engine — ranks dishes by availability + recency
│   ├── shopping.py        # Shopping suggestions — single-ingredient unlock logic
│   ├── history.py         # Cooking history persistence (data/historial.json)
│   ├── storage.py         # Recipe catalog persistence (data/platos.json)
│   ├── fridge.py          # Fridge inventory persistence (data/nevera.json)
│   └── dii.py             # Dynamic Ingredient Interface — stateful session engine
├── data/
│   ├── platos.json        # Recipe catalog (dishes with ingredients)
│   ├── nevera.json        # Current fridge inventory (list of ingredients)
│   ├── historial.json     # Cooking history (dish name → last-cooked ISO date)
│   └── sessions/          # (created lazily) DII session backups for crash recovery
├── test_hermes.py         # Integration smoke test
└── README.md
```

### Data Format Reference

**`data/platos.json`** — Recipe catalog:

```json
{
  "platos": [
    {
      "nombre": "Arroz con Pollo",
      "tiempo_prep": 30,
      "ingredientes": {
        "arroz": true,
        "pollo": true,
        "pimientos": false
      }
    }
  ]
}
```

- `true` = essential ingredient (must be in the fridge to cook the dish)
- `false` = optional ingredient (improves the suggestion score but is not required)

**`data/nevera.json`** — Fridge inventory:

```json
["patatas", "huevos", "arroz"]
```

**`data/historial.json`** — Cooking history:

```json
{"arroz con pollo": "2026-04-02"}
```

---

## Contributing

Contributions are welcome. To get started:

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/my-feature`).
3. Make your changes and verify them with `python3 test_hermes.py`.
4. Commit your changes and open a Pull Request.

Please ensure all ingredient names follow the lowercase/stripped normalization convention used throughout the codebase.

---

## License

This project is licensed under the **GNU General Public License v3.0**.

You may copy, distribute and modify the software as long as you track changes/dates in source files. Any modifications to or software including (via compiler) GPL-licensed code must also be made available under the GPL along with build & install instructions.

See the [LICENSE](LICENSE) file for the full license text.
