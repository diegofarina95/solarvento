from datetime import date

import pytest

from app.bills import (
    BillParseError,
    _statutory_rates_es,
    aggregate_bills,
    derive_bill_tax_rates,
    parse_bill_text,
)
from app.profiles import DAYS_PER_MONTH, MONTHLY_WEIGHTS

SAMPLE_BILL = """
ENDESA ENERGÍA XXI S.L.U.
Factura de electricidad
Nº factura: PMR701N0123456
Periodo de facturación: del 15/03/2026 al 14/04/2026
Titular: DIEGO F.

DATOS DE CONSUMO
Consumo en el periodo: 312 kWh
Lectura anterior 45.230 kWh - Lectura actual 45.542 kWh

IMPORTES
Energía consumida 312 kWh x 0,138 €/kWh 43,06 €
Potencia contratada 4,6 kW 12,30 €
Impuesto eléctrico 2,83 €
Alquiler equipos 0,81 €
IVA (21%) 12,39 €
TOTAL IMPORTE FACTURA 71,39 €
"""


class TestParseBillText:
    def test_extracts_consumption_amount_and_period(self):
        result = parse_bill_text(SAMPLE_BILL)
        assert result["kwh"] == 312.0
        assert result["amount_eur"] == 71.39
        assert result["total_eur"] == 71.39
        assert result["energy_eur"] == 43.06
        assert result["fixed_eur"] == 13.11
        assert result["taxes_eur"] == 15.22
        assert result["currency"] == "EUR"
        assert result["start_date"] == date(2026, 3, 15)
        assert result["end_date"] == date(2026, 4, 14)
        assert result["country_code"] == "ES"
        assert result["language"] == "es"
        assert result["parser"] == "local"
        assert result["warnings"] == []

    def test_spanish_number_format(self):
        text = "Consumo facturado: 1.234 kWh\nTotal factura 234,56 €\n"
        result = parse_bill_text(text)
        assert result["kwh"] == 1234.0
        assert result["amount_eur"] == 234.56

    def test_extracts_french_consumption_amount_and_period(self):
        text = """
        EDF
        Facture d'électricité
        Période de facturation du 01/07/2026 au 31/07/2026
        Consommation totale 245,7 kWh
        Montant total TTC 83,42 €
        """
        result = parse_bill_text(text)
        assert result["kwh"] == 245.7
        assert result["amount_eur"] == 83.42
        assert result["start_date"] == date(2026, 7, 1)
        assert result["end_date"] == date(2026, 7, 31)
        assert result["month"] == 7
        assert result["country_code"] == "FR"
        assert result["language"] == "fr"

    def test_extracts_french_reading_difference(self):
        text = """
        Facture d'électricité EDF
        Ancien relevé 12 000 kWh
        Nouveau relevé 12 245 kWh
        Net à payer 81,20 €
        """
        result = parse_bill_text(text)
        assert result["kwh"] == 245.0
        assert result["amount_eur"] == 81.2

    def test_prefers_french_reading_difference_over_accumulated_meter_value(self):
        text = """
        Facture d'électricité EDF
        Consommation sur la période Ancien relevé 12 000 kWh Nouveau relevé 12 245 kWh
        Net à payer 81,20 €
        """
        result = parse_bill_text(text)
        assert result["kwh"] == 245.0
        assert result["amount_eur"] == 81.2
        assert any("diferencia de lecturas" in warning for warning in result["warnings"])

    def test_missing_fields_produce_warnings(self):
        result = parse_bill_text("Documento sin datos de luz, solo texto.")
        assert result["kwh"] is None
        assert any("kWh" in w for w in result["warnings"])

    def test_empty_text_raises(self):
        with pytest.raises(BillParseError):
            parse_bill_text("   ")

    def test_ignores_meter_readings_larger_than_plausible(self):
        text = "Lectura actual 45.542 kWh\nConsumo del periodo 310 kWh\nTotal 60,00 €"
        result = parse_bill_text(text)
        assert result["kwh"] == 310.0

    def test_uses_meter_reading_difference_when_consumption_label_is_missing(self):
        text = """
        Factura de electricidad
        Periodo de facturación: del 01/01/2026 al 31/01/2026
        Lectura anterior 13.457 kWh - Lectura actual 14.069 kWh
        TOTAL IMPORTE FACTURA 155,15 €
        """
        result = parse_bill_text(text)
        assert result["kwh"] == 612.0
        assert result["amount_eur"] == 155.15

    def test_sums_multiple_meter_reading_differences(self):
        text = """
        P1 Lectura anterior 10.000 kWh Lectura actual 10.120 kWh
        P2 Lectura anterior 20.000 kWh Lectura actual 20.230 kWh
        Total factura 90,00 €
        """
        result = parse_bill_text(text)
        assert result["kwh"] == 350.0

    def test_energy_charge_does_not_use_kwh_as_money(self):
        text = """
        Factura de electricidad
        Energía consumida 312 kWh
        Total importe factura 71,39 €
        """
        result = parse_bill_text(text)
        assert result["energy_eur"] is None
        assert result["amount_eur"] == 71.39

    def test_extracts_multiline_spanish_large_house_january_bill(self):
        text = """
        Factura de electricidad
        Periodo facturado
        01/01/2026 - 31/01/2026
        Total a pagar
        829,17 €
        Total energía consumida
        2.902 kWh
        497,91 €
        Desglose económico
        Importe
        Término de potencia
        70,84 €
        Término de energía
        497,91 €
        Impuesto eléctrico y cargos regulados
        27,41 €
        Alquiler de contador
        0,93 €
        Base imponible
        584,59 €
        IVA 21%
        122,76 €
        TOTAL FACTURA
        829,17 €
        """
        result = parse_bill_text(text)
        assert result["kwh"] == 2902.0
        assert result["total_eur"] == 829.17
        assert result["energy_eur"] == 497.91
        assert result["fixed_eur"] == 71.77
        assert result["taxes_eur"] == 150.17

    def test_extracts_consumption_table_without_repeated_kwh_unit(self):
        text = """
        Factura de electricidad
        Periodo de facturación
        01/07/2026 - 31/07/2026
        RESUMEN DE CONSUMO
        kWh
        Precio medio
        Punta
        496
        0,231 €/kWh
        Llano
        611
        0,204 €/kWh
        Valle
        703
        0,176 €/kWh
        TOTAL
        1.810
        0,200 €/kWh
        CONCEPTO
        IMPORTE
        Término de potencia
        48,91 €
        Término de energía
        362,02 €
        Impuesto electricidad
        21,20 €
        Alquiler contador
        0,81 €
        Base imponible
        439,89 €
        IVA (21%)
        92,38 €
        TOTAL FACTURA
        532,27 €
        """
        result = parse_bill_text(text)
        assert result["kwh"] == 1810.0
        assert result["total_eur"] == 532.27
        assert result["energy_eur"] == 362.02
        assert result["fixed_eur"] == 49.72
        assert result["taxes_eur"] == 113.58


