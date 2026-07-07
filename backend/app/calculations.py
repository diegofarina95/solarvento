"""Cálculos económicos y de dimensionado a partir de la producción PVGIS."""

import math

# Autoconsumo directo típico de una vivienda SIN batería (25-45% de la
# producción). Se usa en la ruta degradada (seriescalc caído): asumir que todo
# lo producido hasta el consumo se autoconsume sería el caso más optimista
# justo cuando menos datos hay.
FALLBACK_SELF_CONSUMPTION_FACTOR = 0.40


def loss_vs_optimal_pct(user_annual_kwh: float, optimal_annual_kwh: float) -> float:
    """% de producción perdida por usar la inclinación/orientación real frente a la óptima."""
    if optimal_annual_kwh <= 0:
        return 0.0
    loss = (optimal_annual_kwh - user_annual_kwh) / optimal_annual_kwh * 100
    # Por redondeos de PVGIS el sistema del usuario puede salir una décima por
    # encima del óptimo; se acota a 0 para no mostrar pérdidas negativas.
    return round(max(loss, 0.0), 1)


def annual_savings_eur(
    annual_production_kwh: float,
    price_eur_kwh: float,
    annual_consumption_kwh: float | None = None,
    self_consumption_factor: float | None = None,
) -> float:
    """Ahorro anual estimado.

    Si se conoce el consumo, solo la energía que puede autoconsumirse ahorra
    dinero (min(producción, consumo)); sin consumo se asume que toda la
    producción se aprovecha. Con self_consumption_factor (ruta degradada, sin
    simulación horaria) solo esa fracción de la producción cuenta como
    autoconsumida, siempre con el consumo como techo.
    """
    usable = annual_production_kwh
    if annual_consumption_kwh is not None:
        if self_consumption_factor is not None:
            usable = min(
                annual_production_kwh * self_consumption_factor,
                annual_consumption_kwh,
            )
        else:
            usable = min(annual_production_kwh, annual_consumption_kwh)
    return round(usable * price_eur_kwh, 2)


def payback_years(installation_cost_eur: float, annual_savings: float) -> float | None:
    """Retorno simple de la inversión en años; None si no hay ahorro."""
    if annual_savings <= 0:
        return None
    return round(installation_cost_eur / annual_savings, 1)


def recommended_panels(
    annual_consumption_kwh: float,
    annual_production_per_kwp: float,
    panel_power_w: int = 450,
) -> dict:
    """Nº de paneles para cubrir el consumo anual dado el rendimiento local.

    annual_production_per_kwp: kWh que genera 1 kWp al año en esa ubicación
    (producción anual del sistema / potencia pico).
    """
    if annual_production_per_kwp <= 0:
        raise ValueError("La producción por kWp debe ser positiva")
    needed_kwp = annual_consumption_kwh / annual_production_per_kwp
    panels = math.ceil(needed_kwp * 1000 / panel_power_w)
    panels = max(panels, 1)
    return {
        "count": panels,
        "total_kwp": round(panels * panel_power_w / 1000, 2),
        "needed_kwp": round(needed_kwp, 2),
        "panel_power_w": panel_power_w,
        # Un panel residencial de ~450 W ocupa ~2,2 m²; se añade un 15% de
        # margen para separaciones y sombras propias.
        "roof_area_m2": round(panels * 2.2 * 1.15, 1),
    }
