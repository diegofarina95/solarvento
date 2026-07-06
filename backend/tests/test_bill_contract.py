"""Layer 1+3 — contrato estricto y normalización/validación deterministas."""

from app.bill_contract import BILL_CONTRACT_SCHEMA
from app.bill_normalise import contract_to_bill
from app.bills import safe_to_float


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


def _caldas_contract(with_pv=True):
    """Caldas: factura de 22 días, P1..P6 (P4-6=0), histórico 12 meses, lecturas
    acumuladas, autoconsumo existente. Verdad anual = suma del histórico (4800)."""
    return {
        "bill_type_hint": "monthly_with_history",
        "annual_consumption_kwh": _nf("346", "Consumo del periodo", 0.9),
        "period_total_kwh": _nf("346", "Total periodos", 0.9),
        "period_split": {
            "p1_punta": _nf("63", "P1"), "p2_llano": _nf("83", "P2"), "p3_valle": _nf("200", "P3"),
            "p4": _nf(None), "p5": _nf(None), "p6": _nf(None),
        },
        "period_split_prices": {
            "p1_punta": _nf("0,20"), "p2_llano": _nf("0,15"), "p3_valle": _nf("0,10"),
            "p4": _nf(None), "p5": _nf(None), "p6": _nf(None),
        },
        "monthly_history": [{"month": m, "kwh": _nf("400", "Histórico")} for m in range(1, 13)],
        "meter_readings": {"initial": _nf("19460", "Lectura anterior"),
                           "final": _nf("19806", "Lectura actual")},
        "self_consumption_block": {
            "present": with_pv,
            "exported_kwh": _nf("500", "Excedentes") if with_pv else _nf(None),
            "compensation_eur_per_kwh": _nf("0,10") if with_pv else _nf(None),
        },
        "contracted_power_kw": [_nf("4,6", "P1"), _nf("4,6", "P2")],
        "tariff": "2.0TD",
        "billing_period": {"start": "2026-09-01", "end": "2026-09-23", "days": _nf("22")},
        "energy_term_eur": _nf("70,00"),
        "energy_term_eur_per_kwh": _nf(None),
        "total_amount_eur": _nf("95,00", "Total"),
        "electricity_tax_eur": _nf(None), "vat_eur": _nf(None), "vat_rate": _nf("0,21"),
        "currency": "EUR", "country_code": "ES", "language": "es",
        "supply_address": {"street": "Rúa X", "cp": "36650",
                           "municipio": "Caldas de Reis", "provincia": "Pontevedra"},
        "cups": "ES0031X", "warnings": [],
    }


class TestCaldasHardCases:
    def test_annual_from_history_not_flat_x365(self):
        bill = contract_to_bill(_caldas_contract(with_pv=False))
        res = bill["consumption_resolution"]
        assert res["method"] == "history"
        assert res["annual_kwh"] == 4800  # 12 × 400, NO 346×365/22≈5742
        assert res["months_real"] == 12

    def test_consumption_is_period_not_meter_reading(self):
        bill = contract_to_bill(_caldas_contract(with_pv=False))
        # El consumo del periodo es 346 (63+83+200), NUNCA la lectura 19806.
        assert bill["kwh"] == 346.0
        assert bill["consumption_periods"] == {"punta": 63.0, "llano": 83.0, "valle": 200.0}

    def test_contracted_power_array_takes_max(self):
        bill = contract_to_bill(_caldas_contract(with_pv=False))
        assert bill["contracted_power_kw"] == 4.6

    def test_period_reconciliation_like_with_like(self):
        # La suma de periodos (346) se reconcilia con el total de ESTA factura
        # (346), NO contra el anual (4800). No debe ir a revisión por "no cuadra".
        bill = contract_to_bill(_caldas_contract(with_pv=False))
        assert not any("no coinciden" in r for r in bill["review_reasons"])

    def test_existing_pv_routed_not_silently_sized(self):
        bill = contract_to_bill(_caldas_contract(with_pv=True))
        assert bill["existing_pv"] is True
        assert bill["needs_review"] is True
        assert any("autoconsumo" in r.lower() for r in bill["review_reasons"])

    def test_effective_price_uses_period_not_annual(self):
        # 95 € / 346 kWh (periodo) = 0,27 €/kWh plausible; NO 95/4800 ni total/anual.
        bill = contract_to_bill(_caldas_contract(with_pv=False))
        assert not any("precio efectivo" in r.lower() for r in bill["review_reasons"])


