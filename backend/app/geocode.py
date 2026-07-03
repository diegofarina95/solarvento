"""Geocoding con Nominatim (OpenStreetMap).

Política de uso de Nominatim: máximo 1 petición/segundo y User-Agent
identificable. El rate limit se aplica con un lock global del proceso.
"""

import asyncio
import time

import httpx


class GeocodeError(Exception):
    pass


class NominatimClient:
    def __init__(self, base_url: str, user_agent: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": user_agent}
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        async with self._lock:
            wait = 1.0 - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

        try:
            resp = await self._client.get(
                f"{self.base_url}/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": limit,
                    "addressdetails": 1,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise GeocodeError(f"Error consultando Nominatim: {exc}") from exc

        return [
            {
                "display_name": item["display_name"],
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "country_code": item.get("address", {}).get("country_code", "").upper()
                or None,
            }
            for item in resp.json()
        ]
