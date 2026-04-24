#! python3
from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import Flask, render_template, request

app = Flask(__name__)

DEFAULT_COOLER_GALLONS = 5.0
TARGET_COOLER_ML = DEFAULT_COOLER_GALLONS * 3785.41
MAX_IMPORT_BYTES = 1_000_000

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
FRACTION_RE = re.compile(
    r"^(?P<whole>\d+)\s+(?P<num>\d+)/(?P<den>\d+)$|^(?P<frac_num>\d+)/(?P<frac_den>\d+)$"
)
AMOUNT_RE = re.compile(
    r"^(?P<amount>\d+(?:\.\d+)?|\d+\s+\d+/\d+|\d+/\d+)\s*(?P<rest>.*)$"
)
JSON_LD_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(?P<json>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

COMMON_INGREDIENT_SIZES = [
    {"name": "Vodka", "amount": 1.75, "unit": "liters", "label": "Vodka handle (1.75L)"},
    {"name": "Vodka", "amount": 750, "unit": "ml", "label": "Vodka bottle (750mL)"},
    {"name": "Vodka", "amount": 1, "unit": "liters", "label": "Vodka bottle (1L)"},
    {"name": "Club Soda", "amount": 2, "unit": "liters", "label": "Club soda (2L)"},
    {"name": "Orange Juice", "amount": 52, "unit": "oz", "label": "Orange juice (52oz)"},
]


def normalize_unit(raw_unit: str) -> str | None:
    return UNIT_ALIASES.get(raw_unit.strip().lower())


def parse_amount(raw_amount: str) -> float | None:
    cleaned = raw_amount.strip()
    if not cleaned:
        return None

    fraction_match = FRACTION_RE.match(cleaned)
    if fraction_match:
        if fraction_match.group("whole"):
            whole = float(fraction_match.group("whole"))
            numerator = float(fraction_match.group("num"))
            denominator = float(fraction_match.group("den"))
            if denominator == 0:
                return None
            return whole + (numerator / denominator)
        numerator = float(fraction_match.group("frac_num"))
        denominator = float(fraction_match.group("frac_den"))
        if denominator == 0:
            return None
        return numerator / denominator

    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_ingredient_line(line: str) -> dict[str, Any] | None:
    normalized = re.sub(r"\s+", " ", line.strip())
    if not normalized:
        return None

    normalized = normalized.replace("—", "-").replace("–", "-")
    normalized = re.sub(r"(\d)([A-Za-z])", r"\1 \2", normalized)

    named_parts = re.match(r"^(?P<name>[^:-]+?)\s*[:\-]\s*(?P<amount_part>.+)$", normalized)
    if named_parts:
        parsed = _parse_amount_unit_name(named_parts.group("amount_part"))
        if not parsed:
            return None
        parsed["name"] = named_parts.group("name").strip()
        return parsed

    return _parse_amount_unit_name(normalized)


def _parse_amount_unit_name(text: str) -> dict[str, Any] | None:
    amount_match = AMOUNT_RE.match(text.strip())
    if not amount_match:
        return None

    amount = parse_amount(amount_match.group("amount"))
    if amount is None or amount <= 0:
        return None

    rest = amount_match.group("rest").strip(" ,.")
    if not rest:
        return None

    rest_parts = rest.split(maxsplit=1)
    unit_key = normalize_unit(rest_parts[0].strip(" ,.;:"))
    if not unit_key:
        return None

    name = rest_parts[1].strip(" ,.") if len(rest_parts) > 1 else ""
    if name.lower().startswith("of "):
        name = name[3:].strip()
    if not name:
        return None

    return {"name": name, "amount": amount, "unit": unit_key}


def extract_recipe_lines_from_json_ld(page_html: str) -> list[str]:
    extracted: list[str] = []
    for match in JSON_LD_RE.finditer(page_html):
        payload = match.group("json").strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        _collect_recipe_ingredients(data, extracted)

    deduped: list[str] = []
    for line in extracted:
        if line not in deduped:
            deduped.append(line)
    return deduped


def _collect_recipe_ingredients(node: Any, sink: list[str]) -> None:
    if isinstance(node, dict):
        ingredients = node.get("recipeIngredient")
        if isinstance(ingredients, list):
            for ingredient in ingredients:
                if isinstance(ingredient, str) and ingredient.strip():
                    sink.append(ingredient.strip())
        for value in node.values():
            _collect_recipe_ingredients(value, sink)
        return
    if isinstance(node, list):
        for item in node:
            _collect_recipe_ingredients(item, sink)


def extract_recipe_lines_from_html(page_html: str) -> list[str]:
    li_matches = re.findall(r"<li[^>]*>(.*?)</li>", page_html, flags=re.IGNORECASE | re.DOTALL)
    candidates: list[str] = []
    for item in li_matches:
        stripped = re.sub(r"<[^>]+>", " ", item)
        line = re.sub(r"\s+", " ", stripped).strip()
        if line:
            candidates.append(line)
    return candidates


def fetch_recipe_lines_from_url(recipe_url: str) -> list[str]:
    parsed = urlparse(recipe_url)
    if parsed.scheme not in {"http", "https"}:
        msg = "Recipe URL must start with http:// or https://."
        raise ValueError(msg)

    try:
        request_obj = Request(
            recipe_url, headers={"User-Agent": "DrinkCalculator/1.0 (+https://example.local)"}
        )
        with urlopen(request_obj, timeout=10) as response:
            raw_bytes = response.read(MAX_IMPORT_BYTES + 1)
            if len(raw_bytes) > MAX_IMPORT_BYTES:
                msg = "Recipe page is too large to import."
                raise ValueError(msg)
            content_type = response.headers.get_content_charset() or "utf-8"
    except (URLError, OSError) as exc:
        msg = f"Could not fetch recipe URL: {exc}"
        raise ValueError(msg) from exc

    page_html = raw_bytes.decode(content_type, errors="replace")
    lines = extract_recipe_lines_from_json_ld(page_html)
    if lines:
        return lines
    return extract_recipe_lines_from_html(page_html)


def import_ingredient_rows_from_url(recipe_url: str) -> list[dict[str, Any]]:
    raw_lines = fetch_recipe_lines_from_url(recipe_url)
    parsed_rows: list[dict[str, Any]] = []
    for line in raw_lines:
        parsed = parse_ingredient_line(line)
        if not parsed:
            continue
        parsed_rows.append(
            {
                "name": parsed["name"],
                "amount": str(parsed["amount"]),
                "unit": parsed["unit"],
            }
        )
    if not parsed_rows:
        msg = "Could not find measurable ingredients at that URL."
        raise ValueError(msg)
    return parsed_rows


def parse_ingredients(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    parsed_ingredients: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        name = row["name"]
        amount_raw = row["amount"]
        unit_raw = row["unit"]

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

        amount_value = parse_amount(amount_raw)
        if amount_value is None:
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
    return parsed_ingredients, errors


def calculate_scaled_recipe(
    ingredients: list[dict[str, Any]], output_unit: str, target_ml: float = TARGET_COOLER_ML
) -> list[dict[str, Any]]:
    total_ml = sum(item["amount_ml"] for item in ingredients)
    multiplier = target_ml / total_ml
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
    recipe_url = ""
    cooler_gallons_input = str(DEFAULT_COOLER_GALLONS)
    ingredient_rows = [{"name": "", "amount": "", "unit": "oz"}]

    if request.method == "POST":
        action = request.form.get("action", "scale")
        recipe_url = request.form.get("recipe_url", "").strip()
        cooler_gallons_input = request.form.get(
            "cooler_gallons", str(DEFAULT_COOLER_GALLONS)
        ).strip()
        output_unit = normalize_unit(request.form.get("output_unit", "oz")) or "oz"

        cooler_gallons = parse_amount(cooler_gallons_input)
        if cooler_gallons is None or cooler_gallons <= 0:
            errors.append("Cooler size must be a number greater than zero.")
            cooler_gallons = DEFAULT_COOLER_GALLONS

        if action == "import":
            if not recipe_url:
                errors.append("Enter a recipe URL before importing.")
            else:
                try:
                    ingredient_rows = import_ingredient_rows_from_url(recipe_url)
                except ValueError as exc:
                    errors.append(str(exc))
                    ingredient_rows = [{"name": "", "amount": "", "unit": "oz"}]
        else:
            names = request.form.getlist("name")
            amounts = request.form.getlist("amount")
            units = request.form.getlist("unit")
            ingredient_rows = []
            for name, amount_raw, unit_raw in zip(names, amounts, units):
                ingredient_rows.append(
                    {
                        "name": name,
                        "amount": amount_raw,
                        "unit": normalize_unit(unit_raw or "oz") or "oz",
                    }
                )

        parsed_ingredients, parsing_errors = parse_ingredients(ingredient_rows)
        errors.extend(parsing_errors)
        if not parsed_ingredients:
            errors.append("Add at least one valid ingredient.")

        total_ml = sum(item["amount_ml"] for item in parsed_ingredients)
        if parsed_ingredients and total_ml <= 0:
            errors.append("Total ingredient volume must be greater than zero.")

        if not errors:
            results = calculate_scaled_recipe(
                parsed_ingredients,
                output_unit,
                target_ml=cooler_gallons * UNIT_TO_ML["gallons"],
            )

    return render_template(
        "index.html",
        errors=errors,
        ingredient_rows=ingredient_rows,
        output_unit=output_unit,
        recipe_url=recipe_url,
        cooler_gallons_input=cooler_gallons_input,
        results=results,
        unit_order=UNIT_ORDER,
        unit_labels=UNIT_LABELS,
        target_gallons=DEFAULT_COOLER_GALLONS,
        common_ingredient_sizes=COMMON_INGREDIENT_SIZES,
    )


if __name__ == "__main__":
    app.run(debug=True)

