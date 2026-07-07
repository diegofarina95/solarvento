"""Tests del flujo de caja plurianual."""

import pytest

from app import cashflow


def _flat(savings: float, years: int = 30) -> list[float]:
    return [savings] * years


def test_payback_flat_savings_is_simple_division():
    result = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    assert result["payback_years"] == 10.0


def test_payback_interpolates_within_year():
    # 1000 de inversión, 400/año: se recupera a mitad del año 3
    result = cashflow.cashflow_analysis(_flat(400.0), investment_eur=1000.0)
    assert result["payback_years"] == 2.5


def test_price_escalation_shortens_payback():
    escalated = cashflow.simple_yearly_savings(
        100.0, panel_degradation=0.0, price_escalation=0.05
    )
    result = cashflow.cashflow_analysis(escalated, investment_eur=1000.0)
    assert result["payback_years"] < 10.0


def test_degradation_lengthens_payback():
    degraded = cashflow.simple_yearly_savings(
        100.0, panel_degradation=0.02, price_escalation=0.0
    )
    result = cashflow.cashflow_analysis(degraded, investment_eur=1000.0)
    assert result["payback_years"] > 10.0


def test_om_and_replacement_reduce_net_flows():
    base = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    with_costs = cashflow.cashflow_analysis(
        _flat(100.0),
        investment_eur=1000.0,
        om_eur_per_year=20.0,
        replacements={3: 100.0},
    )
    assert with_costs["payback_years"] > base["payback_years"]
    year3 = with_costs["cumulative"][2]
    assert year3["net_eur"] == pytest.approx(100.0 - 20.0 - 100.0)


def test_subsidy_reduces_net_investment_and_payback():
    result = cashflow.cashflow_analysis(
        _flat(100.0), investment_eur=1000.0, subsidy_eur=500.0
    )
    assert result["net_investment_eur"] == 500.0
    assert result["payback_years"] == 5.0


def test_payback_none_when_never_recovered():
    result = cashflow.cashflow_analysis(_flat(1.0), investment_eur=1000.0)
    assert result["payback_years"] is None


def test_npv_at_zero_discount_equals_cumulative_savings_minus_investment():
    result = cashflow.cashflow_analysis(
        _flat(100.0), investment_eur=1000.0, discount_rate=0.0
    )
    assert result["npv_eur"] == pytest.approx(100.0 * 25 - 1000.0)


def test_irr_of_25y_annuity_is_close_to_annuity_rate():
    # 1000 invertidos, 100/año durante 25 años: factor de anualidad 10 → TIR ~8.8%
    result = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    assert result["irr_pct"] == pytest.approx(8.8, abs=0.3)


def test_irr_none_when_unprofitable():
    result = cashflow.cashflow_analysis(_flat(1.0), investment_eur=1000.0)
    assert result["irr_pct"] is None


def test_cumulative_rows_cover_horizon():
    result = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    assert len(result["cumulative"]) == 30
    assert result["cumulative"][0] == {
        "year": 1,
        "net_eur": 100.0,
        "cumulative_eur": -900.0,
    }


def test_assumptions_reflect_inputs():
    result = cashflow.cashflow_analysis(
        _flat(100.0),
        investment_eur=1000.0,
        om_eur_per_year=15.0,
        replacements={13: 800.0},
        discount_rate=0.04,
    )
    a = result["assumptions"]
    assert a["om_eur_per_year"] == 15.0
    assert a["inverter_replacement_year"] == 13
    assert a["inverter_replacement_cost_eur"] == 800.0
    assert a["discount_rate_pct"] == 4.0
    assert a["horizon_years"] == 30


def _uniform_profile(daily_kwh_per_hour: float) -> list[list[float]]:
    return [[daily_kwh_per_hour] * 24 for _ in range(12)]


def _solar_profile(peak_kwh: float) -> list[list[float]]:
    """Producción solo entre las 8 y las 18 h, para que haya excedente a mediodía."""
    day = [peak_kwh if 8 <= h < 18 else 0.0 for h in range(24)]
    return [day[:] for _ in range(12)]


def test_simulated_savings_decline_without_escalation():
    savings = cashflow.simulated_yearly_savings(
        _solar_profile(1.0),
        _uniform_profile(0.5),
        0.0,
        0.20,
        0.06,
        "capped_compensation",
        price_escalation=0.0,
    )
    assert len(savings) == 30
    assert savings[10] < savings[0]
    assert savings[29] < savings[10]