def _regulated_no_pv_contract():
    """Factura regulada SIN placas: la línea 'Compensación de excedentes 0,00 €'
    y excedentes 0 kWh aparecen igualmente. NO es autoconsumo."""
    return {
        "bill_type_hint": "monthly",
        "annual_consumption_kwh": _nf("250", "Consumo"),
        "period_total_kwh": _nf("250", "Total"),
        "period_split": {"p1_punta": _nf("80"), "p2_llano": _nf("70"), "p3_valle": _nf("100")},
        "period_split_prices": {"p1_punta": _nf(None), "p2_llano": _nf(None), "p3_valle": _nf(None)},
        "monthly_history": [],
        "meter_readings": {"initial": _nf(None), "final": _nf(None)},
        "self_consumption_block": {
            "present": True,  # el modelo ve la línea de plantilla…
            "exported_kwh": _nf("0"),  # …pero no hay excedentes…
            "compensated_eur": _nf("0,00"),  # …ni compensación.
            "compensation_eur_per_kwh": _nf(None),
        },
        "contracted_power_kw": [_nf("3,45")],
        "tariff": "2.0TD", "bono_social": False,
        "billing_period": {"start": "2026-03-01", "end": "2026-03-31", "days": _nf("30")},
        "energy_term_eur": _nf("40,00"), "energy_term_eur_per_kwh": _nf(None),
        "total_amount_eur": _nf("62,00"), "electricity_tax_eur": _nf(None),
        "vat_eur": _nf(None), "vat_rate": _nf("0,21"),
        "currency": "EUR", "country_code": "ES", "language": "es",
        "supply_address": {"street": None, "cp": "36600", "municipio": "Vilagarcía", "provincia": "Pontevedra"},
        "cups": "ES0031ABC", "warnings": [],
    }


class TestAutoconsumoFalsePositive:
    def test_boilerplate_compensation_line_is_not_pv(self):
        # present=True pero 0 kWh y 0 € → NO autoconsumo (issue #1).
        bill = contract_to_bill(_regulated_no_pv_contract())
        assert bill["existing_pv"] is False
        assert not any("autoconsumo" in r.lower() for r in bill["review_reasons"])

    def test_real_surplus_is_pv(self):
        c = _regulated_no_pv_contract()
        c["self_consumption_block"]["exported_kwh"] = _nf("120")
        assert contract_to_bill(c)["existing_pv"] is True

    def test_compensation_amount_is_pv(self):
        c = _regulated_no_pv_contract()
        c["self_consumption_block"]["compensated_eur"] = _nf("7,20")
        assert contract_to_bill(c)["existing_pv"] is True


class TestBonoSocial:
    def test_low_effective_price_flagged_without_bono(self):
        # 62 € / 250 kWh mensual ≈ 0,25 → en banda. Bajamos el total para forzar
        # un efectivo muy bajo (0,057) SIN bono → fuera de banda, revisión.
        c = _regulated_no_pv_contract()
        c["total_amount_eur"] = _nf("14,25")  # 14,25/250 = 0,057
        bill = contract_to_bill(c)
        assert any("precio efectivo" in r.lower() for r in bill["review_reasons"])

    def test_bono_social_allows_low_effective_price(self):
        c = _regulated_no_pv_contract()
        c["total_amount_eur"] = _nf("14,25")  # 0,057 €/kWh, legítimo con bono
        c["bono_social"] = True
        bill = contract_to_bill(c)
        assert bill["bono_social"] is True
        assert not any("precio efectivo" in r.lower() for r in bill["review_reasons"])


