"""Sprint de estabilización: máquina de 3 estados + cero números fabricados."""

from app.bill_normalise import _rate, contract_to_bill
from app.schemas import SolarEstimateRequest

_VALID = {
    "annual_consumption_kwh": "2.902",
    "total_amount_eur": "725,50",
    "currency": "EUR",
    "country_code": "ES",
    "period_split": {"p1_punta": None, "p2_llano": None, "p3_valle": None},
}

_NUMERIC_KEYS = (
    "kwh", "energy_eur", "total_eur", "amount_eur", "iee_eur", "iva_eur",
    "iva_rate", "contracted_power_kw", "consumption_periods",
)


class TestStateMachine:
    def test_valid_state_computes(self):
        bill = contract_to_bill(_VALID)
        assert bill["state"] == "valid"
        assert bill["needs_review"] is False
        assert bill["kwh"] == 2902.0

    def test_needs_review_state(self):
        # Precio efectivo imposible (una columna sola sin corroborar) → needs_review.
        bill = contract_to_bill({
            "annual_consumption_kwh": "2.150", "total_amount_eur": "3.027,14", "currency": "EUR",
        })
        assert bill["state"] == "needs_review"
        assert bill["needs_review"] is True

    def test_extraction_failed_state(self):
        bill = contract_to_bill(None)
        assert bill["state"] == "extraction_failed"

    def test_only_three_states_exist(self):
        seen = {
            contract_to_bill(_VALID)["state"],
            contract_to_bill({"annual_consumption_kwh": "2.150", "total_amount_eur": "3.027,14",
                              "currency": "EUR"})["state"],
            contract_to_bill(None)["state"],
        }
        assert seen <= {"valid", "needs_review", "extraction_failed"}


class TestNoFabricatedNumbers:
    def test_extraction_failure_leaves_all_numbers_empty(self):
        # PHASE 1/5: en fallo de extracción NINGÚN campo numérico se rellena.
        bill = contract_to_bill(None)
        for key in _NUMERIC_KEYS:
            assert bill.get(key) in (None, {}), f"{key} no debe rellenarse: {bill.get(key)}"

    def test_empty_contract_fabricates_nothing(self):
        bill = contract_to_bill({})
        assert bill["kwh"] is None
        assert bill["state"] in ("extraction_failed", "needs_review")
        assert bill.get("total_eur") is None

    def test_no_phantom_312(self):
        # El fantasma 312/43,06/71,39 no puede aparecer desde el backend.
        bill = contract_to_bill(None)
        assert bill["kwh"] != 312
        assert bill.get("total_eur") not in (43.06, 71.39)


class TestVatRateNormalisation:
    def test_percentage_becomes_fraction(self):
        assert _rate("21") == 0.21
        assert _rate("21%") == 0.21
        assert _rate("0,21") == 0.21
        assert _rate("5,5") == 0.055
        assert _rate(None) is None
        assert _rate("300") is None  # absurdo → se descarta, no rompe el cálculo

    def test_imported_bill_passes_estimate_validation(self):
        # Regresión: IVA "21" (porcentaje) rompía /solar-estimate con 422
        # (iva_rate le=0.3). Ahora se normaliza a 0,21 y valida.
        bill = contract_to_bill({
            "annual_consumption_kwh": "4.200", "total_amount_eur": "1.150,00",
            "energy_term_eur": "820,00", "vat_rate": "21", "currency": "EUR",
            "country_code": "ES",
            "billing_period": {"start": "2025-01-01", "end": "2025-12-31", "days": "365"},
        })
        assert bill["iva_rate"] == 0.21
        row = {
            "kwh": bill["kwh"], "energy_eur": bill["energy_eur"], "total_eur": bill["total_eur"],
            "amount_eur": bill["total_eur"], "currency": "EUR", "iva_rate": bill["iva_rate"],
        }
        # No debe lanzar ValidationError (era el 422 "Invalid parameters").
        SolarEstimateRequest(lat=42.6, lon=-8.5, country_code="ES", peak_power_kwp=3.0, bills=[row])

    def test_absurd_rate_does_not_break_estimate(self):
        bill = contract_to_bill({
            "annual_consumption_kwh": "4.200", "total_amount_eur": "1.150,00",
            "vat_rate": "2100", "currency": "EUR", "country_code": "ES",
        })
        assert bill["iva_rate"] is None
        row = {"kwh": bill["kwh"], "total_eur": bill["total_eur"], "amount_eur": bill["total_eur"],
               "currency": "EUR", "iva_rate": bill["iva_rate"]}
        SolarEstimateRequest(lat=42.6, lon=-8.5, country_code="ES", peak_power_kwp=3.0, bills=[row])
