"""Simulación de autoconsumo con y sin batería.

Modelo: para cada mes se simula un día medio hora a hora (producción PVGIS
contra consumo del perfil) y se escala por los días del mes. La batería se
modela con capacidad útil dada y eficiencia de ida y vuelta del 90% (la
pérdida se aplica al cargar). El día medio se encadena (el estado de carga
final de un día es el inicial del siguiente), empezando vacío cada mes.

Economía (modelo español de compensación simplificada de excedentes): la
energía autoconsumida ahorra el precio de compra; el excedente vertido se
compensa a un precio menor y, como marca la normativa, la compensación de un
mes no puede superar el coste de la energía comprada ese mes.
"""

from .profiles import DAYS_PER_MONTH

ROUND_TRIP_EFFICIENCY = 0.90
BATTERY_CYCLES_PER_MONTH_CHAIN = 3  # días encadenados para estabilizar el estado de carga


def simulate_self_consumption(
    production: list[list[float]],
    consumption: list[list[float]],
    battery_kwh: float = 0.0,
) -> dict:
    """Balance energético anual de la instalación.

    production/consumption: matrices 12x24 en kWh (día medio de cada mes).
    Devuelve kWh anuales: autoconsumo directo, descargado de batería,
    excedente vertido, importado de red, y los porcentajes de autoconsumo
    (producción aprovechada) y autosuficiencia (consumo cubierto), además
    del desglose mensual de compra y vertido para aplicar la compensación.
    """
    totals = {
        "direct_kwh": 0.0,
        "battery_kwh": 0.0,
        "exported_kwh": 0.0,
        "imported_kwh": 0.0,
        "production_kwh": 0.0,
        "consumption_kwh": 0.0,
    }
    monthly = []

    for m in range(12):
        days = DAYS_PER_MONTH[m]
        # Se simulan varios días encadenados y se toma el último, para que el
        # estado de carga inicial refleje el régimen estacionario del mes.
        soc = 0.0
        day = None
        for _ in range(BATTERY_CYCLES_PER_MONTH_CHAIN):
            day = {"direct": 0.0, "battery": 0.0, "exported": 0.0, "imported": 0.0}
            for h in range(24):
                prod, cons = production[m][h], consumption[m][h]
                direct = min(prod, cons)
                surplus = prod - direct
                deficit = cons - direct
                day["direct"] += direct

                if surplus > 0 and battery_kwh > 0:
                    room = (battery_kwh - soc) / ROUND_TRIP_EFFICIENCY
                    charged = min(surplus, room)
                    soc += charged * ROUND_TRIP_EFFICIENCY
                    surplus -= charged
                if deficit > 0 and soc > 0:
                    discharged = min(deficit, soc)
                    soc -= discharged
                    deficit -= discharged
                    day["battery"] += discharged

                day["exported"] += surplus
                day["imported"] += deficit

        month = {k: v * days for k, v in day.items()}
        month["production"] = sum(production[m]) * days
        month["consumption"] = sum(consumption[m]) * days
        monthly.append(month)

        totals["direct_kwh"] += month["direct"]
        totals["battery_kwh"] += month["battery"]
        totals["exported_kwh"] += month["exported"]
        totals["imported_kwh"] += month["imported"]
        totals["production_kwh"] += month["production"]
        totals["consumption_kwh"] += month["consumption"]

    self_consumed = totals["direct_kwh"] + totals["battery_kwh"]
    # Autoconsumo (SCR, def. estándar) = fracción de la producción NO vertida, de
    # modo que SIEMPRE se cumple: excedente = producción × (1 − autoconsumo%).
    # Con batería, la pérdida de ciclado (round-trip) cuenta como "no vertida"
    # (se quedó en tu lado), no como excedente; por eso no basta direct+descarga.
    totals["self_consumption_pct"] = (
        round(
            min(100.0, max(0.0, 100 * (totals["production_kwh"] - totals["exported_kwh"]) / totals["production_kwh"])),
            1,
        )
        if totals["production_kwh"] > 0
        else 0.0
    )
    # Autosuficiencia = parte del CONSUMO realmente cubierta (energía que sirvió
    # a la carga: directa + descarga de batería); la pérdida de ciclado no cuenta.
    totals["self_sufficiency_pct"] = (
        round(min(100.0, max(0.0, 100 * self_consumed / totals["consumption_kwh"])), 1)
        if totals["consumption_kwh"] > 0
        else 0.0
    )
    totals = {k: round(v, 1) if isinstance(v, float) else v for k, v in totals.items()}
    totals["monthly"] = monthly
    return totals