class TestAggregateBills:
    def test_estimates_annual_from_sampled_months(self):
        bills = [
            {
                "kwh": 300,
                "energy_eur": 50,
                "amount_eur": 70,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 31),
            },
            {
                "kwh": 280,
                "energy_eur": 45,
                "amount_eur": 65,
                "start_date": date(2026, 2, 1),
                "end_date": date(2026, 3, 1),
            },
        ]
        result = aggregate_bills(bills)
        jan_month = 300 / 31 * DAYS_PER_MONTH[0]
        feb_month = 280 / 28 * DAYS_PER_MONTH[1]
        expected = (
            (jan_month / (MONTHLY_WEIGHTS[0] / sum(MONTHLY_WEIGHTS))) * 31
            + (feb_month / (MONTHLY_WEIGHTS[1] / sum(MONTHLY_WEIGHTS))) * 28
        ) / 59
        assert result["annual_kwh"] == pytest.approx(expected, rel=0.01)
        assert result["avg_price_eur_kwh"] == pytest.approx(95 / 580, rel=0.01)
        assert result["annual_amount_eur"] is not None
        assert result["bill_count"] == 2
        assert result["priced_bill_count"] == 2
        assert result["total_amount_bill_count"] == 2
        assert result["ignored_price_bill_count"] == 0
        assert result["monthly_kwh"] is not None
        assert result["observed_months"] == [1, 2]
        assert result["seasonality_source"] == "estimated_from_sampled_months"

    def test_manual_months_without_dates_drive_seasonality(self):
        result = aggregate_bills(
            [
                {"month": 1, "kwh": 420, "amount_eur": 105},
                {"month": 7, "kwh": 520, "amount_eur": 130},
                {"month": 9, "kwh": 360, "amount_eur": 90},
            ]
        )
        assert result["observed_months"] == [1, 7, 9]
        assert result["monthly_kwh"][0] == pytest.approx(420, rel=0.01)
        assert result["monthly_kwh"][6] == pytest.approx(520, rel=0.01)
        assert result["monthly_kwh"][8] == pytest.approx(360, rel=0.01)
        assert result["annual_kwh"] > sum([420, 520, 360])
        assert result["avg_price_eur_kwh"] is None
        assert result["annual_amount_eur"] is not None

    def test_january_and_june_manual_bills_do_not_get_multiplied_by_month_days(self):
        result = aggregate_bills(
            [
                {"month": 1, "kwh": 612, "energy_eur": 105.15, "amount_eur": 155.15},
                {"month": 6, "kwh": 344, "energy_eur": 54.04, "amount_eur": 94.04},
            ]
        )

        assert result["observed_months"] == [1, 6]
        assert result["monthly_kwh"][0] == pytest.approx(612, rel=0.01)
        assert result["monthly_kwh"][5] == pytest.approx(344, rel=0.01)
        assert result["annual_kwh"] == pytest.approx(sum(result["monthly_kwh"]), rel=0.001)
        assert 5000 < result["annual_kwh"] < 6500
        assert result["avg_price_eur_kwh"] == round((105.15 + 54.04) / (612 + 344), 4)

    def test_rejects_probable_meter_reading_used_as_consumption(self):
        with pytest.raises(BillParseError, match="lectura acumulada"):
            aggregate_bills(
                [
                    {"month": 1, "kwh": 13457, "amount_eur": 155.15},
                    {"month": 6, "kwh": 15554, "amount_eur": 94.04},
                ]
            )

    def test_full_year_gives_monthly_seasonality(self):
        bills = []
        for m in range(1, 13):
            start = date(2025, m, 1)
            end = date(2025, m + 1, 1) if m < 12 else date(2026, 1, 1)
            bills.append(
                {"kwh": 200 + (m % 3) * 50, "amount_eur": 60, "start_date": start, "end_date": end}
            )
        result = aggregate_bills(bills)
        assert result["monthly_kwh"] is not None
        assert len(result["monthly_kwh"]) == 12

    def test_days_without_dates(self):
        result = aggregate_bills([{"kwh": 300, "days": 30}])
        assert result["annual_kwh"] == pytest.approx(300 / 30 * 365.25, rel=0.01)
        assert result["avg_price_eur_kwh"] is None

    def test_ignores_anomalous_prices_for_weighted_average(self):
        result = aggregate_bills(
            [
                {"month": 1, "kwh": 286, "energy_eur": 95.09, "amount_eur": 120.09},
                {"month": 2, "kwh": 300, "energy_eur": 2.00, "amount_eur": 30.00},
                {"month": 3, "kwh": 250, "energy_eur": 380.00, "amount_eur": 430.00},
            ]
        )

        assert result["avg_price_eur_kwh"] == pytest.approx(95.09 / 286, rel=0.001)
        assert result["bill_count"] == 3
        assert result["priced_bill_count"] == 1
        assert result["ignored_price_bill_count"] == 2

    def test_total_amount_does_not_drive_marginal_price(self):
        result = aggregate_bills([{"month": 1, "kwh": 300, "amount_eur": 120}])

        assert result["avg_price_eur_kwh"] is None
        assert result["annual_amount_eur"] is not None
        assert result["total_amount_bill_count"] == 1

    def test_non_euro_price_thresholds_use_bill_currency(self):
        result = aggregate_bills(
            [{"month": 1, "kwh": 350, "energy_eur": 280, "amount_eur": 420, "currency": "PLN"}]
        )

        assert result["avg_price_eur_kwh"] == pytest.approx(0.8, rel=0.001)
        assert result["priced_bill_count"] == 1

    def test_cross_month_period_is_split_by_days(self):
        result = aggregate_bills(
            [
                {
                    "kwh": 310,
                    "amount_eur": 100,
                    "start_date": date(2026, 1, 20),
                    "end_date": date(2026, 2, 10),
                }
            ]
        )

        assert result["observed_months"] == [1, 2]
        assert result["monthly_kwh"][0] == pytest.approx(310 * 12 / 22 / 12 * DAYS_PER_MONTH[0], rel=0.01)
        assert result["monthly_kwh"][1] == pytest.approx(310 * 10 / 22 / 10 * DAYS_PER_MONTH[1], rel=0.01)

    def test_invalid_bills_raise(self):
        with pytest.raises(BillParseError):
            aggregate_bills([{"kwh": 0, "days": 30}])

    def test_single_month_low_reliability(self):
        # Una sola factura mensual, sin histórico → fiabilidad baja (issue #3).
        result = aggregate_bills([{"kwh": 300, "days": 30}])
        assert result["single_month"] is True
        assert result["consumption_reliability"] == "low"

    def test_full_year_bills_normal_reliability(self):
        bills = [{"month": m, "kwh": 300, "days": 30} for m in range(1, 13)]
        result = aggregate_bills(bills)
        assert result["single_month"] is False
        assert result["consumption_reliability"] == "normal"

    def test_same_cups_not_flagged(self):
        bills = [
            {"month": 1, "kwh": 300, "days": 30, "cups": "ES0031ABC"},
            {"month": 2, "kwh": 280, "days": 30, "cups": "ES0031ABC"},
        ]
        result = aggregate_bills(bills)
        assert result["distinct_cups"] == 1
        assert not any("suministro" in r.lower() for r in result["review_reasons"])

    def test_rolling_annual_overrides_valle_months(self):
        # Solo meses valle subidos (bajos) + anual impreso alto: se usa el anual
        # impreso, no la extrapolación a la baja.
        bills = [
            {"month": 1, "kwh": 120, "days": 30, "rolling_annual_kwh": 3600},
            {"month": 2, "kwh": 110, "days": 30, "rolling_annual_kwh": 3600},
        ]
        result = aggregate_bills(bills)
        assert result["annual_kwh"] == 3600
        assert result["annual_from_printed"] is True
        assert result["single_month"] is False
        assert result["consumption_reliability"] == "normal"

    def test_bono_social_exposed(self):
        result = aggregate_bills([{"kwh": 300, "days": 30, "bono_social": True}])
        assert result["bono_social"] is True

    def test_distinct_cups_flagged(self):
        bills = [
            {"month": 1, "kwh": 300, "days": 30, "cups": "ES0031ABC"},
            {"month": 1, "kwh": 900, "days": 30, "cups": "ES0099XYZ"},
        ]
        result = aggregate_bills(bills)
        assert result["distinct_cups"] == 2
        assert result["needs_review"] is True
        assert any("suministro" in r.lower() for r in result["review_reasons"])


