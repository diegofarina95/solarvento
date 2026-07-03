import respx
import pytest
from httpx import Response

from app.cache import TTLCache
from app.pricing.calculate_system_cost import calculate_system_cost
from app.pricing.countries import COUNTRIES, country_for_coordinates, normalize_country_code
from app.pricing.default_prices import DEFAULT_PRICING_BY_COUNTRY
from app.pricing.fetch_prices import PricingService
from app.pricing.providers import provider_names


def test_country_inference_and_fallback():
    assert country_for_coordinates(40.4168, -3.7038).code == "ES"
    assert country_for_coordinates(48.8566, 2.3522).code == "FR"
    assert country_for_coordinates(50.8503, 4.3517).code == "BE"
    assert normalize_country_code("BE") == "BE"
    assert normalize_country_code("uk") == "GB"
    assert normalize_country_code("EL") == "GR"
    assert normalize_country_code("US") == "EU"


def test_pricing_catalog_covers_supported_countries():
    country_codes = set(COUNTRIES) - {"EU"}
    assert country_codes <= set(DEFAULT_PRICING_BY_COUNTRY)
    assert all(provider_names(code) for code in country_codes)


def test_default_pricing_calculates_ranges():
    pricing = {
        "source_type": "market_average",
        "turnkey_cost_per_kwp": {"low": 1050, "medium": 1250, "high": 1450},
        "battery_price_per_kwh": {"low": 550, "medium": 650, "high": 780},
        "panel_price_per_w": {"low": 0.18, "medium": 0.24, "high": 0.32},
        "inverter_price_per_kwp": {"low": 115, "medium": 160, "high": 230},
        "mounting_price_per_kwp": {"low": 140, "medium": 190, "high": 260},
        "labour_price_per_kwp": {"low": 260, "medium": 360, "high": 500},
    }

    result = calculate_system_cost(
        pricing,
        power_kwp=4.5,
        panel_power_w=450,
        battery_options_kwh=[5, 10],
    )

    # Media ajustada al tamaño (4.5 kWp → factor (5/4.5)^0.3 ≈ 1.0321) y rango
    # típico de presupuestos -12%/+15%, no el min-max de mercado
    factor = (5.0 / 4.5) ** 0.3
    adjusted_kwp = round(1250 * factor, 2)
    assert result["turnkey_cost_per_kwp"]["medium"] == pytest.approx(adjusted_kwp, abs=0.02)
    assert result["system_cost_range"]["medium"] == pytest.approx(adjusted_kwp * 4.5, abs=0.1)
    assert result["system_cost_range"]["low"] == pytest.approx(
        adjusted_kwp * 0.88 * 4.5, abs=0.5
    )
    assert result["system_cost_range"]["high"] == pytest.approx(
        adjusted_kwp * 1.15 * 4.5, abs=0.5
    )
    # La horquilla típica es más estrecha que la banda de mercado completa
    market_width = (1450 - 1050) * 4.5
    typical_width = result["system_cost_range"]["high"] - result["system_cost_range"]["low"]
    assert typical_width < market_width
    assert result["panel_price_per_panel"]["medium"] == 108.0
    # Batería de 5 kWh: más cara por kWh que la media de mercado (a 10 kWh)
    battery_5 = result["battery_option_costs"][0]
    assert battery_5["battery_kwh"] == 5
    per_kwh_5 = 650 * (10.0 / 5.0) ** 0.15
    assert battery_5["investment_range"]["medium"] == pytest.approx(
        result["system_cost_range"]["medium"] + per_kwh_5 * 5, rel=0.001
    )


def test_manual_overrides_do_not_replace_component_catalogue():
    pricing = {
        "source_type": "market_average",
        "turnkey_cost_per_kwp": {"low": 1050, "medium": 1250, "high": 1450},
        "battery_price_per_kwh": {"low": 550, "medium": 650, "high": 780},
        "panel_price_per_w": {"low": 0.18, "medium": 0.24, "high": 0.32},
        "inverter_price_per_kwp": {"low": 115, "medium": 160, "high": 230},
        "mounting_price_per_kwp": {"low": 140, "medium": 190, "high": 260},
        "labour_price_per_kwp": {"low": 260, "medium": 360, "high": 500},
    }

    result = calculate_system_cost(
        pricing,
        power_kwp=4,
        panel_power_w=450,
        battery_options_kwh=[5],
        cost_per_kwp=1400,
        battery_cost_per_kwh=700,
    )

    assert result["system_cost_source"] == "manual"
    assert result["battery_cost_source"] == "manual"
    assert result["system_cost_range"]["medium"] == 5600
    assert result["battery_option_costs"][0]["investment_range"]["medium"] == 9100
    assert result["panel_price_per_panel"]["medium"] == 108.0


