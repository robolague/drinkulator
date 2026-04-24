from __future__ import annotations

import ipaddress
from urllib.error import URLError

import pytest

from main import (
    DEFAULT_COOLER_GALLONS,
    DRINKULATOR_INGREDIENT_USAGE,
    DRINKULATOR_RECIPE_IMPORTS,
    DRINKULATOR_SCALE_REQUESTS,
    PURCHASE_SIZE_PRESETS,
    TARGET_COOLER_ML,
    UNIT_TO_ML,
    app,
    build_scale_payload_from_request,
    build_scale_payload_from_rows,
    calculate_scaled_recipe,
    calculate_scaled_recipe_with_purchase_options,
    calculate_scaled_recipe_with_purchase_suggestions,
    extract_recipe_lines_from_html,
    extract_recipe_lines_from_json_ld,
    fetch_recipe_lines_from_url,
    import_ingredient_rows_from_url,
    normalize_unit,
    parse_amount,
    parse_ingredient_line,
    parse_ingredients,
)


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def _counter_total_value(counter, **labels: str) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name != f"{counter._name}_total":
                continue
            if all(sample.labels.get(key) == value for key, value in labels.items()):
                return float(sample.value)
    return 0.0


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


def test_extract_recipe_lines_from_html_prefers_ingredient_like_entries():
    html = """
    <ul>
        <li>Navigation Link</li>
        <li>2 oz Vodka</li>
        <li>Mix everything and serve.</li>
        <li>1/2 gallon Orange Juice</li>
    </ul>
    """
    assert extract_recipe_lines_from_html(html) == [
        "2 oz Vodka",
        "1/2 gallon Orange Juice",
    ]


def test_parse_ingredients_ignores_completely_blank_row():
    parsed, errors = parse_ingredients([{"name": " ", "amount": " ", "unit": "oz"}])
    assert parsed == []
    assert errors == []


def test_parse_ingredients_collects_validation_errors():
    parsed, errors = parse_ingredients(
        [
            {"name": "", "amount": "1", "unit": "oz"},
            {"name": "Vodka", "amount": "", "unit": "oz"},
            {"name": "Vodka", "amount": "abc", "unit": "oz"},
            {"name": "Vodka", "amount": "1", "unit": "bad"},
        ]
    )
    assert parsed == []
    assert errors == [
        "Ingredient 1: name is required.",
        "Ingredient 2: amount is required.",
        "Ingredient 3: amount must be numeric.",
        "Ingredient 4: unit 'bad' is not valid.",
    ]


class _FakeHeaders:
    def __init__(self, charset: str = "utf-8"):
        self._charset = charset

    def get_content_charset(self):
        return self._charset


class _FakeResponse:
    def __init__(self, body: bytes, charset: str = "utf-8"):
        self._body = body
        self.headers = _FakeHeaders(charset=charset)

    def read(self, _size: int) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_fetch_recipe_lines_from_url_rejects_invalid_scheme():
    with pytest.raises(
        ValueError, match="Recipe URL must start with http:// or https://."
    ):
        fetch_recipe_lines_from_url("ftp://example.com/recipe")


def test_fetch_recipe_lines_from_url_rejects_private_host(monkeypatch):
    monkeypatch.setattr(
        "main._resolve_host_ip_addresses",
        lambda _host: [ipaddress.ip_address("127.0.0.1")],
    )
    with pytest.raises(
        ValueError,
        match="Recipe URL host is not allowed for security reasons.",
    ):
        fetch_recipe_lines_from_url("https://localhost/recipe")


def test_fetch_recipe_lines_from_url_rejects_oversized_response(monkeypatch):
    monkeypatch.setattr("main._resolve_host_ip_addresses", lambda _host: [])
    monkeypatch.setattr(
        "main.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(b"a" * (1_000_000 + 1)),
    )
    with pytest.raises(ValueError, match="Recipe page is too large to import."):
        fetch_recipe_lines_from_url("https://example.com/recipe")


def test_fetch_recipe_lines_from_url_wraps_network_errors(monkeypatch):
    monkeypatch.setattr("main._resolve_host_ip_addresses", lambda _host: [])

    def _raise_error(*_args, **_kwargs):
        raise URLError("boom")

    monkeypatch.setattr("main.urlopen", _raise_error)
    with pytest.raises(ValueError, match="Could not fetch recipe URL:"):
        fetch_recipe_lines_from_url("https://example.com/recipe")


def test_fetch_recipe_lines_from_url_uses_json_ld_then_html_fallback(monkeypatch):
    monkeypatch.setattr("main._resolve_host_ip_addresses", lambda _host: [])
    monkeypatch.setattr(
        "main.urlopen",
        lambda *_args, **_kwargs: _FakeResponse(
            b"<html><body><ul><li>2 oz Vodka</li><li>No amount</li></ul></body></html>"
        ),
    )
    assert fetch_recipe_lines_from_url("https://example.com/recipe") == ["2 oz Vodka"]


