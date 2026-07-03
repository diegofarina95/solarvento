"""Cost calculations from normalized country pricing."""

from typing import Any


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
        effective_turnkey = turnkey_per_kwp
        system_cost_range = _scale_range(turnkey_per_kwp, power_kwp)

    battery_source = pricing["source_type"]
    if battery_cost_per_kwh is not None:
        effective_battery = _manual_assumption_range(battery_cost_per_kwh)
        battery_source = "manual"
    else:
        effective_battery = pricing["battery_price_per_kwh"]

    panel_price_per_panel = _scale_range(pricing["panel_price_per_w"], panel_power_w)
    battery_costs = [
        {
            "battery_kwh": capacity,
            "investment_range": _add_ranges(
                system_cost_range,
                _scale_range(effective_battery, capacity),
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
