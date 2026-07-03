"""Reconciliación del consumo anual entre sus varias fuentes + normalización única.

La misma cifra aparece en varios sitios (tarjeta 'consumo facturado', total de la
tabla de periodos, suma del histórico mensual). Se cruzan: si dos coinciden, esa
manda y se corrige la que discrepe; solo si ninguna se corrobora se revisa. Y todo
extractor numérico pasa por la MISMA función de normalización (_to_float).
"""

from app.bills import (
    _ENERGY_CHARGE_LABELS,
    _find_charge_amount,
    _find_contracted_power_kw,
    _find_total_amount,
    _parse_period_table,
    _to_float,
    parse_consumption_history,
    reconcile_annual_consumption,
    validate_bill_consumption,
)

_LUZNORTE_HISTORY = [
    {"month": m, "kwh": k}
    for m, k in zip(range(1, 13), [612, 560, 545, 520, 498, 470, 455, 460, 500, 540, 600, 791])
]


def _reconciled(bill):
    kwh, note, review = reconcile_annual_consumption(bill)
    review = review + validate_bill_consumption({**bill, "kwh": kwh})
    return kwh, note, review


class TestReconcileCorrects:
    def test_mis_parsed_card_corrected_by_period_and_history(self):
        # Tarjeta 'consumo facturado' mal parseada (14) pero periodos e histórico
        # coinciden en 6.551 → se corrige a 6.551 y la factura calcula.
        bill = {
            "kwh": 14.0, "total_eur": 1689.65, "currency": "EUR",
            "consumption_periods": {"punta": 950, "llano": 1450, "valle": 4151},
            "consumption_history": _LUZNORTE_HISTORY,
        }
        kwh, note, review = _reconciled(bill)
        assert kwh == 6551.0
        assert note is not None
        assert review == []

    def test_single_period_column_repaired_to_sum(self):
        # A Estrada: la cabecera es una sola columna (2.150); la suma es 13.800.
        bill = {
            "kwh": 2150.0, "total_eur": 3027.14, "currency": "EUR",
            "consumption_periods": {"punta": 2150, "llano": 2820, "valle": 8830},
        }
        kwh, note, review = _reconciled(bill)
        assert kwh == 13800.0
        assert review == []

    def test_already_correct_untouched(self):
        bill = {
            "kwh": 6551.0, "total_eur": 1689.65, "currency": "EUR",
            "consumption_periods": {"punta": 950, "llano": 1450, "valle": 4151},
        }
        kwh, note, review = _reconciled(bill)
        assert kwh == 6551.0
        assert note is None
        assert review == []

    def test_effective_price_ok_after_correction(self):
        bill = {
            "kwh": 14.0, "total_eur": 1689.65, "currency": "EUR",
            "consumption_periods": {"punta": 950, "llano": 1450, "valle": 4151},
            "consumption_history": _LUZNORTE_HISTORY,
        }
        kwh, _note, _review = _reconciled(bill)
        assert abs(1689.65 / kwh - 0.258) < 0.005


class TestReconcileReviews:
    def test_genuine_misparse_single_column_no_other_source(self):
        # Una sola columna tomada por total, sin periodos/histórico que corroboren:
        # el precio efectivo imposible SIGUE disparando revisión.
        bill = {"kwh": 2150.0, "total_eur": 3027.14, "currency": "EUR"}
        kwh, _note, review = _reconciled(bill)
        assert kwh == 2150.0
        assert review

    def test_sources_disagree_goes_to_review(self):
        # Dos fuentes que no coinciden entre sí ni reparan → revisión.
        bill = {
            "kwh": 3000.0, "total_eur": 700.0, "currency": "EUR",
            "consumption_history": [{"month": m, "kwh": 100} for m in range(1, 13)],
        }
        # headline 3000 vs histórico 1200; no coinciden, ninguna repara.
        _kwh, _note, review = _reconciled(bill)
        assert review


class TestEveryExtractorNormalises:
    # Formato español: "." = miles, "," = decimal. Si un extractor NO pasara por
    # _to_float, "6.551" saldría como 6.551 (o None). Valores correctos ⇒ pasó.
    def test_to_float_canonical(self):
        assert _to_float("6.551") == 6551.0
        assert _to_float("1.689,65") == 1689.65
        assert _to_float("0,24") == 0.24

    def test_period_table_extractor(self):
        table = _parse_period_table(
            "P1 Punta 950 0,241 228,95\nP2 Llano 1.450 0,205 297,25\nP3 Valle 4.151 0,158 655,86\n"
        )
        assert table["total_kwh"] == 6551.0
        assert table["periods"] == {"punta": 950.0, "llano": 1450.0, "valle": 4151.0}

    def test_total_amount_extractor(self):
        assert _find_total_amount("TOTAL A PAGAR 1.689,65 EUR", []) == 1689.65

    def test_charge_amount_extractor(self):
        assert _find_charge_amount(
            "Término de energía 1.182,06 €", _ENERGY_CHARGE_LABELS
        ) == 1182.06

    def test_contracted_power_extractor(self):
        assert _find_contracted_power_kw("Potencia contratada 4,6 kW") == 4.6

    def test_history_extractor(self):
        rows = parse_consumption_history(
            "Histórico de consumo\nEne 1.234 kWh\nFeb 2.500 kWh\n"
        )
        by_month = {r["month"]: r["kwh"] for r in rows}
        assert by_month[1] == 1234.0
        assert by_month[2] == 2500.0
