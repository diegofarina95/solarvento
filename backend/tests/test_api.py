"""Tests de la API con PVGIS mockeado (respx)."""

import json

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.config import get_settings
from tests.fixtures import pvcalc_response, seriescalc_response

PVGIS = "https://re.jrc.ec.europa.eu/api/v5_2"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLVENTO_CACHE_DB_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setenv("SOLVENTO_PRICING_CACHE_DB_PATH", str(tmp_path / "pricing.db"))
    monkeypatch.setenv("SOLVENTO_UPLOAD_RATELIMIT_DB_PATH", str(tmp_path / "ratelimit.db"))
    # Modo local: ignora cualquier clave OpenAI del entorno o de backend/.env
    monkeypatch.setenv("SOLVENTO_OPENAI_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def openai_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLVENTO_CACHE_DB_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setenv("SOLVENTO_PRICING_CACHE_DB_PATH", str(tmp_path / "pricing.db"))
    monkeypatch.setenv("SOLVENTO_UPLOAD_RATELIMIT_DB_PATH", str(tmp_path / "ratelimit.db"))
    monkeypatch.setenv("SOLVENTO_BILL_CACHE_DB_PATH", str(tmp_path / "bill_cache.db"))
    monkeypatch.setenv("SOLVENTO_OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def standard_openai_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLVENTO_CACHE_DB_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setenv("SOLVENTO_PRICING_CACHE_DB_PATH", str(tmp_path / "pricing.db"))
    monkeypatch.setenv("SOLVENTO_UPLOAD_RATELIMIT_DB_PATH", str(tmp_path / "ratelimit.db"))
    monkeypatch.setenv("SOLVENTO_BILL_CACHE_DB_PATH", str(tmp_path / "bill_cache.db"))
    monkeypatch.delenv("SOLVENTO_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def mock_pvgis(respx_mock):
    def pvcalc_side_effect(request):
        params = request.url.params
        if params.get("optimalangles") == "1":
            return Response(200, json=pvcalc_response(slope=35, azimuth=0))
        return Response(
            200,
            json=pvcalc_response(
                slope=float(params.get("angle", 35)),
                azimuth=float(params.get("aspect", 0)),
                optimal=False,
            ),
        )

    respx_mock.get(f"{PVGIS}/PVcalc").mock(side_effect=pvcalc_side_effect)
    respx_mock.get(f"{PVGIS}/seriescalc").mock(
        return_value=Response(200, json=seriescalc_response())
    )


@respx.mock
def test_sizing_bias_slider_roi_to_independence(respx_mock, client):
    # Slider ROI↔Independencia: bias 0 = óptimo económico; 100 = máximo ahorro.
    # De 0→100 sube la autosuficiencia y empeora el payback (el tradeoff real).
    mock_pvgis(respx_mock)

    def estimate(bias):
        resp = client.post("/api/solar-estimate", json={
            "lat": 42.88, "lon": -8.54, "peak_power_kwp": 1.0,
            "country_code": "ES", "annual_consumption_kwh": 6000,
            "auto_size_power": True, "sizing_bias": bias,
        })
        assert resp.status_code == 200
        return resp.json()

    low, mid, high = estimate(0), estimate(50), estimate(100)
    sa = low["sizing_analysis"]
    # bias 0 → óptimo económico ; bias 100 → máximo ahorro.
    assert low["recommended_system"]["kwp"] == pytest.approx(sa["economic_optimum_kwp"], abs=0.05)
    assert high["recommended_system"]["kwp"] == pytest.approx(sa["max_savings_kwp"], abs=0.05)
    # Monótono: más independencia = más kWp.
    assert (low["recommended_system"]["kwp"]
            <= mid["recommended_system"]["kwp"]
            <= high["recommended_system"]["kwp"])
    # El tradeoff: hacia independencia sube la autosuficiencia...
    assert (high["recommended_system"]["self_sufficiency_pct"]
            >= low["recommended_system"]["self_sufficiency_pct"])
    # ...y empeora (sube) el payback.
    assert high["recommended_system"]["payback_years"] >= low["recommended_system"]["payback_years"]


@respx.mock
def test_sizing_bias_ignored_without_auto_size(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
        "country_code": "ES", "annual_consumption_kwh": 6000, "sizing_bias": 100,
    })
    # Sin auto_size_power, sizing_bias no cambia la potencia semilla (5.0).
    assert resp.status_code == 200
    assert resp.json()["analysis_power_kwp"] == pytest.approx(5.0, abs=0.05)


@respx.mock
def test_solar_estimate_basic_mode(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={"lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["optimal"]["slope_deg"] == 35.0
    assert data["user_system"] is None
    assert data["loss_vs_optimal_pct"] is None
    assert len(data["optimal"]["monthly"]) == 12
    assert len(data["plane_irradiation_monthly"]) == 12
    assert data["plane_irradiation_monthly"][0]["irradiation_kwh_m2"] == data[
        "optimal"
    ]["monthly"][0]["irradiation_kwh_m2"]
    # Sin precio explícito se usa el precio doméstico del país (ES 2025: 0.17)
    assert data["economics"]["electricity_price_eur_kwh"] == 0.17
    assert data["economics"]["electricity_price_source"] == "default"
    assert data["economics"]["annual_savings_eur"] > 0
    # Sin coste indicado se estima por kWp (ES media 1100 a 5 kWp) y se muestra
    # el rango típico de presupuestos para ese tamaño (-12% / +15%), no el
    # min-max de todo el mercado
    assert data["economics"]["installation_cost_eur"] == 5500.0
    assert data["economics"]["installation_cost_range_eur"] == {
        "low": 4840.0,
        "medium": 5500.0,
        "high": 6325.0,
    }
    assert data["economics"]["cost_is_estimated"] is True
    assert data["economics"]["roi_pct"] is not None
    assert data["economics"]["payback_years"] is not None
    assert data["pricing"]["country_code"] == "ES"
    assert data["pricing"]["source_type"] == "market_average"
    assert data["pricing"]["fallback_used"] is True
    assert data["pricing"]["turnkey_cost_per_kwp"]["medium"] == 1100.0
    assert data["pricing"]["battery_cost_per_kwh"]["medium"] == 650.0
    assert data["panels"] is None
    # Sin consumo no hay simulación de baterías
    assert data["battery_analysis"] is None
    assert data["consumption"] is None
    assert data["confidence"]["level"] == "low"


@respx.mock
def test_solar_estimate_advanced_mode(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "tilt_deg": 20,
            "azimuth_deg": 45,
            "annual_consumption_kwh": 4000,
            "installation_cost_eur": 7000,
            "electricity_price_eur_kwh": 0.20,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_system"]["slope_deg"] == 20.0
    assert data["user_system"]["azimuth_deg"] == 45.0
    assert data["loss_vs_optimal_pct"] is not None
    assert data["economics"]["electricity_price_eur_kwh"] == 0.20
    assert data["economics"]["electricity_price_source"] == "manual"
    assert data["economics"]["installation_cost_eur"] == 7000
    assert data["economics"]["installation_cost_range_eur"] == {
        "low": 7000.0,
        "medium": 7000.0,
        "high": 7000.0,
    }
    assert data["economics"]["cost_is_estimated"] is False
    assert data["economics"]["annual_savings_eur"] > 0
    assert data["economics"]["payback_years"] is not None
    assert data["panels"]["count"] >= 1
    assert data["panels"]["panel_power_w"] == 450
    assert data["panels"]["roof_area_m2"] > 0
    # Con consumo conocido hay simulación horaria: escenarios 0/5/10 kWh
    analysis = data["battery_analysis"]
    assert [s["battery_kwh"] for s in analysis["scenarios"]] == [0, 5, 10]
    assert analysis["recommendation"]
    base = analysis["scenarios"][0]
    assert 0 < base["self_consumption_pct"] <= 100
    assert data["typical_day"] is not None
    assert len(data["typical_day"]["production"]) == 12
    assert len(data["typical_day"]["production"][0]) == 24
    assert data["consumption"] == {
        "annual_kwh": 4000,
        "source": "input",
        "avg_price_eur_kwh": None,
        "avg_price_kwh": None,
        "marginal_price_eur_kwh": None,
        "marginal_price_factor": None,
        "tax_rates_source": None,
        "bill_count": 0,
        "priced_bill_count": 0,
        "total_amount_bill_count": 0,
        "ignored_price_bill_count": 0,
        "days_covered": None,
        "monthly_kwh": None,
        "monthly_eur": None,
        "monthly_amount": None,
        "annual_amount_eur": 800.0,
        "annual_amount": 800.0,
        "currency": "EUR",
        "observed_months": [],
        "estimated_months": [],
        "contracted_power_kw": None,
        "seasonality_source": "manual_annual",
        "consumption_reliability": None,
        "single_month": False,
        "months_covered": None,
        "distinct_cups": None,
        "needs_review": False,
        "review_reasons": [],
        "profile": {
            "country_code": "ES",
            "occupancy_profile": "standard",
            "has_heat_pump": False,
            "has_ev": False,
            "has_pool": False,
        },
    }


@respx.mock
def test_solar_estimate_with_bills(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "bills": [
                {
                    "kwh": 300,
                    "energy_eur": 50,
                    "amount_eur": 70,
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                },
                {
                    "kwh": 280,
                    "energy_eur": 46,
                    "amount_eur": 66,
                    "start_date": "2026-02-01",
                    "end_date": "2026-03-01",
                },
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    cons = data["consumption"]
    assert cons["source"] == "bills"
    # Enero/febrero se tratan como meses observados, no como promedio plano de días.
    assert cons["annual_kwh"] == pytest.approx(3206.6, rel=0.01)
    assert cons["monthly_kwh"] is not None
    assert cons["monthly_eur"] is not None
    assert cons["monthly_amount"] is not None
    assert cons["annual_amount_eur"] == pytest.approx(
        cons["annual_amount"], rel=0.01
    )
    assert cons["observed_months"] == [1, 2]
    assert cons["seasonality_source"] == "estimated_from_sampled_months"
    assert cons["bill_count"] == 2
    assert cons["priced_bill_count"] == 2
    assert cons["total_amount_bill_count"] == 2
    assert cons["ignored_price_bill_count"] == 0
    # El precio derivado de las facturas se usa en la economía
    assert data["economics"]["electricity_price_eur_kwh"] == cons["avg_price_eur_kwh"]
    assert data["economics"]["electricity_price_source"] == "bills"
    assert data["economics"]["electricity_price_bill_count"] == 2
    assert data["battery_analysis"] is not None
    assert data["panels"] is not None


@respx.mock
def test_solar_estimate_january_june_bills_regression(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "bills": [
                {"month": 1, "kwh": 612, "energy_eur": 105.15, "amount_eur": 155.15},
                {"month": 6, "kwh": 344, "energy_eur": 54.04, "amount_eur": 94.04},
            ],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    cons = data["consumption"]
    assert cons["annual_kwh"] == pytest.approx(5492.1, rel=0.01)
    assert cons["avg_price_eur_kwh"] == pytest.approx(0.1665, rel=0.001)
    assert 8 <= data["panels"]["count"] <= 12
    assert data["economics"]["annual_savings_eur"] > 500
    assert data["analysis_power_kwp"] == data["requested_peak_power_kwp"]
    # Fuente única: la tarjeta de paneles refleja la potencia analizada, no el
    # tamaño de cobertura del 100% (que queda como 'needed_kwp' informativo).
    assert data["panels"]["total_kwp"] == data["analysis_power_kwp"]
    assert data["recommended_system"]["kwp"] == data["analysis_power_kwp"]

    mock_5kwp_production = pvcalc_response()["outputs"]["totals"]["fixed"]["E_y"]
    assert data["optimal"]["annual_production_kwh"] == pytest.approx(mock_5kwp_production, rel=0.001)
    assert data["annual_energy"]["production_kwh"] == pytest.approx(
        data["optimal"]["annual_production_kwh"], rel=0.001
    )
    assert data["annual_energy"]["consumption_kwh"] == pytest.approx(cons["annual_kwh"])
    assert data["annual_energy"]["coverage_pct"] == pytest.approx(
        data["optimal"]["annual_production_kwh"] / cons["annual_kwh"] * 100,
        abs=0.1,
    )
    assert data["annual_energy"]["production_to_consumption_pct"] == pytest.approx(
        data["optimal"]["annual_production_kwh"] / cons["annual_kwh"] * 100,
        abs=0.1,
    )

    # El coste estimado, la simulación horaria y la amortización usan la potencia introducida.
    assert data["economics"]["installation_cost_eur"] == pytest.approx(
        data["analysis_power_kwp"] * data["pricing"]["turnkey_cost_per_kwp"]["medium"],
        rel=0.001,
    )
    assert data["economics"]["installation_cost_range_eur"]["medium"] == pytest.approx(
        data["analysis_power_kwp"] * data["pricing"]["turnkey_cost_per_kwp"]["medium"]
    )
    # seriescalc se pide siempre a 1 kWp (clave de caché estable entre potencias)
    # y el perfil se normaliza a la producción anual del sistema analizado.
    series_calls = [
        call for call in respx_mock.calls if call.request.url.path.endswith("/seriescalc")
    ]
    assert series_calls[-1].request.url.params["peakpower"] == "1.0"
    from app.profiles import DAYS_PER_MONTH

    typical_annual = sum(
        sum(data["typical_day"]["production"][m]) * DAYS_PER_MONTH[m] for m in range(12)
    )
    assert typical_annual == pytest.approx(data["annual_energy"]["production_kwh"], rel=0.01)

    base = data["battery_analysis"]["scenarios"][0]
    assert data["economics"]["annual_savings_eur"] == base["annual_savings_eur"]
    assert base["production_kwh"] == pytest.approx(data["annual_energy"]["production_kwh"])
    assert base["exported_kwh"] == pytest.approx(
        data["annual_energy"]["production_kwh"] - data["annual_energy"]["self_consumed_kwh"],
        abs=0.3,
    )
    assert base["self_consumption_pct"] < 100
    assert base["self_sufficiency_pct"] > 25
    for scenario in data["battery_analysis"]["scenarios"]:
        assert scenario["investment_range_eur"]["medium"] == scenario["investment_eur"]
        assert scenario["self_consumption_pct"] <= 100
        assert scenario["self_sufficiency_pct"] <= 100


@respx.mock
def test_solar_estimate_pvgis_down_returns_502(respx_mock, client):
    respx_mock.get(f"{PVGIS}/PVcalc").mock(return_value=Response(500))
    resp = client.post(
        "/api/solar-estimate",
        json={"lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0},
    )
    assert resp.status_code == 502


@respx.mock
def test_solar_estimate_outside_europe_returns_422(respx_mock, client):
    respx_mock.get(f"{PVGIS}/PVcalc").mock(
        return_value=Response(400, json={"message": "Location over the sea"})
    )
    resp = client.post(
        "/api/solar-estimate",
        json={"lat": 0.0, "lon": -30.0, "peak_power_kwp": 5.0},
    )
    assert resp.status_code == 422
    assert "Europa" in resp.json()["detail"] or "europeas" in resp.json()["detail"]


def test_validation_rejects_bad_inputs(client):
    cases = [
        {"lat": 999, "lon": -8.54, "peak_power_kwp": 5.0},  # lat fuera de rango
        {"lat": 42.88, "lon": -8.54, "peak_power_kwp": -1},  # potencia negativa
        {"lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "tilt_deg": 120},  # inclinación > 90
        {"lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "loss_pct": 80},  # pérdidas > 50
        {"lat": 42.88, "lon": -8.54},  # falta potencia
    ]
    for body in cases:
        resp = client.post("/api/solar-estimate", json=body)
        assert resp.status_code == 422, body


@respx.mock
def test_optimal_angles_endpoint(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.get("/api/optimal-angles", params={"lat": 42.88, "lon": -8.54})
    assert resp.status_code == 200
    data = resp.json()
    assert data["slope_deg"] == 35.0
    assert data["azimuth_deg"] == 0.0
    assert data["annual_production_per_kwp"] > 0


@respx.mock
def test_pvgis_responses_are_cached(respx_mock, client):
    mock_pvgis(respx_mock)
    body = {"lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0}
    assert client.post("/api/solar-estimate", json=body).status_code == 200
    calls_first = respx_mock.calls.call_count
    assert client.post("/api/solar-estimate", json=body).status_code == 200
    # La segunda petición idéntica no toca PVGIS
    assert respx_mock.calls.call_count == calls_first


def test_parse_bill_unreadable_pdf_returns_empty_row(client):
    # Contrato uniforme: factura ilegible → 200 con aviso, no 422
    resp = client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"esto no es un pdf", "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kwh"] is None
    assert data["warnings"]


def test_parse_bill_rejects_wrong_file_type(client):
    resp = client.post(
        "/api/parse-bill",
        files={"file": ("factura.txt", b"texto", "text/plain")},
    )
    assert resp.status_code == 422


def test_cors_is_restricted_to_configured_origins(client):
    allowed = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"

    blocked = client.options(
        "/api/health",
        headers={
            "Origin": "https://example.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers


def test_invalid_uploads_do_not_consume_valid_upload_quota(client, monkeypatch):
    monkeypatch.setenv("SOLVENTO_UPLOAD_RATELIMIT_MAX", "1")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        invalid = c.post(
            "/api/parse-bill",
            files={"file": ("factura.txt", b"texto", "text/plain")},
        )
        assert invalid.status_code == 422
        valid = c.post(
            "/api/parse-bill",
            files={"file": ("f.pdf", b"%PDF-1.4 basura", "application/pdf")},
        )
        assert valid.status_code == 200
        blocked = c.post(
            "/api/parse-bill",
            files={"file": ("f.pdf", b"%PDF-1.4 basura", "application/pdf")},
        )
        assert blocked.status_code == 429
    get_settings.cache_clear()


def test_parse_bill_rejects_image_without_openai(client):
    # Sin clave OpenAI, las fotos no se pueden procesar: se pide PDF.
    resp = client.post(
        "/api/parse-bill",
        files={"file": ("factura.jpg", b"\xff\xd8\xff\xe0jpeg", "image/jpeg")},
    )
    assert resp.status_code == 422
    assert "PDF" in resp.json()["detail"]


def test_parse_bill_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setenv("SOLVENTO_UPLOAD_RATELIMIT_MAX", "3")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        # Un PDF ilegible da 200 con aviso, y cada intento cuenta para el límite
        for _ in range(3):
            r = c.post(
                "/api/parse-bill",
                files={"file": ("f.pdf", b"%PDF-1.4 basura", "application/pdf")},
            )
            assert r.status_code == 200
        blocked = c.post(
            "/api/parse-bill",
            files={"file": ("f.pdf", b"%PDF-1.4 basura", "application/pdf")},
        )
        assert blocked.status_code == 429
        assert "límite" in blocked.json()["detail"]
    get_settings.cache_clear()


def _cf(raw, label="campo", conf=0.9):
    """Un sobre numérico del contrato (raw_text verbatim; la app normaliza)."""
    return {"raw_text": raw, "value": None, "source_label": label, "confidence": conf}


def _contract(**over):
    """Contrato de extracción con todos los campos en null salvo los indicados."""
    contract = {
        "annual_consumption_kwh": _cf(None),
        "period_total_kwh": _cf(None),
        "period_split": {"p1_punta": _cf(None), "p2_llano": _cf(None), "p3_valle": _cf(None)},
        "period_split_prices": {
            "p1_punta": _cf(None), "p2_llano": _cf(None), "p3_valle": _cf(None),
        },
        "monthly_history": [],
        "contracted_power_kw": _cf(None),
        "tariff": None,
        "billing_period": {"start": None, "end": None},
        "energy_term_eur": _cf(None),
        "energy_term_eur_per_kwh": _cf(None),
        "total_amount_eur": _cf(None),
        "electricity_tax_eur": _cf(None),
        "vat_eur": _cf(None),
        "vat_rate": _cf(None),
        "currency": None,
        "country_code": None,
        "language": None,
        "supply_address": {"street": None, "cp": None, "municipio": None, "provincia": None},
        "cups": None,
        "warnings": [],
    }
    contract.update(over)
    return contract


def _contract_response(**over):
    return Response(
        200,
        json={"status": "completed", "output_text": json.dumps(_contract(**over))},
    )


@respx.mock
def test_parse_bill_accepts_image_with_openai(respx_mock, openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("210", "Consumo facturado"),
            total_amount_eur=_cf("58", "Total"),
            billing_period={"start": "2026-06-01", "end": "2026-06-30"},
            country_code="ES",
            language="es",
        )
    )
    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.jpg", b"\xff\xd8\xff\xe0jpegdata", "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["kwh"] == 210.0
    # La imagen se envía como input_image con data URL de imagen
    payload = json.loads(respx_mock.calls.last.request.content)
    file_content = payload["input"][1]["content"][0]
    assert file_content["type"] == "input_image"
    assert file_content["image_url"].startswith("data:image/jpeg;base64,")


@respx.mock
def test_parse_bill_uses_openai_when_configured(respx_mock, openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("245,7", "Consommation"),
            total_amount_eur=_cf("83,42", "Total TTC"),
            billing_period={"start": "2026-05-01", "end": "2026-05-31"},
            country_code="FR",
            language="fr",
        )
    )

    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("facture.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["kwh"] == 245.7
    assert data["total_eur"] == 83.42
    assert data["country_code"] == "FR"
    assert data["language"] == "fr"
    assert data["parser"] == "openai-contract"

    payload = json.loads(respx_mock.calls.last.request.content)
    assert payload["model"] == "gpt-5.5"
    # 'temperature' NO se envía: los modelos de razonamiento lo rechazan con 400.
    assert "temperature" not in payload
    content = payload["input"][1]["content"]
    assert content[0]["type"] == "input_file"
    assert content[0]["filename"] == "facture.pdf"
    assert content[0]["file_data"].startswith("data:application/pdf;base64,")
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    required = payload["text"]["format"]["schema"]["required"]
    assert "supply_address" in required
    assert "period_split" in required
    assert "annual_consumption_kwh" in required


def test_parse_bill_repairs_openai_single_period_as_total(respx_mock, openai_client):
    # Bug crítico 2.0TD: OpenAI devuelve P1 (2.150) como total; con el split de
    # periodos el endpoint lo corrige a la suma real (13.800), no ~1/6 de escala.
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("2.150", "Consumo (mal: solo P1)"),
            period_split={
                "p1_punta": _cf("2.150", "P1"),
                "p2_llano": _cf("2.820", "P2"),
                "p3_valle": _cf("8.830", "P3"),
            },
            total_amount_eur=_cf("3.027,14", "Total"),
            currency="EUR",
            country_code="ES",
            language="es",
        )
    )
    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kwh"] == 13800.0  # suma de periodos, no 2.150
    assert data["consumption_periods"] == {"punta": 2150, "llano": 2820, "valle": 8830}
    assert data["needs_review"] is False


def test_parse_bill_flags_review_on_implausible_effective_price(respx_mock, openai_client):
    # Sin split de periodos, el precio efectivo 3.027/2.150 = 1,41 €/kWh dispara
    # la guarda → estado 'revisar factura', no un resultado seguro y equivocado.
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("2.150", "Consumo (solo P1)"),
            total_amount_eur=_cf("3.027,14", "Total"),
            currency="EUR",
            country_code="ES",
            language="es",
        )
    )
    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_review"] is True
    assert any("precio efectivo" in r.lower() for r in data["review_reasons"])


@respx.mock
def test_parse_bill_contract_is_authoritative_and_uses_pdf_text_hint(
    respx_mock, openai_client, monkeypatch
):
    # El parser posicional/regex está RETIRADO de la vía primaria: aunque exista,
    # NO se usa cuando hay clave de OpenAI. La capa de texto del PDF viaja solo
    # como señal auxiliar al modelo.
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("2.902", "Consumo facturado"),
            energy_term_eur=_cf("497,91", "Término energía"),
            total_amount_eur=_cf("829,17", "Total"),
            currency="EUR",
            country_code="ES",
            language="es",
        )
    )

    from app.main import bills_mod

    def _boom(_content):
        raise AssertionError("el parser regex no debe usarse con OpenAI configurado")

    monkeypatch.setattr(bills_mod, "parse_bill_pdf", _boom)
    monkeypatch.setattr(
        bills_mod, "extract_pdf_text_safe", lambda _content: "CAPA DE TEXTO DEL PDF"
    )

    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["kwh"] == 2902.0
    assert data["energy_eur"] == 497.91
    assert data["total_eur"] == 829.17
    assert data["parser"] == "openai-contract"
    # El texto del PDF se adjuntó como señal auxiliar en la llamada al modelo.
    payload = json.loads(respx_mock.calls.last.request.content)
    texts = " ".join(
        part.get("text", "") for part in payload["input"][1]["content"]
    )
    assert "CAPA DE TEXTO DEL PDF" in texts


@respx.mock
def test_parse_bill_geocodes_openai_supply_address(respx_mock, openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("245,7", "Consommation"),
            total_amount_eur=_cf("83,42", "Total TTC"),
            country_code="FR",
            language="fr",
            supply_address={
                "street": "10 Rue de Rivoli", "cp": "75001",
                "municipio": "Paris", "provincia": "Île-de-France",
            },
        )
    )
    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=Response(
            200,
            json=[
                {
                    "display_name": "Rue Royale, Bruxelles, Belgique",
                    "lat": "50.85034",
                    "lon": "4.35171",
                    "address": {"country_code": "be"},
                },
                {
                    "display_name": "10 Rue de Rivoli, Paris, France",
                    "lat": "48.856613",
                    "lon": "2.352222",
                    "address": {"country_code": "fr"},
                },
            ],
        )
    )

    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("facture.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["supply_address"] == "10 Rue de Rivoli"
    assert data["postal_code"] == "75001"
    assert data["city"] == "Paris"
    assert data["lat"] == pytest.approx(48.856613)
    assert data["lon"] == pytest.approx(2.352222)
    assert data["location_label"] == "10 Rue de Rivoli, Paris, France"

    geocode_call = [
        call for call in respx_mock.calls if call.request.url.path.endswith("/search")
    ][0]
    # Primaria: CP + municipio (la calle ya no se envía en la query)
    assert "75001" in geocode_call.request.url.params["q"]
    assert "Paris" in geocode_call.request.url.params["q"]


@respx.mock
def test_parse_bill_ignores_non_european_geocode_candidate(respx_mock, openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("245,7", "Consommation"),
            total_amount_eur=_cf("83,42", "Total TTC"),
            country_code="FR",
            language="fr",
            supply_address={
                "street": "10 Rue de Rivoli", "cp": "75001",
                "municipio": "Paris", "provincia": "Île-de-France",
            },
        )
    )
    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=Response(
            200,
            json=[
                {
                    "display_name": "Paris, Lamar County, Texas, United States",
                    "lat": "33.6609389",
                    "lon": "-95.555513",
                    "address": {"country_code": "us"},
                }
            ],
        )
    )

    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("facture.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["country_code"] == "FR"
    assert data["lat"] is None
    assert data["lon"] is None


@respx.mock
def test_parse_bill_uses_standard_openai_api_key(respx_mock, standard_openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("198,4", "Consommation"),
            total_amount_eur=_cf("64,2", "Total TTC"),
            country_code="FR",
            language="fr",
        )
    )

    resp = standard_openai_client.post(
        "/api/parse-bill",
        files={"file": ("facture.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )

    assert resp.status_code == 200
    assert resp.json()["parser"] == "openai-contract"
    assert respx_mock.calls.call_count == 1


@respx.mock
def test_parse_bill_is_deterministic_same_file_cached(respx_mock, openai_client):
    # Determinismo: la misma factura → mismo JSON → mismos euros, y NO se vuelve a
    # llamar al modelo (caché por hash de fichero). Este tool cotiza euros.
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("3.500", "Consumo"),
            total_amount_eur=_cf("820,00", "Total"),
            currency="EUR", country_code="ES", language="es",
        )
    )
    files = {"file": ("factura.pdf", b"%PDF-1.4 misma-factura\n%%EOF", "application/pdf")}
    first = openai_client.post("/api/parse-bill", files=files)
    second = openai_client.post("/api/parse-bill", files=dict(files))
    assert first.status_code == second.status_code == 200
    assert first.json()["kwh"] == second.json()["kwh"] == 3500.0
    assert first.json() == second.json()
    # Segunda subida servida desde caché: una sola llamada al modelo.
    assert respx_mock.calls.call_count == 1


@respx.mock
def test_parse_bill_malformed_model_response_is_review_not_crash(respx_mock, openai_client):
    # El modelo devuelve algo que no es JSON del contrato → estado de revisión,
    # nunca un 500 ni un resultado calculado.
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=Response(
            200, json={"status": "completed", "output_text": "lo siento, no es JSON"}
        )
    )
    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kwh"] is None
    assert data["needs_review"] is True


@respx.mock
def test_parse_bill_uses_plain_text_path_for_text_pdf(respx_mock, openai_client, monkeypatch):
    # Blindado: un PDF con capa de texto se analiza como TEXTO PLANO (sin subir el
    # fichero), que es lo más fiable y barato.
    from app.main import bills_mod
    monkeypatch.setattr(
        bills_mod, "extract_pdf_text_safe", lambda _c: "FACTURA DE ELECTRICIDAD 2.902 kWh"
    )
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=_contract_response(
            annual_consumption_kwh=_cf("2.902", "Consumo"),
            total_amount_eur=_cf("725,50", "Total"), currency="EUR", country_code="ES",
        )
    )
    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["kwh"] == 2902.0
    payload = json.loads(respx_mock.calls.last.request.content)
    content = payload["input"][1]["content"]
    # Vía texto: NO se sube fichero; el texto plano va en la petición.
    assert all(part["type"] == "input_text" for part in content)
    assert any("2.902 kWh" in part["text"] for part in content)


@respx.mock
def test_parse_bill_vision_fallback_when_text_path_fails(respx_mock, openai_client, monkeypatch):
    # Si la vía texto falla (400), se reintenta con VISIÓN (fichero). Blindaje.
    from app.main import bills_mod
    monkeypatch.setattr(bills_mod, "extract_pdf_text_safe", lambda _c: "texto de la factura")
    route = respx_mock.post("https://api.openai.com/v1/responses")
    route.side_effect = [
        Response(400, json={"error": {"message": "text path boom"}}),
        _contract_response(annual_consumption_kwh=_cf("2.902", "Consumo"),
                           total_amount_eur=_cf("725,50", "Total"), currency="EUR"),
    ]
    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["kwh"] == 2902.0
    assert respx_mock.calls.call_count == 2  # texto (falla) + visión (ok)
    last = json.loads(respx_mock.calls.last.request.content)
    assert last["input"][1]["content"][0]["type"] == "input_file"


@respx.mock
def test_parse_bill_schema_rejected_400_is_state_c_no_fabrication(respx_mock, openai_client):
    # PHASE 2/5: si OpenAI rechaza el esquema (400), fila VACÍA en estado C, sin
    # números fabricados; nunca un 500.
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=Response(400, json={"error": {"message": "schema too large"}})
    )
    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("factura.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kwh"] is None
    assert data["state"] == "extraction_failed"
    assert data["total_eur"] is None and data["energy_eur"] is None


@respx.mock
def test_manual_entry_computes_with_extractor_disabled(respx_mock, client):
    # PHASE 3: el suelo manual. Con el extractor DESACTIVADO (client sin clave),
    # un usuario que teclea 2.902 kWh + importes obtiene un cálculo completo.
    mock_pvgis(respx_mock)
    # Entrada manual directa del consumo anual (el usuario teclea su cifra).
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88, "lon": -8.54, "country_code": "ES", "peak_power_kwp": 3.0,
            "annual_consumption_kwh": 2902,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["consumption"]["annual_kwh"] == 2902
    assert data["recommended_system"]["kwp"] > 0

    # Y también por FILAS manuales (12 meses tecleados) sin extractor.
    resp2 = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88, "lon": -8.54, "country_code": "ES", "peak_power_kwp": 3.0,
            "bills": [{"kwh": 2902 / 12, "total_eur": 60.0, "amount_eur": 60.0,
                       "currency": "EUR", "month": m} for m in range(1, 13)],
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["recommended_system"]["kwp"] > 0


@respx.mock
def test_geocode_endpoint(respx_mock, client):
    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=Response(
            200,
            json=[
                {"display_name": "Santiago de Compostela, Galicia, España", "lat": "42.8805", "lon": "-8.5457"}
            ],
        )
    )
    resp = client.get("/api/geocode", params={"q": "Santiago de Compostela"})
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["lat"] == pytest.approx(42.8805)

    # Query demasiado corta → 422
    assert client.get("/api/geocode", params={"q": "a"}).status_code == 422


@respx.mock
def test_geocode_filters_to_european_locations(respx_mock, client):
    respx_mock.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=Response(
            200,
            json=[
                {
                    "display_name": "Paris, Lamar County, Texas, United States",
                    "lat": "33.6609389",
                    "lon": "-95.555513",
                    "address": {"country_code": "us"},
                },
                {
                    "display_name": "Paris, Île-de-France, France",
                    "lat": "48.8534951",
                    "lon": "2.3483915",
                    "address": {"country_code": "fr"},
                },
            ],
        )
    )

    resp = client.get("/api/geocode", params={"q": "paris"})

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["country_code"] == "FR"
    assert data[0]["display_name"] == "Paris, Île-de-France, France"


