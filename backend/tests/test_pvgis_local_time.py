"""Conversión del perfil horario PVGIS de UTC a hora local de reloj.

PVGIS seriescalc devuelve la serie en UTC; el simulador casa producción y
consumo por índice horario, y el perfil de consumo está en hora de reloj.
Sin conversión, la producción queda 1-2 h "antes" que el consumo: se
subestima el autoconsumo directo y se sobreestima el beneficio de la batería.

La conversión es el huso español con DST a resolución de mes (nov-mar +1,
abr-oct +2; Canarias 0/+1). El matiz por longitud (Santiago más tarde que
Madrid) ya viene dentro de la serie UTC y el desplazamiento común lo preserva.
"""

import pytest

from app.profiles import consumption_profile
from app.pvgis import PVGISClient, spain_utc_offset_hours, to_local_clock
from app.simulation import simulate_self_consumption

MADRID = (40.42, -3.70)
SANTIAGO = (42.88, -8.54)
LAS_PALMAS = (28.12, -15.43)

JAN, MAR, APR, JUL, OCT, NOV = 0, 2, 3, 6, 9, 10


def _pulse_profile(hour: int) -> list[list[float]]:
    """Matriz 12x24 con toda la producción del día en una sola hora UTC."""
    return [[1.0 if h == hour else 0.0 for h in range(24)] for _ in range(12)]


def _center_of_mass(row: list[float]) -> float:
    total = sum(row)
    return sum(h * v for h, v in zip(range(24), row)) / total


# --- offset por mes -----------------------------------------------------------


def test_peninsula_offset_invierno_y_verano():
    lat, lon = MADRID
    assert spain_utc_offset_hours(lat, lon, JAN) == 1
    assert spain_utc_offset_hours(lat, lon, MAR) == 1  # el DST arranca a final de marzo
    assert spain_utc_offset_hours(lat, lon, APR) == 2
    assert spain_utc_offset_hours(lat, lon, JUL) == 2
    assert spain_utc_offset_hours(lat, lon, OCT) == 2  # el DST acaba a final de octubre
    assert spain_utc_offset_hours(lat, lon, NOV) == 1


def test_canarias_offset_invierno_y_verano():
    lat, lon = LAS_PALMAS
    assert spain_utc_offset_hours(lat, lon, JAN) == 0
    assert spain_utc_offset_hours(lat, lon, JUL) == 1


# --- rotación de la matriz ----------------------------------------------------


def test_pico_de_madrid_cae_en_hora_de_reloj_13_14():
    # Mediodía solar de Madrid ≈ 12:15 UTC (bin 12) → 13 de reloj en enero,
    # 14 en julio. Este era el bug: sin conversión se quedaba en el bin 12.
    local = to_local_clock(_pulse_profile(12), *MADRID)
    assert local[JAN].index(max(local[JAN])) == 13
    assert local[JUL].index(max(local[JUL])) == 14


def test_canarias_pico_en_hora_de_reloj_correcta():
    local = to_local_clock(_pulse_profile(12), *LAS_PALMAS)
    assert local[JAN].index(max(local[JAN])) == 12
    assert local[JUL].index(max(local[JUL])) == 13


def test_la_energia_se_conserva_al_rotar():
    profile = [[float(h) for h in range(24)] for _ in range(12)]
    local = to_local_clock(profile, *MADRID)
    for m in range(12):
        assert sum(local[m]) == pytest.approx(sum(profile[m]))


def test_santiago_mas_tarde_en_reloj_que_madrid():
    # El mediodía solar en UTC ya depende de la longitud: Madrid ≈ 12:15,
    # Santiago ≈ 12:34. Repartimos la producción entre los bines 12 y 13 según
    # esa fracción y comprobamos que, tras pasar a reloj, el centro de masas
    # de Santiago sigue cayendo MÁS TARDE que el de Madrid.
    def noon_split(fraction_into_bin_13: float) -> list[list[float]]:
        row = [0.0] * 24
        row[12] = 1.0 - fraction_into_bin_13
        row[13] = fraction_into_bin_13
        return [row[:] for _ in range(12)]

    madrid_local = to_local_clock(noon_split(0.25), *MADRID)
    santiago_local = to_local_clock(noon_split(0.57), *SANTIAGO)
    assert _center_of_mass(santiago_local[JUL]) > _center_of_mass(madrid_local[JUL])


# --- propagación al balance ---------------------------------------------------


def test_la_conversion_sube_autoconsumo_directo_y_baja_valor_de_bateria():
    # Campana solar realista (luz 5-19 UTC, pico 12) contra el perfil de punta
    # de tarde, el hogar español típico. En reloj la producción llega hasta más
    # tarde: sube el autoconsumo directo y baja lo que añade la batería. Este
    # era el sesgo del bug: sin conversión se sobrevendía la batería. (En un
    # perfil home_day el efecto es ~neutro; la dirección se fija con evening.)
    bell = [max(0.0, 1.0 - abs(h - 12) / 7) for h in range(24)]
    utc_production = [bell[:] for _ in range(12)]
    local_production = to_local_clock(utc_production, *MADRID)
    consumption = consumption_profile(3500.0, country_code="ES", occupancy_profile="evening")

    before = simulate_self_consumption(utc_production, consumption)
    after = simulate_self_consumption(local_production, consumption)
    assert after["direct_kwh"] > before["direct_kwh"]

    battery_before = simulate_self_consumption(utc_production, consumption, 5.0)
    battery_after = simulate_self_consumption(local_production, consumption, 5.0)
    assert battery_after["battery_kwh"] < battery_before["battery_kwh"]


# --- cableado: hourly_profile devuelve ya la matriz en hora local --------------


@pytest.mark.asyncio
async def test_hourly_profile_aplica_la_conversion(monkeypatch):
    def synthetic_seriescalc() -> dict:
        rows = []
        for month in range(1, 13):
            for hour in range(24):
                rows.append(
                    {
                        "time": f"2020{month:02d}01:{hour:02d}00",
                        "P": 1000.0 if hour == 12 else 0.0,
                    }
                )
        return {"outputs": {"hourly": rows}}

    client = PVGISClient(base_url="https://example.invalid", user_agent="test")

    async def fake_get(endpoint, params):
        return synthetic_seriescalc()

    monkeypatch.setattr(client, "_get", fake_get)
    profile = await client.hourly_profile(
        *MADRID, peakpower_kwp=1.0, loss_pct=11.0, angle=35, aspect=0
    )
    await client.close()
    assert profile[JAN].index(max(profile[JAN])) == 13
    assert profile[JUL].index(max(profile[JUL])) == 14
