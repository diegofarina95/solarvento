"""Fetch, cache and aggregate solar price assumptions."""

from datetime import date
from typing import Any

import httpx

from ..cache import TTLCache
from .countries import Country
from .default_prices import DEFAULT_PRICE_REVIEW_DATE, DEFAULT_PRICING_BY_COUNTRY
from .providers import ProviderPriceRecord, parse_provider_records, provider_names


RANGE_FIELDS = (
    "panel_price_per_w",
    "inverter_price_per_kwp",
    "battery_price_per_kwh",
    "mounting_price_per_kwp",
    "labour_price_per_kwp",
    "turnkey_cost_per_kwp",
)


class PricingService:
    """Country pricing service with 7-day cache and resilient fallback."""

    def __init__(
        self,
        cache: TTLCache,
        *,
        feed_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.cache = cache
        self.feed_url = feed_url
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()
        self.cache.close()

    async def get_prices(self, country: Country, *, force_refresh: bool = False) -> dict[str, Any]:
        key = f"pricing:{country.code}:v5"  # v5: +export_scheme, precios 2025 revisados
        if not force_refresh:
            cached = self.cache.get(key)
            if cached is not None:
                return cached

        records = await self._fetch_provider_records(country.code)
        quote = _build_quote(country, records or [])
        # Si el feed está configurado pero falló (records is None), no se cachea:
        # así un blip de red no congela el fallback genérico durante 7 días.
        if not (self.feed_url and records is None):
            self.cache.set(key, quote)
        return quote

    async def _fetch_provider_records(
        self, country_code: str
    ) -> list[ProviderPriceRecord] | None:
        """Registros del feed; [] si no hay feed, None si el feed falló."""
        if not self.feed_url:
            return []

        try:
            resp = await self._client.get(self.feed_url)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError):
            return None

        return parse_provider_records(payload, country_code)


def _build_quote(country: Country, records: list[ProviderPriceRecord]) -> dict[str, Any]:
    defaults = DEFAULT_PRICING_BY_COUNTRY.get(country.code) or DEFAULT_PRICING_BY_COUNTRY["EU"]
    has_provider_records = bool(records)
    quote: dict[str, Any] = {
        "country_code": country.code,
        "country_name": country.name,
        "currency": country.currency,
        "currency_symbol": country.currency_symbol,
        "vat_rate": _vat_rate(defaults, records),
        "vat_note": defaults["vat_note"],
        "installation_labour_factor": defaults["installation_labour_factor"],
        "surplus_price_eur_kwh": defaults["surplus_price_eur_kwh"],
        "electricity_price_kwh": defaults.get("electricity_price_kwh", 0.20),
        "export_scheme": defaults.get("export_scheme", "capped_compensation"),
        "source_type": "providers" if has_provider_records else "market_average",
        "fallback_used": not has_provider_records,
        "provider_names": _source_names(country.code, records),
        "updated_at": _updated_at(records).isoformat(),
        "cache_ttl_days": 7,
    }
    for field in RANGE_FIELDS:
        quote[field] = _range_from_records(defaults[field], records, field)
    return quote


def _source_names(country_code: str, records: list[ProviderPriceRecord]) -> list[str]:
    if records:
        return sorted({record.provider_name for record in records})
    names = provider_names(country_code)
    return names or provider_names("EU")


def _updated_at(records: list[ProviderPriceRecord]) -> date:
    if records:
        return max(record.updated_at for record in records)
    return DEFAULT_PRICE_REVIEW_DATE


def _vat_rate(defaults: dict[str, Any], records: list[ProviderPriceRecord]) -> float:
    rates = [record.vat_rate for record in records if record.vat_rate is not None]
    if not rates:
        return defaults["vat_rate"]
    return round(sum(rates) / len(rates), 4)


def _range_from_records(
    default_range: dict[str, float],
    records: list[ProviderPriceRecord],
    field: str,
) -> dict[str, float]:
    values = [
        value
        for value in (getattr(record, field) for record in records)
        if value is not None and value > 0
    ]
    if len(values) >= 2:
        return _clean_range(min(values), sum(values) / len(values), max(values))
    if len(values) == 1:
        # Blend a single source with the maintained market range; do not let one
        # external value become the whole cost model.
        value = values[0]
        low = min(default_range["low"], value * 0.90)
        high = max(default_range["high"], value * 1.10)
        medium = (default_range["medium"] + value) / 2
        return _clean_range(low, medium, high)
    return _clean_range(
        default_range["low"],
        default_range["medium"],
        default_range["high"],
    )


def _clean_range(low: float, medium: float, high: float) -> dict[str, float]:
    ordered_low = min(low, medium, high)
    ordered_high = max(low, medium, high)
    ordered_medium = min(max(medium, ordered_low), ordered_high)
    return {
        "low": round(ordered_low, 2),
        "medium": round(ordered_medium, 2),
        "high": round(ordered_high, 2),
    }
