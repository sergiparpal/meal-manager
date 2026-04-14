"""JSON schemas for every meal_manager tool.

Each constant is a complete JSON-schema dict ready to pass to
ctx.register_tool(). The top-level ``description`` tells the LLM when and
how to invoke the tool.
"""

GET_MEAL_SUGGESTIONS_SCHEMA = {
    "description": (
        "Get ranked meal suggestions based on the current fridge contents "
        "and cooking history. Dishes cooked fewer than 2 days ago are "
        "excluded. Returns a list of {dish, score} objects sorted by "
        "descending score. An empty list means no dishes can be suggested."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}

GET_QUICK_SHOPPING_LIST_SCHEMA = {
    "description": (
        "Get a smart shopping list of single ingredients that would unlock "
        "new dishes. For each dish missing exactly one essential ingredient, "
        "returns {missing_ingredient, unlocks_dishes, score} sorted by "
        "projected score. An empty list means no single-ingredient unlocks."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}

UPDATE_FRIDGE_INVENTORY_SCHEMA = {
    "description": (
        "Add or remove ingredients from the fridge inventory. Use when the "
        "user mentions buying groceries, restocking, or when ingredients "
        "have run out."
    ),
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["add", "remove"],
            "description": "add or remove ingredients",
        },
        "ingredients": {
            "type": "array",
            "items": {"type": "string"},
            "description": "list of ingredient names",
        },
    },
    "required": ["action", "ingredients"],
}

REGISTER_COOKED_MEAL_SCHEMA = {
    "description": (
        "Register that a specific dish was cooked today. Records it in the "
        "cooking history so the suggestion engine avoids recommending it "
        "again too soon. Also auto-removes essential ingredients from the "
        "fridge."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name from the catalog",
        },
    },
    "required": ["dish_name"],
}

DELETE_HISTORY_ENTRY_SCHEMA = {
    "description": (
        "Remove a dish from the cooking history. This is the undo for "
        "register_cooked_meal. Use when the user registered a meal by "
        "mistake or wants to reset the recency cooldown for a dish."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name to remove from history",
        },
    },
    "required": ["dish_name"],
}

LIST_FRIDGE_SCHEMA = {
    "description": (
        "Return the current contents of the fridge as a list of ingredient "
        "strings. Use when the user asks what they have in the fridge or "
        "wants to see the inventory."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}

ADD_DISH_SCHEMA = {
    "description": (
        "Add a new recipe to the catalog. Use when the user wants to teach "
        "the system a new dish. The ingredients dict maps ingredient name to "
        "a boolean: true = essential, false = optional."
    ),
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "name of the new dish",
        },
        "ingredients": {
            "oneOf": [
                {
                    "type": "object",
                    "additionalProperties": {"type": "boolean"},
                    "description": "ingredient name -> true (essential) or false (optional)",
                },
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "list of ingredient names (all default to essential)",
                },
            ],
            "description": (
                "Ingredients for the dish. Either an object mapping ingredient "
                "name to boolean (true = essential, false = optional), or a "
                "plain list of ingredient names (all treated as essential)."
            ),
        },
    },
    "required": ["name", "ingredients"],
}

DELETE_DISH_SCHEMA = {
    "description": (
        "Remove a recipe from the catalog. Use when the user wants to "
        "delete a dish they no longer cook or that was added by mistake."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name to delete from catalog",
        },
    },
    "required": ["dish_name"],
}

EDIT_DISH_SCHEMA = {
    "description": (
        "Replace the ingredients of an existing dish in the catalog. This "
        "performs a full replacement, not a merge. Use when the user wants "
        "to change a recipe's ingredient list."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "exact dish name to edit",
        },
        "ingredients": {
            "oneOf": [
                {
                    "type": "object",
                    "additionalProperties": {"type": "boolean"},
                    "description": "ingredient name -> true (essential) or false (optional)",
                },
                {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "list of ingredient names (all default to essential)",
                },
            ],
            "description": (
                "New ingredients for the dish. Either an object mapping "
                "ingredient name to boolean (true = essential, false = "
                "optional), or a plain list of ingredient names (all "
                "treated as essential)."
            ),
        },
    },
    "required": ["dish_name", "ingredients"],
}