# Mecanismos de retribución del excedente vertido a red, por país:
#  - capped_compensation: descuento en factura con tope mensual (España, Portugal):
#    la compensación de un mes no puede superar el coste de la energía comprada.
#  - feed_in: tarifa de inyección pagada por kWh sin tope (Alemania, Francia…):
#    es un ingreso real, puede superar el gasto anual en luz.
#  - net_metering: balance neto, cada kWh vertido anula 1:1 un kWh importado
#    a precio de compra (Países Bajos salderen, algunos países del Este).
#  - market_price: venta a precio de mercado sin tope (net-billing polaco, países nórdicos).
EXPORT_SCHEMES = ("capped_compensation", "feed_in", "net_metering", "market_price")


def annual_savings_with_surplus(
    balance: dict,
    price_eur_kwh: float,
    surplus_price_eur_kwh: float,
    export_scheme: str = "capped_compensation",
) -> float:
    """Ahorro anual: autoconsumo a precio de compra + excedentes según el país."""
    self_consumed_value = (balance["direct_kwh"] + balance["battery_kwh"]) * price_eur_kwh
    annual_spend = balance["consumption_kwh"] * price_eur_kwh

    if export_scheme == "net_metering":
        # Cada kWh vertido compensa un kWh importado al precio de compra;
        # el excedente por encima de lo importado no se retribuye.
        offset_kwh = min(balance["exported_kwh"], balance["imported_kwh"])
        savings = self_consumed_value + offset_kwh * price_eur_kwh
        return round(min(savings, annual_spend), 2)

    if export_scheme in ("feed_in", "market_price"):
        # Ingreso real por kWh vertido, sin tope: puede superar el gasto anual.
        savings = self_consumed_value + balance["exported_kwh"] * surplus_price_eur_kwh
        return round(savings, 2)

    # capped_compensation (default): tope mensual al coste de lo importado
    savings = 0.0
    for month in balance["monthly"]:
        self_consumed = month["direct"] + month["battery"]
        compensation = min(
            month["exported"] * surplus_price_eur_kwh,
            month["imported"] * price_eur_kwh,
        )
        savings += self_consumed * price_eur_kwh + compensation
    return round(min(savings, annual_spend), 2)


def battery_scenarios(
    production: list[list[float]],
    consumption: list[list[float]],
    capacities_kwh: list[float],
    price_eur_kwh: float,
    surplus_price_eur_kwh: float,
    system_cost_eur: float,
    battery_cost_eur_kwh: float,
    export_scheme: str = "capped_compensation",
) -> list[dict]:
    """Compara escenarios de batería (0 = sin batería incluida si se pasa).

    Para cada capacidad: balance, ahorro anual, inversión total y payback.
    El payback marginal de la batería compara con el escenario sin batería.
    battery_cost_eur_kwh puede ser un float único o un dict {capacidad: €/kWh}
    (las baterías pequeñas cuestan más por kWh que las grandes).
    """

    def _unit_cost(capacity: float) -> float:
        if isinstance(battery_cost_eur_kwh, dict):
            return battery_cost_eur_kwh.get(capacity, 0.0)
        return battery_cost_eur_kwh

    base = None
    scenarios = []
    for capacity in capacities_kwh:
        balance = simulate_self_consumption(production, consumption, capacity)
        savings = annual_savings_with_surplus(
            balance, price_eur_kwh, surplus_price_eur_kwh, export_scheme
        )
        investment = system_cost_eur + capacity * _unit_cost(capacity)
        scenario = {
            "battery_kwh": capacity,
            "annual_savings_eur": savings,
            "investment_eur": round(investment, 2),
            "payback_years": round(investment / savings, 1) if savings > 0 else None,
            "self_consumption_pct": balance["self_consumption_pct"],
            "self_sufficiency_pct": balance["self_sufficiency_pct"],
            "production_kwh": balance["production_kwh"],
            "consumption_kwh": balance["consumption_kwh"],
            "self_consumed_kwh": round(
                balance["direct_kwh"] + balance["battery_kwh"], 1
            ),
            "direct_kwh": balance["direct_kwh"],
            "battery_discharged_kwh": balance["battery_kwh"],
            "exported_kwh": balance["exported_kwh"],
            "imported_kwh": balance["imported_kwh"],
        }
        if capacity == 0:
            base = scenario
        if base is not None and capacity > 0:
            # Payback INCREMENTAL de la batería (simple): lo que cuesta la batería
            # dividido por lo que AÑADE de ahorro frente al sistema sin batería.
            # No es el payback del sistema completo (inversión total / ahorro total).
            extra_savings = savings - base["annual_savings_eur"]
            extra_cost = investment - base["investment_eur"]
            scenario["battery_incremental_payback_years"] = (
                round(extra_cost / extra_savings, 1) if extra_savings > 0 else None
            )
            scenario["battery_extra_cost_eur"] = round(extra_cost, 2)
            scenario["battery_extra_savings_eur"] = round(extra_savings, 2)
        scenarios.append(scenario)
    return scenarios
