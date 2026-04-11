from dataclasses import dataclass, field


@dataclass
class Dish:
    name: str
    prep_time: int
    ingredients: dict = field(default_factory=dict)

    @staticmethod
    def normalize_ingredient(name):
        return name.strip().lower()

    def add_ingredient(self, ingredient_name, is_essential=True):
        self.ingredients[self.normalize_ingredient(ingredient_name)] = is_essential

    def can_cook_with(self, available_ingredients):
        for ingredient, essential in self.ingredients.items():
            if essential and ingredient not in available_ingredients:
                return False
        return True

    def to_dict(self):
        return {
            "name": self.name,
            "prep_time": self.prep_time,
            "ingredients": self.ingredients
        }

    @classmethod
    def from_dict(cls, data):
        dish = cls(name=data["name"].strip().lower(), prep_time=data["prep_time"])
        raw = data.get("ingredients", {})
        dish.ingredients = {cls.normalize_ingredient(k): v for k, v in raw.items()}
        return dish