class TestMultiLanguageTotals:
    """El total debe extraerse con etiquetas y monedas de toda Europa."""

    def test_italian_total(self):
        text = """
        Enel Energia - Bolletta luce
        Periodo di fatturazione: dal 01/03/2026 al 31/03/2026
        Consumo fatturato 280 kWh
        Totale da pagare 87,50 €
        """
        result = parse_bill_text(text)
        assert result["amount_eur"] == 87.50
        assert result["kwh"] == 280.0

    def test_german_total_with_eur_code(self):
        text = """
        Stromrechnung
        Verbrauch 310 kWh
        Rechnungsbetrag: 112,40 EUR
        """
        result = parse_bill_text(text)
        assert result["amount_eur"] == 112.40
        assert result["kwh"] == 310.0

    def test_english_total_with_pound_before_number(self):
        text = """
        Electricity bill
        Billing period 01/05/2026 - 31/05/2026
        Consumption for the period 245 kWh
        Total amount due: £81.20
        """
        result = parse_bill_text(text)
        assert result["amount_eur"] == 81.20
        assert result["kwh"] == 245.0

    def test_english_thousands_format(self):
        text = "Annual consumption total 1,234 kWh\nTotal amount due 1,102.56 EUR\n"
        result = parse_bill_text(text)
        assert result["amount_eur"] == 1102.56

    def test_portuguese_total(self):
        text = """
        EDP Comercial - Fatura de eletricidade
        Consumo faturado 190 kWh
        Valor a pagar: 54,30 €
        """
        result = parse_bill_text(text)
        assert result["amount_eur"] == 54.30

    def test_polish_total_with_zloty(self):
        text = """
        Faktura za energie
        Zuzycie 350 kWh
        Do zaplaty razem: 412,80 zł
        """
        result = parse_bill_text(text)
        # sin etiqueta reconocida cae al fallback por moneda adyacente
        assert result["amount_eur"] == 412.80

    def test_total_label_does_not_grab_kwh(self):
        text = "Total consumption for the period 312 kWh\nTotal amount due 71.39 €"
        result = parse_bill_text(text)
        assert result["amount_eur"] == 71.39


