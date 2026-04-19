from dataclasses import dataclass, field


@dataclass
class Dish:
    """Recipe model.

    Invariant: ``name`` is always stored stripped and lowercased. The
    ``__post_init__`` enforces this on every construction path (direct,
    ``from_dict``, dataclass replace), so consumers can compare ``dish.name``
    by equality without re-normalizing.
    """

    name: str
    ingredients: dict = field(default_factory=dict)

    def __post_init__(self):
        self.name = self.normalize_name(self.name)

    @staticmethod
    def _clean(value, *, label):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string, got {type(value).__name__}")
        return value.strip().lower()

    @staticmethod
    def normalize_ingredient(name):
        return Dish._clean(name, label="ingredient name")

    @staticmethod
    def normalize_name(name):
        return Dish._clean(name, label="dish name")

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
        return {
            "name": self.name,
            "ingredients": self.ingredients
        }

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

        dish = cls(name=name)
        for ingredient_name, is_essential in raw_ingredients.items():
            dish.add_ingredient(ingredient_name, is_essential)
        return dish
