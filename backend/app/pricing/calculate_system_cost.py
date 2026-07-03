"""Cost calculations from normalized country pricing.

La banda de mercado por país (low-high) mezcla instalaciones de todos los
tamaños: su anchura refleja sobre todo economías de escala, no incertidumbre
para un tamaño dado. Para estrechar la horquilla sin mentir, el coste se
ajusta por tamaño con una curva calibrada con datos reales (Francia jul-2026:
3 kWc ≈ 2,0 €/Wc frente a 9 kWc ≈ 1,4 → exponente ~0,3) y se presenta el
rango típico de presupuestos alrededor de esa media (−12% / +15%), siempre
dentro de la banda de mercado del país.
"""

from typing import Any

_SYSTEM_REFERENCE_KWP = 5.0  # las medias de país están expresadas a este tamaño
_SYSTEM_SIZE_EXPONENT = 0.3
_SYSTEM_SIZE_KWP_MIN, _SYSTEM_SIZE_KWP_MAX = 2.5, 12.0
_BATTERY_REFERENCE_KWH = 10.0
_BATTERY_SIZE_EXPONENT = 0.15
_BATTERY_SIZE_KWH_MIN, _BATTERY_SIZE_KWH_MAX = 4.0, 20.0
# Banda típica de presupuestos alrededor de la media ajustada al tamaño
_TYPICAL_LOW_FACTOR = 0.88
_TYPICAL_HIGH_FACTOR = 1.15


def _system_size_factor(power_kwp: float) -> float:
    kwp = min(max(power_kwp, _SYSTEM_SIZE_KWP_MIN), _SYSTEM_SIZE_KWP_MAX)
    return (_SYSTEM_REFERENCE_KWP / kwp) ** _SYSTEM_SIZE_EXPONENT


def _battery_size_factor(capacity_kwh: float) -> float:
    kwh = min(max(capacity_kwh, _BATTERY_SIZE_KWH_MIN), _BATTERY_SIZE_KWH_MAX)
    return (_BATTERY_REFERENCE_KWH / kwh) ** _BATTERY_SIZE_EXPONENT


def _size_adjusted_typical(market: dict[str, float], factor: float) -> dict[str, float]:
    """Media ajustada al tamaño (acotada a la banda de mercado) + rango típico."""
    medium = min(max(market["medium"] * factor, market["low"]), market["high"])
    return _clean_range(
        medium * _TYPICAL_LOW_FACTOR, medium, medium * _TYPICAL_HIGH_FACTOR
    )


def calculate_system_cost(
    pricing: dict[str, Any],
    *,
    power_kwp: float,
    panel_power_w: int,
    battery_options_kwh: list[float],
    installation_cost: float | None = None,
    cost_per_kwp: float | None = None,
    battery_cost_per_kwh: float | None = None,
) -> dict[str, Any]:
    """Return the cost ranges used by economics and battery scenarios."""

    turnkey_per_kwp = pricing["turnkey_cost_per_kwp"]
    system_source = pricing["source_type"]
    if installation_cost is not None:
        system_cost_range = _fixed_range(installation_cost)
        effective_turnkey = _fixed_range(installation_cost / power_kwp)
        system_source = "manual"
    elif cost_per_kwp is not None:
        effective_turnkey = _manual_assumption_range(cost_per_kwp)
        system_cost_range = _scale_range(effective_turnkey, power_kwp)
        system_source = "manual"
    else:
        effective_turnkey = _size_adjusted_typical(
            turnkey_per_kwp, _system_size_factor(power_kwp)
        )
        system_cost_range = _scale_range(effective_turnkey, power_kwp)

    battery_source = pricing["source_type"]
    battery_market = pricing["battery_price_per_kwh"]
    if battery_cost_per_kwh is not None:
        effective_battery = _manual_assumption_range(battery_cost_per_kwh)
        battery_source = "manual"
    else:
        effective_battery = _size_adjusted_typical(
            battery_market, _battery_size_factor(_BATTERY_REFERENCE_KWH)
        )

    def _battery_range_for(capacity: float) -> dict[str, float]:
        if battery_source == "manual":
            return effective_battery
        return _size_adjusted_typical(battery_market, _battery_size_factor(capacity))

    panel_price_per_panel = _scale_range(pricing["panel_price_per_w"], panel_power_w)
    battery_costs = [
        {
            "battery_kwh": capacity,
            "investment_range": _add_ranges(
                system_cost_range,
                _scale_range(_battery_range_for(capacity), capacity),
            ),
        }
        for capacity in sorted({capacity for capacity in battery_options_kwh if capacity > 0})
    ]

    return {
        "system_cost_range": system_cost_range,
        "turnkey_cost_per_kwp": effective_turnkey,
        "battery_cost_per_kwh": effective_battery,
        "panel_price_per_w": pricing["panel_price_per_w"],
        "panel_price_per_panel": panel_price_per_panel,
        "inverter_price_per_kwp": pricing["inverter_price_per_kwp"],
        "mounting_price_per_kwp": pricing["mounting_price_per_kwp"],
        "labour_price_per_kwp": pricing["labour_price_per_kwp"],
        "system_cost_source": system_source,
        "battery_cost_source": battery_source,
        "battery_option_costs": battery_costs,
    }


def _fixed_range(value: float) -> dict[str, float]:
    rounded = round(value, 2)
    return {"low": rounded, "medium": rounded, "high": rounded}


def _manual_assumption_range(value: float) -> dict[str, float]:
    return _clean_range(value * 0.90, value, value * 1.10)


def _scale_range(price_range: dict[str, float], factor: float) -> dict[str, float]:
    return _clean_range(
        price_range["low"] * factor,
        price_range["medium"] * factor,
        price_range["high"] * factor,
    )


def _add_ranges(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    return _clean_range(
        left["low"] + right["low"],
        left["medium"] + right["medium"],
        left["high"] + right["high"],
    )


def _clean_range(low: float, medium: float, high: float) -> dict[str, float]:
    return {
        "low": round(min(low, medium, high), 2),
        "medium": round(medium, 2),
        "high": round(max(low, medium, high), 2),
    }
