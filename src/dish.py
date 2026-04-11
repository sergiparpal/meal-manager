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
            "nombre": self.name,
            "tiempo_prep": self.prep_time,
            "ingredientes": self.ingredients
        }

    @classmethod
    def from_dict(cls, data):
        dish = cls(name=data["nombre"].strip().lower(), prep_time=data["tiempo_prep"])
        raw = data.get("ingredientes", {})
        dish.ingredients = {cls.normalize_ingredient(k): v for k, v in raw.items()}
        return dish
