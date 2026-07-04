"""Test de integración contra la API real de PVGIS.

Ubicación de referencia: Santiago de Compostela (lat 42.88, lon -8.54).
Se ejecuta con: uv run pytest -m integration
"""

import pytest

from app.pvgis import PVGISClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

LAT, LON = 42.88, -8.54
PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2"
UA = "SolarVento/0.1 (integration test; diego.farina@gimo.co.uk)"


@pytest.fixture
async def client():
    c = PVGISClient(base_url=PVGIS_URL, user_agent=UA)
    yield c
    await c.close()


async def test_pvcalc_optimal_angles_santiago(client):
    result = await client.pvcalc(
        LAT, LON, peakpower_kwp=5.0, loss_pct=14.0, optimal_angles=True
    )

    # Ángulos óptimos razonables para Galicia: inclinación ~35°, azimut ~0 (sur)
    assert 25 <= result["slope_deg"] <= 45
    assert -20 <= result["azimuth_deg"] <= 20

    # Producción anual de 5 kWp en Santiago: en torno a 6400 kWh
    assert 5000 < result["annual_production_kwh"] < 8000

    # 12 meses ordenados con producción e irradiación positivas
    assert [m["month"] for m in result["monthly"]] == list(range(1, 13))
    assert all(m["production_kwh"] > 0 for m in result["monthly"])
    assert all(m["hsp_daily"] > 0 for m in result["monthly"])

    # HSP medias diarias anuales: entre 3 y 6 en Galicia
    assert 3 < result["hsp_daily_avg"] < 6


async def test_pvcalc_user_angles_santiago(client):
    result = await client.pvcalc(
        LAT, LON, peakpower_kwp=5.0, loss_pct=14.0, angle=20, aspect=45
    )
    assert result["slope_deg"] == 20
    assert result["azimuth_deg"] == 45
    # Con ángulos subóptimos la producción debe seguir siendo plausible
    assert 4000 < result["annual_production_kwh"] < 8000


async def test_hourly_profile_santiago(client):
    profile = await client.hourly_profile(
        LAT, LON, peakpower_kwp=5.0, loss_pct=14.0, angle=35, aspect=0
    )
    assert len(profile) == 12
    assert all(len(month) == 24 for month in profile)
    # De noche no se produce; a mediodía de julio sí (bastante)
    assert profile[6][2] == 0.0
    assert profile[6][12] > 1.5
    # La suma anual debe cuadrar (a grandes rasgos) con la producción de PVcalc
    from app.profiles import DAYS_PER_MONTH

    annual = sum(sum(profile[m]) * DAYS_PER_MONTH[m] for m in range(12))
    assert 5000 < annual < 8000

