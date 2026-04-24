from __future__ import annotations

import pytest

from main import (
    DEFAULT_COOLER_GALLONS,
    PURCHASE_SIZE_PRESETS,
    TARGET_COOLER_ML,
    UNIT_TO_ML,
    app,
    calculate_scaled_recipe,
    calculate_scaled_recipe_with_purchase_suggestions,
    extract_recipe_lines_from_json_ld,
    import_ingredient_rows_from_url,
    normalize_unit,
    parse_amount,
    parse_ingredient_line,
)


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_normalize_unit_handles_aliases():
    assert normalize_unit("  Ounces ") == "oz"
    assert normalize_unit("L") == "liters"
    assert normalize_unit("unknown") is None


def test_parse_amount_handles_fraction_values():
    assert parse_amount("1.5") == pytest.approx(1.5)
    assert parse_amount("1/2") == pytest.approx(0.5)
    assert parse_amount("1 1/2") == pytest.approx(1.5)
    assert parse_amount("invalid") is None


def test_parse_ingredient_line_supports_multiple_formats():
    assert parse_ingredient_line("2 oz Vodka") == {
        "name": "Vodka",
        "amount": 2.0,
        "unit": "oz",
    }
    assert parse_ingredient_line("Orange Juice: 1/2 gallon") == {
        "name": "Orange Juice",
        "amount": 0.5,
        "unit": "gallons",
    }
    assert parse_ingredient_line("not parseable") is None


def test_extract_recipe_lines_from_json_ld():
    html = """
    <script type="application/ld+json">
        {"@type":"Recipe","recipeIngredient":["2 oz Vodka", "4 oz Orange Juice"]}
    </script>
    """
    assert extract_recipe_lines_from_json_ld(html) == [
        "2 oz Vodka",
        "4 oz Orange Juice",
    ]


def test_import_ingredient_rows_from_url_parses_recipe(monkeypatch):
    sample_lines = ["2 oz Vodka", "4 oz Orange Juice", "pinch of salt"]
    monkeypatch.setattr("main.fetch_recipe_lines_from_url", lambda _url: sample_lines)

    imported = import_ingredient_rows_from_url("https://example.com/recipe")

    assert imported == [
        {"name": "Vodka", "amount": "2.0", "unit": "oz"},
        {"name": "Orange Juice", "amount": "4.0", "unit": "oz"},
    ]


def test_import_ingredient_rows_from_url_raises_when_nothing_parseable(monkeypatch):
    monkeypatch.setattr(
        "main.fetch_recipe_lines_from_url",
        lambda _url: ["dash bitters"],
    )

    with pytest.raises(ValueError, match="Could not find measurable ingredients"):
        import_ingredient_rows_from_url("https://example.com/recipe")


def test_calculate_scaled_recipe_scales_to_cooler_size():
    ingredients = [
        {"name": "Vodka", "amount_ml": UNIT_TO_ML["oz"] * 2},
        {"name": "Orange Juice", "amount_ml": UNIT_TO_ML["oz"] * 4},
    ]

    results = calculate_scaled_recipe(ingredients, "oz")

    total_output_ml = sum(item["amount"] * UNIT_TO_ML["oz"] for item in results)
    assert total_output_ml == pytest.approx(TARGET_COOLER_ML, abs=0.1)
    assert [item["name"] for item in results] == ["Vodka", "Orange Juice"]


def test_calculate_scaled_recipe_with_purchase_suggestions():
    ingredients = [
        {"name": "Vodka", "amount_ml": 1750.0},
    ]

    results = calculate_scaled_recipe_with_purchase_suggestions(
        ingredients=ingredients,
        output_unit="liters",
        target_ml=3500.0,
        purchase_unit="handles",
    )

    assert results == [
        {
            "name": "Vodka",
            "amount": 3.5,
            "purchase_count": 2,
            "purchase_label": "Handles (1.75L)",
        }
    ]


def test_purchase_size_presets_include_common_units():
    keys = {item["unit"] for item in PURCHASE_SIZE_PRESETS}
    assert "bottles_750ml" in keys
    assert "handles" in keys
    assert "bottles_2l" in keys


def test_index_get_renders_form(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Drink Calculator" in body
    assert f'value="{DEFAULT_COOLER_GALLONS}"' in body
    assert "Purchase size suggestions" in body
    assert "Recipe Input" in body


def test_index_post_shows_validation_errors(client):
    response = client.post(
        "/",
        data={
            "name": ["", "Vodka"],
            "amount": ["1", "-2"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "purchase_unit": "bottles_750ml",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Ingredient 1: name is required." in body
    assert "Ingredient 2: amount must be greater than zero." in body


def test_index_post_shows_scaled_recipe(client):
    response = client.post(
        "/",
        data={
            "name": ["Vodka", "Orange Juice"],
            "amount": ["2", "4"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "purchase_unit": "bottles_750ml",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Scaled Recipe" in body
    assert "Vodka" in body
    assert "Orange Juice" in body
    assert "Bottles (750mL)" in body


def test_index_post_imports_recipe_from_url(client, monkeypatch):
    monkeypatch.setattr(
        "main.import_ingredient_rows_from_url",
        lambda _url: [
            {"name": "Vodka", "amount": "2.0", "unit": "oz"},
            {"name": "Orange Juice", "amount": "4.0", "unit": "oz"},
        ],
    )
    response = client.post(
        "/",
        data={
            "recipe_url": "https://example.com/drink",
            "output_unit": "oz",
            "purchase_unit": "bottles_750ml",
            "cooler_gallons": "5",
            "action": "import",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Scaled Recipe" in body
    assert "Vodka" in body
    assert "Orange Juice" in body
    assert "Bottles (750mL)" in body
