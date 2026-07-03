from datetime import date

from app.subsidies import (
    compute_subsidy,
    effective_status,
    get_region_record,
    region_from_postal_code,
)

TODAY = date(2026, 7, 1)


def _valid_record(**over):
    rec = {
        "organismo": "INEGA",
        "convocatoria_id": "FV-2026",
        "eur_per_kwp": 300.0,
        "eur_per_kwh_battery": 200.0,
        "cap_absolute_eur": 3000.0,
        "cap_pct_of_cost": 0.40,
        "max_subsidised_kwp": 8.0,
        "window_start": "2026-01-01",
        "window_end": "2026-12-31",
        "status": "open",
        "source_url": "https://x",
        "verified_on": "2026-06-01",
        "irpf_deduction_pct": 0.20,
        "irpf_base_cap_eur": 3000.0,
        "irpf_years": 4,
    }
    rec.update(over)
    return rec


class TestRegionResolver:
    def test_cp2_maps_to_comunidad(self):
        assert region_from_postal_code("15896") == "GALICIA"
        assert region_from_postal_code("27001") == "GALICIA"
        assert region_from_postal_code("28001") == "MADRID"
        assert region_from_postal_code("08001") == "CATALUNA"
        assert region_from_postal_code("75001") is None  # no español


class TestExpiryGuard:
    def test_unverified_record_not_open(self):
        assert effective_status(_valid_record(status="unverified"), TODAY) == "unverified"

    def test_closed_and_exhausted(self):
        assert effective_status(_valid_record(status="closed"), TODAY) == "closed"
        assert effective_status(_valid_record(status="exhausted"), TODAY) == "exhausted"

    def test_expired_by_window_end(self):
        assert effective_status(_valid_record(window_end="2026-06-30"), TODAY) == "expired"

    def test_missing_amounts_is_unverified(self):
        assert effective_status(_valid_record(eur_per_kwp=None), TODAY) == "unverified"

    def test_open_when_valid(self):
        assert effective_status(_valid_record(), TODAY) == "open"


class TestComputeSubsidy:
    def test_unverified_applies_nothing(self):
        r = compute_subsidy(
            _valid_record(status="unverified"),
            power_kwp=7.5, system_cost_eur=9000, today=TODAY,
        )
        assert r["applicable"] is False
        assert r["grant_eur"] == 0.0
        assert r["irpf"] is None

    def test_expired_applies_nothing(self):
        r = compute_subsidy(
            _valid_record(window_end="2026-06-30"),
            power_kwp=7.5, system_cost_eur=9000, today=TODAY,
        )
        assert r["applicable"] is False
        assert r["status"] == "expired"
        assert r["grant_eur"] == 0.0

    def test_smaller_scenario_full_grant_larger_capped(self):
        # max_subsidised_kwp=8: 7,5 kWp elegible entero; 19,8 kWp topado a 8
        small = compute_subsidy(_valid_record(), power_kwp=7.5, system_cost_eur=9000, today=TODAY)
        large = compute_subsidy(_valid_record(), power_kwp=19.8, system_cost_eur=24000, today=TODAY)
        assert small["applicable"] and large["applicable"]
        assert small["eligible_kwp"] == 7.5
        assert large["eligible_kwp"] == 8.0  # topado
        assert small["grant_eur"] == 2250.0  # 7,5 × 300
        assert large["grant_eur"] == 2400.0  # 8 × 300
        # el pequeño recibe más por kWp instalado → favorece el óptimo
        assert small["grant_eur"] / 7.5 > large["grant_eur"] / 19.8

    def test_absolute_and_pct_caps(self):
        # eur_per_kwp alto → domina el tope absoluto
        r = compute_subsidy(
            _valid_record(eur_per_kwp=1000.0, max_subsidised_kwp=None),
            power_kwp=10, system_cost_eur=100000, today=TODAY,
        )
        assert r["grant_eur"] == 3000.0  # cap_absolute_eur
        # cap por % del coste
        r2 = compute_subsidy(
            _valid_record(cap_absolute_eur=None, eur_per_kwp=1000.0, max_subsidised_kwp=None),
            power_kwp=10, system_cost_eur=5000, today=TODAY,
        )
        assert r2["grant_eur"] == 2000.0  # 0,40 × 5000

    def test_irpf_is_net_of_grant_and_separate(self):
        r = compute_subsidy(_valid_record(), power_kwp=7.5, system_cost_eur=9000, today=TODAY)
        # base IRPF = min(9000 − 2250, 3000) = 3000 → 0,20 × 3000 = 600
        assert r["irpf"]["recoverable_eur"] == 600.0
        assert r["irpf"]["years"] == 4
        # el IRPF NO se suma a la subvención (capas separadas)
        assert r["grant_eur"] == 2250.0


class TestShippedGalicia:
    def test_galicia_record_ships_unverified_no_amounts(self):
        rec = get_region_record("GALICIA")
        assert rec is not None
        assert rec["status"] == "unverified"
        assert rec["eur_per_kwp"] is None  # sin cifras inventadas
        r = compute_subsidy(rec, power_kwp=7.5, system_cost_eur=9000, today=TODAY)
        assert r["applicable"] is False
        assert r["grant_eur"] == 0.0
