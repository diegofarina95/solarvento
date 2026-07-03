"""Default market pricing by country.

Values are intentionally ranges. They are not binding quotes; they are
market-average assumptions used when no maintained provider feed is available.
All amounts are in the country's local currency, VAT included where applicable.
"""

from datetime import date
from typing import Any


DEFAULT_PRICE_REVIEW_DATE = date(2026, 7, 2)


def price_range(low: float, medium: float, high: float) -> dict[str, float]:
    return {"low": low, "medium": medium, "high": high}


DEFAULT_PRICING_BY_COUNTRY: dict[str, dict[str, Any]] = {
    "ES": {
        "vat_rate": 0.21,
        "vat_note": "standard_or_local_reductions",
        "panel_price_per_w": price_range(0.18, 0.24, 0.32),
        "inverter_price_per_kwp": price_range(115, 160, 230),
        "battery_price_per_kwh": price_range(550, 650, 780),
        "mounting_price_per_kwp": price_range(140, 190, 260),
        "labour_price_per_kwp": price_range(260, 360, 500),
        "turnkey_cost_per_kwp": price_range(1050, 1250, 1450),
        "installation_labour_factor": 0.30,
        "surplus_price_eur_kwh": 0.06,
        "electricity_price_kwh": 0.17,
        "export_scheme": "capped_compensation",
    },
    "FR": {
        "vat_rate": 0.055,
        "vat_note": "reduced_residential_if_eligible",
        "panel_price_per_w": price_range(0.20, 0.28, 0.38),
        "inverter_price_per_kwp": price_range(140, 200, 280),
        "battery_price_per_kwh": price_range(650, 790, 950),
        "mounting_price_per_kwp": price_range(180, 260, 360),
        "labour_price_per_kwp": price_range(420, 620, 850),
        "turnkey_cost_per_kwp": price_range(1700, 2100, 2500),
        "installation_labour_factor": 0.36,
        "surplus_price_eur_kwh": 0.04,
        "electricity_price_kwh": 0.25,
        "export_scheme": "feed_in",
    },
    "IT": {
        "vat_rate": 0.10,
        "vat_note": "reduced_residential_if_eligible",
        "panel_price_per_w": price_range(0.25, 0.37, 0.48),
        "inverter_price_per_kwp": price_range(170, 180, 220),
        "battery_price_per_kwh": price_range(620, 760, 950),
        "mounting_price_per_kwp": price_range(290, 360, 420),
        "labour_price_per_kwp": price_range(90, 110, 150),
        "turnkey_cost_per_kwp": price_range(1360, 1600, 1890),
        "installation_labour_factor": 0.18,
        "surplus_price_eur_kwh": 0.1,
        "electricity_price_kwh": 0.31,
        "export_scheme": "market_price",
    },
    "DE": {
        "vat_rate": 0.0,
        "vat_note": "zero_vat_residential_if_eligible",
        "panel_price_per_w": price_range(0.18, 0.25, 0.34),
        "inverter_price_per_kwp": price_range(130, 190, 280),
        "battery_price_per_kwh": price_range(500, 620, 780),
        "mounting_price_per_kwp": price_range(160, 240, 330),
        "labour_price_per_kwp": price_range(430, 600, 850),
        "turnkey_cost_per_kwp": price_range(1300, 1550, 1850),
        "installation_labour_factor": 0.39,
        "surplus_price_eur_kwh": 0.079,
        "electricity_price_kwh": 0.39,
        "export_scheme": "feed_in",
    },
    "PT": {
        "vat_rate": 0.23,
        "vat_note": "standard_or_local_reductions",
        "panel_price_per_w": price_range(0.18, 0.25, 0.34),
        "inverter_price_per_kwp": price_range(120, 170, 240),
        "battery_price_per_kwh": price_range(560, 670, 820),
        "mounting_price_per_kwp": price_range(145, 200, 280),
        "labour_price_per_kwp": price_range(260, 380, 540),
        "turnkey_cost_per_kwp": price_range(1050, 1300, 1550),
        "installation_labour_factor": 0.31,
        "surplus_price_eur_kwh": 0.05,
        "electricity_price_kwh": 0.19,
        "export_scheme": "capped_compensation",
    },
    "GB": {
        "vat_rate": 0.0,
        "vat_note": "zero_vat_energy_saving_materials_if_eligible",
        "panel_price_per_w": price_range(0.20, 0.30, 0.42),
        "inverter_price_per_kwp": price_range(130, 190, 280),
        "battery_price_per_kwh": price_range(700, 900, 1150),
        "mounting_price_per_kwp": price_range(170, 250, 360),
        "labour_price_per_kwp": price_range(500, 720, 980),
        "turnkey_cost_per_kwp": price_range(1375, 1700, 2200),
        "installation_labour_factor": 0.42,
        "surplus_price_eur_kwh": 0.1,
        "electricity_price_kwh": 0.27,
        "export_scheme": "feed_in",
    },
    "EU": {
        "vat_rate": 0.21,
        "vat_note": "country_specific",
        "panel_price_per_w": price_range(0.20, 0.29, 0.40),
        "inverter_price_per_kwp": price_range(130, 190, 280),
        "battery_price_per_kwh": price_range(580, 720, 900),
        "mounting_price_per_kwp": price_range(170, 250, 350),
        "labour_price_per_kwp": price_range(330, 500, 750),
        "turnkey_cost_per_kwp": price_range(1250, 1600, 2150),
        "installation_labour_factor": 0.34,
        "surplus_price_eur_kwh": 0.06,
        "electricity_price_kwh": 0.2,
        "export_scheme": "capped_compensation",
    },
}