FEBRERO_2026 = """
COMERCIALIZADORA SOLAR S.A.
Factura de electricidad
Periodo de facturación: del 01/02/2026 al 28/02/2026
Consumo en el periodo: 2.455 kWh
Desglose económico
Término de energía 486,09 €
Término de potencia 62,00 €
Impuesto especial sobre la electricidad 28,02 €
Alquiler de contador 0,81 €
Base imponible 576,92 €
IVA (21%) 121,15 €
TOTAL IMPORTE FACTURA 698,07 €
"""

ABRIL_2026_REDUCIDA = """
COMERCIALIZADORA SOLAR S.A.
Factura de electricidad
Periodo de facturación: del 01/04/2026 al 30/04/2026
Consumo en el periodo: 1.898 kWh
Desglose económico
Término de energía 379,60 €
Término de potencia 60,00 €
Impuesto especial sobre la electricidad 2,20 €
Alquiler de contador 0,81 €
Base imponible 442,61 €
IVA (10%) 44,26 €
TOTAL IMPORTE FACTURA 486,87 €
"""


class TestParseBillTaxLines:
    def test_extracts_itemised_tax_lines_standard(self):
        result = parse_bill_text(FEBRERO_2026)
        assert result["energy_eur"] == 486.09
        assert result["power_eur"] == 62.00
        assert result["iee_eur"] == 28.02
        assert result["iva_eur"] == 121.15
        assert result["iva_rate"] == 0.21
        assert result["vat_base_eur"] == 576.92

    def test_extracts_itemised_tax_lines_reduced_window(self):
        result = parse_bill_text(ABRIL_2026_REDUCIDA)
        assert result["iee_eur"] == 2.20
        assert result["iva_eur"] == 44.26
        assert result["iva_rate"] == 0.10
        assert result["vat_base_eur"] == 442.61

    def test_lumped_electricity_tax_is_not_used_as_iee(self):
        text = """
        Factura de electricidad
        Periodo facturado 01/01/2026 - 31/01/2026
        Término de energía 497,91 €
        Impuesto eléctrico y cargos regulados 27,41 €
        TOTAL FACTURA 829,17 €
        """
        result = parse_bill_text(text)
        # La línea agrupa IEE con cargos regulados: no sirve para derivar el tipo
        assert result["iee_eur"] is None

    def test_simple_iee_line_is_extracted(self):
        result = parse_bill_text(SAMPLE_BILL)
        assert result["iee_eur"] == 2.83
        assert result["power_eur"] == 12.30
        assert result["iva_rate"] == 0.21


