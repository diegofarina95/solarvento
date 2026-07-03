"""Flujo de caja plurianual de la instalación.

El payback simple (coste / ahorro del año 1) ignora efectos que mueven el
resultado en años enteros: degradación de los paneles, subida del precio de
la electricidad, mantenimiento y reemplazo del inversor. Este módulo simula
el horizonte año a año y devuelve payback real, ahorro acumulado, VAN y TIR.
Los supuestos son constantes documentadas y viajan en la respuesta de la API.
"""

from .simulation import annual_savings_with_surplus, simulate_self_consumption

HORIZON_YEARS = 30
HEADLINE_YEARS = 25  # cifras titulares (ahorro total, VAN, TIR) a 25 años
PANEL_DEGRADATION_PER_YEAR = 0.005  # garantías Tier-1: ~85-88% a los 25 años
PRICE_ESCALATION_PER_YEAR = 0.02  # conservador frente al histórico europeo
BATTERY_DEGRADATION_PER_YEAR = 0.02  # LFP: ~80% de capacidad a los 10 años
OM_PCT_PER_YEAR = 0.01  # mantenimiento/seguro anual sobre el coste del sistema
INVERTER_REPLACEMENT_YEAR = 13  # vida típica de un inversor: 10-15 años
DISCOUNT_RATE = 0.03  # tasa nominal para el VAN


def simple_yearly_savings(
    first_year_savings: float,
    *,
    years: int = HORIZON_YEARS,
    panel_degradation: float = PANEL_DEGRADATION_PER_YEAR,
    price_escalation: float = PRICE_ESCALATION_PER_YEAR,
) -> list[float]:
    """Ahorro de cada año sin re-simular: degradación y escalada sobre el año 1."""
    return [
        first_year_savings
        * (1 - panel_degradation) ** y
        * (1 + price_escalation) ** y
        for y in range(years)
    ]


def simulated_yearly_savings(
    production: list[list[float]],
    consumption: list[list[float]],
    battery_kwh: float,
    price_eur_kwh: float,
    surplus_price_eur_kwh: float,
    export_scheme: str,
    *,
    years: int = HORIZON_YEARS,
    panel_degradation: float = PANEL_DEGRADATION_PER_YEAR,
    battery_degradation: float = BATTERY_DEGRADATION_PER_YEAR,
    price_escalation: float = PRICE_ESCALATION_PER_YEAR,
    battery_discharge_price_eur_kwh: float | None = None,
) -> list[float]:
    """Ahorro anual re-simulando cada año con paneles y batería envejecidos.

    El precio del excedente solo escala en esquemas ligados al precio
    minorista; las tarifas de inyección reguladas (feed_in) quedan fijas. La
    energía servida por la batería se valora a su precio de periodo (valle) si
    se indica, escalando igual que el precio minorista, para que el payback
    plurianual sea coherente con el ahorro del año 1.
    """
    surplus_escalates = export_scheme != "feed_in"
    savings = []
    for y in range(years):
        production_factor = (1 - panel_degradation) ** y
        production_y = [
            [value * production_factor for value in month] for month in production
        ]
        capacity_y = battery_kwh * (1 - battery_degradation) ** y
        balance = simulate_self_consumption(production_y, consumption, capacity_y)
        escalation = (1 + price_escalation) ** y
        price_y = price_eur_kwh * escalation
        surplus_y = surplus_price_eur_kwh * (escalation if surplus_escalates else 1.0)
        battery_price_y = (
            battery_discharge_price_eur_kwh * escalation
            if battery_discharge_price_eur_kwh is not None
            else None
        )
        savings.append(
            annual_savings_with_surplus(
                balance, price_y, surplus_y, export_scheme, battery_price_y
            )
        )
    return savings