_MARKET_TIERS_EUR = {
    "western": {
        "panel_price_per_w": price_range(0.21, 0.30, 0.42),
        "inverter_price_per_kwp": price_range(140, 210, 300),
        "battery_price_per_kwh": price_range(650, 820, 1050),
        "mounting_price_per_kwp": price_range(180, 270, 380),
        "labour_price_per_kwp": price_range(450, 690, 950),
        "turnkey_cost_per_kwp": price_range(1500, 1900, 2400),
        "installation_labour_factor": 0.38,
    },
    "high_cost": {
        "panel_price_per_w": price_range(0.22, 0.32, 0.45),
        "inverter_price_per_kwp": price_range(150, 230, 330),
        "battery_price_per_kwh": price_range(700, 900, 1150),
        "mounting_price_per_kwp": price_range(200, 300, 430),
        "labour_price_per_kwp": price_range(650, 920, 1250),
        "turnkey_cost_per_kwp": price_range(1800, 2300, 2900),
        "installation_labour_factor": 0.42,
    },
    "central": {
        "panel_price_per_w": price_range(0.18, 0.25, 0.35),
        "inverter_price_per_kwp": price_range(120, 180, 260),
        "battery_price_per_kwh": price_range(550, 700, 880),
        "mounting_price_per_kwp": price_range(150, 220, 320),
        "labour_price_per_kwp": price_range(300, 470, 680),
        "turnkey_cost_per_kwp": price_range(1150, 1450, 1850),
        "installation_labour_factor": 0.34,
    },
    "southern": {
        "panel_price_per_w": price_range(0.18, 0.26, 0.36),
        "inverter_price_per_kwp": price_range(120, 180, 260),
        "battery_price_per_kwh": price_range(570, 710, 900),
        "mounting_price_per_kwp": price_range(150, 220, 320),
        "labour_price_per_kwp": price_range(260, 420, 620),
        "turnkey_cost_per_kwp": price_range(1100, 1400, 1800),
        "installation_labour_factor": 0.32,
    },
    "island": {
        "panel_price_per_w": price_range(0.22, 0.32, 0.45),
        "inverter_price_per_kwp": price_range(150, 230, 330),
        "battery_price_per_kwh": price_range(700, 880, 1100),
        "mounting_price_per_kwp": price_range(220, 330, 470),
        "labour_price_per_kwp": price_range(380, 580, 820),
        "turnkey_cost_per_kwp": price_range(1400, 1800, 2300),
        "installation_labour_factor": 0.34,
    },
    "balkan": {
        "panel_price_per_w": price_range(0.16, 0.23, 0.32),
        "inverter_price_per_kwp": price_range(105, 160, 235),
        "battery_price_per_kwh": price_range(500, 650, 830),
        "mounting_price_per_kwp": price_range(120, 190, 280),
        "labour_price_per_kwp": price_range(180, 310, 480),
        "turnkey_cost_per_kwp": price_range(900, 1150, 1550),
        "installation_labour_factor": 0.29,
    },
    "eastern": {
        "panel_price_per_w": price_range(0.17, 0.24, 0.34),
        "inverter_price_per_kwp": price_range(110, 170, 250),
        "battery_price_per_kwh": price_range(520, 680, 860),
        "mounting_price_per_kwp": price_range(130, 200, 290),
        "labour_price_per_kwp": price_range(220, 360, 540),
        "turnkey_cost_per_kwp": price_range(950, 1250, 1650),
        "installation_labour_factor": 0.30,
    },
    "micro_high": {
        "panel_price_per_w": price_range(0.22, 0.33, 0.46),
        "inverter_price_per_kwp": price_range(150, 230, 340),
        "battery_price_per_kwh": price_range(720, 930, 1200),
        "mounting_price_per_kwp": price_range(220, 330, 480),
        "labour_price_per_kwp": price_range(620, 900, 1250),
        "turnkey_cost_per_kwp": price_range(1700, 2200, 2800),
        "installation_labour_factor": 0.41,
    },
}


