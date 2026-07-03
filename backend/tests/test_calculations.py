import pytest

from app import calculations


class TestLossVsOptimal:
    def test_typical_loss(self):
        assert calculations.loss_vs_optimal_pct(5500, 6400) == 14.1

    def test_equal_production_is_zero(self):
        assert calculations.loss_vs_optimal_pct(6400, 6400) == 0.0

    def test_user_above_optimal_clamped_to_zero(self):
        assert calculations.loss_vs_optimal_pct(6410, 6400) == 0.0

    def test_zero_optimal_is_zero(self):
        assert calculations.loss_vs_optimal_pct(100, 0) == 0.0


class TestAnnualSavings:
    def test_without_consumption_uses_all_production(self):
        assert calculations.annual_savings_eur(6000, 0.15) == 900.0

    def test_consumption_caps_savings(self):
        # Solo se ahorra lo que se consume
        assert calculations.annual_savings_eur(6000, 0.15, annual_consumption_kwh=4000) == 600.0

    def test_consumption_above_production_does_not_cap(self):
        assert calculations.annual_savings_eur(6000, 0.15, annual_consumption_kwh=9000) == 900.0


class TestPayback:
    def test_simple_payback(self):
        assert calculations.payback_years(9000, 900) == 10.0

    def test_rounding(self):
        assert calculations.payback_years(10000, 900) == 11.1

    def test_no_savings_returns_none(self):
        assert calculations.payback_years(9000, 0) is None


class TestRecommendedPanels:
    def test_typical_sizing(self):
        # 4500 kWh/año con 1300 kWh/kWp → 3.46 kWp → 8 paneles de 450 W
        result = calculations.recommended_panels(4500, 1300, panel_power_w=450)
        assert result["count"] == 8
        assert result["total_kwp"] == 3.6
        assert result["needed_kwp"] == 3.46

    def test_minimum_one_panel(self):
        result = calculations.recommended_panels(100, 1500, panel_power_w=450)
        assert result["count"] == 1

    def test_invalid_production_raises(self):
        with pytest.raises(ValueError):
            calculations.recommended_panels(4500, 0)
