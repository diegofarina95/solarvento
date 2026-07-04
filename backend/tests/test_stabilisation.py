"""Sprint de estabilización: máquina de 3 estados + cero números fabricados."""

from app.bill_normalise import contract_to_bill

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
