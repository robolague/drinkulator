from __future__ import annotations

import pytest

from main import TARGET_COOLER_ML, UNIT_TO_ML, app, calculate_scaled_recipe, normalize_unit


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_normalize_unit_handles_aliases():
    assert normalize_unit("  Ounces ") == "oz"
    assert normalize_unit("L") == "liters"
    assert normalize_unit("unknown") is None


def test_calculate_scaled_recipe_scales_to_cooler_size():
    ingredients = [
        {"name": "Vodka", "amount_ml": UNIT_TO_ML["oz"] * 2},
        {"name": "Orange Juice", "amount_ml": UNIT_TO_ML["oz"] * 4},
    ]

    results = calculate_scaled_recipe(ingredients, "oz")

    total_output_ml = sum(item["amount"] * UNIT_TO_ML["oz"] for item in results)
    assert round(total_output_ml, 2) == round(TARGET_COOLER_ML, 2)
    assert [item["name"] for item in results] == ["Vodka", "Orange Juice"]


def test_index_get_renders_form(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Drink Calculator" in body
    assert "Recipe Input" in body


def test_index_post_shows_validation_errors(client):
    response = client.post(
        "/",
        data={
            "name": ["", "Vodka"],
            "amount": ["1", "-2"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
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
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Scaled Recipe" in body
    assert "Vodka" in body
    assert "Orange Juice" in body
