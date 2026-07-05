"""Layer 4 — resolutor del consumo anual (mata la suposición 'la factura es anual')."""

from app.bill_resolver import resolve_annual_consumption

_FULL_HISTORY = [{"month": m, "kwh": 500} for m in range(1, 13)]  # 6000 kWh/año


class TestResolver:
    def test_embedded_history_single_bill_is_full_year(self):
        # Una factura de 22 días con histórico de 12 meses → año completo del
        # histórico, NO ×365 del consumo de 22 días.
        r = resolve_annual_consumption(
            bill_period_kwh=346, history=_FULL_HISTORY,
            start="2026-09-01", end="2026-09-23", days=22,
        )
        assert r["method"] == "history"
        assert r["annual_kwh"] == 6000
        assert r["months_real"] == 12
        assert r["confidence"] == "high"

    def test_declared_annual_bill(self):
        r = resolve_annual_consumption(
            bill_period_kwh=13800, history=[], start="2026-01-01", end="2026-12-31", days=365,
        )
        assert r["method"] == "declared_annual"
        assert r["annual_kwh"] == 13800
        assert r["confidence"] == "high"

    def test_short_period_seasonal_not_flat(self):
        # 22 días de septiembre, sin histórico → un solo mes: estimación estacional
        # (NO plano ×365) pero marcada single_month para avisar de estacionalidad.
        r = resolve_annual_consumption(
            bill_period_kwh=346, history=[], start="2026-09-01", end="2026-09-23", days=22,
        )
        assert r["method"] == "single_month_estimate"
        assert r["single_month"] is True
        assert r["confidence"] == "low"  # <10 meses reales
        assert r["months_real"] < 10
        flat = 346 / 22 * 365.25
        assert abs(r["annual_kwh"] - flat) > 50  # estacional ≠ plano

    def test_single_month_history_flagged(self):
        # Un solo mes de histórico → single_month (no anualizar como fiable).
        r = resolve_annual_consumption(
            bill_period_kwh=None, history=[{"month": 7, "kwh": 300}],
        )
        assert r["method"] == "single_month_estimate"
        assert r["single_month"] is True
        assert r["confidence"] == "low"

    def test_monthly_hint_no_dates_not_confident_annual(self):
        # Sin fechas ni histórico pero el modelo dice 'monthly': se estima ×12
        # marcado single_month, NO se toma como anual fiable.
        r = resolve_annual_consumption(
            bill_period_kwh=250, history=[], bill_type_hint="monthly",
        )
        assert r["method"] == "single_month_estimate"
        assert r["single_month"] is True
        assert r["annual_kwh"] == 3000
        assert r["confidence"] == "low"

    def test_partial_history_low_confidence(self):
        r = resolve_annual_consumption(
            bill_period_kwh=None, history=[{"month": m, "kwh": 400} for m in range(1, 5)],
        )
        assert r["method"] == "annualised_estimate"
        assert r["months_real"] == 4
        assert r["confidence"] == "low"

    def test_no_signal_assumes_declared(self):
        # Sin fechas ni histórico no se puede detectar sub-anual → se asume anual.
        r = resolve_annual_consumption(bill_period_kwh=4000, history=[])
        assert r["annual_kwh"] == 4000
        assert r["method"] == "declared_annual"

    def test_insufficient(self):
        r = resolve_annual_consumption(bill_period_kwh=None, history=[])
        assert r["annual_kwh"] is None
        assert r["method"] == "insufficient"

    def test_ten_months_is_high_confidence(self):
        r = resolve_annual_consumption(
            bill_period_kwh=None, history=[{"month": m, "kwh": 400} for m in range(1, 11)],
        )
        assert r["months_real"] == 10
        assert r["confidence"] == "high"
