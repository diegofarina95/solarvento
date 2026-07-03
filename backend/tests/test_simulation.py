import pytest

from app.profiles import consumption_profile
from app.simulation import (
    annual_savings_with_surplus,
    battery_scenarios,
    simulate_self_consumption,
)


def flat_profile(kwh_per_hour: float, hours: range = range(24)) -> list[list[float]]:
    return [[kwh_per_hour if h in hours else 0.0 for h in range(24)] for _ in range(12)]


class TestSimulateSelfConsumption:
    def test_no_overlap_no_battery(self):
        # Produce solo de 10-16h, consume solo de 20-23h → sin batería no hay autoconsumo
        production = flat_profile(1.0, range(10, 16))
        consumption = flat_profile(1.0, range(20, 24))
        result = simulate_self_consumption(production, consumption, battery_kwh=0)
        assert result["direct_kwh"] == 0
        assert result["self_consumption_pct"] == 0
        assert result["exported_kwh"] == result["production_kwh"]
        assert result["imported_kwh"] == result["consumption_kwh"]

    def test_no_overlap_with_battery_shifts_energy(self):
        production = flat_profile(1.0, range(10, 16))  # 6 kWh/día
        consumption = flat_profile(1.0, range(20, 24))  # 4 kWh/día
        result = simulate_self_consumption(production, consumption, battery_kwh=10)
        # La batería traslada el excedente de mediodía a la noche
        assert result["battery_kwh"] > 0
        assert result["imported_kwh"] < result["consumption_kwh"]
        assert result["self_sufficiency_pct"] > 80

    def test_full_overlap_all_direct(self):
        production = flat_profile(0.5)
        consumption = flat_profile(0.5)
        result = simulate_self_consumption(production, consumption, battery_kwh=0)
        assert result["self_consumption_pct"] == 100.0
        assert result["exported_kwh"] == 0
        assert result["imported_kwh"] == 0

    def test_battery_respects_round_trip_efficiency(self):
        production = flat_profile(1.0, range(10, 12))  # 2 kWh/día de excedente
        consumption = flat_profile(1.0, range(20, 22))  # 2 kWh/día de consumo
        result = simulate_self_consumption(production, consumption, battery_kwh=100)
        # Con eficiencia 0.9 no puede descargar más del 90% de lo producido
        assert result["battery_kwh"] <= result["production_kwh"] * 0.9 + 1e-6

    def test_energy_balance_conserved(self):
        production = flat_profile(0.8, range(8, 18))
        consumption = consumption_profile(3500)
        for battery in (0, 5):
            r = simulate_self_consumption(production, consumption, battery)
            # producción = directo + exportado + (cargado ≈ descargado/0.9)
            charged = r["battery_kwh"] / 0.9
            assert r["direct_kwh"] + r["exported_kwh"] + charged == pytest.approx(
                r["production_kwh"], rel=0.02
            )
            # consumo = directo + batería + importado
            assert r["direct_kwh"] + r["battery_kwh"] + r["imported_kwh"] == pytest.approx(
                r["consumption_kwh"], rel=0.001
            )


class TestSavingsWithSurplus:
    def test_compensation_capped_by_monthly_import_cost(self):
        production = flat_profile(2.0, range(10, 16))  # mucho excedente
        consumption = flat_profile(0.1, range(20, 22))  # casi sin consumo nocturno
        balance = simulate_self_consumption(production, consumption, 0)
        savings = annual_savings_with_surplus(balance, 0.20, 0.06)
        # La compensación no puede superar el coste de lo importado
        max_possible = (
            balance["direct_kwh"] * 0.20 + balance["imported_kwh"] * 0.20 * 12
        )
        assert savings <= max_possible

    def test_more_selfconsumption_more_savings(self):
        consumption = consumption_profile(4000)
        production = flat_profile(0.7, range(9, 17))
        no_batt = simulate_self_consumption(production, consumption, 0)
        with_batt = simulate_self_consumption(production, consumption, 8)
        s0 = annual_savings_with_surplus(no_batt, 0.20, 0.06)
        s8 = annual_savings_with_surplus(with_batt, 0.20, 0.06)
        assert s8 > s0


class TestBatteryScenarios:
    def test_scenarios_structure_and_marginal_payback(self):
        consumption = consumption_profile(4500)
        production = flat_profile(0.9, range(9, 17))
        scenarios = battery_scenarios(
            production,
            consumption,
            [0, 5, 10],
            price_eur_kwh=0.20,
            surplus_price_eur_kwh=0.06,
            system_cost_eur=6000,
            battery_cost_eur_kwh=600,
        )
        assert [s["battery_kwh"] for s in scenarios] == [0, 5, 10]
        base = scenarios[0]
        assert "battery_marginal_payback_years" not in base
        for s in scenarios[1:]:
            assert s["investment_eur"] == 6000 + s["battery_kwh"] * 600
            assert s["annual_savings_eur"] >= base["annual_savings_eur"]
            assert s["self_sufficiency_pct"] >= base["self_sufficiency_pct"]


class TestExportSchemes:
    """La retribución del excedente cambia según el país."""

    def _balance(self, base_load=0.3):
        production = flat_profile(1.0, range(10, 16))  # excedente grande de mediodía
        consumption = flat_profile(base_load)
        return simulate_self_consumption(production, consumption, 0)

    def test_feed_in_pays_all_exports_without_cap(self):
        # Consumo muy bajo → el vertido domina y el tope mensual recorta mucho
        balance = self._balance(base_load=0.1)
        capped = annual_savings_with_surplus(balance, 0.20, 0.08, "capped_compensation")
        feed_in = annual_savings_with_surplus(balance, 0.20, 0.08, "feed_in")
        # El feed-in alemán paga todo el vertido; con tope se recorta
        assert feed_in > capped
        # Y puede superar el gasto anual en luz (es ingreso real)
        annual_spend = balance["consumption_kwh"] * 0.20
        assert feed_in > annual_spend
        # Coincide con la fórmula sin tope
        expected = (
            (balance["direct_kwh"] + balance["battery_kwh"]) * 0.20
            + balance["exported_kwh"] * 0.08
        )
        assert feed_in == pytest.approx(expected, rel=0.001)

    def test_net_metering_offsets_imports_at_retail_price(self):
        balance = self._balance()
        nm = annual_savings_with_surplus(balance, 0.20, 0.08, "net_metering")
        self_consumed = (balance["direct_kwh"] + balance["battery_kwh"]) * 0.20
        offset = min(balance["exported_kwh"], balance["imported_kwh"]) * 0.20
        expected = min(self_consumed + offset, balance["consumption_kwh"] * 0.20)
        assert nm == pytest.approx(expected, rel=0.001)

    def test_market_price_uncapped(self):
        balance = self._balance()
        mp = annual_savings_with_surplus(balance, 0.20, 0.05, "market_price")
        expected = (
            (balance["direct_kwh"] + balance["battery_kwh"]) * 0.20
            + balance["exported_kwh"] * 0.05
        )
        assert mp == pytest.approx(expected, rel=0.001)

    def test_default_scheme_is_capped(self):
        balance = self._balance()
        assert annual_savings_with_surplus(balance, 0.20, 0.08) == annual_savings_with_surplus(
            balance, 0.20, 0.08, "capped_compensation"
        )