@respx.mock
def test_non_euro_country_uses_local_currency_prices(respx_mock, client):
    """Regresión: en países sin euro, surplus y precio eléctrico van en moneda local.

    Antes los costes se escalaban a PLN pero la compensación de excedentes y el
    precio eléctrico por defecto se quedaban en EUR (~4x infravalorados).
    """
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 52.23,
            "lon": 21.01,
            "peak_power_kwp": 5.0,
            "country_code": "PL",
            "annual_consumption_kwh": 4000,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pricing"]["currency"] == "PLN"
    # 0.22 EUR/kWh * 4.3 ≈ 0.95 PLN/kWh (no el 0.15 EUR genérico)
    assert data["economics"]["electricity_price_eur_kwh"] > 0.5
    # Surplus escalado a PLN: muy por encima del rango 0.03-0.08 EUR
    assert data["battery_analysis"]["surplus_price_eur_kwh"] > 0.1
    # Coherencia: el ahorro no puede superar el gasto anual en PLN
    annual_spend = 4000 * data["economics"]["electricity_price_eur_kwh"]
    assert data["economics"]["annual_savings_eur"] <= annual_spend + 0.5


@respx.mock
def test_german_feed_in_scheme_is_uncapped(respx_mock, client):
    """En Alemania (feed_in) el vertido se paga sin tope mensual."""
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 52.52,
            "lon": 13.4,
            "peak_power_kwp": 5.0,
            "country_code": "DE",
            "annual_consumption_kwh": 2000,  # consumo bajo → mucho excedente
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pricing"]["export_scheme"] == "feed_in"
    assert data["battery_analysis"]["export_scheme"] == "feed_in"
    # Sin tope: el ahorro coincide con autoconsumo×precio + vertido×tarifa
    base = data["battery_analysis"]["scenarios"][0]
    price = data["economics"]["electricity_price_eur_kwh"]
    surplus = data["battery_analysis"]["surplus_price_eur_kwh"]
    expected = base["self_consumed_kwh"] * price + base["exported_kwh"] * surplus
    assert data["economics"]["annual_savings_eur"] == pytest.approx(expected, rel=0.01)