class TestSingleMonthResolution:
    def test_monthly_bill_flagged_single_month(self):
        bill = contract_to_bill(_regulated_no_pv_contract())
        res = bill["consumption_resolution"]
        assert res["single_month"] is True
        assert res["monthly_kwh"] == 250.0
        assert any("un mes" in w.lower() or "mensual" in w.lower() for w in bill["warnings"])

    def test_printed_rolling_annual_used(self):
        # Con "consumo acumulado del último año" en el contrato, se usa como anual
        # y deja de ser single_month.
        c = _regulated_no_pv_contract()
        c["rolling_annual_kwh"] = _nf("3.450", "Acumulado último año")
        bill = contract_to_bill(c)
        res = bill["consumption_resolution"]
        assert res["method"] == "printed_annual"
        assert res["annual_kwh"] == 3450.0
        assert res["single_month"] is False


class TestRedactPii:
    def test_removes_name_nif_iban_keeps_the_rest(self):
        from app.bills import redact_pii
        text = (
            "Titular: JUAN PÉREZ GARCÍA\n"
            "Nombre y apellidos: María López Ruiz\n"
            "NIF: 12345678Z\n"
            "IBAN: ES91 2100 0418 4502 0005 1332\n"
            "Dirección suministro: LUG QUINTAS 0027, 36687 A Estrada (Pontevedra)\n"
            "CUPS: ES0031405512345678XY\n"
            "Consumo facturado: 3.450 kWh\n"
        )
        out = redact_pii(text)
        # PII fuera
        assert "JUAN PÉREZ GARCÍA" not in out
        assert "María López Ruiz" not in out
        assert "12345678Z" not in out
        assert "ES91 2100 0418 4502 0005 1332" not in out
        # Lo necesario se conserva
        assert "LUG QUINTAS 0027" in out and "A Estrada" in out  # dirección
        assert "ES0031405512345678XY" in out  # CUPS intacto
        assert "3.450 kWh" in out  # consumo

    def test_nie_and_cif(self):
        from app.bills import redact_pii
        out = redact_pii("NIE X1234567L y CIF B12345674 en la factura")
        assert "X1234567L" not in out
        assert "B12345674" not in out

    def test_none_and_empty(self):
        from app.bills import redact_pii
        assert redact_pii(None) is None
        assert redact_pii("") == ""

    def test_multilingual_labels_catalan_galician_basque(self):
        from app.bills import redact_pii
        # Català
        ca = redact_pii("Titular: Jordi Puig\nNom i cognoms: Marta Roca\nAdreça de subministrament: Carrer Gran 5")
        assert "Jordi Puig" not in ca and "Marta Roca" not in ca
        assert "Carrer Gran 5" in ca  # dirección conservada
        # Galego
        gl = redact_pii("Titular do contrato: Xoán Castro\nNome e apelidos: Uxía Vázquez\nEnderezo de subministro: Rúa Nova 3")
        assert "Xoán Castro" not in gl and "Uxía Vázquez" not in gl
        assert "Rúa Nova 3" in gl
        # Euskara
        eu = redact_pii("Titularra: Aitor Etxeberria\nIzen-abizenak: Nerea Agirre")
        assert "Aitor Etxeberria" not in eu and "Nerea Agirre" not in eu