def test_build_scale_payload_from_rows_handles_invalid_default_purchase_unit():
    ingredient_rows = [{"name": "Vodka", "amount": "2", "unit": "oz"}]
    (
        _rows,
        results,
        errors,
        _output_unit,
        default_purchase_unit,
        _recipe_url,
        _cooler_input,
    ) = build_scale_payload_from_rows(
        ingredient_rows=ingredient_rows,
        output_unit="oz",
        default_purchase_unit="not-a-real-unit",
        cooler_gallons_input="0.3",
        recipe_url="",
    )
    assert errors == []
    assert results
    assert default_purchase_unit == "bottles_750ml"
    assert results[0]["purchase_unit"] == "bottles_750ml"


def test_build_scale_payload_from_rows_reports_invalid_cooler_size():
    (
        _rows,
        results,
        errors,
        _output_unit,
        _default_purchase_unit,
        _recipe_url,
        _cooler_input,
    ) = build_scale_payload_from_rows(
        ingredient_rows=[{"name": "Vodka", "amount": "2", "unit": "oz"}],
        output_unit="oz",
        default_purchase_unit="bottles_750ml",
        cooler_gallons_input="-1",
        recipe_url="",
    )
    assert "Cooler size must be a number greater than zero." in errors
    assert results == []


def test_build_scale_payload_from_request_preserves_purchase_overrides():
    class _FakeForm:
        def __init__(self):
            self._data = {
                "output_unit": "oz",
                "default_purchase_unit": "bottles_750ml",
                "cooler_gallons": "5",
                "purchase_unit_vodka-1": "handles",
            }
            self._lists = {
                "name": ["Vodka"],
                "amount": ["2"],
                "unit": ["oz"],
            }

        def get(self, key, default=None):
            return self._data.get(key, default)

        def getlist(self, key):
            return self._lists.get(key, [])

        def items(self):
            return self._data.items()

    (
        _rows,
        results,
        errors,
        _output_unit,
        _default_purchase_unit,
        _recipe_url,
        _cooler_input,
    ) = build_scale_payload_from_request(_FakeForm())
    assert errors == []
    assert results
    assert results[0]["slug"] == "vodka-1"
    assert results[0]["purchase_unit"] == "handles"


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


def test_calculate_scaled_recipe_raises_when_total_volume_zero():
    with pytest.raises(
        ValueError,
        match="Total ingredient volume must be greater than zero.",
    ):
        calculate_scaled_recipe([], "oz")


def test_calculate_scaled_recipe_with_purchase_suggestions():
    ingredients = [{"name": "Vodka", "amount_ml": 1750.0}]

    results = calculate_scaled_recipe_with_purchase_suggestions(
        ingredients=ingredients,
        output_unit="liters",
        target_ml=3500.0,
        selected_purchase_units={"vodka-1": "handles"},
        default_purchase_unit="bottles_750ml",
    )

    assert results == [
        {
            "index": 1,
            "slug": "vodka-1",
            "name": "Vodka",
            "amount": 3.5,
            "scaled_ml": 3500.0,
            "purchase_unit": "handles",
            "purchase_count": 2,
            "purchase_label": "Handles (1.75L)",
            "purchase_options": PURCHASE_SIZE_PRESETS,
        }
    ]


def test_calculate_scaled_recipe_with_purchase_options_raises_when_total_volume_zero():
    with pytest.raises(
        ValueError,
        match="Total ingredient volume must be greater than zero.",
    ):
        calculate_scaled_recipe_with_purchase_options([], "oz")


def test_purchase_size_presets_include_common_units():
    keys = {item["unit"] for item in PURCHASE_SIZE_PRESETS}
    assert "cans_12oz" in keys
    assert "bottles_375ml" in keys
    assert "bottles_750ml" in keys
    assert "bottles_1l" in keys
    assert "handles" in keys
    assert "bottles_2l" in keys
    assert "jugs_1gal" in keys


def test_core_unit_conversions_match_us_customary_definitions():
    assert UNIT_TO_ML["oz"] == pytest.approx(29.5735295625)
    assert UNIT_TO_ML["gallons"] == pytest.approx(3785.411784)
    assert UNIT_TO_ML["cups"] == pytest.approx(236.5882365)
    assert UNIT_TO_ML["quarts"] == pytest.approx(946.352946)
    assert UNIT_TO_ML["tbsp"] == pytest.approx(14.78676478125)
    assert UNIT_TO_ML["tsp"] == pytest.approx(4.92892159375)


def test_index_get_renders_form(client):
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Drinkulator" in body
    assert f'value="{DEFAULT_COOLER_GALLONS}"' in body
    assert "Recipe Input" in body