@respx.mock
def test_confidence_high_with_two_seasonal_priced_bills(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "bills": [
                {"month": 1, "kwh": 400, "energy_eur": 70, "amount_eur": 95},
                {"month": 7, "kwh": 300, "energy_eur": 50, "amount_eur": 75},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["confidence"]["level"] == "high"
    assert data["confidence"]["improvement_hints"] == []


@respx.mock
def test_confidence_hints_guide_the_user(respx_mock, client):
    mock_pvgis(respx_mock)
    # Solo consumo manual → media, con pista de subir facturas
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "annual_consumption_kwh": 4000,
            "electricity_price_eur_kwh": 0.2,
        },
    )
    data = resp.json()
    assert data["confidence"]["level"] == "medium"
    assert "add_priced_bills" in data["confidence"]["improvement_hints"]
    # Una sola factura con importe → media, pista de añadir meses distintos
    resp2 = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "bills": [{"month": 1, "kwh": 400, "energy_eur": 70, "amount_eur": 95}],
        },
    )
    data2 = resp2.json()
    assert data2["confidence"]["level"] == "medium"
    assert "add_seasonal_bills" in data2["confidence"]["improvement_hints"]


@respx.mock
def test_estimate_rate_limited_per_ip(respx_mock, client, monkeypatch):
    monkeypatch.setenv("SOLVENTO_ESTIMATE_RATELIMIT_MAX", "2")
    get_settings.cache_clear()
    from app.main import app

    mock_pvgis(respx_mock)
    with TestClient(app) as c:
        body = {"lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0}
        assert c.post("/api/solar-estimate", json=body).status_code == 200
        assert c.post("/api/solar-estimate", json=body).status_code == 200
        blocked = c.post("/api/solar-estimate", json=body)
        assert blocked.status_code == 429
    get_settings.cache_clear()


def test_upload_global_cap(client, monkeypatch):
    monkeypatch.setenv("SOLVENTO_UPLOAD_RATELIMIT_MAX", "10")
    monkeypatch.setenv("SOLVENTO_UPLOAD_RATELIMIT_GLOBAL_MAX", "2")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        for _ in range(2):
            r = c.post(
                "/api/parse-bill",
                files={"file": ("f.pdf", b"%PDF-1.4 x", "application/pdf")},
            )
            assert r.status_code == 200  # ilegible pero cuenta para el cupo
        blocked = c.post(
            "/api/parse-bill",
            files={"file": ("f.pdf", b"%PDF-1.4 x", "application/pdf")},
        )
        assert blocked.status_code == 429
        assert "cupo diario" in blocked.json()["detail"]
    get_settings.cache_clear()


@respx.mock
def test_solar_estimate_multiyear_economics(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "tilt_deg": 20,
            "azimuth_deg": 45,
            "annual_consumption_kwh": 4000,
            "installation_cost_eur": 7000,
            "electricity_price_eur_kwh": 0.20,
        },
    )
    assert resp.status_code == 200
    eco = resp.json()["economics"]
    assert eco["payback_years"] is not None
    assert eco["simple_payback_years"] is not None
    assert eco["savings_25yr_eur"] is not None
    assert len(eco["cumulative_cashflow"]) == 30
    a = eco["assumptions"]
    assert a["price_escalation_pct_per_year"] == 2.0
    assert a["inverter_replacement_year"] == 13
    assert a["inverter_replacement_cost_eur"] > 0
    assert a["om_eur_per_year"] == pytest.approx(70.0)  # 1% de 7000
    # Precio manual: sin corrección fiscal
    assert eco["marginal_price_factor"] == 1.0
    assert eco["effective_price_eur_kwh"] == 0.20
    # El año 13 refleja el reemplazo del inversor
    year13 = eco["cumulative_cashflow"][12]
    year12 = eco["cumulative_cashflow"][11]
    assert year13["net_eur"] < year12["net_eur"]
    # Escenarios de batería con métricas plurianuales
    scenarios = resp.json()["battery_analysis"]["scenarios"]
    assert all("npv_eur" in s for s in scenarios)


