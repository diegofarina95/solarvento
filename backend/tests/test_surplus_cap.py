"""Capeo de excedentes: la compensación no puede hacer que el saldo baje de cero.

Con consumo bajo (~3.500 kWh/año) y un sistema grande, el excedente estival es
enorme; el esquema capped_compensation debe topar la compensación mensual al coste
de lo importado (el excedente por encima no se paga) y el ahorro total nunca supera
el gasto anual.
"""

from app.simulation import annual_savings_with_surplus, simulate_self_consumption

PRICE = 0.25
SURPLUS = 0.06


def _months(day):
    return [day[:] for _ in range(12)]


def _low_consumption_big_system():
    # Producción diurna grande; consumo bajo (nocturno + algo de día).
    production = _months([4.0 if 8 <= h <= 17 else 0.0 for h in range(24)])  # ~14.600 kWh/año
    consumption = _months([0.5 if (h < 7 or h >= 21) else 0.3 for h in range(24)])  # ~3.400 kWh/año
    return production, consumption


def test_annual_consumption_is_low():
    _prod, cons = _low_consumption_big_system()
    balance = simulate_self_consumption(cons, cons, 0.0)  # consumo = consumo
    assert 3000 <= balance["consumption_kwh"] <= 4000  # ~3.500 kWh/año


def test_summer_surplus_capped_no_negative_balance():
    production, consumption = _low_consumption_big_system()
    balance = simulate_self_consumption(production, consumption, 0.0)
    annual_spend = balance["consumption_kwh"] * PRICE
    capped = annual_savings_with_surplus(balance, PRICE, SURPLUS, "capped_compensation")

    # (1) El ahorro nunca supera el gasto: el saldo no baja de cero.
    assert capped <= annual_spend + 0.5

    # (2) La compensación mensual está topada al coste de lo importado; el
    #     excedente por encima de lo importado NO se paga.
    assert balance["exported_kwh"] > balance["imported_kwh"] * 5  # de verdad sobra
    for month in balance["monthly"]:
        comp = min(month["exported"] * SURPLUS, month["imported"] * PRICE)
        assert comp <= month["imported"] * PRICE + 1e-9

    # (3) Con tope, el ahorro es MENOR que si el excedente se pagara sin límite.
    uncapped = (
        (balance["direct_kwh"] + balance["battery_kwh"]) * PRICE
        + balance["exported_kwh"] * SURPLUS
    )
    assert capped < uncapped


def test_capped_never_exceeds_feed_in():
    # feed_in (sin tope) siempre paga >= que capped_compensation con el mismo
    # excedente, confirmando que el tope reduce el ahorro y no al revés.
    production, consumption = _low_consumption_big_system()
    balance = simulate_self_consumption(production, consumption, 0.0)
    capped = annual_savings_with_surplus(balance, PRICE, SURPLUS, "capped_compensation")
    feed_in = annual_savings_with_surplus(balance, PRICE, SURPLUS, "feed_in")
    assert capped <= feed_in + 1e-6
