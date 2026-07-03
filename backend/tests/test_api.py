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
        "bill_count": 0,
        "priced_bill_count": 0,
        "ignored_price_bill_count": 0,
        "days_covered": None,
        "monthly_kwh": None,
        "monthly_eur": None,
        "annual_amount_eur": 800.0,
        "observed_months": [],
        "seasonality_source": "manual_annual",
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
                {"kwh": 300, "amount_eur": 70, "start_date": "2026-01-01", "end_date": "2026-01-31"},
                {"kwh": 280, "amount_eur": 66, "start_date": "2026-02-01", "end_date": "2026-03-01"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    cons = data["consumption"]
    assert cons["source"] == "bills"
    # Enero/febrero se tratan como meses observados, no como promedio plano de días.
    assert cons["annual_kwh"] == pytest.approx(3261.8, rel=0.01)
    assert cons["monthly_kwh"] is not None
    assert cons["monthly_eur"] is not None
    assert cons["annual_amount_eur"] == pytest.approx(
        cons["annual_kwh"] * cons["avg_price_eur_kwh"], rel=0.01
    )
    assert cons["observed_months"] == [1, 2]
    assert cons["seasonality_source"] == "estimated_from_sampled_months"
    assert cons["bill_count"] == 2
    assert cons["priced_bill_count"] == 2
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
                {"month": 1, "kwh": 612, "amount_eur": 155.15},
                {"month": 6, "kwh": 344, "amount_eur": 94.04},
            ],
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    cons = data["consumption"]
    assert cons["annual_kwh"] == pytest.approx(5492.1, rel=0.01)
    assert cons["avg_price_eur_kwh"] == pytest.approx(0.2607, rel=0.001)
    assert 8 <= data["panels"]["count"] <= 12
    assert data["economics"]["annual_savings_eur"] > 500
    assert data["analysis_power_kwp"] == data["panels"]["total_kwp"]
    assert data["analysis_power_kwp"] != data["requested_peak_power_kwp"]

    mock_5kwp_production = pvcalc_response()["outputs"]["totals"]["fixed"]["E_y"]
    expected_production = mock_5kwp_production * data["analysis_power_kwp"] / 5.0
    assert data["optimal"]["annual_production_kwh"] == pytest.approx(
        expected_production, rel=0.001
    )
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

    # El coste estimado, la simulación horaria y la amortización usan la potencia recomendada.
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


@respx.mock
def test_parse_bill_accepts_image_with_openai(respx_mock, openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "kwh": 210.0,
                        "amount_eur": 58.0,
                        "month": 6,
                        "start_date": "2026-06-01",
                        "end_date": "2026-06-30",
                        "country_code": "ES",
                        "country_name": "España",
                        "language": "es",
                        "warnings": [],
                    }
                ),
            },
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
        return_value=Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "kwh": 245.7,
                        "amount_eur": 83.42,
                        "month": 5,
                        "start_date": "2026-05-01",
                        "end_date": "2026-05-31",
                        "country_code": "FR",
                        "country_name": "France",
                        "language": "fr",
                        "warnings": [],
                    }
                ),
            },
        )
    )

    resp = openai_client.post(
        "/api/parse-bill",
        files={"file": ("facture.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["kwh"] == 245.7
    assert data["amount_eur"] == 83.42
    assert data["country_code"] == "FR"
    assert data["language"] == "fr"
    assert data["parser"] == "openai"

    payload = json.loads(respx_mock.calls.last.request.content)
    assert payload["model"] == "gpt-5.5"
    content = payload["input"][1]["content"]
    assert content[0]["type"] == "input_file"
    assert content[0]["filename"] == "facture.pdf"
    assert content[0]["file_data"].startswith("data:application/pdf;base64,")
    assert payload["text"]["format"]["type"] == "json_schema"
    assert "supply_address" in payload["text"]["format"]["schema"]["required"]


@respx.mock
def test_parse_bill_geocodes_openai_supply_address(respx_mock, openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "kwh": 245.7,
                        "amount_eur": 83.42,
                        "month": 7,
                        "start_date": "2026-07-01",
                        "end_date": "2026-07-31",
                        "country_code": "FR",
                        "country_name": "France",
                        "supply_address": "10 Rue de Rivoli",
                        "postal_code": "75001",
                        "city": "Paris",
                        "region": "Île-de-France",
                        "language": "fr",
                        "warnings": [],
                    }
                ),
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
    assert "10 Rue de Rivoli" in geocode_call.request.url.params["q"]
    assert "75001" in geocode_call.request.url.params["q"]


@respx.mock
def test_parse_bill_ignores_non_european_geocode_candidate(respx_mock, openai_client):
    respx_mock.post("https://api.openai.com/v1/responses").mock(
        return_value=Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "kwh": 245.7,
                        "amount_eur": 83.42,
                        "month": 7,
                        "start_date": "2026-07-01",
                        "end_date": "2026-07-31",
                        "country_code": "FR",
                        "country_name": "France",
                        "supply_address": "10 Rue de Rivoli",
                        "postal_code": "75001",
                        "city": "Paris",
                        "region": "Île-de-France",
                        "language": "fr",
                        "warnings": [],
                    }
                ),
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
        return_value=Response(
            200,
            json={
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "kwh": 198.4,
                        "amount_eur": 64.2,
                        "month": 2,
                        "start_date": "2026-02-01",
                        "end_date": "2026-02-28",
                        "country_code": "FR",
                        "country_name": "France",
                        "language": "fr",
                        "warnings": [],
                    }
                ),
            },
        )
    )

    resp = standard_openai_client.post(
        "/api/parse-bill",
        files={"file": ("facture.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
    )

    assert resp.status_code == 200
    assert resp.json()["parser"] == "openai"
    assert respx_mock.calls.call_count == 1


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
                {"month": 1, "kwh": 400, "amount_eur": 95},
                {"month": 7, "kwh": 300, "amount_eur": 75},
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
            "bills": [{"month": 1, "kwh": 400, "amount_eur": 95}],
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