@respx.mock
def test_solar_estimate_subsidy_reduces_payback(respx_mock, client):
    mock_pvgis(respx_mock)
    base_body = {
        "lat": 42.88,
        "lon": -8.54,
        "peak_power_kwp": 5.0,
        "annual_consumption_kwh": 4000,
        "installation_cost_eur": 7000,
        "electricity_price_eur_kwh": 0.20,
    }
    base = client.post("/api/solar-estimate", json=base_body).json()["economics"]
    subsidized = client.post(
        "/api/solar-estimate", json={**base_body, "subsidy_eur": 2000}
    ).json()["economics"]
    assert subsidized["net_investment_eur"] == 5000.0
    assert subsidized["subsidy_eur"] == 2000.0
    assert subsidized["payback_years"] < base["payback_years"]


@respx.mock
def test_bills_price_gets_tax_factor(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "bills": [
                {"kwh": 300, "energy_eur": 45.0, "month": 1},
                {"kwh": 250, "energy_eur": 38.0, "month": 6},
            ],
        },
    )
    assert resp.status_code == 200
    eco = resp.json()["economics"]
    assert eco["electricity_price_source"] == "bills"
    # España: el término de energía va sin impuestos; el kWh evitado los incluye
    assert eco["marginal_price_factor"] == pytest.approx(1.27, abs=0.01)
    assert eco["effective_price_eur_kwh"] == pytest.approx(
        eco["electricity_price_eur_kwh"] * 1.27, rel=0.01
    )