_COUNTRY_PRICE_TIERS = {
    "AL": "balkan",
    "AD": "micro_high",
    "AT": "western",
    "BY": "eastern",
    "BE": "western",
    "BA": "balkan",
    "BG": "eastern",
    "HR": "central",
    "CY": "island",
    "CZ": "central",
    "DK": "high_cost",
    "EE": "central",
    "FI": "high_cost",
    "GR": "southern",
    "HU": "central",
    "IS": "high_cost",
    "IE": "high_cost",
    "XK": "balkan",
    "LV": "central",
    "LI": "micro_high",
    "LT": "central",
    "LU": "micro_high",
    "MT": "island",
    "MD": "eastern",
    "MC": "micro_high",
    "ME": "balkan",
    "NL": "western",
    "MK": "balkan",
    "NO": "high_cost",
    "PL": "central",
    "RO": "eastern",
    "RU": "eastern",
    "SM": "micro_high",
    "RS": "balkan",
    "SK": "central",
    "SI": "central",
    "SE": "high_cost",
    "CH": "high_cost",
    "TR": "balkan",
    "UA": "eastern",
    "VA": "micro_high",
}


_EUR_TO_LOCAL = {
    "AL": 100.0,
    "BY": 3.5,
    "BA": 1.95583,
    "BG": 1.95583,
    "CZ": 24.7,
    "DK": 7.46,
    "HU": 390.0,
    "IS": 150.0,
    "LI": 0.95,
    "MD": 19.5,
    "MK": 61.5,
    "NO": 11.5,
    "PL": 4.3,
    "RO": 5.0,
    "RU": 100.0,
    "RS": 117.2,
    "SE": 11.3,
    "CH": 0.95,
    "TR": 45.0,
    "UA": 45.0,
}


_VAT_RATES = {
    "AD": 0.045,
    "AL": 0.20,
    "AT": 0.20,
    "BY": 0.20,
    "BE": 0.21,
    "BA": 0.17,
    "BG": 0.20,
    "HR": 0.25,
    "CY": 0.19,
    "CZ": 0.21,
    "DK": 0.25,
    "EE": 0.24,
    "FI": 0.255,
    "GR": 0.24,
    "HU": 0.27,
    "IS": 0.24,
    "IE": 0.135,
    "XK": 0.18,
    "LV": 0.21,
    "LI": 0.081,
    "LT": 0.21,
    "LU": 0.17,
    "MT": 0.18,
    "MD": 0.20,
    "MC": 0.20,
    "ME": 0.21,
    "NL": 0.21,
    "MK": 0.18,
    "NO": 0.25,
    "PL": 0.23,
    "RO": 0.19,
    "RU": 0.20,
    "SM": 0.17,
    "RS": 0.20,
    "SK": 0.20,
    "SI": 0.22,
    "SE": 0.25,
    "CH": 0.081,
    "TR": 0.20,
    "UA": 0.20,
    "VA": 0.0,
}


# Precio doméstico medio de la electricidad (EUR/kWh, impuestos incluidos,
# aproximado). Para países sin euro se convierte con _EUR_TO_LOCAL al generar
# la entrada, de modo que el quote siempre está en la moneda local.
_ELECTRICITY_PRICE_EUR_KWH = {
    "AT": 0.25, "BE": 0.33, "CH": 0.29, "CZ": 0.30, "DK": 0.36, "FI": 0.18,
    "GR": 0.19, "HU": 0.10, "IE": 0.37, "LU": 0.28, "NL": 0.29, "NO": 0.14,
    "PL": 0.25, "RO": 0.26, "SE": 0.19, "SK": 0.19, "HR": 0.14, "SI": 0.17,
    "EE": 0.19, "LV": 0.20, "LT": 0.19, "BG": 0.12, "CY": 0.23, "MT": 0.13,
}


