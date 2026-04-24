#! python3
from __future__ import annotations

from typing import Any

from flask import Flask, render_template, request

app = Flask(__name__)

TARGET_COOLER_ML = 18927.1

UNIT_TO_ML = {
    "ml": 1.0,
    "oz": 29.5735,
    "tbsp": 14.7868,
    "tsp": 4.92892,
    "liters": 1000.0,
    "shots": 44.3602943,
    "handles": 1750.0,
    "cups": 236.588,
    "gallons": 3785.41,
    "quarts": 946.353,
}

UNIT_ALIASES = {
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "oz": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "tbsp": "tbsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tsp": "tsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "l": "liters",
    "liter": "liters",
    "liters": "liters",
    "shot": "shots",
    "shots": "shots",
    "handle": "handles",
    "handles": "handles",
    "cup": "cups",
    "cups": "cups",
    "gallon": "gallons",
    "gallons": "gallons",
    "quart": "quarts",
    "quarts": "quarts",
}

UNIT_LABELS = {
    "ml": "mL",
    "oz": "Oz",
    "tbsp": "Tbsp",
    "tsp": "Tsp",
    "liters": "Liters",
    "shots": "Shots",
    "handles": "Handles",
    "cups": "Cups",
    "gallons": "Gallons",
    "quarts": "Quarts",
}

UNIT_ORDER = list(UNIT_TO_ML.keys())


def normalize_unit(raw_unit: str) -> str | None:
    return UNIT_ALIASES.get(raw_unit.strip().lower())


def calculate_scaled_recipe(
    ingredients: list[dict[str, Any]], output_unit: str
) -> list[dict[str, Any]]:
    total_ml = sum(item["amount_ml"] for item in ingredients)
    multiplier = TARGET_COOLER_ML / total_ml
    output_factor = UNIT_TO_ML[output_unit]

    results: list[dict[str, Any]] = []
    for ingredient in ingredients:
        scaled_ml = ingredient["amount_ml"] * multiplier
        output_amount = scaled_ml / output_factor
        results.append(
            {
                "name": ingredient["name"],
                "amount": round(output_amount, 2),
            }
        )
    return results


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    output_unit = "oz"
    ingredient_rows = [{"name": "", "amount": "", "unit": "oz"}]

    if request.method == "POST":
        names = request.form.getlist("name")
        amounts = request.form.getlist("amount")
        units = request.form.getlist("unit")
        output_unit = normalize_unit(request.form.get("output_unit", "oz")) or "oz"

        parsed_ingredients: list[dict[str, Any]] = []
        ingredient_rows = []

        for index, (name, amount_raw, unit_raw) in enumerate(zip(names, amounts, units), start=1):
            ingredient_rows.append(
                {
                    "name": name,
                    "amount": amount_raw,
                    "unit": normalize_unit(unit_raw or "oz") or "oz",
                }
            )

            if not name.strip() and not amount_raw.strip():
                continue
            if not name.strip():
                errors.append(f"Ingredient {index}: name is required.")
                continue
            if not amount_raw.strip():
                errors.append(f"Ingredient {index}: amount is required.")
                continue

            unit_key = normalize_unit(unit_raw)
            if not unit_key:
                errors.append(f"Ingredient {index}: unit '{unit_raw}' is not valid.")
                continue

            try:
                amount_value = float(amount_raw)
            except ValueError:
                errors.append(f"Ingredient {index}: amount must be numeric.")
                continue

            if amount_value <= 0:
                errors.append(f"Ingredient {index}: amount must be greater than zero.")
                continue

            parsed_ingredients.append(
                {
                    "name": name.strip(),
                    "amount_ml": amount_value * UNIT_TO_ML[unit_key],
                }
            )

        if not parsed_ingredients:
            errors.append("Add at least one valid ingredient.")

        total_ml = sum(item["amount_ml"] for item in parsed_ingredients)
        if parsed_ingredients and total_ml <= 0:
            errors.append("Total ingredient volume must be greater than zero.")

        if not errors:
            results = calculate_scaled_recipe(parsed_ingredients, output_unit)

    return render_template(
        "index.html",
        errors=errors,
        ingredient_rows=ingredient_rows,
        output_unit=output_unit,
        results=results,
        unit_order=UNIT_ORDER,
        unit_labels=UNIT_LABELS,
        target_gallons=round(TARGET_COOLER_ML / UNIT_TO_ML["gallons"], 1),
    )


if __name__ == "__main__":
    app.run(debug=True)

