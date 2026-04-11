"""meal_manager – Hermes plugin entry point."""

from pathlib import Path

from .schemas import (
    GET_MEAL_SUGGESTIONS_SCHEMA,
    GET_QUICK_SHOPPING_LIST_SCHEMA,
    UPDATE_FRIDGE_INVENTORY_SCHEMA,
    REGISTER_COOKED_MEAL_SCHEMA,
    DELETE_HISTORY_ENTRY_SCHEMA,
    LIST_FRIDGE_SCHEMA,
    ADD_DISH_SCHEMA,
    ADD_DISHES_BATCH_SCHEMA,
    DELETE_DISH_SCHEMA,
    EDIT_DISH_SCHEMA,
    CLEAR_FRIDGE_SCHEMA,
    INIT_INGREDIENT_SESSION_SCHEMA,
    DII_ADD_SUGGESTED_SCHEMA,
    DII_SKIP_SUGGESTED_SCHEMA,
    DII_REMOVE_INGREDIENT_SCHEMA,
    DII_ADD_MANUAL_SCHEMA,
    DII_CLEAR_ALL_SCHEMA,
    FINALIZE_INGREDIENT_SESSION_SCHEMA,
    DII_GET_STATE_SCHEMA,
)
from .tools import (
    get_meal_suggestions,
    get_quick_shopping_list,
    update_fridge_inventory,
    register_cooked_meal,
    delete_history_entry,
    list_fridge,
    add_dish,
    add_dishes_batch,
    delete_dish,
    edit_dish,
    clear_fridge,
    init_ingredient_session,
    dii_add_suggested,
    dii_skip_suggested,
    dii_remove_ingredient,
    dii_add_manual,
    dii_clear_all,
    finalize_ingredient_session,
    dii_get_state,
)

_TOOLS = [
    ("get_meal_suggestions",    GET_MEAL_SUGGESTIONS_SCHEMA,    get_meal_suggestions),
    ("get_quick_shopping_list", GET_QUICK_SHOPPING_LIST_SCHEMA, get_quick_shopping_list),
    ("update_fridge_inventory", UPDATE_FRIDGE_INVENTORY_SCHEMA, update_fridge_inventory),
    ("register_cooked_meal",    REGISTER_COOKED_MEAL_SCHEMA,    register_cooked_meal),
    ("delete_history_entry",    DELETE_HISTORY_ENTRY_SCHEMA,    delete_history_entry),
    ("list_fridge",             LIST_FRIDGE_SCHEMA,             list_fridge),
    ("add_dish",                ADD_DISH_SCHEMA,                add_dish),
    ("add_dishes_batch",        ADD_DISHES_BATCH_SCHEMA,        add_dishes_batch),
    ("delete_dish",             DELETE_DISH_SCHEMA,             delete_dish),
    ("edit_dish",               EDIT_DISH_SCHEMA,               edit_dish),
    ("clear_fridge",            CLEAR_FRIDGE_SCHEMA,            clear_fridge),
    # Dynamic Ingredient Interface (DII)
    ("init_ingredient_session",     INIT_INGREDIENT_SESSION_SCHEMA,     init_ingredient_session),
    ("dii_add_suggested",           DII_ADD_SUGGESTED_SCHEMA,           dii_add_suggested),
    ("dii_skip_suggested",          DII_SKIP_SUGGESTED_SCHEMA,          dii_skip_suggested),
    ("dii_remove_ingredient",       DII_REMOVE_INGREDIENT_SCHEMA,       dii_remove_ingredient),
    ("dii_add_manual",              DII_ADD_MANUAL_SCHEMA,              dii_add_manual),
    ("dii_clear_all",               DII_CLEAR_ALL_SCHEMA,               dii_clear_all),
    ("finalize_ingredient_session", FINALIZE_INGREDIENT_SESSION_SCHEMA, finalize_ingredient_session),
    ("dii_get_state",               DII_GET_STATE_SCHEMA,               dii_get_state),
]


def register(ctx):
    """Register all meal_manager tools and the skill with the Hermes context."""
    for name, schema, handler in _TOOLS:
        ctx.register_tool(name, "meal_manager", schema, handler)

    skill_path = Path(__file__).parent / "skill.md"
    ctx.inject_message(skill_path.read_text(encoding="utf-8"))