def _history_bills(months_kwh):
    """Facturas con el mismo histórico mensual; cada una cubre un mes distinto."""
    history = [{"month": m, "kwh": kwh} for m, kwh in months_kwh.items()]
    return {m: {
        "kwh": months_kwh[m],
        "month": m,
        "consumption_history": history,
    } for m in months_kwh}


@respx.mock
def test_annual_consumption_is_deterministic_across_bill_subsets(respx_mock, client):
    mock_pvgis(respx_mock)
    # Histórico con 11 meses reales (sin febrero), suma 21.086 kWh
    real = {1: 2902, 3: 2350, 4: 1898, 5: 1620, 6: 1450, 7: 1810,
            8: 1210, 9: 1358, 10: 1738, 11: 2100, 12: 2650}
    per_month = _history_bills(real)

    def annual(months):
        resp = client.post("/api/solar-estimate", json={
            "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
            "bills": [per_month[m] for m in months],
        })
        assert resp.status_code == 200
        return resp.json()["consumption"]

    a = annual([1, 7])          # enero + julio
    b = annual([3, 7])          # marzo + julio
    c = annual([1, 3, 7])       # enero + marzo + julio
    assert a["annual_kwh"] == b["annual_kwh"] == c["annual_kwh"]
    assert a["seasonality_source"] == "bill_history"
    assert 2 in a["estimated_months"]
    # 11 reales (21.086) + febrero estimado ≈ 23.500-24.000, NO ≈ 25.600
    assert 23500 <= a["annual_kwh"] <= 24000