def test_simulated_savings_grow_with_escalation_above_degradation():
    savings = cashflow.simulated_yearly_savings(
        _solar_profile(1.0),
        _uniform_profile(0.5),
        0.0,
        0.20,
        0.06,
        "capped_compensation",
        price_escalation=0.03,
    )
    assert savings[10] > savings[0]


def test_feed_in_surplus_price_does_not_escalate():
    # Sistema muy excedentario: casi todo el valor viene del vertido
    production = _solar_profile(2.0)
    consumption = _uniform_profile(0.05)
    feed_in = cashflow.simulated_yearly_savings(
        production, consumption, 0.0, 0.30, 0.08, "feed_in",
        panel_degradation=0.0, price_escalation=0.05,
    )
    market = cashflow.simulated_yearly_savings(
        production, consumption, 0.0, 0.30, 0.08, "market_price",
        panel_degradation=0.0, price_escalation=0.05,
    )
    # Con feed_in el excedente no escala: el ahorro del año 10 crece menos
    assert feed_in[9] / feed_in[0] < market[9] / market[0]


def test_battery_capacity_degrades_over_years():
    with_battery = cashflow.simulated_yearly_savings(
        _solar_profile(1.5),
        _uniform_profile(0.6),
        10.0,
        0.25,
        0.05,
        "capped_compensation",
        price_escalation=0.0,
        panel_degradation=0.0,
        battery_degradation=0.03,
    )
    # Sin degradación de paneles ni escalada, la única pérdida es la batería
    assert with_battery[20] < with_battery[0]


def test_marginal_battery_payback_interpolates():
    with_battery = [300.0] * 30
    without = [200.0] * 30
    # 100 extra/año, sobrecoste 250: payback marginal 2.5 años
    assert cashflow.marginal_battery_payback(with_battery, without, 250.0) == 2.5


def test_marginal_battery_payback_none_cases():
    assert cashflow.marginal_battery_payback([100.0] * 30, [100.0] * 30, 500.0) is None
    assert cashflow.marginal_battery_payback([200.0] * 30, [100.0] * 30, 0.0) is None


# --- Verificación del "payback ajustado = simple" visto en informes (jul-2026) ---
# NO es un bug: el ajustado SÍ incorpora escalada, degradación, O&M e inversor
# (guardas de arriba). A paybacks cortos los efectos casi se cancelan:
# escalada (+2%) − degradación (−0,5%) ≈ +1,5%/año de crecimiento del ahorro,
# frente a un O&M del 1% del capex/año; y el inversor (año 13) no puede tocar
# un payback que llega antes del año 13. Estos tests fijan el caso de
# referencia (25.637 kWh, Santiago) para que la casi-igualdad no se vuelva a
# diagnosticar como costes sin aplicar.


def test_referencia_santiago_ajustado_una_decima_sobre_el_simple():
    investment = 7642.72
    savings_year1 = 1616.97
    om = round(investment * cashflow.OM_PCT_PER_YEAR, 2)
    yearly = cashflow.simple_yearly_savings(savings_year1)
    analysis = cashflow.cashflow_analysis(
        yearly,
        investment_eur=investment,
        om_eur_per_year=om,
        replacements={cashflow.INVERTER_REPLACEMENT_YEAR: 900.0},
    )
    simple = round(investment / savings_year1, 1)
    assert simple == 4.7
    assert analysis["payback_years"] == 4.8
    # A paybacks cortos el O&M pesa más que la escalada acumulada: el ajustado
    # queda (ligeramente) por encima del simple, nunca por debajo.
    assert analysis["payback_years"] >= simple


def test_reemplazo_antes_del_payback_si_lo_alarga():
    investment = 1000.0
    yearly = _flat(250.0)  # simple: 4,0 años
    without = cashflow.cashflow_analysis(yearly, investment_eur=investment)
    with_early = cashflow.cashflow_analysis(
        yearly, investment_eur=investment, replacements={3: 250.0}
    )
    assert without["payback_years"] == 4.0
    assert with_early["payback_years"] == 5.0


def test_reemplazo_despues_del_payback_no_lo_toca_pero_baja_el_van():
    investment = 1000.0
    yearly = _flat(250.0)
    base = cashflow.cashflow_analysis(yearly, investment_eur=investment)
    late = cashflow.cashflow_analysis(
        yearly, investment_eur=investment, replacements={13: 400.0}
    )
    assert late["payback_years"] == base["payback_years"] == 4.0
    assert late["npv_eur"] < base["npv_eur"]
