"""Valoración de la batería a precio de valle, no plano/punta (punto 8).

La batería desplaza consumo nocturno (valle), más barato que el precio medio;
valorar su energía a plano sobreestima su ahorro. Estas pruebas fijan que el
ahorro con precio de valle es menor y que el precio fluye hasta el motor.
"""

from app.bills import _parse_period_table, aggregate_bills
from app.cashflow import simulated_yearly_savings
from app.simulation import annual_savings_with_surplus, simulate_self_consumption

# Perfil sencillo: producción diurna, consumo repartido día/noche, con batería
# que cubre parte del consumo nocturno.
_HOURS = list(range(24))


def _daytime_production():
    # 12 meses idénticos; sol de 8h a 18h.
    day = [3.0 if 8 <= h <= 17 else 0.0 for h in _HOURS]
    return [day[:] for _ in range(12)]


def _consumption():
    # Consumo con carga nocturna significativa (valle).
    day = [2.0 if (h < 7 or h >= 21) else 0.5 for h in _HOURS]
    return [day[:] for _ in range(12)]


class TestBatteryDischargePricing:
    def test_valle_price_lowers_battery_savings(self):
        prod, cons = _daytime_production(), _consumption()
        balance = simulate_self_consumption(prod, cons, battery_kwh=10.0)
        assert balance["battery_kwh"] > 0  # la batería sí desplaza energía nocturna

        flat = annual_savings_with_surplus(balance, 0.25, 0.06, "capped_compensation")
        valle = annual_savings_with_surplus(
            balance, 0.25, 0.06, "capped_compensation",
            battery_discharge_price_eur_kwh=0.13,  # valle, más barato
        )
        # Valorar la energía de batería a valle da MENOS ahorro que a plano.
        assert valle < flat

    def test_default_matches_flat(self):
        prod, cons = _daytime_production(), _consumption()
        balance = simulate_self_consumption(prod, cons, battery_kwh=10.0)
        flat = annual_savings_with_surplus(balance, 0.25, 0.06)
        explicit = annual_savings_with_surplus(
            balance, 0.25, 0.06, battery_discharge_price_eur_kwh=0.25
        )
        assert flat == explicit  # sin precio de valle → sin cambio de comportamiento

    def test_multiyear_uses_valle_price(self):
        prod, cons = _daytime_production(), _consumption()
        flat = simulated_yearly_savings(prod, cons, 10.0, 0.25, 0.06, "capped_compensation")
        valle = simulated_yearly_savings(
            prod, cons, 10.0, 0.25, 0.06, "capped_compensation",
            battery_discharge_price_eur_kwh=0.13,
        )
        assert valle[0] < flat[0]  # año 1 coherente con annual_savings_with_surplus
        assert valle[-1] < flat[-1]  # y escala igual todos los años


class TestVallePriceFlowsFromBill:
    def test_period_table_captures_valle_price(self):
        text = (
            "P1 Punta 2.150 0,189000 406,35\n"
            "P2 Llano 2.820 0,151000 425,82\n"
            "P3 Valle 8.830 0,112000 989,29\n"
        )
        table = _parse_period_table(text)
        assert table["prices"] == {"punta": 0.189, "llano": 0.151, "valle": 0.112}

    def test_aggregate_surfaces_weighted_valle_price(self):
        bills = [
            {
                "kwh": 13800.0,
                "energy_eur": 2086.92,
                "total_eur": 3027.14,
                "currency": "EUR",
                "days": 365,
                "consumption_periods": {"punta": 2150, "llano": 2820, "valle": 8830},
                "consumption_period_prices": {"punta": 0.189, "llano": 0.151, "valle": 0.112},
            }
        ]
        agg = aggregate_bills(bills)
        assert agg["valle_price_eur_kwh"] == 0.112
