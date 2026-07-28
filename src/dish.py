from dataclasses import dataclass, field

MAX_INSTRUCTIONS_LENGTH = 20_000


def clean_label(value, *, label: str) -> str:
    """Strip and lowercase *value*, rejecting anything that is not a string.

    Module-level and public because the tool boundary needs the same rule:
    ``handlers/_common._normalize_label`` layers a non-empty check and a length
    cap on top of it. That helper used to reach into ``Dish._clean``, which was
    the only place in the package where one layer touched another's private
    API. The rule itself belongs to neither layer, so it lives out here.
    """
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string, got {type(value).__name__}")
    return value.strip().lower()


@dataclass
class Dish:
    """Recipe model.

    Invariant: ``name`` is always stored stripped and lowercased. The
    ``__post_init__`` enforces this on every construction path (direct,
    ``from_dict``, dataclass replace), so consumers can compare ``dish.name``
    by equality without re-normalizing.

    ``instructions`` is free-form cooking text (or ``None``). It sits after
    ``ingredients`` so existing positional construction is unaffected.
    """

    name: str
    ingredients: dict = field(default_factory=dict)
    instructions: str | None = None

    def __post_init__(self):
        self.name = self.normalize_name(self.name)
        self.instructions = self.normalize_instructions(self.instructions)
        # Enforce the same normalization invariant on ingredient keys for every
        # construction path (direct, dataclasses.replace, …), so consumers can
        # compare against the always-lowercased fridge without re-normalizing.
        if self.ingredients:
            normalized = {}
            for key, value in self.ingredients.items():
                ingredient = self.normalize_ingredient(key)
                # The same checks ``add_ingredient`` applies. Without them,
                # direct construction accepted an empty name and a non-boolean
                # flag, and ``can_cook_with`` then read any truthy value as
                # essential — so ``{"": "yes"}`` became a nameless blocking
                # ingredient no fridge could ever satisfy.
                if not ingredient:
                    raise ValueError("ingredient name cannot be empty")
                if not isinstance(value, bool):
                    raise ValueError("ingredient essential flag must be a boolean")
                # Two keys that collide after normalization carry contradictory
                # flags ({"Rice": True, "rice": False}); silently keeping one
                # would drop a declaration the caller made on purpose.
                if ingredient in normalized:
                    raise ValueError(
                        f"duplicate ingredient '{ingredient}' after normalization"
                    )
                normalized[ingredient] = value
            self.ingredients = normalized

    @staticmethod
    def normalize_ingredient(name):
        return clean_label(name, label="ingredient name")

    @staticmethod
    def normalize_name(name):
        return clean_label(name, label="dish name")

    @staticmethod
    def normalize_instructions(value):
        """Validate free-form cooking text; blank collapses to ``None``.

        "Cleared" and "never set" are the same state, so an empty string is not
        allowed to persist as a second representation of it.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("instructions must be a string or null")
        text = value.strip()
        if not text:
            return None
        if len(text) > MAX_INSTRUCTIONS_LENGTH:
            raise ValueError(
                f"instructions too long (max {MAX_INSTRUCTIONS_LENGTH} chars)"
            )
        return text

    def add_ingredient(self, ingredient_name, is_essential=True):
        if not isinstance(is_essential, bool):
            raise ValueError("ingredient essential flag must be a boolean")
        ingredient = self.normalize_ingredient(ingredient_name)
        if not ingredient:
            raise ValueError("ingredient name cannot be empty")
        self.ingredients[ingredient] = is_essential

    def can_cook_with(self, available_ingredients):
        for ingredient, essential in self.ingredients.items():
            if essential and ingredient not in available_ingredients:
                return False
        return True

    def to_dict(self):
        data = {
            "name": self.name,
            "ingredients": self.ingredients
        }
        # Emitted only when set, so a catalog with no instructions round-trips
        # byte-identically and this field causes no diff churn in dishes.json.
        if self.instructions is not None:
            data["instructions"] = self.instructions
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("dish data must be a dict")

        name = cls.normalize_name(data["name"])
        if not name:
            raise ValueError("dish name cannot be empty")

        raw_ingredients = data.get("ingredients", {})
        if not isinstance(raw_ingredients, dict):
            raise ValueError("ingredients must be a dict")

        dish = cls(name=name, instructions=data.get("instructions"))
        for ingredient_name, is_essential in raw_ingredients.items():
            dish.add_ingredient(ingredient_name, is_essential)
        return dish