# Mecanismo de retribución del excedente por país (revisión 2026-07):
#  - capped_compensation: descuento en factura con tope mensual (ES/PT)
#  - feed_in: tarifa de inyección por kWh sin tope (DE EEG, FR OA, IE CEG, GB SEG…)
#  - net_metering: balance neto kWh a kWh (NL salderen hasta 2027, RO compensare)
#  - market_price: venta a precio de mercado/net-billing (PL, nórdicos, IT RID, GR…)
_EXPORT_SCHEME = {
    "ES": "capped_compensation",
    "PT": "capped_compensation",
    "DE": "feed_in",
    "FR": "feed_in",
    "AT": "feed_in",
    "CH": "feed_in",
    "GB": "feed_in",
    "IE": "feed_in",
    "LU": "feed_in",
    "NL": "net_metering",
    "RO": "net_metering",
    "IT": "market_price",
    "BE": "market_price",
    "PL": "market_price",
    "SE": "market_price",
    "DK": "market_price",
    "NO": "market_price",
    "FI": "market_price",
    "GR": "market_price",
    "CZ": "market_price",
    "HU": "market_price",
}
EXPORT_SCHEME_DEFAULT = "capped_compensation"


def export_scheme_for(country_code: str) -> str:
    return _EXPORT_SCHEME.get(country_code, EXPORT_SCHEME_DEFAULT)


_SURPLUS_PRICE_EUR_KWH = {
    "AL": 0.04,
    "AD": 0.05,
    "AT": 0.06,
    "BY": 0.03,
    "BE": 0.04,
    "BA": 0.04,
    "BG": 0.05,
    "HR": 0.06,
    "CY": 0.07,
    "CZ": 0.05,
    "DK": 0.05,
    "EE": 0.05,
    "FI": 0.05,
    "GR": 0.06,
    "HU": 0.05,
    "IS": 0.04,
    "IE": 0.18,
    "XK": 0.04,
    "LV": 0.05,
    "LI": 0.06,
    "LT": 0.05,
    "LU": 0.05,
    "MT": 0.06,
    "MD": 0.04,
    "MC": 0.05,
    "ME": 0.04,
    "NL": 0.05,
    "MK": 0.04,
    "NO": 0.04,
    "PL": 0.05,
    "RO": 0.05,
    "RU": 0.03,
    "SM": 0.06,
    "RS": 0.04,
    "SK": 0.05,
    "SI": 0.06,
    "SE": 0.05,
    "CH": 0.07,
    "TR": 0.04,
    "UA": 0.04,
    "VA": 0.05,
}


def _scale_range(values: dict[str, float], factor: float) -> dict[str, float]:
    return price_range(
        round(values["low"] * factor, 2),
        round(values["medium"] * factor, 2),
        round(values["high"] * factor, 2),
    )


def _country_market_average(country_code: str, tier: str) -> dict[str, Any]:
    base = _MARKET_TIERS_EUR[tier]
    factor = _EUR_TO_LOCAL.get(country_code, 1.0)
    return {
        "vat_rate": _VAT_RATES[country_code],
        "vat_note": "country_specific",
        "panel_price_per_w": _scale_range(base["panel_price_per_w"], factor),
        "inverter_price_per_kwp": _scale_range(base["inverter_price_per_kwp"], factor),
        "battery_price_per_kwh": _scale_range(base["battery_price_per_kwh"], factor),
        "mounting_price_per_kwp": _scale_range(base["mounting_price_per_kwp"], factor),
        "labour_price_per_kwp": _scale_range(base["labour_price_per_kwp"], factor),
        "turnkey_cost_per_kwp": _scale_range(base["turnkey_cost_per_kwp"], factor),
        "installation_labour_factor": base["installation_labour_factor"],
        # Surplus y precio eléctrico también en moneda local: sin escalar, en
        # países sin euro se mezclaban EUR con PLN/CZK/SEK en la economía.
        "surplus_price_eur_kwh": round(
            _SURPLUS_PRICE_EUR_KWH.get(country_code, 0.05) * factor, 3
        ),
        "electricity_price_kwh": round(
            _ELECTRICITY_PRICE_EUR_KWH.get(country_code, 0.18) * factor, 3
        ),
        "export_scheme": export_scheme_for(country_code),
    }


for _country_code, _tier in _COUNTRY_PRICE_TIERS.items():
    DEFAULT_PRICING_BY_COUNTRY.setdefault(
        _country_code,
        _country_market_average(_country_code, _tier),
    )
