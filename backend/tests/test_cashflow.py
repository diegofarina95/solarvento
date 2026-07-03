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
