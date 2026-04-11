from dataclasses import dataclass, field


@dataclass
class Dish:
    name: str
    ingredients: dict = field(default_factory=dict)

    @staticmethod
    def normalize_ingredient(name):
        if not isinstance(name, str):
            raise ValueError(f"ingredient name must be a string, got {type(name).__name__}")
        return name.strip().lower()

    @staticmethod
    def normalize_name(name):
        if not isinstance(name, str):
            raise ValueError(f"dish name must be a string, got {type(name).__name__}")
        return name.strip().lower()

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

        raw = data.get("ingredients", {})
        if not isinstance(raw, dict):
            raise ValueError("ingredients must be a dict")

        dish = cls(name=name)
        for ingredient_name, is_essential in raw.items():
            dish.add_ingredient(ingredient_name, is_essential)
        return dish
