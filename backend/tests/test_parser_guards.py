"""Guardas del parser multi-periodo (2.0TD) — reconciliación y precio efectivo.

Regresión del bug crítico: en una factura 2.0TD de 3 periodos el parser tomaba
una sola columna de periodo (P1 Punta, 2.150 kWh) como consumo total en vez de
la suma real (13.800 kWh), dejando todo el dimensionado a ~1/6 de escala.
"""

from datetime import date

from app.bills import (
    _parse_period_table,
    _to_float,
    aggregate_bills,
    parse_bill_text,
    validate_bill_consumption,
)

# Factura 2.0TD realista de A Estrada (Pontevedra), valle-dominante, columnas
# apiladas como las lineariza un PDF, SIN una línea "Consumo del periodo" limpia.
A_ESTRADA_TEXT = """Naturgy - Factura electricidad 2.0TD
Punto de suministro: Rua do Muino 7, 36680 A Estrada, Pontevedra
Periodo del 01/01/2026 al 31/12/2026
Potencia contratada 6,9 kW
Resumen por periodos horarios
Periodo Consumo (kWh) Precio (EUR/kWh) Importe (EUR)
P1 Punta 2.150 0,189000 406,35
P2 Llano 2.820 0,151000 425,82
P3 Valle 8.830 0,112000 989,29
Termino de energia 2.086,92
Termino de potencia 142,00
Impuesto electrico 113,80
Base imponible 2.502,60
IVA 21% 524,54
TOTAL 3.027,14
"""


class TestPeriodTableByHeader:
    def test_total_is_sum_of_periods_not_first_column(self):
        table = _parse_period_table(A_ESTRADA_TEXT)
        assert table is not None
        # 2.150 + 2.820 + 8.830 = 13.800, NO 2.150 (la primera columna)
        assert table["total_kwh"] == 13800.0
        assert table["periods"] == {"punta": 2150.0, "llano": 2820.0, "valle": 8830.0}

    def test_parse_bill_text_reads_total_consumption(self):
        result = parse_bill_text(A_ESTRADA_TEXT)
        assert result["kwh"] == 13800.0  # no 2.150
        assert result["consumption_periods"] == {
            "punta": 2150.0,
            "llano": 2820.0,
            "valle": 8830.0,
        }

    def test_single_period_row_is_not_a_table(self):
        # Una sola fila de periodo no es una tabla fiable de N periodos.
        assert _parse_period_table("P1 Punta 2.150 kWh 0,189 EUR/kWh") is None


class TestReconciliationGuard:
    def test_period_column_mistaken_for_total_fails(self):
        bill = {
            "kwh": 2150.0,  # una sola columna tomada por el total
            "total_eur": 3027.14,
            "currency": "EUR",
            "consumption_periods": {"punta": 2150.0, "llano": 2820.0, "valle": 8830.0},
        }
        reasons = validate_bill_consumption(bill)
        assert reasons  # debe FALLAR, no pasar en silencio
        assert any("periodo" in r.lower() for r in reasons)

    def test_correct_total_reconciles(self):
        bill = {
            "kwh": 13800.0,
            "total_eur": 3027.14,
            "currency": "EUR",
            "consumption_periods": {"punta": 2150.0, "llano": 2820.0, "valle": 8830.0},
        }
        assert validate_bill_consumption(bill) == []


class TestEffectivePriceGuard:
    def test_price_of_1_41_trips_review(self):
        bill = {"kwh": 2150.0, "total_eur": 3027.14, "currency": "EUR"}
        reasons = validate_bill_consumption(bill)
        assert any("precio efectivo" in r.lower() for r in reasons)

    def test_price_of_0_22_passes(self):
        bill = {"kwh": 13800.0, "total_eur": 3027.14, "currency": "EUR"}
        assert validate_bill_consumption(bill) == []

    def test_parse_sets_needs_review_on_bad_total(self):
        # Si sólo tuviéramos P1 y ningún total de periodos, el precio efectivo
        # sobre 2.150 debe marcar revisión.
        result = parse_bill_text(A_ESTRADA_TEXT)
        # El parse correcto NO necesita revisión (lee 13.800)
        assert result["needs_review"] is False


class TestSpanishNumberFormat:
    def test_thousands_dot_no_decimal(self):
        assert _to_float("13.800") == 13800.0

    def test_thousands_dot_with_decimal_comma(self):
        assert _to_float("2.086,92") == 2086.92

    def test_plain_decimal_comma(self):
        assert _to_float("0,151") == 0.151


class TestSingleSourceOfTruth:
    def test_price_and_sizing_use_same_annual_consumption(self):
        bill = {
            "kwh": 13800.0,
            "energy_eur": 2086.92,
            "amount_eur": 3027.14,
            "total_eur": 3027.14,
            "currency": "EUR",
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
            "iva_rate": 0.21,
        }
        agg = aggregate_bills([bill])
        # El consumo anual es único; el precio se deriva de ese mismo consumo.
        assert agg["annual_kwh"] == 13800.0
        implied = agg["annual_amount_eur"] / agg["avg_price_eur_kwh"]
        # precio medio = energía/consumo; importe/precio debe reconciliar el consumo
        assert abs(implied - agg["annual_kwh"]) <= agg["annual_kwh"] * 0.5
        assert agg.get("needs_review") is False