class TestAugmentFromText:
    def test_detects_bono_social(self):
        from app.bills import augment_contract_from_text, detect_bono_social
        assert detect_bono_social("... Descuento por Bono Social -5,40 €") is True
        assert detect_bono_social("PVPC con Bono Social") is True
        assert detect_bono_social("cliente marcado como consumidor vulnerable") is True
        assert detect_bono_social("factura normal sin descuentos") is False
        c = augment_contract_from_text({"bono_social": False}, "Aplicado Bono Social")
        assert c["bono_social"] is True

    def test_bono_social_note_and_no_price_warning(self):
        # Con bono social: aviso de ahorro bajo (código) y SIN aviso de precio.
        c = _regulated_no_pv_contract()
        c["total_amount_eur"] = _nf("14,25")  # 0,057 €/kWh, legítimo con bono
        c["bono_social"] = True
        bill = contract_to_bill(c)
        codes = {n["code"] for n in bill["warning_notes"]}
        assert "bono_social_savings" in codes
        assert "effective_price_out_of_range" not in codes


class TestNoModelReasoningLeak:
    def test_model_warnings_not_shown_to_user(self):
        # El razonamiento libre del modelo NO llega a la UI (ni notas ni texto).
        c = _regulated_no_pv_contract()
        c["warnings"] = [
            "the schema has single initial/final meter reading fields, so they were not transcribed",
            "El tipo de IVA aparece impreso como 21%; se transcribe sin el símbolo",
        ]
        bill = contract_to_bill(c)
        # Ninguna nota "raw" con el texto del modelo.
        assert all(n.get("code") != "raw" for n in bill["warning_notes"])
        joined = " ".join(bill["warnings"]).lower()
        assert "schema" not in joined
        assert "transcribe" not in joined
        # Los avisos tipados (single_month) sí siguen presentes.
        assert any(n["code"] == "single_month" for n in bill["warning_notes"])


class TestPerPeriodMeterReadings:
    def _contract_with_period_meters(self):
        c = _regulated_no_pv_contract()
        # Sin columnas de periodo: el reparto se deriva de las lecturas por periodo.
        c["period_split"] = {"p1_punta": _nf(None), "p2_llano": _nf(None), "p3_valle": _nf(None)}
        c["period_total_kwh"] = _nf(None)
        c["annual_consumption_kwh"] = _nf(None)
        c["total_amount_eur"] = _nf(None)  # evita ruido del guardián de precio
        c["meter_readings"] = {
            "initial": _nf(None), "final": _nf(None),
            "p1_initial": _nf("0"), "p1_final": _nf("8.491"),
            "p2_initial": _nf("0"), "p2_final": _nf("9.758"),
            "p3_initial": _nf("0"), "p3_final": _nf("6.267"),
        }
        return c

    def test_split_derived_from_period_meter_diffs(self):
        bill = contract_to_bill(self._contract_with_period_meters())
        assert bill["consumption_periods"] == {"punta": 8491.0, "llano": 9758.0, "valle": 6267.0}

    def test_meter_diff_rounded_no_float_noise(self):
        # 1353.3 - 1000.0 da 353.2999999… en float; debe redondearse a 353.3.
        c = self._contract_with_period_meters()
        c["meter_readings"] = {
            "initial": _nf(None), "final": _nf(None),
            "p1_initial": _nf("1.000,0"), "p1_final": _nf("1.353,3"),
            "p2_initial": _nf(None), "p2_final": _nf(None),
            "p3_initial": _nf(None), "p3_final": _nf(None),
        }
        bill = contract_to_bill(c)
        assert bill["consumption_periods"]["punta"] == 353.3

    def test_period_meter_sum_is_a_candidate_and_reconciles(self):
        bill = contract_to_bill(self._contract_with_period_meters())
        by = {c["candidate"]: c for c in bill["consumption_candidates"]}
        assert "period_meter_sum" in by
        assert by["period_meter_sum"]["value"] == 24516.0
        assert bill["kwh"] == 24516.0  # 8491+9758+6267


