"""SolVento — API de cálculo solar fotovoltaico sobre PVGIS."""

import asyncio
import ipaddress
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import bills as bills_mod
from . import calculations, cashflow, simulation
from .cache import TTLCache
from .config import get_settings
from .geocode import GeocodeError, NominatimClient
from .openai_bills import OpenAIBillParser
from .pricing import (
    PricingService,
    calculate_system_cost,
    country_for_coordinates,
    ensure_european_location,
    normalize_country_code,
)
from .profiles import DAYS_PER_MONTH, consumption_profile
from .pvgis import PVGISClient, PVGISError
from .ratelimit import RateLimiter
from .schemas import (
    GeocodeResult,
    OptimalAnglesResponse,
    ParsedBill,
    SolarEstimateRequest,
    SolarEstimateResponse,
)

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    cache = TTLCache(settings.cache_db_path, settings.cache_ttl_seconds)
    pricing_cache = TTLCache(
        settings.pricing_cache_db_path,
        settings.pricing_cache_ttl_seconds,
    )
    app.state.pvgis = PVGISClient(
        base_url=settings.pvgis_base_url,
        user_agent=settings.http_user_agent,
        timeout=settings.http_timeout_seconds,
        cache=cache,
    )
    app.state.nominatim = NominatimClient(
        base_url=settings.nominatim_base_url,
        user_agent=settings.http_user_agent,
        timeout=settings.http_timeout_seconds,
    )
    app.state.pricing = PricingService(
        pricing_cache,
        feed_url=settings.pricing_feed_url,
        timeout=settings.http_timeout_seconds,
    )
    openai_api_key = settings.resolved_openai_api_key
    app.state.openai_bill_parser = (
        OpenAIBillParser(
            openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_bill_parser_model,
            timeout=settings.openai_bill_parser_timeout_seconds,
        )
        if openai_api_key
        else None
    )
    app.state.bill_parser_mode = "openai" if openai_api_key else "local"
    app.state.upload_limiter = RateLimiter(
        settings.upload_ratelimit_db_path,
        limit=settings.upload_ratelimit_max,
        window_seconds=settings.upload_ratelimit_window_seconds,
        global_limit=settings.upload_ratelimit_global_max,
        table="upload_events",
    )
    app.state.invalid_upload_limiter = RateLimiter(
        settings.upload_ratelimit_db_path,
        limit=max(settings.upload_ratelimit_max * 3, settings.upload_ratelimit_max),
        window_seconds=settings.upload_ratelimit_window_seconds,
        global_limit=None,
        table="invalid_upload_events",
    )
    app.state.estimate_limiter = RateLimiter(
        settings.upload_ratelimit_db_path,
        limit=settings.estimate_ratelimit_max,
        window_seconds=settings.upload_ratelimit_window_seconds,
        global_limit=settings.estimate_ratelimit_global_max,
        table="estimate_events",
    )
    yield
    await app.state.pvgis.close()
    await app.state.nominatim.close()
    await app.state.pricing.close()
    if app.state.openai_bill_parser:
        await app.state.openai_bill_parser.close()
    app.state.upload_limiter.close()
    app.state.invalid_upload_limiter.close()
    app.state.estimate_limiter.close()
    cache.close()


app = FastAPI(title="SolVento", version="0.1.0", lifespan=lifespan)

# En desarrollo el frontend corre en el puerto de Vite; en producción se sirve
# desde este mismo proceso y CORS no interviene.
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "bill_parser": getattr(app.state, "bill_parser_mode", "local")}


@app.get("/api/geocode", response_model=list[GeocodeResult])
async def geocode(q: str = Query(..., min_length=2, max_length=200)):
    try:
        return _european_geocode_results(await app.state.nominatim.search(q))
    except GeocodeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/optimal-angles", response_model=OptimalAnglesResponse)