def test_index_post_shows_validation_errors(client):
    response = client.post(
        "/",
        data={
            "name": ["", "Vodka"],
            "amount": ["1", "-2"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
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
    assert "purchase_unit_vodka-1" in body


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


def test_index_post_allows_per_ingredient_purchase_unit_override(client):
    response = client.post(
        "/",
        data={
            "name": ["Vodka", "Orange Juice"],
            "amount": ["2", "4"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "purchase_unit_vodka-1": "handles",
            "purchase_unit_orange-juice-2": "cans_12oz",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Handles (1.75L)" in body
    assert "Cans (12oz)" in body


def test_index_uses_htmx_for_live_purchase_size_updates(client):
    response = client.post(
        "/",
        data={
            "name": ["Vodka", "Orange Juice"],
            "amount": ["2", "4"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'src="https://unpkg.com/htmx.org@2.0.4"' in body
    assert 'hx-post="/scale-results"' in body
    assert "purchase-apply" not in body


def test_scale_results_returns_partial_with_updated_purchase_count(client):
    response = client.post(
        "/scale-results",
        data={
            "name": ["Vodka", "Orange Juice"],
            "amount": ["2", "4"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "cooler_gallons": "5",
            "purchase_unit_vodka-1": "handles",
            "purchase_unit_orange-juice-2": "cans_12oz",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<!doctype html>" not in body
    assert 'id="scaled-recipe-results"' in body
    assert 'id="purchase_vodka-1"' in body
    assert 'id="purchase_orange-juice-2"' in body
    assert "4</span> x" in body
    assert "36</span> x" in body


def test_metrics_endpoint_exposes_prometheus_metrics(client):
    client.get("/")
    client.post(
        "/",
        data={
            "name": ["Vodka", "Orange Juice"],
            "amount": ["2", "4"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    body = response.get_data(as_text=True)
    assert "http_server_requests_total" in body
    assert "http_server_request_duration_seconds_bucket" in body
    assert "drinkulator_scale_requests_total" in body
    assert "drinkulator_scale_input_rows_bucket" in body
    assert 'http_route="/metrics"' not in body


def test_scale_request_metrics_track_success_and_validation_errors(client):
    success_before = _counter_total_value(
        DRINKULATOR_SCALE_REQUESTS,
        source="form",
        result="success",
    )
    error_before = _counter_total_value(
        DRINKULATOR_SCALE_REQUESTS,
        source="form",
        result="validation_error",
    )

    client.post(
        "/",
        data={
            "name": ["", "Vodka"],
            "amount": ["1", "-2"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )
    client.post(
        "/",
        data={
            "name": ["Vodka", "Orange Juice"],
            "amount": ["2", "4"],
            "unit": ["oz", "oz"],
            "output_unit": "oz",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )

    success_after = _counter_total_value(
        DRINKULATOR_SCALE_REQUESTS,
        source="form",
        result="success",
    )
    error_after = _counter_total_value(
        DRINKULATOR_SCALE_REQUESTS,
        source="form",
        result="validation_error",
    )

    assert success_after >= success_before + 1
    assert error_after >= error_before + 1


def test_recipe_import_metrics_track_validation_error(client):
    error_before = _counter_total_value(
        DRINKULATOR_RECIPE_IMPORTS,
        result="validation_error",
    )

    response = client.post(
        "/",
        data={
            "recipe_url": "",
            "output_unit": "oz",
            "cooler_gallons": "5",
            "action": "import",
        },
    )

    assert response.status_code == 200
    error_after = _counter_total_value(
        DRINKULATOR_RECIPE_IMPORTS,
        result="validation_error",
    )
    assert error_after >= error_before + 1


def test_ingredient_usage_metric_tracks_popular_spirits(client):
    vodka_before = _counter_total_value(
        DRINKULATOR_INGREDIENT_USAGE,
        ingredient="vodka",
        source="form",
    )
    gin_before = _counter_total_value(
        DRINKULATOR_INGREDIENT_USAGE,
        ingredient="gin",
        source="form",
    )
    rum_before = _counter_total_value(
        DRINKULATOR_INGREDIENT_USAGE,
        ingredient="rum",
        source="form",
    )

    client.post(
        "/",
        data={
            "name": ["Vodka", "Gin", "Lime Juice"],
            "amount": ["2", "1", "3"],
            "unit": ["oz", "oz", "oz"],
            "output_unit": "oz",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )
    client.post(
        "/",
        data={
            "name": ["RUM", "vodka", "Cola"],
            "amount": ["2", "1", "4"],
            "unit": ["oz", "oz", "oz"],
            "output_unit": "oz",
            "cooler_gallons": "5",
            "action": "scale",
        },
    )

    vodka_after = _counter_total_value(
        DRINKULATOR_INGREDIENT_USAGE,
        ingredient="vodka",
        source="form",
    )
    gin_after = _counter_total_value(
        DRINKULATOR_INGREDIENT_USAGE,
        ingredient="gin",
        source="form",
    )
    rum_after = _counter_total_value(
        DRINKULATOR_INGREDIENT_USAGE,
        ingredient="rum",
        source="form",
    )

    assert vodka_after >= vodka_before + 2
    assert gin_after >= gin_before + 1
    assert rum_after >= rum_before + 1
