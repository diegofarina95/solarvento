import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SOLVENTO_", extra="ignore")

    # Precio de la electricidad por defecto (€/kWh), configurable por el usuario en cada cálculo
    electricity_price_eur_kwh: float = 0.15
    # Potencia por panel por defecto (W)
    panel_power_w: int = 450
    # Batería doméstica: la GARANTÍA (típico 10 años) y la VIDA ÚTIL real (LFP
    # ~12–15 años / 4.000–6.000 ciclos) son cosas distintas; no se fusionan. La
    # decisión de recomendar batería se toma contra la vida útil.
    battery_warranty_years: int = 10
    battery_useful_life_years: int = 12
    # TTL de la caché de PVGIS (segundos). Las coordenadas dan siempre el mismo
    # resultado, así que el TTL es largo por defecto: 90 días.
    cache_ttl_seconds: int = 90 * 24 * 3600
    cache_db_path: str = "pvgis_cache.db"
    pricing_cache_ttl_seconds: int = 7 * 24 * 3600
    pricing_cache_db_path: str = "pricing_cache.db"
    pricing_feed_url: str | None = None

    # Límite de subidas de factura: por equipo (IP) y global diario
    # (cada subida es una llamada de pago a OpenAI)
    upload_ratelimit_max: int = 10
    upload_ratelimit_global_max: int = 100
    upload_ratelimit_window_seconds: int = 24 * 3600
    upload_ratelimit_db_path: str = "upload_ratelimit.db"
    # Límite de cálculos por equipo (cada uno lanza hasta 4 llamadas a PVGIS)
    estimate_ratelimit_max: int = 60
    estimate_ratelimit_global_max: int = 1000

    # Parser IA opcional de facturas. Si no hay clave, se usa solo el extractor local.
    openai_api_key: str | None = None
    standard_openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str = "https://api.openai.com/v1"
    openai_bill_parser_model: str = "gpt-5.5"
    openai_bill_parser_timeout_seconds: float = 60.0

    pvgis_base_url: str = "https://re.jrc.ec.europa.eu/api/v5_2"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    http_user_agent: str = "SolVento/0.1 (solar calculator; diego.farina@gimo.co.uk)"
    http_timeout_seconds: float = 30.0
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trusted_proxy_hosts: str = "127.0.0.1,::1"

    @property
    def resolved_openai_api_key(self) -> str | None:
        """Accept SolVento-specific config and the standard OpenAI env var."""
        if self.openai_api_key and self.openai_api_key.strip():
            return self.openai_api_key.strip()
        if self.standard_openai_api_key and self.standard_openai_api_key.strip():
            return self.standard_openai_api_key.strip()
        standard_key = os.getenv("OPENAI_API_KEY")
        if standard_key and standard_key.strip():
            return standard_key.strip()
        return None

    @property
    def cors_allow_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def trusted_proxy_host_set(self) -> set[str]:
        return {host.strip() for host in self.trusted_proxy_hosts.split(",") if host.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