class TestBillTaxRates:
    """Derivación por factura del coste marginal evitado (IEE + IVA)."""

    def _bill(self, **kwargs):
        base = {
            "kwh": 2455,
            "energy_eur": 486.09,
            "power_eur": 62.00,
            "iee_eur": 28.02,
            "iva_eur": 121.15,
            "iva_rate": 0.21,
            "vat_base_eur": 576.92,
            "start_date": date(2026, 2, 1),
            "end_date": date(2026, 2, 28),
        }
        base.update(kwargs)
        return base

    def test_rates_derived_from_itemised_lines(self):
        result = aggregate_bills([self._bill()], country_code="ES")
        assert result["marginal_price_factor"] == pytest.approx(1.2719, abs=0.001)
        assert result["marginal_price_eur_kwh"] == pytest.approx(
            (486.09 / 2455) * 1.2719, abs=0.001
        )
        assert result["tax_rates_source"] == "bill"

    def test_reduced_window_bill_derives_lower_rates_than_standard(self):
        reduced = {
            "kwh": 1898,
            "energy_eur": 379.60,
            "power_eur": 60.00,
            "iee_eur": 2.20,
            "iva_eur": 44.26,
            "iva_rate": 0.10,
            "vat_base_eur": 442.61,
            "start_date": date(2026, 4, 1),
            "end_date": date(2026, 4, 30),
        }
        result_reduced = aggregate_bills([reduced], country_code="ES")
        result_standard = aggregate_bills([self._bill()], country_code="ES")
        assert result_reduced["marginal_price_factor"] == pytest.approx(1.1055, abs=0.001)
        assert (
            result_reduced["marginal_price_factor"]
            < result_standard["marginal_price_factor"]
        )

    def test_statutory_fallback_reduced_window_small_power_gets_reduced_iva(self):
        # Sin líneas de impuestos, periodo (mayo 2026) en la ventana reducida y
        # potencia ≤ 10 kW → IEE 0,5% e IVA 10%
        bill = {
            "kwh": 1500,
            "energy_eur": 300.0,
            "contracted_power_kw": 5.0,
            "start_date": date(2026, 5, 1),
            "end_date": date(2026, 5, 31),
        }
        result = aggregate_bills([bill], country_code="ES")
        assert result["marginal_price_factor"] == pytest.approx(1.1055, abs=0.001)
        assert result["tax_rates_source"] == "statutory"

    def test_statutory_fallback_reduced_window_large_power_keeps_standard_iva(self):
        # Misma ventana pero > 10 kW: el IVA 10% no aplica → IEE 0,5% pero IVA 21%
        bill = {
            "kwh": 1500,
            "energy_eur": 300.0,
            "contracted_power_kw": 14.49,
            "start_date": date(2026, 5, 1),
            "end_date": date(2026, 5, 31),
        }
        result = aggregate_bills([bill], country_code="ES")
        assert result["marginal_price_factor"] == pytest.approx(1.005 * 1.21, abs=0.001)

    def test_statutory_fallback_standard_when_no_dates(self):
        bill = {"kwh": 300, "energy_eur": 60.0, "month": 1}
        result = aggregate_bills([bill], country_code="ES")
        assert result["marginal_price_factor"] == pytest.approx(1.2719, abs=0.001)

    def test_bill_lines_preferred_over_statutory_table(self):
        # Periodo dentro de la ventana reducida pero con IVA 21% detallado:
        # manda la factura, no la tabla
        bill = self._bill(
            start_date=date(2026, 4, 1), end_date=date(2026, 4, 30)
        )
        result = aggregate_bills([bill], country_code="ES")
        assert result["marginal_price_factor"] == pytest.approx(1.2719, abs=0.001)

    def test_blend_weights_by_kwh(self):
        standard = self._bill()  # 2455 kWh, factor 1.2719
        reduced = {
            "kwh": 1898,
            "energy_eur": 379.60,
            "power_eur": 60.00,
            "iee_eur": 2.20,
            "iva_eur": 44.26,
            "iva_rate": 0.10,
            "vat_base_eur": 442.61,
            "start_date": date(2026, 4, 1),
            "end_date": date(2026, 4, 30),
        }
        result = aggregate_bills([standard, reduced], country_code="ES")
        expected = (2455 * 1.27186 + 1898 * 1.10550) / (2455 + 1898)
        assert result["marginal_price_factor"] == pytest.approx(expected, abs=0.001)
        # Ambas facturas derivan sus tipos de las propias líneas
        assert result["tax_rates_source"] == "bill"

    def test_non_spanish_bills_without_tax_lines_have_no_factor(self):
        bill = {"kwh": 300, "energy_eur": 60.0, "month": 1}
        result = aggregate_bills([bill], country_code="DE")
        assert result["marginal_price_factor"] is None
        assert result["marginal_price_eur_kwh"] is None

    def test_non_spanish_bills_with_itemised_lines_derive_factor(self):
        # La derivación por líneas es válida en cualquier país
        bill = self._bill()
        result = aggregate_bills([bill], country_code="DE")
        assert result["marginal_price_factor"] == pytest.approx(1.2719, abs=0.001)


# --- Bug 2: consumo anual desde el histórico mensual de la factura -----------

_SHARED_HISTORY = """
Histórico de consumo
Ene 2.902 kWh
Mar 2.350 kWh
Abr 1.898 kWh
May 1.620 kWh
Jun 1.450 kWh
Jul 1.810 kWh
Ago 1.210 kWh
Sep 1.358 kWh
Oct 1.738 kWh
Nov 2.100 kWh
Dic 2.650 kWh
"""


def _bill_with_history(period_start, period_end, period_kwh, energy_eur):
    return f"""
    COMERCIALIZADORA SOLAR S.A.
    Factura de electricidad
    Periodo de facturación: del {period_start} al {period_end}
    Consumo en el periodo: {period_kwh} kWh
    Término de energía {energy_eur} €
    TOTAL IMPORTE FACTURA 500,00 €
    {_SHARED_HISTORY}
    """


class TestConsumptionHistory:
    def test_parses_history_table(self):
        result = parse_bill_text(_bill_with_history("01/01/2026", "31/01/2026", 2902, "486,09"))
        history = {e["month"]: e["kwh"] for e in result["consumption_history"]}
        assert history[1] == 2902
        assert history[3] == 2350
        assert history[12] == 2650
        assert 2 not in history  # febrero no aparece en el histórico
        assert len(history) == 11

    def test_period_kwh_not_corrupted_by_history_values(self):
        # El consumo del periodo (etiquetado) no debe confundirse con el histórico
        result = parse_bill_text(_bill_with_history("01/07/2026", "31/07/2026", 1810, "369,24"))
        assert result["kwh"] == 1810

    def test_no_history_returns_empty_list(self):
        result = parse_bill_text(SAMPLE_BILL)
        assert result["consumption_history"] == []