@respx.mock
def test_solar_estimate_accepts_annual_bill(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
            "bills": [{
                "kwh": 9600, "energy_eur": 1920, "total_eur": 2600,
                "start_date": "2025-01-01", "end_date": "2025-12-31",
            }],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    cons = data["consumption"]
    assert cons["seasonality_source"] == "annual_bill"
    assert cons["annual_kwh"] == pytest.approx(9600, abs=1)
    # La simulación horaria corre con el perfil estacional aguas abajo
    assert data["battery_analysis"] is not None
    assert data["economics"]["annual_savings_eur"] > 0


@respx.mock
def test_solar_estimate_accepts_large_annual_bill(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
            "bills": [{
                "kwh": 23712, "energy_eur": 4742, "total_eur": 6400,
                "start_date": "2025-01-01", "end_date": "2025-12-31",
            }],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["consumption"]["annual_kwh"] == pytest.approx(23712, abs=1)


@respx.mock
def test_auto_size_power_uses_recommended_kwp(respx_mock, client):
    mock_pvgis(respx_mock)
    body = {
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
        "annual_consumption_kwh": 12000, "electricity_price_eur_kwh": 0.20,
    }
    manual = client.post("/api/solar-estimate", json=body).json()
    auto = client.post("/api/solar-estimate", json={**body, "auto_size_power": True}).json()

    # Sin auto: analiza los 5 kWp pedidos (comportamiento actual)
    assert manual["analysis_power_kwp"] == 5.0
    # Con auto: analiza el ÓPTIMO ECONÓMICO del barrido, no el 5 kWp por defecto
    assert auto["requested_peak_power_kwp"] == 5.0
    assert auto["analysis_power_kwp"] == pytest.approx(
        auto["sizing_analysis"]["economic_optimum_kwp"], abs=0.01
    )
    # La producción escala linealmente con la potencia (mismo rendimiento/kWp)
    per_kwp_manual = manual["optimal"]["annual_production_kwh"] / 5.0
    per_kwp_auto = auto["optimal"]["annual_production_kwh"] / auto["analysis_power_kwp"]
    assert per_kwp_auto == pytest.approx(per_kwp_manual, rel=0.01)


@respx.mock
def test_auto_size_power_ignored_without_consumption(respx_mock, client):
    mock_pvgis(respx_mock)
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
    }).json()
    # Sin consumo no hay recomendación: se respeta la potencia pedida
    assert data["analysis_power_kwp"] == 5.0


@respx.mock
def test_annual_bill_confidence_is_high(respx_mock, client):
    mock_pvgis(respx_mock)
    real = {1: 2902, 2: 2640, 3: 2210, 4: 1874, 5: 1632, 6: 1542,
            7: 1810, 8: 1948, 9: 1765, 10: 2009, 11: 2430, 12: 2875}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    resp = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
        "bills": [{
            "kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
            "iee_eur": 22.5, "iva_rate": 0.21, "vat_base_eur": 6059.65,
            "contracted_power_kw": 14.49,
            "start_date": "2026-01-01", "end_date": "2026-12-31",
            "consumption_history": history,
        }],
    })
    assert resp.status_code == 200
    conf = resp.json()["confidence"]
    # Un año completo de meses reales (aunque sea 1 factura) → confianza alta
    assert conf["level"] == "high"
    assert conf["real_months"] == 12
    assert conf["improvement_hints"] == []  # ya no pide "otra factura"


def test_sizing_economic_optimum_beats_full_coverage():
    from app.main import _size_scenarios

    day = [0.0] * 24
    for h, v in zip(range(8, 18), [0.2, 0.4, 0.6, 0.75, 0.85, 0.85, 0.75, 0.6, 0.4, 0.2]):
        day[h] = v
    per_kwp_hourly = [day[:] for _ in range(12)]
    cons_profile = [[1.5] * 24 for _ in range(12)]

    scenarios, optimum_kwp, max_savings_kwp = _size_scenarios(
        per_kwp_hourly=per_kwp_hourly,
        cons_profile=cons_profile,
        price=0.26,
        surplus_price=0.06,
        export_scheme="capped_compensation",
        annual_consumption=sum(sum(m) for m in cons_profile) * 30.4,
        subsidy=0.0,
        om_pct=0.01,
        inverter_per_kwp=160.0,
        cost_fn=lambda kwp: 1200.0 * kwp,
        coverage_kwp=15.0,
        step_kwp=1.0,
    )
    assert optimum_kwp < max_savings_kwp
    by_kwp = {s["power_kwp"]: s for s in scenarios}
    opt_s = by_kwp[optimum_kwp]
    cov_s = by_kwp[max_savings_kwp]
    assert opt_s["roi_pct"] > cov_s["roi_pct"]
    assert opt_s["payback_years"] < cov_s["payback_years"]
    assert cov_s["annual_savings_eur"] > opt_s["annual_savings_eur"]
    assert opt_s["self_consumption_pct"] > cov_s["self_consumption_pct"]


