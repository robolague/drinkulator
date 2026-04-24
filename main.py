#! python3
from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import Flask, Response, g, render_template, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

app = Flask(__name__)

DEFAULT_COOLER_GALLONS = 5.0
US_FLUID_OUNCE_ML = 29.5735295625
US_GALLON_ML = 3785.411784
TARGET_COOLER_ML = DEFAULT_COOLER_GALLONS * US_GALLON_ML
MAX_IMPORT_BYTES = 1_000_000
METRICS_EXCLUDED_PATHS = {"/metrics"}

HTTP_SERVER_REQUESTS = Counter(
    "http_server_requests",
    "Total number of HTTP server requests.",
    ["http_request_method", "http_route", "http_response_status_code"],
)
HTTP_SERVER_REQUEST_DURATION_SECONDS = Histogram(
    "http_server_request_duration_seconds",
    "Duration of inbound HTTP requests in seconds.",
    ["http_request_method", "http_route", "http_response_status_code"],
)
HTTP_SERVER_ACTIVE_REQUESTS = Gauge(
    "http_server_active_requests",
    "In-flight HTTP server requests.",
    ["http_request_method", "http_route"],
)
DRINK_CALCULATOR_SCALE_REQUESTS = Counter(
    "drink_calculator_scale_requests",
    "Drink scale request outcomes.",
    ["source", "result"],
)
DRINK_CALCULATOR_SCALE_INPUT_ROWS = Histogram(
    "drink_calculator_scale_input_rows",
    "Ingredient row count submitted for scaling.",
    ["source"],
)
DRINK_CALCULATOR_SCALE_RESULT_ROWS = Histogram(
    "drink_calculator_scale_result_rows",
    "Scaled ingredient count returned by successful requests.",
    ["source"],
)
DRINK_CALCULATOR_RECIPE_IMPORTS = Counter(
    "drink_calculator_recipe_imports",
    "Recipe import outcomes.",
    ["result"],
)