class TestConsumptionFromHistory:
    def _parse(self, *bills):
        return [parse_bill_text(b) for b in bills]

    def _agg(self, parsed):
        return aggregate_bills(parsed, country_code="ES")

    def test_annual_is_deterministic_across_upload_subsets(self):
        enero = _bill_with_history("01/01/2026", "31/01/2026", 2902, "486,09")
        febrero = _bill_with_history("01/02/2026", "28/02/2026", 2680, "450,00")
        marzo = _bill_with_history("01/03/2026", "31/03/2026", 2350, "467,65")
        julio = _bill_with_history("01/07/2026", "31/07/2026", 1810, "369,24")

        subset_a = self._agg(self._parse(enero, julio))
        subset_b = self._agg(self._parse(febrero, marzo, julio))
        assert subset_a["annual_kwh"] == subset_b["annual_kwh"]
        assert subset_a["seasonality_source"] == "bill_history"

    def test_eleven_real_months_sum_and_estimated_february(self):
        enero = _bill_with_history("01/01/2026", "31/01/2026", 2902, "486,09")
        julio = _bill_with_history("01/07/2026", "31/07/2026", 1810, "369,24")
        agg = self._agg(self._parse(enero, julio))

        # 11 meses reales suman 21.086; con febrero estimado el anual cae en
        # 23.500-24.000, NO en ~25.600 (que daría la extrapolación x(12/N))
        real = sum(agg["monthly_kwh"][m - 1] for m in agg["observed_months"])
        assert real == pytest.approx(21086, abs=1)
        assert 2 in agg["estimated_months"]
        assert 23500 <= agg["annual_kwh"] <= 24000
        assert agg["annual_kwh"] != pytest.approx(25600, abs=500)

    def test_estimated_february_interpolates_neighbours(self):
        enero = _bill_with_history("01/01/2026", "31/01/2026", 2902, "486,09")
        agg = self._agg(self._parse(enero))
        # Febrero entre enero (2902) y marzo (2350): media 2626
        assert agg["monthly_kwh"][1] == pytest.approx(2626, abs=1)

    def test_conflict_prefers_most_recent_bill(self):
        older = f"""
        Factura de electricidad
        Periodo de facturación: del 01/01/2026 al 31/01/2026
        Consumo en el periodo: 2000 kWh
        Término de energía 400,00 €
        TOTAL IMPORTE FACTURA 500,00 €
        Histórico de consumo
        Ene 2.000 kWh
        """
        newer = f"""
        Factura de electricidad
        Periodo de facturación: del 01/06/2026 al 30/06/2026
        Consumo en el periodo: 1500 kWh
        Término de energía 300,00 €
        TOTAL IMPORTE FACTURA 400,00 €
        Histórico de consumo
        Ene 2.500 kWh
        """
        agg = self._agg(self._parse(older, newer))
        # Enero aparece en ambas: gana la factura más reciente (junio → 2.500)
        assert agg["monthly_kwh"][0] == pytest.approx(2500, abs=1)

    def test_twelve_months_summed_directly_without_estimation(self):
        full = """
        Factura de electricidad
        Periodo de facturación: del 01/01/2026 al 31/01/2026
        Consumo en el periodo: 300 kWh
        Término de energía 60,00 €
        TOTAL IMPORTE FACTURA 100,00 €
        Histórico de consumo
        Ene 300 kWh
        Feb 280 kWh
        Mar 260 kWh
        Abr 240 kWh
        May 220 kWh
        Jun 200 kWh
        Jul 210 kWh
        Ago 230 kWh
        Sep 250 kWh
        Oct 270 kWh
        Nov 290 kWh
        Dic 310 kWh
        """
        agg = self._agg(self._parse(full))
        assert agg["estimated_months"] == []
        assert agg["annual_kwh"] == pytest.approx(3060, abs=1)
        assert agg["seasonality_source"] == "bill_history"

    def test_bills_without_history_keep_extrapolation_path(self):
        agg = aggregate_bills(
            [
                {"month": 1, "kwh": 612, "energy_eur": 105.15, "amount_eur": 155.15},
                {"month": 6, "kwh": 344, "energy_eur": 54.04, "amount_eur": 94.04},
            ],
            country_code="ES",
        )
        assert agg["seasonality_source"] == "estimated_from_sampled_months"
        assert agg["estimated_months"] == []