@respx.mock
def test_grid_limits_note_when_recommended_exceeds_contracted(respx_mock, client):
    mock_pvgis(respx_mock)
    real = {1: 2902, 2: 2640, 3: 2210, 4: 1874, 5: 1632, 6: 1542,
            7: 1810, 8: 1948, 9: 1765, 10: 2009, 11: 2430, 12: 2875}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
        "bills": [{
            "kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
            "contracted_power_kw": 14.49,
            "start_date": "2026-01-01", "end_date": "2026-12-31",
            "consumption_history": history,
        }],
    }).json()
    gl = data["grid_limits"]
    assert gl is not None
    assert gl["contracted_power_kw"] == 14.49
    assert gl["tariff_threshold_kw"] == 15.0
    # La cobertura 100% (~20 kWp) supera potencia contratada y techo 2.0TD
    assert gl["exceeds_contracted"] is True
    assert gl["exceeds_tariff"] is True


@respx.mock
def test_no_grid_limits_note_for_small_system(respx_mock, client):
    mock_pvgis(respx_mock)
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 3.0,
        "annual_consumption_kwh": 3000, "electricity_price_eur_kwh": 0.20,
        "auto_size_power": False,
    }).json()
    # Sin facturas no hay potencia contratada conocida → sin aviso
    assert data["grid_limits"] is None


@respx.mock
def test_single_source_consistency_recommended_system(respx_mock, client):
    """REFACTOR K: ningún valor de tamaño/paneles/consumo diverge de la fuente única."""
    mock_pvgis(respx_mock)
    real = {1: 2902, 2: 2640, 3: 2210, 4: 1874, 5: 1632, 6: 1542,
            7: 1810, 8: 1948, 9: 1765, 10: 2009, 11: 2430, 12: 2875}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
        "bills": [{
            "kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
            "iee_eur": 22.5, "iva_rate": 0.21, "vat_base_eur": 6059.65,
            "contracted_power_kw": 14.49,
            "start_date": "2026-01-01", "end_date": "2026-12-31",
            "consumption_history": history,
        }],
    }).json()

    rs = data["recommended_system"]
    panels = data["panels"]
    eco = data["economics"]
    energy = data["annual_energy"]

    assert panels["total_kwp"] == rs["kwp"] == data["analysis_power_kwp"]
    assert panels["count"] == rs["panel_count"]
    assert panels["roof_area_m2"] == rs["roof_area_m2"]
    assert panels["production_to_consumption_pct"] == rs["production_to_consumption_pct"]
    assert rs["annual_production_kwh"] == pytest.approx(energy["production_kwh"], rel=0.001)
    assert rs["savings_per_year_eur"] == eco["annual_savings_eur"]
    assert rs["payback_years"] == eco["payback_years"]
    assert rs["roi_pct"] == eco["roi_pct"]
    assert rs["self_consumption_pct"] == energy["self_consumption_pct"]
    assert abs(panels["count"] * panels["panel_power_w"] / 1000 - panels["total_kwp"]) <= panels["panel_power_w"] / 1000 + 0.01
    assert data["consumption"]["annual_kwh"] == pytest.approx(sum(data["consumption"]["monthly_kwh"]), rel=0.001)
    assert rs["scenario_name"] == "economic_optimum"


@respx.mock
def test_panels_card_matches_recommended_optimum(respx_mock, client):
    """BUG G: la tarjeta de paneles usa el óptimo (7-8 kWp, ~35%), no la cobertura 100%."""
    mock_pvgis(respx_mock)
    real = {m: v for m, v in zip(range(1, 13),
            [2902, 2640, 2210, 1874, 1632, 1542, 1810, 1948, 1765, 2009, 2430, 2875])}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
        "bills": [{"kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
                   "start_date": "2026-01-01", "end_date": "2026-12-31",
                   "consumption_history": history}],
    }).json()
    panels = data["panels"]
    # Óptimo ~7-9 kWp → ~16-20 paneles, NO ~45; cobertura ~35%, NO ~100%
    assert panels["total_kwp"] < 12
    assert panels["count"] < 25
    assert panels["production_to_consumption_pct"] < 60
    # La cobertura 100% queda como 'needed_kwp' (mayor)
    assert panels["needed_kwp"] > panels["total_kwp"]


@respx.mock
def test_sizing_scenarios_flag_grid_oversize(respx_mock, client):
    """FLAG I: los escenarios que superan potencia contratada / 15 kW se marcan."""
    mock_pvgis(respx_mock)
    real = {m: v for m, v in zip(range(1, 13),
            [2902, 2640, 2210, 1874, 1632, 1542, 1810, 1948, 1765, 2009, 2430, 2875])}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
        "bills": [{"kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
                   "contracted_power_kw": 14.49,
                   "start_date": "2026-01-01", "end_date": "2026-12-31",
                   "consumption_history": history}],
    }).json()
    scenarios = data["sizing_analysis"]["scenarios"]
    by = {s["power_kwp"]: s for s in scenarios}
    cov = by[data["sizing_analysis"]["max_savings_kwp"]]
    opt = by[data["sizing_analysis"]["economic_optimum_kwp"]]
    # La cobertura 100% (~20 kWp) supera contratada y techo; el óptimo (~7-8) no
    assert cov["exceeds_contracted"] is True
    assert cov["exceeds_tariff"] is True
    assert opt["exceeds_tariff"] is False


def test_apply_postal_fallback_uses_province_centroid():
    """FEATURE J: si el geocodificado no da coordenadas, se usa el centroide del CP."""
    from app.main import _apply_postal_fallback
    parsed = {"postal_code": "15896", "country_code": "ES"}
    out = _apply_postal_fallback(parsed)
    assert 42.5 < out["lat"] < 43.8 and -9.5 < out["lon"] < -7.5
    assert out["location_confidence"] == "low"
    assert out["country_code"] == "ES"
    # CP que no mapea (francés) no aplica fallback
    assert _apply_postal_fallback({"postal_code": "75001", "country_code": "FR"}) == {
        "postal_code": "75001", "country_code": "FR"
    }


@respx.mock
def test_battery_incremental_payback_and_surplus_reconcile(respx_mock, client):
    """BUG L/M/N: payback incremental ≠ sistema; excedente reconcilia; params distintos."""
    mock_pvgis(respx_mock)
    real = {m: v for m, v in zip(range(1, 13),
            [2902, 2640, 2210, 1874, 1632, 1542, 1810, 1948, 1765, 2009, 2430, 2875])}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
        "bills": [{"kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
                   "start_date": "2026-01-01", "end_date": "2026-12-31",
                   "consumption_history": history}],
    }).json()
    ba = data["battery_analysis"]
    # BUG L: garantía y vida útil son parámetros DISTINTOS
    assert ba["battery_warranty_years"] == 10
    assert ba["battery_useful_life_years"] == 12
    assert ba["battery_warranty_years"] != ba["battery_useful_life_years"]
    scenarios = {s["battery_kwh"]: s for s in ba["scenarios"]}
    base = scenarios[0.0]
    for kwh, s in scenarios.items():
        # BUG M: excedente = producción × (1 − autoconsumo%) en TODA fila
        assert s["exported_kwh"] == pytest.approx(
            s["production_kwh"] * (1 - s["self_consumption_pct"] / 100), abs=s["production_kwh"] * 0.001 + 1
        )
        if kwh > 0:
            # BUG L: payback incremental presente y distinto del del sistema
            inc = s["battery_incremental_payback_years"]
            assert inc is not None
            assert inc != s["payback_years"]  # no es el whole-system (4.5/5.5)
            # BUG N: incremental == coste extra / ahorro extra (ratio simple)
            expected = round(
                (s["investment_eur"] - base["investment_eur"])
                / (s["annual_savings_eur"] - base["annual_savings_eur"]), 1)
            assert inc == pytest.approx(expected, abs=0.1)
    # decisión: con autoconsumo alto, batería no rentable → recomendación 0
    assert ba["recommended_battery_kwh"] == 0.0
    # techo estructural expuesto y positivo
    assert ba["max_battery_value_eur"] >= 0