UNIT_TO_ML = {
    "ml": 1.0,
    "oz": US_FLUID_OUNCE_ML,
    "tbsp": US_FLUID_OUNCE_ML / 2,
    "tsp": US_FLUID_OUNCE_ML / 6,
    "liters": 1000.0,
    "shots": US_FLUID_OUNCE_ML * 1.5,
    "handles": 1750.0,
    "cups": US_FLUID_OUNCE_ML * 8,
    "gallons": US_GALLON_ML,
    "quarts": US_GALLON_ML / 4,
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
    r"^(?P<amount>\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(?P<rest>.*)$"
)
JSON_LD_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(?P<json>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
RECIPE_INGREDIENT_ITEMPROP_RE = re.compile(
    r"<[^>]*itemprop=[\"']recipeIngredient[\"'][^>]*>(?P<value>.*?)</[^>]+>",
    re.IGNORECASE | re.DOTALL,
)
RECIPE_INGREDIENT_LIST_RE = re.compile(
    r"<(?:ul|ol)[^>]*(?:id|class)=[\"'][^\"']*ingredient[^\"']*[\"'][^>]*>"
    r"(?P<body>.*?)</(?:ul|ol)>",
    re.IGNORECASE | re.DOTALL,
)
LIST_ITEM_RE = re.compile(r"<li[^>]*>(?P<item>.*?)</li>", re.IGNORECASE | re.DOTALL)

PURCHASE_SIZE_PRESETS = [
    {
        "unit": "cans_12oz",
        "label": "Cans (12oz)",
        "size_ml": 355.0,
    },
    {"unit": "bottles_375ml", "label": "Bottles (375mL)", "size_ml": 375.0},
    {"unit": "bottles_750ml", "label": "Bottles (750mL)", "size_ml": 750.0},
    {"unit": "bottles_1l", "label": "Bottles (1L)", "size_ml": 1000.0},
    {"unit": "handles", "label": "Handles (1.75L)", "size_ml": 1750.0},
    {"unit": "bottles_2l", "label": "Bottles (2L)", "size_ml": 2000.0},
    {"unit": "jugs_1gal", "label": "Jugs (1 gallon)", "size_ml": UNIT_TO_ML["gallons"]},
]
DEFAULT_PURCHASE_UNIT = "bottles_750ml"


def _should_track_request_metrics() -> bool:
    if request.path in METRICS_EXCLUDED_PATHS:
        return False
    if request.endpoint == "static":
        return False
    return True


def _get_request_route() -> str:
    if request.url_rule and request.url_rule.rule:
        return request.url_rule.rule
    if request.endpoint:
        return request.endpoint
    return "unknown"


@app.before_request
def _record_http_metrics_on_request_start() -> None:
    if not _should_track_request_metrics():
        g.metrics_tracked = False
        return

    method = request.method.upper()
    route = _get_request_route()
    g.metrics_tracked = True
    g.metrics_http_method = method
    g.metrics_http_route = route
    g.metrics_started_at = time.perf_counter()
    HTTP_SERVER_ACTIVE_REQUESTS.labels(
        http_request_method=method,
        http_route=route,
    ).inc()


@app.after_request
def _record_http_metrics_on_request_end(response: Response) -> Response:
    if not getattr(g, "metrics_tracked", False):
        return response

    method = getattr(g, "metrics_http_method", "UNKNOWN")
    route = getattr(g, "metrics_http_route", "unknown")
    status = str(response.status_code)

    HTTP_SERVER_REQUESTS.labels(
        http_request_method=method,
        http_route=route,
        http_response_status_code=status,
    ).inc()

    started_at = getattr(g, "metrics_started_at", None)
    if started_at is not None:
        HTTP_SERVER_REQUEST_DURATION_SECONDS.labels(
            http_request_method=method,
            http_route=route,
            http_response_status_code=status,
        ).observe(max(0.0, time.perf_counter() - started_at))
    return response


@app.teardown_request
def _record_http_metrics_after_teardown(_exception: BaseException | None) -> None:
    if not getattr(g, "metrics_tracked", False):
        return
    method = getattr(g, "metrics_http_method", "UNKNOWN")
    route = getattr(g, "metrics_http_route", "unknown")
    HTTP_SERVER_ACTIVE_REQUESTS.labels(
        http_request_method=method,
        http_route=route,
    ).dec()


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

    named_parts = re.match(
        r"^(?P<name>[^:-]+?)\s*[:\-]\s*(?P<amount_part>.+)$",
        normalized,
    )
    if named_parts:
        parsed = _parse_amount_unit(named_parts.group("amount_part"))
        if parsed is None:
            return None
        return {
            "name": named_parts.group("name").strip(),
            "amount": parsed[0],
            "unit": parsed[1],
        }

    return _parse_amount_unit_name(normalized)


def _parse_amount_unit(text: str) -> tuple[float, str] | None:
    amount_match = AMOUNT_RE.match(text.strip())
    if not amount_match:
        return None

    amount = parse_amount(amount_match.group("amount"))
    if amount is None or amount <= 0:
        return None

    rest = amount_match.group("rest").strip(" ,.")
    if not rest:
        return None

    unit_token = rest.split(maxsplit=1)[0].strip(" ,.;:")
    unit_key = normalize_unit(unit_token)
    if not unit_key:
        return None
    return amount, unit_key


def _parse_amount_unit_name(text: str) -> dict[str, Any] | None:
    parsed = _parse_amount_unit(text)
    if parsed is None:
        return None
    amount, unit_key = parsed

    rest = AMOUNT_RE.match(text.strip()).group("rest").strip(" ,.")
    rest_parts = rest.split(maxsplit=1)

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
    return _dedupe_lines(extracted)


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


def _dedupe_lines(lines: list[str]) -> list[str]:
    deduped: list[str] = []
    for line in lines:
        if line and line not in deduped:
            deduped.append(line)
    return deduped


def _clean_html_text(raw_html: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", raw_html)
    return re.sub(r"\s+", " ", without_tags).strip()


def _extract_li_text(page_html: str) -> list[str]:
    lines: list[str] = []
    for item_match in LIST_ITEM_RE.finditer(page_html):
        line = _clean_html_text(item_match.group("item"))
        if line:
            lines.append(line)
    return lines


def extract_recipe_lines_from_html(page_html: str) -> list[str]:
    candidates: list[str] = []
    for itemprop_match in RECIPE_INGREDIENT_ITEMPROP_RE.finditer(page_html):
        line = _clean_html_text(itemprop_match.group("value"))
        if line:
            candidates.append(line)

    for list_match in RECIPE_INGREDIENT_LIST_RE.finditer(page_html):
        candidates.extend(_extract_li_text(list_match.group("body")))

    if not candidates:
        candidates = _extract_li_text(page_html)

    deduped_candidates = _dedupe_lines(candidates)
    measurable_lines = [
        line for line in deduped_candidates if parse_ingredient_line(line) is not None
    ]
    if measurable_lines:
        return measurable_lines
    return deduped_candidates


def _is_disallowed_host_ip(
    host_ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return (
        host_ip.is_private
        or host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_multicast
        or host_ip.is_reserved
        or host_ip.is_unspecified
    )


def _resolve_host_ip_addresses(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        host_records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []

    resolved_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for host_record in host_records:
        socket_address = host_record[4]
        resolved_host = socket_address[0]
        try:
            resolved_ip = ipaddress.ip_address(resolved_host)
        except ValueError:
            continue
        resolved_addresses.append(resolved_ip)
    return resolved_addresses


def _validate_public_recipe_host(hostname: str | None) -> None:
    if not hostname:
        msg = "Recipe URL must include a hostname."
        raise ValueError(msg)

    normalized_host = hostname.strip().lower()
    if normalized_host == "localhost":
        msg = "Recipe URL host is not allowed for security reasons."
        raise ValueError(msg)

    try:
        literal_host_ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        literal_host_ip = None

    if literal_host_ip is not None:
        if _is_disallowed_host_ip(literal_host_ip):
            msg = "Recipe URL host is not allowed for security reasons."
            raise ValueError(msg)
        return

    for resolved_ip in _resolve_host_ip_addresses(hostname):
        if _is_disallowed_host_ip(resolved_ip):
            msg = "Recipe URL host is not allowed for security reasons."
            raise ValueError(msg)


def fetch_recipe_lines_from_url(recipe_url: str) -> list[str]:
    parsed = urlparse(recipe_url)
    if parsed.scheme not in {"http", "https"}:
        msg = "Recipe URL must start with http:// or https://."
        raise ValueError(msg)
    _validate_public_recipe_host(parsed.hostname)

    try:
        request_obj = Request(recipe_url, headers={"User-Agent": "DrinkCalculator/1.0"})
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


def get_purchase_preset(purchase_unit: str) -> dict[str, Any]:
    for preset in PURCHASE_SIZE_PRESETS:
        if preset["unit"] == purchase_unit:
            return preset
    return get_purchase_preset(DEFAULT_PURCHASE_UNIT)


def get_purchase_option_with_fallback(purchase_unit: str) -> dict[str, Any]:
    return get_purchase_preset(purchase_unit)


def calculate_purchase_count(scaled_ml: float, purchase_option: dict[str, Any]) -> int:
    return max(1, math.ceil(scaled_ml / purchase_option["size_ml"]))


def make_ingredient_slug(name: str, index: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not base:
        base = "ingredient"
    return f"{base}-{index}"


def default_purchase_unit_for_amount(
    scaled_ml: float, default_purchase_unit: str
) -> str:
    if scaled_ml >= 1500 and any(
        item["unit"] == "handles" for item in PURCHASE_SIZE_PRESETS
    ):
        return "handles"
    if scaled_ml <= 355.0 and any(
        item["unit"] == "cans_12oz" for item in PURCHASE_SIZE_PRESETS
    ):
        return "cans_12oz"
    return default_purchase_unit


def calculate_scaled_recipe(
    ingredients: list[dict[str, Any]],
    output_unit: str,
    target_ml: float = TARGET_COOLER_ML,
) -> list[dict[str, Any]]:
    total_ml = sum(item["amount_ml"] for item in ingredients)
    if total_ml <= 0:
        msg = "Total ingredient volume must be greater than zero."
        raise ValueError(msg)
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


def calculate_scaled_recipe_with_purchase_options(
    ingredients: list[dict[str, Any]],
    output_unit: str,
    selected_purchase_units: dict[str, str] | None = None,
    default_purchase_unit: str = DEFAULT_PURCHASE_UNIT,
    target_ml: float = TARGET_COOLER_ML,
) -> list[dict[str, Any]]:
    total_ml = sum(item["amount_ml"] for item in ingredients)
    if total_ml <= 0:
        msg = "Total ingredient volume must be greater than zero."
        raise ValueError(msg)
    multiplier = target_ml / total_ml
    output_factor = UNIT_TO_ML[output_unit]
    selected_purchase_units = selected_purchase_units or {}

    results: list[dict[str, Any]] = []
    for index, ingredient in enumerate(ingredients, start=1):
        scaled_ml = ingredient["amount_ml"] * multiplier
        output_amount = scaled_ml / output_factor
        slug = make_ingredient_slug(ingredient["name"], index)
        purchase_unit = selected_purchase_units.get(slug)
        if not purchase_unit:
            purchase_unit = default_purchase_unit_for_amount(
                scaled_ml,
                default_purchase_unit,
            )
        purchase_option = get_purchase_option_with_fallback(purchase_unit)
        purchase_count = calculate_purchase_count(scaled_ml, purchase_option)
        results.append(
            {
                "index": index,
                "slug": slug,
                "name": ingredient["name"],
                "amount": round(output_amount, 2),
                "scaled_ml": round(scaled_ml, 2),
                "purchase_unit": purchase_option["unit"],
                "purchase_count": purchase_count,
                "purchase_label": purchase_option["label"],
                "purchase_options": PURCHASE_SIZE_PRESETS,
            }
        )
    return results


def calculate_scaled_recipe_with_purchase_suggestions(
    ingredients: list[dict[str, Any]],
    output_unit: str,
    selected_purchase_units: dict[str, str] | None = None,
    default_purchase_unit: str = DEFAULT_PURCHASE_UNIT,
    target_ml: float = TARGET_COOLER_ML,
) -> list[dict[str, Any]]:
    return calculate_scaled_recipe_with_purchase_options(
        ingredients=ingredients,
        output_unit=output_unit,
        selected_purchase_units=selected_purchase_units,
        default_purchase_unit=default_purchase_unit,
        target_ml=target_ml,
    )


def build_scale_payload_from_rows(
    ingredient_rows: list[dict[str, str]],
    output_unit: str,
    default_purchase_unit: str,
    cooler_gallons_input: str,
    recipe_url: str,
    selected_purchase_units: dict[str, str] | None = None,
    source: str = "unknown",
) -> tuple[
    list[dict[str, str]],
    list[dict[str, Any]],
    list[str],
    str,
    str,
    str,
    str,
]:
    errors: list[str] = []
    selected_purchase_units = selected_purchase_units or {}
    DRINK_CALCULATOR_SCALE_INPUT_ROWS.labels(source=source).observe(len(ingredient_rows))
    if not any(item["unit"] == default_purchase_unit for item in PURCHASE_SIZE_PRESETS):
        default_purchase_unit = DEFAULT_PURCHASE_UNIT

    cooler_gallons = parse_amount(cooler_gallons_input)
    if cooler_gallons is None or cooler_gallons <= 0:
        errors.append("Cooler size must be a number greater than zero.")
        cooler_gallons = DEFAULT_COOLER_GALLONS

    parsed_ingredients, parsing_errors = parse_ingredients(ingredient_rows)
    errors.extend(parsing_errors)
    if not parsed_ingredients:
        errors.append("Add at least one valid ingredient.")

    total_ml = sum(item["amount_ml"] for item in parsed_ingredients)
    if parsed_ingredients and total_ml <= 0:
        errors.append("Total ingredient volume must be greater than zero.")

    results: list[dict[str, Any]] = []
    if not errors:
        selected_purchase_units_for_recipe: dict[str, str] = {}
        for index, ingredient in enumerate(parsed_ingredients, start=1):
            slug = make_ingredient_slug(ingredient["name"], index)
            submitted_purchase_unit = selected_purchase_units.get(slug, "").strip()
            if submitted_purchase_unit:
                selected_purchase_units_for_recipe[slug] = submitted_purchase_unit
        results = calculate_scaled_recipe_with_purchase_options(
            parsed_ingredients,
            output_unit,
            selected_purchase_units=selected_purchase_units_for_recipe,
            default_purchase_unit=default_purchase_unit,
            target_ml=cooler_gallons * UNIT_TO_ML["gallons"],
        )

    result = "success" if not errors else "validation_error"
    DRINK_CALCULATOR_SCALE_REQUESTS.labels(source=source, result=result).inc()
    if not errors:
        DRINK_CALCULATOR_SCALE_RESULT_ROWS.labels(source=source).observe(len(results))

    return (
        ingredient_rows,
        results,
        errors,
        output_unit,
        default_purchase_unit,
        recipe_url,
        cooler_gallons_input,
    )


def build_scale_payload_from_request(
    form_data: Any,
    source: str = "form",
) -> tuple[
    list[dict[str, str]],
    list[dict[str, Any]],
    list[str],
    str,
    str,
    str,
    str,
]:
    output_unit = normalize_unit(form_data.get("output_unit", "oz")) or "oz"
    default_purchase_unit = form_data.get(
        "default_purchase_unit",
        DEFAULT_PURCHASE_UNIT,
    ).strip()
    if not any(item["unit"] == default_purchase_unit for item in PURCHASE_SIZE_PRESETS):
        default_purchase_unit = DEFAULT_PURCHASE_UNIT

    recipe_url = form_data.get("recipe_url", "").strip()
    cooler_gallons_input = form_data.get(
        "cooler_gallons",
        str(DEFAULT_COOLER_GALLONS),
    ).strip()

    names = form_data.getlist("name")
    amounts = form_data.getlist("amount")
    units = form_data.getlist("unit")
    ingredient_rows: list[dict[str, str]] = []
    for name, amount_raw, unit_raw in zip(names, amounts, units):
        ingredient_rows.append(
            {
                "name": name,
                "amount": amount_raw,
                "unit": normalize_unit(unit_raw or "oz") or "oz",
            }
        )

    selected_purchase_units = {
        key.removeprefix("purchase_unit_"): value
        for key, value in form_data.items()
        if key.startswith("purchase_unit_")
    }
    return build_scale_payload_from_rows(
        ingredient_rows=ingredient_rows,
        output_unit=output_unit,
        default_purchase_unit=default_purchase_unit,
        cooler_gallons_input=cooler_gallons_input,
        recipe_url=recipe_url,
        selected_purchase_units=selected_purchase_units,
        source=source,
    )


@app.route("/", methods=["GET", "POST"])
def index() -> str:
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    output_unit = "oz"
    default_purchase_unit = DEFAULT_PURCHASE_UNIT
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
        default_purchase_unit = request.form.get(
            "default_purchase_unit",
            DEFAULT_PURCHASE_UNIT,
        ).strip()
        if not any(
            item["unit"] == default_purchase_unit for item in PURCHASE_SIZE_PRESETS
        ):
            default_purchase_unit = DEFAULT_PURCHASE_UNIT

        cooler_gallons = parse_amount(cooler_gallons_input)
        if cooler_gallons is None or cooler_gallons <= 0:
            errors.append("Cooler size must be a number greater than zero.")
            cooler_gallons = DEFAULT_COOLER_GALLONS

        if action == "import":
            if not recipe_url:
                errors.append("Enter a recipe URL before importing.")
                DRINK_CALCULATOR_RECIPE_IMPORTS.labels(result="validation_error").inc()
            else:
                try:
                    ingredient_rows = import_ingredient_rows_from_url(recipe_url)
                    DRINK_CALCULATOR_RECIPE_IMPORTS.labels(result="success").inc()
                    (
                        ingredient_rows,
                        results,
                        scale_errors,
                        output_unit,
                        default_purchase_unit,
                        recipe_url,
                        cooler_gallons_input,
                    ) = build_scale_payload_from_rows(
                        ingredient_rows=ingredient_rows,
                        output_unit=output_unit,
                        default_purchase_unit=default_purchase_unit,
                        cooler_gallons_input=cooler_gallons_input,
                        recipe_url=recipe_url,
                        source="import",
                    )
                    errors.extend(scale_errors)
                except ValueError as exc:
                    DRINK_CALCULATOR_RECIPE_IMPORTS.labels(result="fetch_error").inc()
                    errors.append(str(exc))
                    ingredient_rows = [{"name": "", "amount": "", "unit": "oz"}]
        else:
            (
                ingredient_rows,
                results,
                scale_errors,
                output_unit,
                default_purchase_unit,
                recipe_url,
                cooler_gallons_input,
            ) = build_scale_payload_from_request(request.form)
            errors.extend(scale_errors)

    return render_template(
        "index.html",
        errors=errors,
        ingredient_rows=ingredient_rows,
        output_unit=output_unit,
        default_purchase_unit=default_purchase_unit,
        purchase_size_presets=PURCHASE_SIZE_PRESETS,
        recipe_url=recipe_url,
        cooler_gallons_input=cooler_gallons_input,
        results=results,
        unit_order=UNIT_ORDER,
        unit_labels=UNIT_LABELS,
    )


@app.route("/scale-results", methods=["POST"])
def scale_results() -> str:
    (
        ingredient_rows,
        results,
        errors,
        output_unit,
        default_purchase_unit,
        recipe_url,
        cooler_gallons_input,
    ) = build_scale_payload_from_request(request.form, source="htmx")

    return render_template(
        "_scaled_results.html",
        errors=errors,
        ingredient_rows=ingredient_rows,
        output_unit=output_unit,
        default_purchase_unit=default_purchase_unit,
        recipe_url=recipe_url,
        cooler_gallons_input=cooler_gallons_input,
        results=results,
        unit_labels=UNIT_LABELS,
    )


@app.route("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    app.run(debug=True)