async def test_pricing_service_uses_country_market_average_without_feed(tmp_path):
    service = PricingService(TTLCache(tmp_path / "pricing.db", 7 * 24 * 3600))
    try:
        quote = await service.get_prices(COUNTRIES["BE"])
    finally:
        await service.close()

    assert quote["country_code"] == "BE"
    assert quote["source_type"] == "market_average"
    assert quote["fallback_used"] is True
    # BE verificado jul-2026 (comparadores nacionales): 1000/1400/1800
    assert quote["turnkey_cost_per_kwp"]["medium"] == 1400.0
    assert quote["provider_names"]


@respx.mock
async def test_pricing_service_aggregates_provider_feed(tmp_path):
    feed_url = "https://prices.example.test/feed.json"
    respx.get(feed_url).mock(
        return_value=Response(
            200,
            json={
                "records": [
                    {
                        "provider_name": "Provider A",
                        "country_code": "ES",
                        "updated_at": "2026-07-01",
                        "turnkey_cost_per_kwp": 1200,
                        "battery_price_per_kwh": 620,
                    },
                    {
                        "provider_name": "Provider B",
                        "country_code": "ES",
                        "updated_at": "2026-07-02",
                        "turnkey_cost_per_kwp": 1400,
                        "battery_price_per_kwh": 700,
                    },
                ]
            },
        )
    )
    service = PricingService(TTLCache(tmp_path / "pricing.db", 7 * 24 * 3600), feed_url=feed_url)
    try:
        quote = await service.get_prices(COUNTRIES["ES"])
    finally:
        await service.close()

    assert quote["source_type"] == "providers"
    assert quote["fallback_used"] is False
    assert quote["provider_names"] == ["Provider A", "Provider B"]
    assert quote["updated_at"] == "2026-07-02"
    assert quote["turnkey_cost_per_kwp"] == {"low": 1200.0, "medium": 1300.0, "high": 1400.0}
    assert quote["battery_price_per_kwh"] == {"low": 620.0, "medium": 660.0, "high": 700.0}


def test_europe_bounds_exclude_north_africa_but_keep_islands():
    from app.pricing.countries import ensure_european_location

    # Dentro: península, Canarias, Madeira, Azores, Creta, Malta, Chipre
    for lat, lon in [(40.4, -3.7), (28.1, -15.4), (32.7, -16.9), (37.7, -25.7),
                     (35.3, 25.1), (35.9, 14.5), (35.1, 33.4)]:
        assert ensure_european_location(lat, lon), (lat, lon)
    # Fuera: Marrakech, El Cairo, Tel Aviv, Nueva York
    for lat, lon in [(31.6, -8.0), (30.0, 31.2), (32.1, 34.8), (40.7, -74.0)]:
        assert not ensure_european_location(lat, lon), (lat, lon)


def test_electricity_tax_factor_present_for_verified_countries():
    from app.pricing.default_prices import ELECTRICITY_TAX_FACTOR_BY_COUNTRY

    assert ELECTRICITY_TAX_FACTOR_BY_COUNTRY["ES"] == pytest.approx(1.27, abs=0.01)
    # Solo países con dato verificado; el resto no corrige (factor 1.0)
    assert "MD" not in ELECTRICITY_TAX_FACTOR_BY_COUNTRY


def test_quote_includes_electricity_tax_factor():
    from app.pricing.fetch_prices import _build_quote

    spain = country_for_coordinates(40.4, -3.7, None)
    quote = _build_quote(spain, [])
    assert quote["electricity_tax_factor"] == pytest.approx(1.27, abs=0.01)

    poland = country_for_coordinates(52.2, 21.0, None)
    quote_pl = _build_quote(poland, [])
    assert quote_pl["electricity_tax_factor"] == 1.0