class TestAnnualBills:
    """Facturas que cubren un periodo anual (~12 meses)."""

    def test_annual_period_bill_is_treated_as_annual_total(self):
        agg = aggregate_bills(
            [{
                "kwh": 9600, "energy_eur": 1920, "total_eur": 2600,
                "start_date": date(2025, 1, 1), "end_date": date(2025, 12, 31),
            }],
            country_code="ES",
        )
        assert agg["seasonality_source"] == "annual_bill"
        assert agg["annual_kwh"] == pytest.approx(9600, abs=1)
        # Sin reparto mensual plano: la estacionalidad la aplica el perfil aguas abajo
        assert agg["monthly_kwh"] is None
        assert agg["observed_months"] == []
        assert agg["estimated_months"] == []
        assert agg["annual_amount_eur"] == pytest.approx(2600, abs=1)

    def test_annual_bill_by_days_field(self):
        agg = aggregate_bills([{"kwh": 8000, "days": 365}], country_code="ES")
        assert agg["seasonality_source"] == "annual_bill"
        assert agg["annual_kwh"] == pytest.approx(8000, abs=1)

    def test_large_annual_bill_above_old_limit_is_accepted(self):
        agg = aggregate_bills(
            [{
                "kwh": 23712, "energy_eur": 4742, "total_eur": 6400,
                "start_date": date(2025, 1, 1), "end_date": date(2025, 12, 31),
            }],
            country_code="ES",
        )
        assert agg["annual_kwh"] == pytest.approx(23712, abs=1)
        assert agg["marginal_price_factor"] == pytest.approx(1.2719, abs=0.001)

    def test_two_annual_bills_sum(self):
        agg = aggregate_bills(
            [
                {"kwh": 9000, "days": 365},
                {"kwh": 500, "days": 365},
            ],
            country_code="ES",
        )
        assert agg["seasonality_source"] == "annual_bill"
        assert agg["annual_kwh"] == pytest.approx(9500, abs=1)

    def test_history_takes_precedence_over_annual_period(self):
        # Una factura anual que ADEMÁS trae histórico usa el histórico (más preciso)
        agg = aggregate_bills(
            [{
                "kwh": 9600,
                "start_date": date(2025, 1, 1), "end_date": date(2025, 12, 31),
                "consumption_history": [
                    {"month": m, "kwh": 800} for m in range(1, 13)
                ],
            }],
            country_code="ES",
        )
        assert agg["seasonality_source"] == "bill_history"
        assert agg["annual_kwh"] == pytest.approx(9600, abs=1)

    def test_short_period_bill_still_uses_sampled_path(self):
        agg = aggregate_bills(
            [{
                "kwh": 800, "energy_eur": 160,
                "start_date": date(2025, 1, 1), "end_date": date(2025, 1, 31),
            }],
            country_code="ES",
        )
        assert agg["seasonality_source"] != "annual_bill"


class TestTaxPlausibilityGuards:
    """BUG A: tipos derivados fuera de banda se rechazan y caen al normativo."""

    def test_implausible_low_iee_is_rejected_and_falls_back(self):
        # Fixture anual: IEE 22,50 / (5350,51 + 586,92) = 0,379% < 0,5% legal
        bill = {
            "kwh": 25637,
            "energy_eur": 5350.51,
            "power_eur": 586.92,
            "iee_eur": 22.50,
            "iva_eur": 1272.53,
            "iva_rate": 0.21,
            "vat_base_eur": 6059.65,
            "contracted_power_kw": 14.49,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        }
        rates = derive_bill_tax_rates(bill, "ES")
        # IEE de la factura (0,379%) rechazado → normativo ponderado del año
        assert rates["iee_source"] == "statutory-fallback"
        assert rates["iee_rate"] > 0.005
        # IVA sí es plausible (21%) → de la factura
        assert rates["iva_source"] == "from-bill"
        assert rates["iva_rate"] == 0.21
        assert rates["source"] == "mixed"

    def test_clean_itemised_iee_uses_from_bill(self):
        bill = {
            "kwh": 2455,
            "energy_eur": 486.09,
            "power_eur": 62.00,
            "iee_eur": 28.02,  # 28,02/(486,09+62)=5,11% plausible
            "iva_rate": 0.21,
            "start_date": date(2026, 2, 1),
            "end_date": date(2026, 2, 28),
        }
        rates = derive_bill_tax_rates(bill, "ES")
        assert rates["iee_source"] == "from-bill"
        assert rates["iee_rate"] == pytest.approx(0.0511, abs=0.001)
        assert rates["source"] == "bill"

    def test_lumped_iee_line_not_parsed_falls_back(self):
        # 'Impuesto eléctrico y cargos regulados' no se extrae como iee_eur
        text = """
        Factura de electricidad
        Periodo de facturación: del 01/01/2026 al 31/01/2026
        Consumo en el periodo: 500 kWh
        Término de energía 100,00 €
        Impuesto eléctrico y cargos regulados 27,41 €
        IVA (21%) 26,00 €
        TOTAL FACTURA 160,00 €
        """
        parsed = parse_bill_text(text)
        assert parsed["iee_eur"] is None  # línea agrupada no se usa
        rates = derive_bill_tax_rates(parsed, "ES")
        assert rates["iee_source"] == "statutory-fallback"

    def test_weighted_statutory_across_rate_change(self):
        # Periodo anual que cruza la ventana reducida: IEE ponderado por días
        bill = {
            "kwh": 25637,
            "energy_eur": 5350.51,
            "contracted_power_kw": 14.49,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        }
        iee, iva = _statutory_rates_es(bill)
        # 71 días reducidos (22-mar..31-may), resto estándar
        expected_iee = (294 * 0.0511269632 + 71 * 0.005) / 365
        assert iee == pytest.approx(expected_iee, abs=1e-4)
        assert iva == pytest.approx(0.21, abs=1e-6)  # 14,49 kW > 10 kW → sin IVA reducido

    def test_implausible_iva_ratio_is_rejected(self):
        # IVA/base absurdo (no cerca de 21% ni 10%) se descarta
        bill = {"kwh": 300, "energy_eur": 60.0, "iva_eur": 5.0, "vat_base_eur": 100.0}
        # 5/100 = 5% → no cerca de 10% ni 21% → None
        from app.bills import _derived_iva_rate
        assert _derived_iva_rate(bill) is None

    def test_contracted_power_parsed_from_text(self):
        text = """
        Factura de electricidad
        Periodo de facturación: del 01/01/2026 al 31/01/2026
        Potencia contratada 14,49 kW punta / 14,49 kW valle
        Consumo en el periodo: 500 kWh
        TOTAL FACTURA 160,00 €
        """
        assert parse_bill_text(text)["contracted_power_kw"] == 14.49


