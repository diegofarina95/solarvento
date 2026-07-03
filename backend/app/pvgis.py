"""Cliente de la API pública PVGIS v5.2 (Comisión Europea).

- PVcalc: producción fotovoltaica (con optimalangles=1 devuelve también los
  ángulos óptimos de inclinación y azimut).
- seriescalc: producción horaria (se promedia a un día tipo 12x24).

Convención de azimut de PVGIS: 0 = Sur, 90 = Oeste, -90 = Este, ±180 = Norte.
Las coordenadas se redondean a 2 decimales para la caché (~1 km, misma celda
de datos de PVGIS).
"""

import asyncio
from typing import Any

import httpx

from .cache import TTLCache


class PVGISError(Exception):
    """Error al consultar PVGIS (servicio caído, ubicación sin datos, etc.)."""


class PVGISClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout: float = 30.0,
        cache: TTLCache | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self._client = httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": user_agent}
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        cache_key = f"{endpoint}?" + "&".join(
            f"{k}={params[k]}" for k in sorted(params)
        )
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        # PVGIS corta conexiones esporádicamente: un reintento evita fallos espurios
        last_exc: httpx.HTTPError | None = None
        resp = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(0.5 * attempt)
            try:
                resp = await self._client.get(f"{self.base_url}/{endpoint}", params=params)
                break
            except httpx.HTTPError as exc:
                last_exc = exc
        if resp is None:
            raise PVGISError(
                f"No se pudo conectar con PVGIS: {last_exc or 'error de red'}"
            ) from last_exc

        if resp.status_code == 400:
            # PVGIS devuelve 400 con un mensaje para ubicaciones sin datos (p.ej. océano)
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except ValueError:
                detail = resp.text[:200]
            raise PVGISError(f"PVGIS no tiene datos para esa ubicación: {detail}")
        if resp.status_code != 200:
            raise PVGISError(f"PVGIS respondió con error HTTP {resp.status_code}")

        data = resp.json()
        if self.cache is not None:
            self.cache.set(cache_key, data)
        return data

    async def pvcalc(
        self,
        lat: float,
        lon: float,
        peakpower_kwp: float,
        loss_pct: float,
        angle: float | None = None,
        aspect: float | None = None,
        optimal_angles: bool = False,
    ) -> dict[str, Any]:
        """Llama a PVcalc y devuelve la respuesta parseada (ver parse_pvcalc)."""
        params: dict[str, Any] = {
            "lat": round(lat, 2),
            "lon": round(lon, 2),
            "peakpower": peakpower_kwp,
            "loss": loss_pct,
            "outputformat": "json",
        }
        if optimal_angles:
            params["optimalangles"] = 1
        else:
            params["angle"] = angle if angle is not None else 35
            params["aspect"] = aspect if aspect is not None else 0
        raw = await self._get("PVcalc", params)
        return parse_pvcalc(raw)

    async def hourly_profile(
        self,
        lat: float,
        lon: float,
        peakpower_kwp: float,
        loss_pct: float,
        angle: float,
        aspect: float,
    ) -> list[list[float]]:
        """Producción horaria media por mes (seriescalc, año de referencia 2020).

        Devuelve una matriz 12x24: kWh producidos en la hora h de un día medio
        del mes m. Se usa para simular autoconsumo y baterías.
        """
        params = {
            "lat": round(lat, 2),
            "lon": round(lon, 2),
            "peakpower": peakpower_kwp,
            "loss": loss_pct,
            "angle": angle,
            "aspect": aspect,
            "pvcalculation": 1,
            "startyear": 2020,
            "endyear": 2020,
            "outputformat": "json",
        }
        raw = await self._get("seriescalc", params)
        return parse_seriescalc(raw)



def parse_pvcalc(raw: dict[str, Any]) -> dict[str, Any]:
    """Extrae de la respuesta de PVcalc los campos que usa la app.

    Devuelve:
      - slope_deg / azimuth_deg: ángulos usados (los óptimos si optimalangles=1)
      - monthly: [{month, production_kwh, irradiation_kwh_m2, hsp_daily}] x12
      - annual_production_kwh, annual_irradiation_kwh_m2
      - hsp_daily_avg: horas de sol pico medias diarias (H(i)_d anual)
    """
    try:
        mounting = raw["inputs"]["mounting_system"]["fixed"]
        monthly_raw = raw["outputs"]["monthly"]["fixed"]
        totals = raw["outputs"]["totals"]["fixed"]
    except (KeyError, TypeError) as exc:
        raise PVGISError(f"Respuesta de PVcalc con formato inesperado: {exc}") from exc

    monthly = [
        {
            "month": m["month"],
            "production_kwh": m["E_m"],
            "irradiation_kwh_m2": m["H(i)_m"],
            "hsp_daily": m["H(i)_d"],
        }
        for m in sorted(monthly_raw, key=lambda m: m["month"])
    ]
    return {
        "slope_deg": float(mounting["slope"]["value"]),
        "azimuth_deg": float(mounting["azimuth"]["value"]),
        "monthly": monthly,
        "annual_production_kwh": totals["E_y"],
        "annual_irradiation_kwh_m2": totals["H(i)_y"],
        "hsp_daily_avg": totals["H(i)_d"],
        "elevation_m": raw["inputs"]["location"].get("elevation"),
    }


def parse_seriescalc(raw: dict[str, Any]) -> list[list[float]]:
    """Promedia la serie horaria de seriescalc a una matriz 12x24 en kWh.

    'P' viene en W; una lectura por hora, así que P/1000 ≈ kWh de esa hora.
    """
    try:
        rows = raw["outputs"]["hourly"]
    except (KeyError, TypeError) as exc:
        raise PVGISError(f"Respuesta de seriescalc con formato inesperado: {exc}") from exc

    sums = [[0.0] * 24 for _ in range(12)]
    counts = [[0] * 24 for _ in range(12)]
    for row in rows:
        # formato de time: 'YYYYMMDD:HHMM'
        t = row["time"]
        month = int(t[4:6]) - 1
        hour = int(t[9:11])
        sums[month][hour] += float(row["P"]) / 1000.0
        counts[month][hour] += 1

    profile = []
    for m in range(12):
        if any(c == 0 for c in counts[m]):
            raise PVGISError(f"seriescalc no devolvió datos completos para el mes {m + 1}")
        profile.append([round(sums[m][h] / counts[m][h], 4) for h in range(24)])
    return profile