class TestNotesAreCoded:
    def test_review_and_warning_notes_have_codes(self):
        bill = contract_to_bill(_regulated_no_pv_contract())
        # single_month → warning con código, no texto suelto
        assert any(n["code"] == "single_month" for n in bill["warning_notes"])
        for n in bill["warning_notes"] + bill["review_notes"]:
            assert "code" in n and "params" in n

    def test_existing_pv_note_coded(self):
        c = _regulated_no_pv_contract()
        c["self_consumption_block"]["exported_kwh"] = _nf("120")
        bill = contract_to_bill(c)
        assert any(n["code"] == "existing_pv" for n in bill["review_notes"])

    def test_bono_and_rolling_multilingual(self):
        from app.bills import detect_bono_social, detect_rolling_annual_kwh
        # Bono social en ca / gl
        assert detect_bono_social("Descompte per bo social aplicat") is True  # ca
        assert detect_bono_social("Desconto por bono social") is True  # gl
        assert detect_bono_social("PVPC amb bo social") is True  # ca
        # Consumo anual impreso en ca / gl
        assert detect_rolling_annual_kwh("Consum acumulat de l'últim any: 3.450 kWh") == 3450.0  # ca
        assert detect_rolling_annual_kwh("Consumo acumulado do último ano 4.120 kWh") == 4120.0  # gl
        assert detect_rolling_annual_kwh("Consum anual 2.900 kWh") == 2900.0  # ca
        # NO confundir el consumo del último PERIODO (mensual) con el anual
        assert detect_rolling_annual_kwh("Consumo del último periodo: 300 kWh") is None

    def test_detects_rolling_annual(self):
        from app.bills import augment_contract_from_text, detect_rolling_annual_kwh
        assert detect_rolling_annual_kwh("Consumo acumulado del último año: 3.450 kWh") == 3450.0
        assert detect_rolling_annual_kwh("Consumo anual 4.120 kWh") == 4120.0
        c = augment_contract_from_text(
            {"rolling_annual_kwh": None},
            "Consumo acumulado del último año 3.450 kWh",
        )
        assert c["rolling_annual_kwh"] == "3450.0"

    def test_does_not_overwrite_model_values(self):
        from app.bills import augment_contract_from_text
        c = augment_contract_from_text(
            {"bono_social": True, "rolling_annual_kwh": "5000"},
            "Consumo acumulado del último año 3.450 kWh bono social",
        )
        assert c["rolling_annual_kwh"] == "5000"  # no se pisa lo del modelo


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

    def test_numeric_fields_are_verbatim_strings(self):
        # Los campos numéricos son STRING verbatim (la app normaliza). Sin sobre de
        # 4 propiedades: eso disparó el esquema a 157 props > límite 100 de OpenAI.
        field = BILL_CONTRACT_SCHEMA["properties"]["annual_consumption_kwh"]
        assert field["type"] == ["string", "null"]

    def test_schema_under_openai_property_limit(self):
        # Guarda de regresión: structured-outputs rechaza >100 propiedades (400) y
        # entonces NINGUNA factura se parsea. Nunca volver a pasarse.
        def count(s):
            n = 0
            if isinstance(s, dict):
                if isinstance(s.get("properties"), dict):
                    n += len(s["properties"])
                    for v in s["properties"].values():
                        n += count(v)
                if "items" in s:
                    n += count(s["items"])
            return n
        assert count(BILL_CONTRACT_SCHEMA) < 100


class TestSafeToFloat:
    # Única función de normalización española, aplicada a TODO raw_text.
    def test_thousands_and_decimals(self):
        assert safe_to_float("6.551") == 6551.0
        assert safe_to_float("13.800") == 13800.0
        assert safe_to_float("1.689,65") == 1689.65
        assert safe_to_float("0,24") == 0.24
        assert safe_to_float("6551.00") == 6551.0  # ya normalizado, intacto

    def test_units_and_symbols_ignored(self):
        assert safe_to_float("6.551 kWh") == 6551.0
        assert safe_to_float("0,241000 €/kWh") == 0.241
        assert safe_to_float("1.689,65 €") == 1689.65

    def test_junk_is_none_not_crash(self):
        assert safe_to_float(None) is None
        assert safe_to_float("") is None
        assert safe_to_float("n/d") is None


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
