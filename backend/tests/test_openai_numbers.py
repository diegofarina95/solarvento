"""Normalización de números del parser IA: formato español uniforme.

Regresión del bug: el esquema pedía los números como `number` JSON, así que el
modelo resolvía mal el separador de miles español ("6.551" -> 6.551 ≈ 7 kWh)
antes de que llegaran a la app. Ahora cada campo numérico viaja como texto y se
normaliza con la MISMA función canónica (_to_float) que el parser local.
"""

from app.bills import _to_float, aggregate_bills, validate_bill_consumption
from app.openai_bills import _normalize_openai_bill, _optional_float
from app.schemas import BillInput

# Factura LuzNorte (Santiago), 6.551 kWh/año, valle-dominante, 3 periodos.
LUZNORTE_OPENAI = {
    "kwh": "6.551",
    "energy_eur": "1.182,06",
    "total_eur": "1.689,65",
    "amount_eur": "1.689,65",
    "power_eur": "132,40",
    "iva_rate": "0,21",
    "contracted_power_kw": "4,6",
    "currency": "EUR",
    "start_date": "2026-01-01",
    "end_date": "2026-12-31",
    "consumption_periods": {"punta": "950", "llano": "1.450", "valle": "4.151"},
    "consumption_period_prices": {"punta": "0,241", "llano": "0,205", "valle": "0,158"},
    "consumption_history": [
        {"month": m, "kwh": v, "eur": None}
        for m, v in zip(
            range(1, 13),
            ["612", "560", "545", "520", "498", "470",
             "455", "460", "500", "540", "600", "791"],
        )
    ],
    "warnings": [],
}


class TestCanonicalNumberFormat:
    def test_spanish_tokens_kwh_and_currency(self):
        # Punto = miles, coma = decimal — aplicado igual a kWh y a importe.
        assert _to_float("6.551") == 6551.0
        assert _to_float("1.689,65") == 1689.65
        assert _to_float("0,24") == 0.24
        assert _optional_float("6.551") == 6551.0
        assert _optional_float("1.689,65") == 1689.65
        assert _optional_float("0,24") == 0.24
        # Token con unidad/símbolo: se ignora la unidad, no el número.
        assert _optional_float("0,241000 EUR/kWh") == 0.241
        assert _optional_float("1.689,65 €") == 1689.65
        # Ya normalizado (punto decimal con 2 cifras, sin coma) → intacto.
        assert _optional_float("6551.00") == 6551.0

    def test_no_numeric_field_bypasses_normaliser(self):
        # Cada campo se entrega en formato español; float() nativo daría None
        # (comas) o magnitud errónea (puntos). Si sale el valor correcto, pasó
        # por _to_float. Ningún campo se salta la normalización.
        bill = _normalize_openai_bill(LUZNORTE_OPENAI)
        assert bill["kwh"] == 6551.0
        assert bill["energy_eur"] == 1182.06
        assert bill["total_eur"] == 1689.65
        assert bill["amount_eur"] == 1689.65
        assert bill["power_eur"] == 132.40
        assert bill["iva_rate"] == 0.21
        assert bill["contracted_power_kw"] == 4.6
        assert bill["consumption_periods"] == {"punta": 950.0, "llano": 1450.0, "valle": 4151.0}
        assert bill["consumption_period_prices"] == {
            "punta": 0.241, "llano": 0.205, "valle": 0.158,
        }
        # Histórico: kWh de cada mes también normalizado.
        assert bill["consumption_history"][0]["kwh"] == 612.0

    def test_numeric_passthrough_backcompat(self):
        # Un número JSON sin ambigüedad de miles sigue aceptándose.
        assert _optional_float(245.7) == 245.7
        assert _optional_float(0) is None or _optional_float(0) == 0.0


class TestLuzNorteReconciles:
    def test_parses_to_6551_no_review(self):
        bill = _normalize_openai_bill(LUZNORTE_OPENAI)
        assert bill["kwh"] == 6551.0  # no 14, no 7
        assert bill["needs_review"] is False
        assert bill["review_reasons"] == []

    def test_period_sum_and_effective_price(self):
        bill = _normalize_openai_bill(LUZNORTE_OPENAI)
        periods = bill["consumption_periods"]
        assert sum(periods.values()) == 6551.0  # 950 + 1450 + 4151
        # Precio efectivo 1.689,65 / 6.551 ≈ 0,258 €/kWh, dentro de banda.
        assert abs(bill["total_eur"] / bill["kwh"] - 0.258) < 0.005
        # Cuota valle ≈ 63,4 %.
        assert abs(periods["valle"] / bill["kwh"] - 0.634) < 0.01

    def test_history_reconciles_and_aggregate_ok(self):
        bill = _normalize_openai_bill(LUZNORTE_OPENAI)
        assert sum(h["kwh"] for h in bill["consumption_history"]) == 6551.0
        assert validate_bill_consumption(bill) == []
        # Producción: los campos pasan por BillInput (fechas → date) antes de agregar.
        agg = aggregate_bills([BillInput(**{
            k: v for k, v in bill.items()
            if k in BillInput.model_fields
        }).model_dump()])
        assert agg["annual_kwh"] == 6551.0
        assert agg["needs_review"] is False
        assert agg["valle_price_eur_kwh"] == 0.158


class TestGuardsNotWeakened:
    def test_a_estrada_still_13800(self):
        # Regresión: A Estrada por la vía IA (strings) sigue dando 13.800.
        bill = _normalize_openai_bill({
            "kwh": "13.800", "total_eur": "3.027,14", "amount_eur": "3.027,14",
            "currency": "EUR",
            "consumption_periods": {"punta": "2.150", "llano": "2.820", "valle": "8.830"},
            "warnings": [],
        })
        assert bill["kwh"] == 13800.0
        assert bill["needs_review"] is False

    def test_genuine_misparse_still_trips_review(self):
        # Una columna de periodo tomada por el total, ya normalizada, sin split
        # que la repare: el precio efectivo imposible SIGUE disparando revisión.
        bill = _normalize_openai_bill({
            "kwh": "2.150", "total_eur": "3.027,14", "amount_eur": "3.027,14",
            "currency": "EUR", "warnings": [],
        })
        assert bill["kwh"] == 2150.0
        assert bill["needs_review"] is True
        assert any("precio efectivo" in r.lower() for r in bill["review_reasons"])
