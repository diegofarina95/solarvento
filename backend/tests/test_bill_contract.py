"""Layer 1+3 — contrato estricto y normalización/validación deterministas."""

from app.bill_contract import BILL_CONTRACT_SCHEMA
from app.bill_normalise import contract_to_bill


def _nf(raw, label="x", conf=0.9, value=None):
    return {"raw_text": raw, "value": value, "source_label": label, "confidence": conf}


def _luznorte_contract(headline="6.551"):
    return {
        "annual_consumption_kwh": _nf(headline, "Consumo facturado"),
        "period_total_kwh": _nf("6.551", "Total periodos"),
        "period_split": {
            "p1_punta": _nf("950", "P1"),
            "p2_llano": _nf("1.450", "P2"),
            "p3_valle": _nf("4.151", "P3"),
        },
        "period_split_prices": {
            "p1_punta": _nf("0,241", "P1 €"),
            "p2_llano": _nf("0,205", "P2 €"),
            "p3_valle": _nf("0,158", "P3 €"),
        },
        "monthly_history": [
            {"month": m, "kwh": _nf(str(k), "hist")}
            for m, k in zip(
                range(1, 13),
                [612, 560, 545, 520, 498, 470, 455, 460, 500, 540, 600, 791],
            )
        ],
        "contracted_power_kw": _nf("4,6", "Potencia"),
        "tariff": "2.0TD",
        "billing_period": {"start": "2026-01-01", "end": "2026-12-31"},
        "energy_term_eur": _nf("1.182,06", "Energía"),
        "energy_term_eur_per_kwh": _nf("0,180", "precio"),
        "total_amount_eur": _nf("1.689,65", "Total factura"),
        "electricity_tax_eur": _nf("86,40", "IEE"),
        "vat_eur": _nf("293,20", "IVA"),
        "vat_rate": _nf("0,21", "IVA%"),
        "currency": "EUR",
        "country_code": "ES",
        "language": "es",
        "supply_address": {
            "street": "Rua Nova 3", "cp": "15701",
            "municipio": "Santiago de Compostela", "provincia": "A Coruña",
        },
        "cups": "ES0031X",
        "warnings": [],
    }


def _assert_strict(schema):
    """Todo objeto: additionalProperties=False y required == todas las propiedades."""
    if isinstance(schema, dict):
        types = schema.get("type")
        is_object = types == "object" or (isinstance(types, list) and "object" in types)
        if is_object and "properties" in schema:
            assert schema.get("additionalProperties") is False
            assert set(schema.get("required", [])) == set(schema["properties"])
            for sub in schema["properties"].values():
                _assert_strict(sub)
        if "items" in schema:
            _assert_strict(schema["items"])


class TestContractSchemaStrict:
    def test_schema_is_strict_recursively(self):
        _assert_strict(BILL_CONTRACT_SCHEMA)

    def test_numeric_fields_carry_the_envelope(self):
        env = BILL_CONTRACT_SCHEMA["properties"]["annual_consumption_kwh"]["properties"]
        assert set(env) == {"raw_text", "value", "source_label", "confidence"}


class TestNormaliseAndReconcile:
    def test_spanish_numbers_normalised_deterministically(self):
        bill = contract_to_bill(_luznorte_contract())
        assert bill["kwh"] == 6551.0
        assert bill["total_eur"] == 1689.65
        assert bill["contracted_power_kw"] == 4.6
        assert bill["consumption_periods"] == {"punta": 950.0, "llano": 1450.0, "valle": 4151.0}
        assert bill["needs_review"] is False

    def test_mis_parsed_headline_corrected_by_agreement(self):
        # "6.551" mal leído como 14 en la cabecera; total de periodos + histórico
        # + suma de columnas coinciden en 6.551 → se corrige, computa.
        bill = contract_to_bill(_luznorte_contract(headline="14"))
        assert bill["kwh"] == 6551.0
        assert bill["needs_review"] is False
        assert any("corregido" in w for w in bill["warnings"])

    def test_effective_price_in_band(self):
        bill = contract_to_bill(_luznorte_contract())
        assert abs(bill["total_eur"] / bill["kwh"] - 0.258) < 0.005

    def test_candidates_surface_raw_and_normalised(self):
        bill = contract_to_bill(_luznorte_contract(headline="14"))
        by = {c["candidate"]: c for c in bill["consumption_candidates"]}
        assert by["headline"]["raw_text"] == "14"
        assert by["period_total_printed"]["value"] == 6551.0
        assert by["monthly_history_sum"]["value"] == 6551.0
        assert all(c.get("source_label") is not None for c in bill["consumption_candidates"])


class TestReviewOnBadInput:
    def test_malformed_contract_is_review_not_crash(self):
        assert contract_to_bill(None)["needs_review"] is True
        assert contract_to_bill({})["needs_review"] is True

    def test_partial_contract_missing_consumption_reviews(self):
        bill = contract_to_bill({
            "total_amount_eur": _nf("1.689,65", "Total"),
            "currency": "EUR", "warnings": [],
        })
        assert bill["needs_review"] is True

    def test_sources_disagree_reviews(self):
        c = _luznorte_contract(headline="9.999")
        # sin total impreso ni histórico que corroboren: cabecera 9999 vs suma 6551
        c["period_total_kwh"] = _nf(None, "Total")
        c["monthly_history"] = []
        bill = contract_to_bill(c)
        assert bill["needs_review"] is True

    def test_single_column_as_total_repaired(self):
        # A Estrada: la cabecera es una sola columna (2.150); columnas suman 13.800.
        c = {
            "annual_consumption_kwh": _nf("2.150", "Consumo (mal: solo P1)"),
            "period_total_kwh": _nf(None, "-"),
            "period_split": {
                "p1_punta": _nf("2.150", "P1"),
                "p2_llano": _nf("2.820", "P2"),
                "p3_valle": _nf("8.830", "P3"),
            },
            "period_split_prices": {"p1_punta": _nf(None), "p2_llano": _nf(None), "p3_valle": _nf(None)},
            "monthly_history": [],
            "contracted_power_kw": _nf("6,9", "Potencia"),
            "tariff": "2.0TD",
            "billing_period": {"start": "2026-01-01", "end": "2026-12-31"},
            "energy_term_eur": _nf("2.086,92", "Energía"),
            "energy_term_eur_per_kwh": _nf(None),
            "total_amount_eur": _nf("3.027,14", "Total"),
            "electricity_tax_eur": _nf(None), "vat_eur": _nf(None), "vat_rate": _nf("0,21"),
            "currency": "EUR", "country_code": "ES", "language": "es",
            "supply_address": {"street": None, "cp": "36680", "municipio": "A Estrada", "provincia": "Pontevedra"},
            "cups": None, "warnings": [],
        }
        bill = contract_to_bill(c)
        assert bill["kwh"] == 13800.0
        assert bill["needs_review"] is False