def marginal_battery_payback(
    yearly_savings: list[float],
    base_yearly_savings: list[float],
    extra_cost_eur: float,
) -> float | None:
    """Años hasta que el ahorro extra acumulado de la batería cubre su sobrecoste."""
    if extra_cost_eur <= 0:
        return None
    cumulative = 0.0
    for year, (with_battery, without) in enumerate(
        zip(yearly_savings, base_yearly_savings, strict=True), start=1
    ):
        extra = with_battery - without
        previous = cumulative
        cumulative += extra
        if cumulative >= extra_cost_eur and extra > 0:
            return round(year - 1 + (extra_cost_eur - previous) / extra, 1)
    return None


def cashflow_analysis(
    yearly_savings: list[float],
    *,
    investment_eur: float,
    subsidy_eur: float = 0.0,
    om_eur_per_year: float = 0.0,
    replacements: dict[int, float] | None = None,
    discount_rate: float = DISCOUNT_RATE,
    headline_years: int = HEADLINE_YEARS,
) -> dict:
    """Payback real, ahorro acumulado, VAN y TIR a partir del ahorro anual.

    replacements: coste extra en un año dado (p. ej. {13: coste del inversor}).
    El payback se busca en todo el horizonte; el resto de cifras se calculan a
    headline_years.
    """
    replacements = replacements or {}
    net_investment = max(investment_eur - subsidy_eur, 0.0)
    flows = [
        savings - om_eur_per_year - replacements.get(year, 0.0)
        for year, savings in enumerate(yearly_savings, start=1)
    ]

    cumulative_rows = []
    cumulative = -net_investment
    payback = None
    for year, net in enumerate(flows, start=1):
        previous = cumulative
        cumulative += net
        cumulative_rows.append(
            {
                "year": year,
                "net_eur": round(net, 2),
                "cumulative_eur": round(cumulative, 2),
            }
        )
        if payback is None and cumulative >= 0 and net > 0:
            payback = round(year - 1 + -previous / net, 1)

    headline_flows = flows[:headline_years]
    irr = _irr(net_investment, headline_flows)
    return {
        "payback_years": payback,
        "net_investment_eur": round(net_investment, 2),
        "savings_headline_eur": round(sum(headline_flows), 2),
        "npv_eur": round(_npv(discount_rate, net_investment, headline_flows), 2),
        "irr_pct": round(irr * 100, 1) if irr is not None else None,
        "cumulative": cumulative_rows,
        "assumptions": {
            "horizon_years": len(yearly_savings),
            "headline_years": headline_years,
            "panel_degradation_pct_per_year": round(PANEL_DEGRADATION_PER_YEAR * 100, 2),
            "price_escalation_pct_per_year": round(PRICE_ESCALATION_PER_YEAR * 100, 2),
            "battery_degradation_pct_per_year": round(BATTERY_DEGRADATION_PER_YEAR * 100, 2),
            "om_pct_per_year": round(OM_PCT_PER_YEAR * 100, 2),
            "om_eur_per_year": round(om_eur_per_year, 2),
            "inverter_replacement_year": INVERTER_REPLACEMENT_YEAR,
            "inverter_replacement_cost_eur": round(
                replacements.get(INVERTER_REPLACEMENT_YEAR, 0.0), 2
            ),
            "discount_rate_pct": round(discount_rate * 100, 2),
        },
    }


def _npv(rate: float, net_investment: float, flows: list[float]) -> float:
    return -net_investment + sum(
        flow / (1 + rate) ** year for year, flow in enumerate(flows, start=1)
    )


def _irr(net_investment: float, flows: list[float]) -> float | None:
    """TIR por bisección; None si la inversión no es rentable en el horizonte."""
    if net_investment <= 0:
        return None
    # Si ni siquiera sin descontar se recupera la inversión, no hay TIR que
    # mostrar (sería negativa y confusa para el usuario).
    if _npv(0.0, net_investment, flows) <= 0:
        return None
    low, high = 0.0, 1.0
    if _npv(high, net_investment, flows) > 0:
        return high
    for _ in range(80):
        mid = (low + high) / 2
        if _npv(mid, net_investment, flows) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2
