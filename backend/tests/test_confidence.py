"""Tests del nivel de confianza del informe (_confidence_summary).

La confianza del PERFIL de consumo depende de qué ESTACIONES cubren las
facturas (frío nov-feb + cálido jun-sep), no de cuántos ficheros se suban ni de
si llevan importe. Dos facturas de estaciones opuestas fijan la forma del
consumo (invierno alto / verano bajo o A/A) y dan confianza alta; dos facturas
de la misma estación, no. El importe (priced) afecta al PRECIO, no a la forma.
"""

from datetime import date

from app import main
from app.bills import aggregate_bills

PRICES_CURRENT = {"source_type": "providers", "fallback_used": False}


def _summary(observed_months, *, bill_count, priced_bill_count, annual_from_printed=False):
    return {
        "source": "bills",
        "bill_count": bill_count,
        "priced_bill_count": priced_bill_count,
        "observed_months": observed_months,
        "annual_from_printed": annual_from_printed,
    }


def _confidence(summary):
    return main._confidence_summary(summary, "bills", PRICES_CURRENT, hourly_degraded=False)


def test_opposite_seasons_two_bills_is_high_even_if_only_one_priced():
    # Q1 (ene-mar, frío) + Q3 (jul-sep, cálido): cubren estaciones opuestas.
    conf = _confidence(
        _summary([1, 2, 3, 7, 8, 9], bill_count=2, priced_bill_count=1)
    )
    assert conf["level"] == "high"
    # Y NO debe pedir "invierno + verano": ya están cubiertos.
    assert "add_seasonal_bills" not in conf["improvement_hints"]


def test_same_season_two_bills_not_high_and_asks_for_opposite_season():
    # Jun + Ago: dos facturas de VERANO. Falta el invierno.
    conf = _confidence(_summary([6, 8], bill_count=2, priced_bill_count=2))
    assert conf["level"] != "high"
    assert "add_seasonal_bills" in conf["improvement_hints"]


def test_full_year_history_is_high():
    conf = _confidence(
        _summary(list(range(1, 13)), bill_count=1, priced_bill_count=1)
    )
    assert conf["level"] == "high"
    assert conf["improvement_hints"] == []


def test_declared_annual_plus_two_bills_is_high():
    # Anual impreso ("consumo último año") + 2 facturas: el anual real manda.
    conf = _confidence(
        _summary([1, 2], bill_count=2, priced_bill_count=2, annual_from_printed=True)
    )
    assert conf["level"] == "high"


def test_no_bills_suggests_uploading_one():
    conf = _confidence(_summary([], bill_count=0, priced_bill_count=0))
    assert conf["level"] != "high"
    assert "add_priced_bills" in conf["improvement_hints"]


def test_single_winter_bill_asks_for_opposite_season():
    conf = _confidence(_summary([1, 2], bill_count=1, priced_bill_count=1))
    assert conf["level"] != "high"
    assert "add_seasonal_bills" in conf["improvement_hints"]


def test_end_to_end_two_quarter_bills_opposite_seasons_is_high():
    # El caso de verificación del usuario: dos facturas trimestrales del MISMO
    # CUPS (ene-mar + jul-sep) → confianza alta, sin pedir invierno+verano.
    cups = "ES0031ABC"
    agg = aggregate_bills(
        [
            {"start_date": date(2025, 1, 1), "end_date": date(2025, 3, 31),
             "kwh": 900, "energy_eur": 180, "cups": cups},
            {"start_date": date(2025, 7, 1), "end_date": date(2025, 9, 30),
             "kwh": 600, "cups": cups},
        ]
    )
    summary = {
        "source": "bills",
        "bill_count": agg["bill_count"],
        "priced_bill_count": agg["priced_bill_count"],
        "observed_months": agg["observed_months"],
        "annual_from_printed": agg.get("annual_from_printed", False),
    }
    conf = _confidence(summary)
    assert conf["level"] == "high"
    assert "add_seasonal_bills" not in conf["improvement_hints"]
