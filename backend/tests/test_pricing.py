import respx
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

    assert result["system_cost_range"] == {
        "low": 4725.0,
        "medium": 5625.0,
        "high": 6525.0,
    }
    assert result["panel_price_per_panel"]["medium"] == 108.0
    assert result["battery_option_costs"][0]["investment_range"]["medium"] == 8875.0


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