ADD_DISHES_BATCH_SCHEMA = {
    "description": (
        "Add multiple new recipes to the catalog in a single call. Use when "
        "the user wants to add several dishes at once, e.g. during initial "
        "catalog setup. Skips dishes that already exist. Each dish's "
        "ingredients can be an object (name -> bool) or a plain list of "
        "names (all treated as essential)."
    ),
    "type": "object",
    "properties": {
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "name of the dish",
                    },
                    "ingredients": {
                        "oneOf": [
                            {
                                "type": "object",
                                "additionalProperties": {"type": "boolean"},
                            },
                            {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        ],
                        "description": (
                            "Ingredients as object (name -> bool) or list "
                            "(all essential)."
                        ),
                    },
                },
                "required": ["name", "ingredients"],
            },
            "description": "list of dishes to add",
        },
    },
    "required": ["dishes"],
}

CLEAR_FRIDGE_SCHEMA = {
    "description": (
        "Empty the fridge completely. Use when the user wants to reset the "
        "fridge inventory, e.g. after a move or a full cleanout."
    ),
    "type": "object",
    "properties": {},
    "required": [],
}

# ---------------------------------------------------------------------------
# Dynamic Ingredient Interface (DII) schemas
# ---------------------------------------------------------------------------

INIT_INGREDIENT_SESSION_SCHEMA = {
    "description": (
        "Initialize a Dynamic Ingredient Interface session for a dish. "
        "The agent provides ranked ingredient suggestions. Top N are auto-selected. "
        "Returns session state with the first hidden suggestion revealed. "
        "To recalculate after removing an essential ingredient, pass the existing "
        "session_id — the session will be reset in place and the same id reused."
    ),
    "type": "object",
    "properties": {
        "dish_name": {
            "type": "string",
            "description": "Name of the dish to configure ingredients for",
        },
        "ingredients": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of ingredient names in order of relevance (highest first)",
        },
        "is_essential": {
            "type": "array",
            "items": {"type": "boolean"},
            "description": "Parallel array - true if ingredient at same index is essential, false if optional",
        },
        "pre_select_top_n": {
            "type": "integer",
            "minimum": 0,
            "description": "How many top ingredients to auto-select (default 3)",
        },
        "session_id": {
            "type": "string",
            "description": (
                "Optional. When recalculating an existing session, pass its id "
                "here to reset it in place. Omit to create a brand-new session."
            ),
        },
    },
    "required": ["dish_name", "ingredients", "is_essential"],
}

DII_ADD_SUGGESTED_SCHEMA = {
    "description": (
        "Accept the currently shown ingredient suggestion in a DII session. "
        "Adds it to the selected list and reveals the next suggestion from "
        "the hidden queue."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
    },
    "required": ["session_id"],
}

DII_SKIP_SUGGESTED_SCHEMA = {
    "description": (
        "Skip/reject the currently shown ingredient suggestion in a DII "
        "session without adding it. Advances to the next suggestion."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
    },
    "required": ["session_id"],
}

DII_REMOVE_INGREDIENT_SCHEMA = {
    "description": (
        "Remove a specific ingredient from a DII session's selected list. "
        "If the removed ingredient was essential, the response includes "
        "recalculation_needed=true signaling the agent should re-evaluate "
        "the remaining suggestions."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
        "ingredient": {
            "type": "string",
            "description": "Ingredient name to remove",
        },
    },
    "required": ["session_id", "ingredient"],
}

DII_ADD_MANUAL_SCHEMA = {
    "description": (
        "Manually add an ingredient to a DII session that was not in the "
        "suggestion queue. Use when the user names a custom ingredient to "
        "add directly rather than accepting the current suggestion."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
        "ingredient": {
            "type": "string",
            "description": "Ingredient name to add",
        },
        "is_essential": {
            "type": "boolean",
            "description": "True if essential, False if optional (default true)",
        },
    },
    "required": ["session_id", "ingredient"],
}

DII_CLEAR_ALL_SCHEMA = {
    "description": (
        "Clear all selected ingredients from a DII session, resetting the "
        "essential and optional lists. Always sets recalculation_needed=true."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
    },
    "required": ["session_id"],
}

FINALIZE_INGREDIENT_SESSION_SCHEMA = {
    "description": (
        "Finalize a DII session, committing the selected ingredients. "
        "Can optionally add ingredients to the fridge and/or create/update "
        "the dish in the catalog. Cleans up the session afterwards."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
        "commit_to_fridge": {
            "type": "boolean",
            "description": "Add selected ingredients to fridge inventory (default true)",
        },
        "commit_to_dish": {
            "type": "boolean",
            "description": "Create/update the dish in the catalog with these ingredients (default true)",
        },
    },
    "required": ["session_id"],
}

DII_GET_STATE_SCHEMA = {
    "description": (
        "Get the current state of a DII session without modifying it. "
        "Returns the full session state including next_actions and instructions "
        "to guide the interaction flow."
    ),
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Active DII session ID",
        },
    },
    "required": ["session_id"],
}
