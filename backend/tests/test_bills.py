from datetime import date

import pytest

from app.bills import BillParseError, aggregate_bills, parse_bill_text
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


class TestAggregateBills:
    def test_estimates_annual_from_sampled_months(self):
        bills = [
            {"kwh": 300, "amount_eur": 70, "start_date": date(2026, 1, 1), "end_date": date(2026, 1, 31)},
            {"kwh": 280, "amount_eur": 65, "start_date": date(2026, 2, 1), "end_date": date(2026, 3, 1)},
        ]
        result = aggregate_bills(bills)
        jan_month = 300 / 30 * DAYS_PER_MONTH[0]
        feb_month = 280 / 28 * DAYS_PER_MONTH[1]
        expected = (
            (jan_month / (MONTHLY_WEIGHTS[0] / sum(MONTHLY_WEIGHTS))) * 30
            + (feb_month / (MONTHLY_WEIGHTS[1] / sum(MONTHLY_WEIGHTS))) * 28
        ) / 58
        assert result["annual_kwh"] == pytest.approx(expected, rel=0.01)
        assert result["avg_price_eur_kwh"] == pytest.approx(135 / 580, rel=0.01)
        assert result["bill_count"] == 2
        assert result["priced_bill_count"] == 2
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
        assert result["avg_price_eur_kwh"] == pytest.approx(325 / 1300, rel=0.01)

    def test_january_and_june_manual_bills_do_not_get_multiplied_by_month_days(self):
        result = aggregate_bills(
            [
                {"month": 1, "kwh": 612, "amount_eur": 155.15},
                {"month": 6, "kwh": 344, "amount_eur": 94.04},
            ]
        )

        assert result["observed_months"] == [1, 6]
        assert result["monthly_kwh"][0] == pytest.approx(612, rel=0.01)
        assert result["monthly_kwh"][5] == pytest.approx(344, rel=0.01)
        assert result["annual_kwh"] == pytest.approx(sum(result["monthly_kwh"]), rel=0.001)
        assert 5000 < result["annual_kwh"] < 6500
        assert result["avg_price_eur_kwh"] == round((155.15 + 94.04) / (612 + 344), 4)

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
                {"month": 1, "kwh": 286, "amount_eur": 95.09},
                {"month": 2, "kwh": 300, "amount_eur": 2.00},
                {"month": 3, "kwh": 250, "amount_eur": 380.00},
            ]
        )

        assert result["avg_price_eur_kwh"] == pytest.approx(95.09 / 286, rel=0.001)
        assert result["bill_count"] == 3
        assert result["priced_bill_count"] == 1
        assert result["ignored_price_bill_count"] == 2

    def test_invalid_bills_raise(self):
        with pytest.raises(BillParseError):
            aggregate_bills([{"kwh": 0, "days": 30}])


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