# --- BUG B: tabla "Detalle mensual consolidado" (factura anual) --------------

_ANNUAL_CONSOLIDATED = """
RESUMEN / FACTURA ANUAL DE ELECTRICIDAD 2026 (DOCUMENTO FICTICIO)
Periodo consolidado
01/01/2026 - 31/12/2026
Potencia contratada
14,49 kW punta / 14,49 kW valle
Consumo anual total
25.637 kWh
Importe anual total
7.332,17 €
Detalle mensual consolidado
MES
CONSUMO (kWh)
IMPORTE
Enero
2.902
829,97 €
Febrero
2.640
755,04 €
Marzo
2.210
632,06 €
Abril
1.874
535,96 €
Mayo
1.632
466,75 €
Junio
1.542
441,01 €
Julio
1.810
517,66 €
Agosto
1.948
557,13 €
Septiembre
1.765
504,79 €
Octubre
2.009
574,57 €
Noviembre
2.430
694,98 €
Diciembre
2.875
822,25 €
TOTAL 2026
25.637
7.332,17 €
DESGLOSE ANUAL ORIENTATIVO
Término de energía 5.350,51 €
Impuesto electricidad 22,50 €
Base imponible 6.059,65 €
IVA (21%) 1.272,53 €
TOTAL ANUAL 7.332,18 €
"""


class TestConsolidatedMonthlyTable:
    def test_local_parser_reads_all_12_months_with_spend(self):
        parsed = parse_bill_text(_ANNUAL_CONSOLIDATED)
        history = {e["month"]: e for e in parsed["consumption_history"]}
        assert len(history) == 12
        assert history[1]["kwh"] == 2902
        assert history[8]["kwh"] == 1948  # agosto
        assert history[7]["kwh"] == 1810  # julio
        assert history[8]["kwh"] > history[7]["kwh"]  # bump de verano
        # importe mensual también capturado
        assert history[1]["eur"] == pytest.approx(829.97, abs=0.01)
        assert history[12]["eur"] == pytest.approx(822.25, abs=0.01)

    def test_annual_consumption_exact_no_interpolation(self):
        parsed = parse_bill_text(_ANNUAL_CONSOLIDATED)
        agg = aggregate_bills([parsed], country_code="ES")
        assert agg["annual_kwh"] == pytest.approx(25637, abs=1)
        assert agg["seasonality_source"] == "bill_history"
        assert agg["estimated_months"] == []  # 12 meses reales, sin estimación
        # el mes de agosto supera al de julio (perfil genérico no lo haría)
        assert agg["monthly_kwh"][7] > agg["monthly_kwh"][6]
        # gasto mensual real del histórico, no reconstruido plano
        assert agg["monthly_eur"][0] == pytest.approx(829.97, abs=0.5)

    def test_vertical_history_with_year(self):
        # Histórico vertical 'Marzo 2026 / 2.115' (formato factura de Julio)
        text = """
        Factura de electricidad
        Periodo de facturación: del 01/07/2026 al 31/07/2026
        Consumo en el periodo: 1.810 kWh
        TOTAL FACTURA 532,27 €
        HISTÓRICO DE CONSUMO
        kWh
        Marzo 2026
        2.115
        Abril 2026
        1.874
        Mayo 2026
        1.632
        Junio 2026
        1.542
        Julio 2026
        1.810
        """
        parsed = parse_bill_text(text)
        history = {e["month"]: e["kwh"] for e in parsed["consumption_history"]}
        assert history[3] == 2115
        assert history[7] == 1810
        assert parsed["kwh"] == 1810  # consumo del periodo intacto


# --- FEATURE J: detección del domicilio de suministro ------------------------

class TestSupplyAddressDetection:
    def test_prefers_supply_over_fiscal_address(self):
        text = """
        Factura de electricidad Endesa
        Periodo de facturación: del 01/01/2026 al 31/01/2026
        Consumo en el periodo: 300 kWh
        Dirección fiscal: Gran Vía 1, 28013 Madrid
        Dirección de suministro: Lugar de Abaixo 12, 15896 Santiago de Compostela, A Coruña
        TOTAL FACTURA 90,00 €
        """
        result = parse_bill_text(text)
        # Gana el CP de suministro (15896), no el fiscal (28013 Madrid)
        assert result["postal_code"] == "15896"
        assert result["country_code"] == "ES"
        assert "Santiago" in (result["city"] or "") or "Santiago" in result["supply_address"]

    def test_postal_code_maps_to_province(self):
        from app.spain_postal import province_from_postal_code
        name, lat, lon = province_from_postal_code("15896")
        assert name == "A Coruña"
        assert 42.5 < lat < 43.8 and -9.5 < lon < -7.5
        assert province_from_postal_code("75001") is None  # CP francés, fuera de 01-52

    def test_spanish_cp_sets_country_only_in_spanish_context(self):
        # Contexto español (Endesa/es) → CP fija país ES
        es = parse_bill_text(
            "Factura Endesa\nPeriodo del 01/01/2026 al 31/01/2026\n"
            "Consumo en el periodo: 300 kWh\nSuministro: Rúa Nova 3, 36001 Pontevedra\n"
            "Total factura 90,00 €"
        )
        assert es["postal_code"] == "36001"
        assert es["country_code"] == "ES"