async def optimal_angles(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    if not ensure_european_location(lat, lon):
        raise HTTPException(
            status_code=422,
            detail=(
                "Actualmente SolVento solo ofrece estimaciones para ubicaciones "
                "europeas cubiertas por PVGIS."
            ),
        )
    try:
        result = await app.state.pvgis.pvcalc(
            lat, lon, peakpower_kwp=1.0, loss_pct=14.0, optimal_angles=True
        )
    except PVGISError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OptimalAnglesResponse(
        lat=round(lat, 2),
        lon=round(lon, 2),
        slope_deg=result["slope_deg"],
        azimuth_deg=result["azimuth_deg"],
        annual_production_per_kwp=result["annual_production_kwh"],
        hsp_daily_avg=result["hsp_daily_avg"],
    )


_PDF_TYPES = ("application/pdf", "application/x-pdf")
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _client_ip(request: Request) -> str:
    settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    trusted_hosts = settings.trusted_proxy_host_set
    if forwarded and _is_trusted_proxy(client_host, trusted_hosts):
        return forwarded.split(",")[0].strip()
    return client_host


def _is_trusted_proxy(host: str, trusted_hosts: set[str]) -> bool:
    if "*" in trusted_hosts:
        return True
    if host in trusted_hosts:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    for trusted in trusted_hosts:
        try:
            if ip in ipaddress.ip_network(trusted, strict=False):
                return True
        except ValueError:
            continue
    return False


def _reject_invalid_upload(request: Request, detail: str) -> None:
    limiter: RateLimiter = app.state.invalid_upload_limiter
    allowed, _blocked_by = limiter.check_and_record(_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos inválidos de subida. Inténtalo más tarde.",
        )
    raise HTTPException(status_code=422, detail=detail)


@app.post("/api/parse-bill", response_model=ParsedBill)
async def parse_bill(request: Request, file: UploadFile, website: str | None = Form(None)):
    if website:
        _reject_invalid_upload(request, "Subida no válida")
    content_type = (file.content_type or "").lower()
    is_pdf = content_type in _PDF_TYPES or content_type == ""
    is_image = content_type in _IMAGE_TYPES
    if not (is_pdf or is_image):
        _reject_invalid_upload(request, "Sube la factura en PDF o imagen (JPG/PNG)")
    if file.size is not None and file.size > _MAX_UPLOAD_BYTES:
        _reject_invalid_upload(request, "El archivo supera los 10 MB")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        _reject_invalid_upload(request, "El archivo supera los 10 MB")

    openai_parser: OpenAIBillParser | None = app.state.openai_bill_parser

    # Las imágenes solo las entiende OpenAI (pypdf no lee fotos): sin clave,
    # se pide un PDF en su lugar.
    if is_image and openai_parser is None:
        _reject_invalid_upload(
            request,
            "Las fotos de factura no están disponibles ahora; sube la factura en PDF.",
        )

    limiter: RateLimiter = app.state.upload_limiter
    allowed, blocked_by = limiter.check_and_record(_client_ip(request))
    if not allowed:
        detail = (
            "El servicio de lectura de facturas ha alcanzado su cupo diario. "
            "Introduce los datos a mano o inténtalo mañana."
            if blocked_by == "global"
            else f"Has alcanzado el límite de {limiter.limit} facturas subidas. "
            "Introduce el resto de datos a mano o inténtalo más tarde."
        )
        raise HTTPException(status_code=429, detail=detail)

    remote = None
    if openai_parser:
        parser_type = content_type if is_image else "application/pdf"
        try:
            remote = await openai_parser.parse_pdf(content, file.filename, parser_type)
        except Exception as exc:
            # Cualquier fallo del parser remoto (red, JSON inesperado, cuota…)
            # degrada al extractor local en vez de romper la petición.
            logger.warning("OpenAI bill parser failed; falling back to local parser: %s", exc)
            remote = None

    if is_image:
        # No hay extractor local para imágenes: se devuelve lo que OpenAI sacara
        # (aunque falte el consumo) para que el usuario lo complete a mano.
        if remote is not None:
            return await _enrich_bill_location(remote)
        return _unreadable_bill(
            "No se pudo leer la imagen de la factura; introduce los datos a mano."
        )

    # pypdf es CPU-bound: fuera del event loop para no bloquear otras peticiones
    try:
        local = await run_in_threadpool(bills_mod.parse_bill_pdf, content)
    except bills_mod.BillParseError as exc:
        if remote is not None:
            return await _enrich_bill_location(remote)
        # Contrato uniforme con y sin OpenAI: factura ilegible → 200 con avisos
        # y campos vacíos para completar a mano (el 422 se reserva para
        # peticiones inválidas: tipo de archivo, tamaño…).
        return _unreadable_bill(str(exc))

    if remote is not None:
        if local.get("kwh") is None and remote.get("kwh") is not None:
            return await _enrich_bill_location(remote)
        _merge_bill_context(local, remote)
        local["warnings"] = _dedupe_strings(
            [*local.get("warnings", []), *remote.get("warnings", [])]
        )
        local["parser"] = "local+openai"
    return await _enrich_bill_location(local)


def _unreadable_bill(reason: str) -> dict:
    """Respuesta 200 para facturas ilegibles: fila vacía + aviso."""
    return {
        "kwh": None,
        "amount_eur": None,
        "energy_eur": None,
        "fixed_eur": None,
        "taxes_eur": None,
        "total_eur": None,
        "currency": None,
        "parser": "local",
        "warnings": [reason],
    }


def _merge_bill_context(target: dict, source: dict | None) -> None:
    """Completa en target los campos que el otro parser sí extrajo."""
    if not source:
        return
    for key in (
        "amount_eur",
        "energy_eur",
        "fixed_eur",
        "taxes_eur",
        "power_eur",
        "iee_eur",
        "iva_eur",
        "iva_rate",
        "vat_base_eur",
        "consumption_history",
        "total_eur",
        "currency",
        "month",
        "start_date",
        "end_date",
        "country_code",
        "country_name",
        "language",
        "supply_address",
        "postal_code",
        "city",
        "region",
        "location_label",
        "lat",
        "lon",
    ):
        if target.get(key) in (None, "", []) and source.get(key) not in (None, "", []):
            target[key] = source[key]


def _bill_location_query(parsed: dict) -> str | None:
    country = parsed.get("country_name") or parsed.get("country_code")
    location_parts = [
        parsed.get("supply_address"),
        parsed.get("postal_code"),
        parsed.get("city"),
        parsed.get("region"),
    ]
    if not any(str(part or "").strip() for part in location_parts):
        return None
    parts = [
        *location_parts,
        country,
    ]
    query = ", ".join(str(part).strip() for part in parts if str(part or "").strip())
    return query or None


async def _enrich_bill_location(parsed: dict) -> dict:
    """Attach coordinates to parsed bills when the invoice contains an address."""
    if _is_european_geocode_result(parsed):
        return parsed
    parsed.pop("lat", None)
    parsed.pop("lon", None)

    query = _bill_location_query(parsed)
    if not query:
        return parsed

    try:
        candidates = await app.state.nominatim.search(query, limit=5)
    except GeocodeError as exc:
        logger.warning("Bill address geocoding failed: %s", exc)
        return parsed

    candidates = _european_geocode_results(candidates)
    if not candidates:
        return parsed

    country_code = parsed.get("country_code")
    normalized_country = normalize_country_code(country_code) if country_code else None
    selected = None
    if normalized_country and normalized_country != "EU":
        selected = next(
            (
                candidate
                for candidate in candidates
                if normalize_country_code(candidate.get("country_code")) == normalized_country
            ),
            None,
        )
        if not selected:
            return parsed
    selected = selected or candidates[0]
    parsed["lat"] = round(float(selected["lat"]), 6)
    parsed["lon"] = round(float(selected["lon"]), 6)
    parsed["location_label"] = selected.get("display_name")
    if selected.get("country_code") and not parsed.get("country_code"):
        parsed["country_code"] = selected["country_code"]
    return parsed


def _is_european_geocode_result(result: dict) -> bool:
    try:
        return ensure_european_location(float(result["lat"]), float(result["lon"]))
    except (TypeError, ValueError, KeyError):
        return False


def _european_geocode_results(results: list[dict]) -> list[dict]:
    return [result for result in results if _is_european_geocode_result(result)]


def _dedupe_strings(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _profile_summary(req: SolarEstimateRequest, country_code: str) -> dict:
    return {
        "country_code": country_code,
        "occupancy_profile": req.occupancy_profile,
        "has_heat_pump": req.has_heat_pump,
        "has_ev": req.has_ev,
        "has_pool": req.has_pool,
    }


def _resolve_consumption(
    req: SolarEstimateRequest, default_currency: str, country_code: str
) -> tuple[dict | None, float | None]:
    """Consumo anual y resumen: de las facturas si las hay, si no del campo manual."""
    if req.bills:
        try:
            agg = bills_mod.aggregate_bills(
                [b.model_dump() for b in req.bills],
                default_currency=default_currency,
                country_code=country_code,
            )
        except bills_mod.BillParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        summary = {
            "annual_kwh": agg["annual_kwh"],
            "source": "bills",
            "avg_price_eur_kwh": agg["avg_price_eur_kwh"],
            "avg_price_kwh": agg["avg_price_kwh"],
            "marginal_price_eur_kwh": agg["marginal_price_eur_kwh"],
            "marginal_price_factor": agg["marginal_price_factor"],
            "tax_rates_source": agg["tax_rates_source"],
            "bill_count": agg["bill_count"],
            "priced_bill_count": agg["priced_bill_count"],
            "total_amount_bill_count": agg["total_amount_bill_count"],
            "ignored_price_bill_count": agg["ignored_price_bill_count"],
            "days_covered": agg["days_covered"],
            "monthly_kwh": agg["monthly_kwh"],
            "monthly_eur": agg["monthly_eur"],
            "monthly_amount": agg["monthly_amount"],
            "annual_amount_eur": agg["annual_amount_eur"],
            "annual_amount": agg["annual_amount"],
            "currency": agg["currency"],
            "observed_months": agg["observed_months"],
            "estimated_months": agg["estimated_months"],
            "seasonality_source": agg["seasonality_source"],
            "profile": _profile_summary(req, country_code),
        }
        return summary, agg["annual_kwh"]
    if req.annual_consumption_kwh is not None:
        return (
            {
                "annual_kwh": req.annual_consumption_kwh,
                "source": "input",
                "avg_price_eur_kwh": None,
                "avg_price_kwh": None,
                "bill_count": 0,
                "priced_bill_count": 0,
                "total_amount_bill_count": 0,
                "ignored_price_bill_count": 0,
                "days_covered": None,
                "monthly_kwh": None,
                "monthly_eur": None,
                "monthly_amount": None,
                "annual_amount_eur": None,
                "annual_amount": None,
                "currency": default_currency,
                "observed_months": [],
                "estimated_months": [],
                "seasonality_source": "manual_annual",
                "profile": _profile_summary(req, country_code),
            },
            req.annual_consumption_kwh,
        )
    return None, None


def _attach_consumption_costs(summary: dict | None, price_eur_kwh: float) -> None:
    """Añade gasto estimado si no viene de importes totales de factura."""
    if not summary:
        return
    if summary.get("annual_amount_eur") is None:
        summary["annual_amount_eur"] = round(summary["annual_kwh"] * price_eur_kwh, 2)
        summary["annual_amount"] = summary["annual_amount_eur"]
    if summary.get("monthly_kwh") and summary.get("monthly_eur") is None:
        summary["monthly_eur"] = [
            round(kwh * price_eur_kwh, 2) for kwh in summary["monthly_kwh"]
        ]
        summary["monthly_amount"] = summary["monthly_eur"]


def _scale_system(system: dict, target_kwp: float, source_kwp: float) -> dict:
    """Escala los kWh de un resultado PVGIS manteniendo irradiación y ángulos."""
    if source_kwp <= 0:
        return system
    factor = target_kwp / source_kwp
    scaled = system.copy()
    scaled["monthly"] = [
        {**month, "production_kwh": round(month["production_kwh"] * factor, 2)}
        for month in system["monthly"]
    ]
    scaled["annual_production_kwh"] = round(
        system["annual_production_kwh"] * factor, 2
    )
    return scaled


def _coverage_pct(production_kwh: float, consumption_kwh: float | None) -> float | None:
    """Producción anual como porcentaje del consumo anual, sin acotarla al 100%."""
    if not consumption_kwh or consumption_kwh <= 0:
        return None
    return round(production_kwh / consumption_kwh * 100, 1)


def _profile_annual_kwh(profile: list[list[float]]) -> float:
    return sum(sum(profile[m]) * DAYS_PER_MONTH[m] for m in range(12))


def _normalize_hourly_profile(
    profile: list[list[float]], target_annual_kwh: float
) -> list[list[float]]:
    """Ajusta el perfil horario al total anual PVcalc mostrado al usuario."""
    annual = _profile_annual_kwh(profile)
    if annual <= 0:
        return profile
    factor = target_annual_kwh / annual
    return [[round(value * factor, 4) for value in month] for month in profile]


def _panels_explanation(panels: dict) -> str:
    ratio = panels.get("production_to_consumption_pct")
    if ratio is None:
        return (
            "La potencia recomendada se calcula con el rendimiento solar de tu "
            "ubicación y el consumo anual indicado."
        )
    return (
        f"Esta instalación produce anualmente alrededor del {ratio:g}% de la "
        "energía que consumes. La autosuficiencia real depende de cuándo se "
        "consume esa energía, por eso se calcula aparte con el perfil horario."
    )


BATTERY_LIFETIME_YEARS = 10  # garantía típica de una batería doméstica


def _battery_recommendation(scenarios: list[dict]) -> tuple[float, str]:
    """Recomienda la batería con mejor payback marginal si baja de la vida útil."""
    LIFETIME = BATTERY_LIFETIME_YEARS
    base = next((s for s in scenarios if s["battery_kwh"] == 0), scenarios[0])
    candidates = [
        s
        for s in scenarios
        if s["battery_kwh"] > 0 and s.get("battery_marginal_payback_years") is not None
    ]
    best = min(
        candidates, key=lambda s: s["battery_marginal_payback_years"], default=None
    )
    if best and best["battery_marginal_payback_years"] <= LIFETIME:
        return best["battery_kwh"], (
            f"Recomendamos una batería de {best['battery_kwh']:g} kWh porque aumenta "
            f"la autosuficiencia del {base['self_sufficiency_pct']:g}% al "
            f"{best['self_sufficiency_pct']:g}% y se amortiza en unos "
            f"{best['battery_marginal_payback_years']:g} años, dentro de su vida útil "
            f"estimada (~{LIFETIME} años)."
        )
    detail = ""
    if best:
        extra_savings = max(0.0, best["annual_savings_eur"] - base["annual_savings_eur"])
        extra_investment = max(0.0, best["investment_eur"] - base["investment_eur"])
        detail = (
            f" La mejor opción no recomendada ({best['battery_kwh']:g} kWh) exigiría "
            f"{extra_investment:,.0f} adicionales para ahorrar {extra_savings:,.0f}/año "
            f"y tardaría {best['battery_marginal_payback_years']:g} años en amortizarse."
        )
    return 0.0, (
        "No recomendamos instalar batería porque el ahorro adicional frente a la inversión "
        f"no permite amortizarla durante su vida útil estimada (~{LIFETIME} años).{detail}"
    )


def _attach_battery_cost_ranges(
    scenarios: list[dict],
    system_cost_range: dict,
    battery_option_costs: list[dict],
) -> None:
    ranges = {
        item["battery_kwh"]: item["investment_range"]
        for item in battery_option_costs
    }
    ranges[0.0] = system_cost_range
    for scenario in scenarios:
        scenario["investment_range_eur"] = ranges.get(
            scenario["battery_kwh"],
            system_cost_range,
        )


def _monthly_irradiation_from_system(system: dict) -> list[dict]:
    return [
        {
            "month": month["month"],
            "irradiation_kwh_m2": month["irradiation_kwh_m2"],
        }
        for month in system["monthly"]
    ]


def _resolve_electricity_price(
    req: SolarEstimateRequest,
    consumption_summary: dict | None,
    default_price: float,
) -> tuple[float, str, int]:
    if req.electricity_price_eur_kwh is not None:
        return req.electricity_price_eur_kwh, "manual", 0
    if consumption_summary and consumption_summary.get("avg_price_eur_kwh") is not None:
        return (
            consumption_summary["avg_price_eur_kwh"],
            "bills",
            consumption_summary.get("priced_bill_count", 0),
        )
    return default_price, "default", 0


def _confidence_summary(
    consumption_summary: dict | None,
    price_source: str,
    price_quote: dict,
) -> dict:
    bill_count = consumption_summary.get("bill_count", 0) if consumption_summary else 0
    priced_bill_count = (
        consumption_summary.get("priced_bill_count", 0) if consumption_summary else 0
    )
    prices_current = (
        price_quote.get("source_type") == "providers"
        and not price_quote.get("fallback_used", True)
    )
    estimated_inputs = []
    if not consumption_summary:
        estimated_inputs.append("consumption")
    elif consumption_summary.get("source") == "input":
        estimated_inputs.append("consumption_profile")
    if price_source == "default":
        estimated_inputs.append("electricity_price")
    if price_quote.get("fallback_used", True):
        estimated_inputs.append("market_prices")

    observed_months = (
        consumption_summary.get("observed_months", []) if consumption_summary else []
    )
    seasonal_spread = len(set(observed_months)) >= 2

    # 'Alta' es alcanzable con datos que el usuario controla: ≥2 facturas con
    # importe repartidas en ≥2 meses. La producción (PVGIS) es fiable de por sí
    # y los precios de mercado son orientativos en cualquier caso; el feed de
    # proveedores suma (prices_current) pero no es condición necesaria.
    if priced_bill_count >= 2 and seasonal_spread:
        level = "high"
    elif priced_bill_count >= 1 or (
        consumption_summary is not None and price_source in {"manual", "bills"}
    ):
        level = "medium"
    else:
        level = "low"

    hints = []
    if level != "high":
        if priced_bill_count == 0:
            hints.append("add_priced_bills")
        elif priced_bill_count < 2 or not seasonal_spread:
            hints.append("add_seasonal_bills")

    return {
        "level": level,
        "bill_count": bill_count,
        "priced_bill_count": priced_bill_count,
        "pvgis_ok": True,
        "prices_current": prices_current,
        "estimated_inputs": estimated_inputs,
        "improvement_hints": hints,
    }


def _cap_savings_to_annual_spend(
    savings: float,
    annual_consumption: float | None,
    price_eur_kwh: float,
    export_scheme: str = "capped_compensation",
) -> float:
    # Con tarifa de inyección o venta a mercado el vertido es un ingreso real:
    # el "ahorro" anual puede superar legítimamente el gasto anual en luz.
    if annual_consumption is None or export_scheme in ("feed_in", "market_price"):
        return savings
    annual_spend = annual_consumption * price_eur_kwh
    return round(min(savings, annual_spend), 2)


def _validate_estimate_consistency(
    *,
    selected: dict,
    annual_energy: dict,
    economics: dict,
    panels: dict | None,
    analysis_power_kwp: float,
) -> None:
    warnings = []

    production = selected["annual_production_kwh"]
    if production < 0:
        warnings.append("annual production is negative")
    if any(month["production_kwh"] < 0 for month in selected["monthly"]):
        warnings.append("monthly production contains negative values")

    monthly_production = sum(month["production_kwh"] for month in selected["monthly"])
    if abs(monthly_production - production) > max(1.0, production * 0.01):
        warnings.append("annual production does not match monthly PVGIS production")

    annual_irradiation = selected["annual_irradiation_kwh_m2"]
    monthly_irradiation = sum(month["irradiation_kwh_m2"] for month in selected["monthly"])
    if abs(monthly_irradiation - annual_irradiation) > max(1.0, annual_irradiation * 0.01):
        warnings.append("annual irradiation does not match monthly PVGIS irradiation")

    expected_hsp = annual_irradiation / 365.25
    if abs(expected_hsp - selected["hsp_daily_avg"]) > 0.2:
        warnings.append("HSP is not coherent with annual irradiation")

    if analysis_power_kwp <= 0:
        warnings.append("analysis power is not positive")
    else:
        annual_yield = production / analysis_power_kwp
        if annual_yield < 400 or annual_yield > 2400:
            warnings.append("annual production is outside the expected range for installed power")

    consumption = annual_energy.get("consumption_kwh")
    if consumption and consumption > 0:
        reference_price = (
            economics.get("effective_price_eur_kwh")
            or economics["electricity_price_eur_kwh"]
        )
        annual_spend = consumption * reference_price
        if economics["annual_savings_eur"] > annual_spend + 0.5:
            warnings.append("annual savings exceed annual electricity spend")

    if economics.get("payback_years") is not None and economics["payback_years"] <= 0:
        warnings.append("payback is not positive")

    for key in ("self_consumed_kwh", "exported_kwh", "imported_kwh"):
        value = annual_energy.get(key)
        if value is not None and value < -0.1:
            warnings.append(f"{key} is negative")

    coverage = annual_energy.get("production_to_consumption_pct")
    if coverage is not None and (coverage < 0 or coverage > 300):
        warnings.append("production-to-consumption ratio is outside the expected range")

    if panels is not None:
        expected_kwp = round(panels["count"] * panels["panel_power_w"] / 1000, 2)
        if abs(expected_kwp - panels["total_kwp"]) > 0.01:
            warnings.append("recommended panel count is not coherent with total kWp")
        ratio = panels.get("production_to_consumption_pct")
        if (
            ratio is not None
            and coverage is not None
            and abs(panels["total_kwp"] - analysis_power_kwp) <= 0.01
            and abs(ratio - coverage) > 0.2
        ):
            warnings.append("panel production ratio is not coherent with annual energy")

    if warnings:
        logger.warning("Solar estimate consistency warnings: %s", "; ".join(warnings))


@app.post("/api/solar-estimate", response_model=SolarEstimateResponse)
async def solar_estimate(req: SolarEstimateRequest, request: Request):
    estimate_limiter: RateLimiter = app.state.estimate_limiter
    allowed, blocked_by = estimate_limiter.check_and_record(_client_ip(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                "El servicio ha alcanzado su cupo diario de cálculos; inténtalo mañana."
                if blocked_by == "global"
                else "Has hecho demasiados cálculos seguidos; espera un rato e inténtalo de nuevo."
            ),
        )
    settings = get_settings()
    pvgis: PVGISClient = app.state.pvgis
    pricing_service: PricingService = app.state.pricing
    has_user_angles = req.tilt_deg is not None or req.azimuth_deg is not None

    if not ensure_european_location(req.lat, req.lon):
        raise HTTPException(
            status_code=422,
            detail=(
                "Actualmente SolVento solo ofrece estimaciones para ubicaciones "
                "europeas cubiertas por PVGIS."
            ),
        )
    country = country_for_coordinates(req.lat, req.lon, req.country_code)
    consumption_summary, annual_consumption = _resolve_consumption(
        req,
        default_currency=country.currency,
        country_code=country.code,
    )

    # Todo lo que no depende de resultados previos va en un único gather:
    # cotización de precios, PVcalc óptimo, PVcalc del usuario y, si ya
    # conocemos los ángulos (los dio el usuario), también la serie horaria.
    user_angle = req.tilt_deg if req.tilt_deg is not None else 35
    user_aspect = req.azimuth_deg if req.azimuth_deg is not None else 0
    try:
        tasks = [
            pricing_service.get_prices(country, force_refresh=req.refresh_prices),
            pvgis.pvcalc(
                req.lat, req.lon, req.peak_power_kwp, req.loss_pct, optimal_angles=True
            ),
        ]
        if has_user_angles:
            tasks.append(
                pvgis.pvcalc(
                    req.lat,
                    req.lon,
                    req.peak_power_kwp,
                    req.loss_pct,
                    angle=user_angle,
                    aspect=user_aspect,
                )
            )
        needs_hourly = annual_consumption is not None
        if needs_hourly and has_user_angles:
            tasks.append(
                pvgis.hourly_profile(
                    req.lat, req.lon, 1.0, req.loss_pct, angle=user_angle, aspect=user_aspect
                )
            )
        results = await asyncio.gather(*tasks)

        price_quote = results[0]
        optimal = results[1]
        user_system = results[2] if has_user_angles else None
        hourly_production = results[3] if needs_hourly and has_user_angles else None
        selected = user_system or optimal

        # Modo básico con consumo: la serie horaria necesita los ángulos óptimos
        if needs_hourly and hourly_production is None:
            hourly_production = await pvgis.hourly_profile(
                req.lat,
                req.lon,
                1.0,
                req.loss_pct,
                angle=selected["slope_deg"],
                aspect=selected["azimuth_deg"],
            )
    except PVGISError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    panels = None
    analysis_power_kwp = req.peak_power_kwp
    if annual_consumption is not None:
        per_kwp = selected["annual_production_kwh"] / req.peak_power_kwp
        panels = calculations.recommended_panels(
            annual_consumption, per_kwp, req.panel_power_w
        )
        recommended_production = per_kwp * panels["total_kwp"]
        recommended_coverage = _coverage_pct(recommended_production, annual_consumption)
        panels["coverage_pct"] = recommended_coverage
        panels["production_to_consumption_pct"] = recommended_coverage
    selected = user_system or optimal

    # La serie horaria se pide siempre a 1 kWp (la clave de caché no varía con
    # cada potencia analizada) y se reescala aquí a la producción del sistema
    # que se muestra en producción, ahorro y payback.
    if hourly_production is not None:
        hourly_production = _normalize_hourly_profile(
            hourly_production, selected["annual_production_kwh"]
        )

    # Precio: prioridad al explícito, luego al derivado de facturas, luego default.
    # Si hay facturas con cargo variable de energía válido, no se usa un precio medio nacional.
    price, price_source, price_bill_count = _resolve_electricity_price(
        req,
        consumption_summary,
        # El default del país (en su moneda) antes que el genérico en EUR
        price_quote.get("electricity_price_kwh") or settings.electricity_price_eur_kwh,
    )
    # El término de energía de las facturas va sin impuestos: cada kWh
    # autoconsumido evita también impuesto eléctrico + IVA (coste marginal
    # evitado). Los tipos se derivan de las propias facturas (o de la tabla
    # normativa por fechas); la tabla fija por país queda como último recurso
    # para facturas sin datos de países sin tabla normativa propia. Los precios
    # por defecto ya incluyen impuestos y el manual se asume final.
    if price_source == "bills":
        marginal_price_factor = (
            (consumption_summary or {}).get("marginal_price_factor")
            or price_quote.get("electricity_tax_factor", 1.0)
        )
    else:
        marginal_price_factor = 1.0
    effective_price = round(price * marginal_price_factor, 4)
    _attach_consumption_costs(consumption_summary, effective_price)

    cost_details = calculate_system_cost(
        price_quote,
        power_kwp=analysis_power_kwp,
        panel_power_w=req.panel_power_w,
        battery_options_kwh=req.battery_options_kwh,
        installation_cost=req.installation_cost_eur,
        cost_per_kwp=req.cost_per_kwp_eur,
        battery_cost_per_kwh=req.battery_cost_per_kwh_eur,
    )
    cost = cost_details["system_cost_range"]["medium"]
    cost_is_estimated = req.installation_cost_eur is None
    battery_cost_per_kwh = cost_details["battery_cost_per_kwh"]["medium"]
    surplus_price = (
        req.surplus_price_eur_kwh
        if req.surplus_price_eur_kwh is not None
        else price_quote["surplus_price_eur_kwh"]
    )
    export_scheme = price_quote.get("export_scheme", "capped_compensation")
    # El excedente se paga a la tarifa de compensación tal cual (con su tope
    # mensual): el factor fiscal solo aplica al kWh autoconsumido evitado.
    effective_surplus = surplus_price
    subsidy = req.subsidy_eur or 0.0
    om_eur = round(cost * cashflow.OM_PCT_PER_YEAR, 2)
    inverter_replacement_cost = round(
        cost_details["inverter_price_per_kwp"]["medium"] * analysis_power_kwp, 2
    )
    replacements = {cashflow.INVERTER_REPLACEMENT_YEAR: inverter_replacement_cost}

    battery_analysis = None
    typical_day = None
    coverage = _coverage_pct(selected["annual_production_kwh"], annual_consumption)
    annual_energy = {
        "production_kwh": selected["annual_production_kwh"],
        "consumption_kwh": annual_consumption,
        "coverage_pct": coverage,
        # Alias mantenido por compatibilidad con el frontend
        "production_to_consumption_pct": coverage,
    }
    if hourly_production is not None:
        cons_profile = consumption_profile(
            annual_consumption,
            consumption_summary.get("monthly_kwh") if consumption_summary else None,
            country_code=country.code,
            occupancy_profile=req.occupancy_profile,
            has_heat_pump=req.has_heat_pump,
            has_ev=req.has_ev,
            has_pool=req.has_pool,
        )
        capacities = [0.0] + sorted(
            {c for c in req.battery_options_kwh if c > 0}
        )
        # €/kWh por capacidad (las baterías pequeñas cuestan más por kWh):
        # coherente con las horquillas de inversión que se muestran
        battery_unit_costs = {
            item["battery_kwh"]: round(
                (item["investment_range"]["medium"] - cost) / item["battery_kwh"], 2
            )
            for item in cost_details["battery_option_costs"]
            if item["battery_kwh"] > 0
        }
        scenarios = simulation.battery_scenarios(
            hourly_production,
            cons_profile,
            capacities,
            effective_price,
            effective_surplus,
            cost,
            battery_unit_costs,
            export_scheme=export_scheme,
        )
        _attach_battery_cost_ranges(
            scenarios,
            cost_details["system_cost_range"],
            cost_details["battery_option_costs"],
        )
        # Métricas plurianuales por escenario: el payback mostrado y la
        # recomendación de batería usan el flujo de caja real, no el año 1.
        scenario_yearly = {
            s["battery_kwh"]: cashflow.simulated_yearly_savings(
                hourly_production,
                cons_profile,
                s["battery_kwh"],
                effective_price,
                effective_surplus,
                export_scheme,
            )
            for s in scenarios
        }
        base_yearly = scenario_yearly[0.0]
        base_analysis = None
        for s in scenarios:
            analysis = cashflow.cashflow_analysis(
                scenario_yearly[s["battery_kwh"]],
                investment_eur=s["investment_eur"],
                subsidy_eur=subsidy,
                om_eur_per_year=om_eur,
                replacements=replacements,
            )
            s["payback_years"] = analysis["payback_years"]
            s["npv_eur"] = analysis["npv_eur"]
            if s["battery_kwh"] == 0:
                base_analysis = analysis
            else:
                s["battery_marginal_payback_years"] = cashflow.marginal_battery_payback(
                    scenario_yearly[s["battery_kwh"]],
                    base_yearly,
                    s["investment_eur"] - cost,
                )
        recommended_kwh, recommendation = _battery_recommendation(scenarios)
        base_scenario = scenarios[0]
        annual_energy.update(
            {
                "production_kwh": base_scenario["production_kwh"],
                "consumption_kwh": base_scenario["consumption_kwh"],
                "self_consumed_kwh": base_scenario["self_consumed_kwh"],
                "exported_kwh": base_scenario["exported_kwh"],
                "imported_kwh": base_scenario["imported_kwh"],
                "self_consumption_pct": base_scenario["self_consumption_pct"],
                "self_sufficiency_pct": base_scenario["self_sufficiency_pct"],
            }
        )
        battery_analysis = {
            "scenarios": scenarios,
            "recommended_battery_kwh": recommended_kwh,
            "recommendation": recommendation,
            "battery_lifetime_years": BATTERY_LIFETIME_YEARS,
            "export_scheme": export_scheme,
            "surplus_price_eur_kwh": surplus_price,
            "battery_cost_per_kwh_eur": battery_cost_per_kwh,
            "battery_cost_range_eur_per_kwh": cost_details[
                "battery_cost_per_kwh"
            ],
        }
        typical_day = {"production": hourly_production, "consumption": cons_profile}
        # Con simulación, el ahorro base es el del escenario sin batería
        # (incluye compensación de excedentes): más realista que el modelo simple
        savings = scenarios[0]["annual_savings_eur"]
    else:
        savings = calculations.annual_savings_eur(
            selected["annual_production_kwh"], effective_price, annual_consumption
        )
        savings = _cap_savings_to_annual_spend(
            savings, annual_consumption, effective_price, export_scheme
        )
        base_analysis = cashflow.cashflow_analysis(
            cashflow.simple_yearly_savings(savings),
            investment_eur=cost,
            subsidy_eur=subsidy,
            om_eur_per_year=om_eur,
            replacements=replacements,
        )
    savings = _cap_savings_to_annual_spend(
        savings, annual_consumption, effective_price, export_scheme
    )

    payback = base_analysis["payback_years"]
    simple_payback = calculations.payback_years(base_analysis["net_investment_eur"], savings)
    roi_pct = round(savings / cost * 100, 1) if cost > 0 else None
    economics = {
        "electricity_price_eur_kwh": price,
        "electricity_price_source": price_source,
        "electricity_price_bill_count": price_bill_count,
        "annual_savings_eur": savings,
        "payback_years": payback,
        "simple_payback_years": simple_payback,
        "installation_cost_eur": cost,
        "installation_cost_range_eur": cost_details["system_cost_range"],
        "cost_is_estimated": cost_is_estimated,
        "roi_pct": roi_pct,
        "savings_25yr_eur": base_analysis["savings_headline_eur"],
        "npv_eur": base_analysis["npv_eur"],
        "irr_pct": base_analysis["irr_pct"],
        "subsidy_eur": subsidy if subsidy > 0 else None,
        "net_investment_eur": base_analysis["net_investment_eur"],
        "effective_price_eur_kwh": effective_price,
        "marginal_price_factor": marginal_price_factor,
        "cumulative_cashflow": base_analysis["cumulative"],
        "assumptions": base_analysis["assumptions"],
    }
    if panels is not None:
        panels["explanation"] = _panels_explanation(panels)

    _validate_estimate_consistency(
        selected=selected,
        annual_energy=annual_energy,
        economics=economics,
        panels=panels,
        analysis_power_kwp=analysis_power_kwp,
    )

    return SolarEstimateResponse(
        lat=round(req.lat, 2),
        lon=round(req.lon, 2),
        requested_peak_power_kwp=req.peak_power_kwp,
        analysis_power_kwp=analysis_power_kwp,
        loss_pct=req.loss_pct,
        elevation_m=optimal.get("elevation_m"),
        optimal={k: optimal[k] for k in SystemKeys},
        user_system={k: user_system[k] for k in SystemKeys} if user_system else None,
        loss_vs_optimal_pct=(
            calculations.loss_vs_optimal_pct(
                user_system["annual_production_kwh"], optimal["annual_production_kwh"]
            )
            if user_system
            else None
        ),
        plane_irradiation_monthly=_monthly_irradiation_from_system(selected),
        economics=economics,
        pricing={
            **price_quote,
            **cost_details,
        },
        panels=panels,
        consumption=consumption_summary,
        annual_energy=annual_energy,
        battery_analysis=battery_analysis,
        typical_day=typical_day,
        confidence=_confidence_summary(consumption_summary, price_source, price_quote),
    )


SystemKeys = (
    "slope_deg",
    "azimuth_deg",
    "monthly",
    "annual_production_kwh",
    "annual_irradiation_kwh_m2",
    "hsp_daily_avg",
)


# En producción el frontend compilado se sirve como estáticos desde FastAPI.
if FRONTEND_DIST.is_dir():
    # La app se publica bajo /solvento (el funnel elimina el prefijo antes de
    # llegar aquí), pero también se accede directo por IP:puerto en la tailnet.
    # El build usa base /solvento/, así que aceptamos ambas formas quitando el
    # prefijo cuando llega.
    PUBLIC_PREFIX = "/solvento"

    @app.middleware("http")
    async def _strip_public_prefix(request: Request, call_next):
        path = request.scope["path"]
        if path == PUBLIC_PREFIX or path.startswith(PUBLIC_PREFIX + "/"):
            request.scope["path"] = path[len(PUBLIC_PREFIX):] or "/"
        return await call_next(request)

    @app.middleware("http")
    async def _static_cache_headers(request: Request, call_next):
        """Caché correcta del frontend.

        El index.html debe revalidarse siempre (un HTML viejo en el navegador
        apunta a assets con hash que ya no existen → página en blanco); los
        assets con hash pueden cachearse para siempre.
        """
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/"):
            return response
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