class _FakeNominatim:
    def __init__(self, results):
        self.results = results
        self.last_query = None

    async def search(self, query, limit=5):
        self.last_query = query
        return self.results

    async def close(self):
        pass


def test_bill_location_query_uses_cp_and_municipio_not_province():
    from app.main import _bill_location_query
    q = _bill_location_query({
        "postal_code": "15896", "city": "Santiago de Compostela",
        "region": "A Coruña", "country_code": "ES",
    })
    assert "A Coruña" not in q  # BUG P: la provincia nunca es el objetivo
    assert "15896" in q and "Santiago de Compostela" in q and "España" in q


@respx.mock
def test_geocode_resolves_municipio_not_province(respx_mock, client):
    import asyncio
    from app.main import app, _enrich_bill_location, _haversine_km
    app.state.nominatim = _FakeNominatim([
        {"display_name": "Santiago de Compostela, A Coruña, España",
         "lat": 42.8805, "lon": -8.5457, "country_code": "ES"},
    ])
    parsed = {"postal_code": "15896", "city": "Santiago de Compostela",
              "region": "A Coruña", "country_code": "ES"}
    out = asyncio.run(_enrich_bill_location(dict(parsed)))
    assert "15896" in app.state.nominatim.last_query
    assert "A Coruña" not in app.state.nominatim.last_query
    # pin cerca de Santiago (~42.88, −8.54), NO A Coruña ciudad
    assert _haversine_km(out["lat"], out["lon"], 42.88, -8.54) < 25
    assert out["location_confidence"] == "high"


@respx.mock
def test_geocode_province_mismatch_falls_back_to_cp_centroid(respx_mock, client):
    import asyncio
    from app.main import app, _enrich_bill_location, _haversine_km
    # El geocoder devuelve Madrid (otra región) para un CP de A Coruña
    app.state.nominatim = _FakeNominatim([
        {"display_name": "Madrid, España", "lat": 40.4168, "lon": -3.7038, "country_code": "ES"},
    ])
    parsed = {"postal_code": "15896", "city": "Santiago de Compostela", "country_code": "ES"}
    out = asyncio.run(_enrich_bill_location(dict(parsed)))
    # Rechazado por distancia → centroide del CP (provincia 15 = A Coruña), baja confianza
    assert out["location_confidence"] == "low"
    assert _haversine_km(out["lat"], out["lon"], 43.36, -8.41) < 5


def test_seasonal_self_sufficiency_winter_below_summer():
    """FEATURE R: invierno < verano con producción estival y consumo plano."""
    from app.main import _seasonal_self_sufficiency
    prod = [
        [(2.0 if m in (5, 6, 7) else 0.2) if 9 <= h < 17 else 0.0 for h in range(24)]
        for m in range(12)
    ]
    cons = [[1.0] * 24 for _ in range(12)]
    winter, summer = _seasonal_self_sufficiency(prod, cons)
    assert winter is not None and summer is not None
    assert winter < summer


@respx.mock
def test_annual_energy_exposes_seasonal_self_sufficiency(respx_mock, client):
    mock_pvgis(respx_mock)
    real = {m: v for m, v in zip(range(1, 13),
            [2902, 2640, 2210, 1874, 1632, 1542, 1810, 1948, 1765, 2009, 2430, 2875])}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    e = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
        "bills": [{"kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
                   "start_date": "2026-01-01", "end_date": "2026-12-31",
                   "consumption_history": history}],
    }).json()["annual_energy"]
    assert e["winter_self_sufficiency_pct"] is not None
    assert e["summer_self_sufficiency_pct"] is not None
    for v in (e["winter_self_sufficiency_pct"], e["summer_self_sufficiency_pct"]):
        assert 0 <= v <= 100


@respx.mock
def test_subsidies_galicia_unverified_shows_no_amount(respx_mock, client):
    """FEATURE S: registro sin verificar → sin ayuda aplicada, estado 'unverified'."""
    mock_pvgis(respx_mock)
    real = {m: v for m, v in zip(range(1, 13),
            [2902, 2640, 2210, 1874, 1632, 1542, 1810, 1948, 1765, 2009, 2430, 2875])}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
        "postal_code": "15896",
        "bills": [{"kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
                   "start_date": "2026-01-01", "end_date": "2026-12-31",
                   "consumption_history": history}],
    }).json()
    sub = data["subsidies"]
    assert sub["region"] == "GALICIA"
    assert sub["status"] == "unverified"
    assert sub["applicable"] is False
    assert sub["grant_eur"] == 0.0
    # sin ayuda: payback con ayuda == sin ayuda en cada escenario
    for s in data["sizing_analysis"]["scenarios"]:
        assert s["subsidy_grant_eur"] == 0.0
        assert s["payback_with_subsidy_years"] == s["payback_years"]


@respx.mock
def test_subsidies_valid_record_applies_per_scenario(respx_mock, client, monkeypatch):
    """FEATURE S: con registro válido, la ayuda baja el payback por escenario y
    el óptimo recibe grant completo mientras el grande queda topado."""
    mock_pvgis(respx_mock)
    from app import subsidies as subsidies_mod

    valid = {
        "organismo": "INEGA", "convocatoria_id": "FV-2026",
        "eur_per_kwp": 300.0, "eur_per_kwh_battery": 200.0,
        "cap_absolute_eur": 4000.0, "cap_pct_of_cost": 0.40,
        "max_subsidised_kwp": 8.0,
        "window_start": "2026-01-01", "window_end": "2999-12-31",
        "status": "open", "source_url": "https://x", "verified_on": "2026-06-01",
        "irpf_deduction_pct": 0.20, "irpf_base_cap_eur": 3000.0, "irpf_years": 4,
    }
    monkeypatch.setattr(subsidies_mod, "get_region_record", lambda code, config=None: valid)

    real = {m: v for m, v in zip(range(1, 13),
            [2902, 2640, 2210, 1874, 1632, 1542, 1810, 1948, 1765, 2009, 2430, 2875])}
    history = [{"month": m, "kwh": k} for m, k in real.items()]
    data = client.post("/api/solar-estimate", json={
        "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0, "auto_size_power": True,
        "postal_code": "15896",
        "bills": [{"kwh": 25637, "energy_eur": 5350.51, "total_eur": 7332.17,
                   "start_date": "2026-01-01", "end_date": "2026-12-31",
                   "consumption_history": history}],
    }).json()
    sub = data["subsidies"]
    assert sub["applicable"] is True
    assert sub["grant_eur"] > 0
    sc = data["sizing_analysis"]
    by = {s["power_kwp"]: s for s in sc["scenarios"]}
    opt = by[sc["economic_optimum_kwp"]]
    cov = by[sc["max_savings_kwp"]]
    # ayuda por escenario reduce el payback y la inversión neta
    for s in (opt, cov):
        assert s["subsidy_grant_eur"] > 0
        assert s["net_investment_with_subsidy_eur"] < s["investment_eur"]
        assert s["payback_with_subsidy_years"] < s["payback_years"]
    # el óptimo (<8 kWp) recibe más ayuda por kWp instalado que el grande (topado)
    assert opt["subsidy_grant_eur"] / opt["power_kwp"] > cov["subsidy_grant_eur"] / cov["power_kwp"]
