"""SolarVento — API de cálculo solar fotovoltaico sobre PVGIS."""

import asyncio
import hashlib
import ipaddress
import logging
import math
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import bill_normalise
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
from .spain_postal import province_from_postal_code
from . import subsidies as subsidies_mod
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
    app.state.bill_cache = TTLCache(
        settings.bill_cache_db_path, settings.bill_cache_ttl_seconds
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
    app.state.bill_cache.close()
    cache.close()


app = FastAPI(title="SolarVento", version="0.1.0", lifespan=lifespan)

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
                "Actualmente SolarVento solo ofrece estimaciones para ubicaciones "
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

    # Vía primaria: extractor LLM → contrato tipado → normalización/validación
    # deterministas (bill_normalise). El parser posicional/regex queda RETIRADO de
    # la vía primaria: solo se usa como degradación cuando NO hay clave de OpenAI.
    if openai_parser:
        parser_type = content_type if is_image else "application/pdf"
        text_hint = None
        if is_pdf:
            text_hint = await run_in_threadpool(bills_mod.extract_pdf_text_safe, content)
        try:
            bill = await _extract_bill_contract(
                openai_parser, content, file.filename, parser_type, text_hint
            )
        except bills_mod.BillParseError as exc:
            # Fallo duro del modelo (red/cuota/JSON): no se cae al regex en
            # silencio; se devuelve estado de revisión para que el usuario
            # complete a mano (mejor revisar que un número seguro y equivocado).
            logger.warning("LLM bill extraction failed: %s", exc)
            bill = bill_normalise.contract_to_bill(None)
            bill["warnings"] = [
                "No se pudo leer la factura automáticamente; revisa e introduce los datos a mano."
            ]
        return await _enrich_bill_location(bill)

    # Sin clave de OpenAI: degradación al extractor local (solo PDF-texto).
    if is_image:
        return _unreadable_bill(
            "Las fotos de factura no están disponibles ahora; sube la factura en PDF."
        )
    try:
        local = await run_in_threadpool(bills_mod.parse_bill_pdf, content)
    except bills_mod.BillParseError as exc:
        return _unreadable_bill(str(exc))
    return await _enrich_bill_location(local)


async def _extract_bill_contract(
    parser: OpenAIBillParser,
    content: bytes,
    filename: str | None,
    parser_type: str,
    text_hint: str | None,
) -> dict:
    """Extrae el contrato (con caché por hash de fichero) y lo normaliza a factura.

    La caché guarda el CONTRATO en crudo por hash: la misma factura devuelve
    siempre el mismo JSON y, tras la normalización determinista, los mismos euros
    (determinismo + sin repetir llamadas de pago al modelo)."""
    cache: TTLCache = app.state.bill_cache
    key = f"bill:{hashlib.sha256(content).hexdigest()}"
    contract = cache.get(key)
    if contract is None:
        contract = await parser.extract_contract(content, filename, parser_type, text_hint)
        cache.set(key, contract)
    # Refuerzo determinista sobre el texto del PDF: el modelo a veces no marca el
    # bono social ni el "consumo acumulado del último año". Si están escritos en
    # la factura, se rellenan (sin pisar lo que el modelo sí detectó).
    if isinstance(contract, dict) and text_hint:
        contract = bills_mod.augment_contract_from_text(contract, text_hint)
    return bill_normalise.contract_to_bill(contract)


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
        "state": "extraction_failed",
        "needs_review": False,
        "review_reasons": [],
        "warnings": [reason],
    }


def _bill_location_query(parsed: dict) -> str | None:
    """Consulta primaria de geocodificado: CP + municipio, nunca la provincia.

    La provincia (p. ej. 'A Coruña', que también es el nombre de la capital)
    hace que el geocoder devuelva el centroide provincial ignorando el CP; por
    eso NO se envía como objetivo, solo se usa después como filtro de validación.
    """
    cp = str(parsed.get("postal_code") or "").strip()
    city = str(parsed.get("city") or "").strip()
    country = "España" if _is_spanish(parsed) else (
        str(parsed.get("country_name") or parsed.get("country_code") or "").strip()
    )
    # Primaria: CP + municipio. NO se manda la dirección de suministro completa:
    # suele traer la provincia (y a veces CP/municipio duplicados), que confunde
    # al geocoder y devuelve 0 resultados o el centroide provincial. La provincia
    # solo filtra el resultado; el país ancla la búsqueda.
    if cp or city:
        base = " ".join(part for part in (cp, city) if part)
    else:
        # Último recurso, sin CP ni municipio: la calle tal cual.
        base = str(parsed.get("supply_address") or "").strip()
    if not base:
        return None
    return f"{base}, {country}" if country else base


def _is_spanish(parsed: dict) -> bool:
    code = parsed.get("country_code")
    return bool(code) and normalize_country_code(code) == "ES"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Un resultado a más de esta distancia del centroide provincial del CP (y cuyo
# municipio no coincide con el nombre devuelto) se considera de otra región: se
# rechaza y se cae al centroide del CP, nunca a la capital de provincia en silencio.
_MAX_REGION_DISTANCE_KM = 120.0


def _apply_postal_fallback(parsed: dict) -> dict:
    """Sin geocodificar: sesga el mapa al centroide provincial del CP español.

    Baja confianza; solo para CP que mapean a provincia ES (evita colisión con
    CP de otros países). No fuerza país si ya viene otro.
    """
    if normalize_country_code(parsed.get("country_code") or "ES") not in ("ES", "EU"):
        return parsed
    province = province_from_postal_code(parsed.get("postal_code"))
    if not province:
        return parsed
    name, lat, lon = province
    parsed["lat"] = lat
    parsed["lon"] = lon
    parsed["location_label"] = f"{name} ({parsed.get('postal_code')})"
    parsed["location_confidence"] = "low"
    parsed["country_code"] = parsed.get("country_code") or "ES"
    return parsed


async def _enrich_bill_location(parsed: dict) -> dict:
    """Attach coordinates to parsed bills when the invoice contains an address.

    Prefers a precise geocode of the supply address; if that fails but a Spanish
    postal code parsed, biases the map to the province centroid (low confidence).
    """
    if _is_european_geocode_result(parsed):
        parsed.setdefault("location_confidence", "high")
        return parsed
    parsed.pop("lat", None)
    parsed.pop("lon", None)

    query = _bill_location_query(parsed)
    if not query:
        return _apply_postal_fallback(parsed)

    try:
        candidates = await app.state.nominatim.search(query, limit=5)
    except GeocodeError as exc:
        logger.warning("Bill address geocoding failed: %s", exc)
        return _apply_postal_fallback(parsed)

    candidates = _european_geocode_results(candidates)
    if not candidates:
        return _apply_postal_fallback(parsed)

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
            return _apply_postal_fallback(parsed)
    # Entre los candidatos del país, preferir el que nombra el municipio del CP.
    city = str(parsed.get("city") or "").strip().lower()
    country_matches = [
        c
        for c in candidates
        if not normalized_country
        or normalized_country == "EU"
        or normalize_country_code(c.get("country_code")) == normalized_country
    ]
    pool = country_matches or candidates
    if city:
        named = next(
            (c for c in pool if city in str(c.get("display_name") or "").lower()), None
        )
        selected = named or selected or pool[0]
    else:
        selected = selected or pool[0]

    lat, lon = round(float(selected["lat"]), 6), round(float(selected["lon"]), 6)
    # Guarda de distancia: la provincia se usa como FILTRO, no como objetivo. Un
    # resultado lejos del centroide provincial del CP y que no nombra el municipio
    # es de otra región → se descarta al centroide del CP (baja confianza).
    province = province_from_postal_code(parsed.get("postal_code"))
    names_city = bool(city) and city in str(selected.get("display_name") or "").lower()
    if province and not names_city:
        _name, plat, plon = province
        if _haversine_km(lat, lon, plat, plon) > _MAX_REGION_DISTANCE_KM:
            return _apply_postal_fallback(parsed)

    parsed["lat"] = lat
    parsed["lon"] = lon
    parsed["location_label"] = selected.get("display_name")
    parsed["location_confidence"] = "high"
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
            "valle_price_eur_kwh": agg["valle_price_eur_kwh"],
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
            "contracted_power_kw": agg["contracted_power_kw"],
            "seasonality_source": agg["seasonality_source"],
            "consumption_reliability": agg.get("consumption_reliability"),
            "single_month": agg.get("single_month", False),
            "months_covered": agg.get("months_covered"),
            "distinct_cups": agg.get("distinct_cups"),
            "bono_social": agg.get("bono_social", False),
            "annual_from_printed": agg.get("annual_from_printed", False),
            "needs_review": agg.get("needs_review", False),
            "review_reasons": agg.get("review_reasons", []),
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


_WINTER_MONTHS = (12, 1, 2)
_SUMMER_MONTHS = (6, 7, 8)


def _seasonal_self_sufficiency(
    production: list[list[float]], consumption: list[list[float]]
) -> tuple[float | None, float | None]:
    """Autosuficiencia invierno vs verano del perfil horario (misma fuente que el
    titular; no re-simula). Sin batería: servido = Σ min(prod, cons) por hora.

    Devuelve (invierno %, verano %), ponderando meses por su consumo real.
    """

    def _window(months: tuple[int, ...]) -> float | None:
        served = 0.0
        consumed = 0.0
        for m in months:
            days = DAYS_PER_MONTH[m - 1]
            prod, cons = production[m - 1], consumption[m - 1]
            served += sum(min(prod[h], cons[h]) for h in range(24)) * days
            consumed += sum(cons) * days
        if consumed <= 0:
            return None
        return round(min(100.0, max(0.0, 100 * served / consumed)), 1)

    return _window(_WINTER_MONTHS), _window(_SUMMER_MONTHS)


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


def _battery_recommendation(
    scenarios: list[dict], useful_life_years: int
) -> tuple[float, str]:
    """Recomienda una batería si su payback INCREMENTAL cabe en la vida útil.

    La decisión se toma con el payback incremental (coste extra / ahorro extra),
    no con el del sistema completo. Devuelve (kWh recomendados, texto de reserva;
    la UI construye su propia narrativa con las cifras de esta casa).
    """
    candidates = [
        s
        for s in scenarios
        if s["battery_kwh"] > 0
        and s.get("battery_incremental_payback_years") is not None
    ]
    best = min(
        candidates,
        key=lambda s: s["battery_incremental_payback_years"],
        default=None,
    )
    if best and best["battery_incremental_payback_years"] <= useful_life_years:
        return best["battery_kwh"], (
            f"Una batería de {best['battery_kwh']:g} kWh se amortiza en "
            f"~{best['battery_incremental_payback_years']:g} años (payback incremental), "
            f"dentro de su vida útil estimada (~{useful_life_years} años)."
        )
    detail = ""
    if best:
        detail = (
            f" La mejor opción ({best['battery_kwh']:g} kWh) cuesta "
            f"{best.get('battery_extra_cost_eur', 0):,.0f} extra y solo añade "
            f"{best.get('battery_extra_savings_eur', 0):,.0f}/año: payback incremental "
            f"~{best['battery_incremental_payback_years']:g} años, por encima de la "
            f"vida útil (~{useful_life_years} años)."
        )
    return 0.0, (
        "Una batería no se amortiza aquí: el ahorro extra no cubre su coste dentro de "
        f"la vida útil estimada (~{useful_life_years} años).{detail}"
    )


def _size_scenarios(
    *,
    per_kwp_hourly: list[list[float]],
    cons_profile: list[list[float]],
    price: float,
    surplus_price: float,
    export_scheme: str,
    annual_consumption: float,
    subsidy: float,
    om_pct: float,
    inverter_per_kwp: float,
    cost_fn,
    coverage_kwp: float,
    step_kwp: float,
    grant_fn=None,
) -> tuple[list[dict], float, float]:
    """Barrido de tamaños de PV (sin batería): payback/ROI/VAN por potencia.

    El óptimo económico maximiza el VAN: añadir kWp deja de compensar cuando su
    producción marginal ya solo se vierte a la tarifa de excedentes en vez de
    evitar compra de red. El de 'máximo ahorro' es la cobertura ~100%.
    """
    sizes: set[float] = {round(coverage_kwp, 2)}
    k = max(step_kwp, 1.0)
    while k < coverage_kwp:
        sizes.add(round(k, 2))
        k += step_kwp

    scenarios: list[dict] = []
    for kwp in sorted(sizes):
        production = [[value * kwp for value in month] for month in per_kwp_hourly]
        balance = simulation.simulate_self_consumption(production, cons_profile, 0.0)
        savings = simulation.annual_savings_with_surplus(
            balance, price, surplus_price, export_scheme
        )
        savings = _cap_savings_to_annual_spend(
            savings, annual_consumption, price, export_scheme
        )
        cost = cost_fn(kwp)
        replacements = {
            cashflow.INVERTER_REPLACEMENT_YEAR: round(inverter_per_kwp * kwp, 2)
        }
        om = round(cost * om_pct, 2)
        yearly = cashflow.simple_yearly_savings(savings)
        analysis = cashflow.cashflow_analysis(
            yearly, investment_eur=cost, subsidy_eur=subsidy,
            om_eur_per_year=om, replacements=replacements,
        )
        # Subvención autonómica POR ESCENARIO (0 si no aplica): el tope de kWp
        # elegibles hace que un sistema grande reciba proporcionalmente menos,
        # favoreciendo aún más el óptimo económico. Se muestra CON y SIN ayuda.
        grant = grant_fn(kwp, cost) if grant_fn else 0.0
        with_subsidy = cashflow.cashflow_analysis(
            yearly, investment_eur=cost, subsidy_eur=subsidy + grant,
            om_eur_per_year=om, replacements=replacements,
        ) if grant > 0 else analysis
        scenarios.append(
            {
                "power_kwp": kwp,
                "annual_savings_eur": savings,
                "investment_eur": round(cost, 2),
                "payback_years": analysis["payback_years"],
                "npv_eur": analysis["npv_eur"],
                "subsidy_grant_eur": round(grant, 2),
                "net_investment_with_subsidy_eur": with_subsidy["net_investment_eur"],
                "payback_with_subsidy_years": with_subsidy["payback_years"],
                "roi_pct": round(savings / cost * 100, 1) if cost > 0 else None,
                "production_kwh": balance["production_kwh"],
                "self_consumption_pct": balance["self_consumption_pct"],
                "self_sufficiency_pct": balance["self_sufficiency_pct"],
                "self_consumed_kwh": round(
                    balance["direct_kwh"] + balance["battery_kwh"], 1
                ),
                "exported_kwh": balance["exported_kwh"],
                "imported_kwh": balance["imported_kwh"],
            }
        )

    # Óptimo económico = la mayor potencia cuya ÚLTIMA porción añadida todavía
    # se autoconsume mayoritariamente (evita compra de red a precio alto). Más
    # allá, cada kWp extra solo se vierte a la tarifa de excedentes: engorda el
    # ahorro absoluto pero hunde ROI y payback. La fracción autoconsumida marginal
    # decrece de forma monótona con el tamaño, así que basta avanzar hasta el codo.
    SELF_CONSUMPTION_KNEE = 0.5
    optimum = scenarios[0]
    for prev, cur in zip(scenarios, scenarios[1:], strict=False):
        marginal_production = cur["production_kwh"] - prev["production_kwh"]
        marginal_self = cur["self_consumed_kwh"] - prev["self_consumed_kwh"]
        fraction = marginal_self / marginal_production if marginal_production > 0 else 0.0
        if fraction >= SELF_CONSUMPTION_KNEE:
            optimum = cur
        else:
            break
    max_savings = max(scenarios, key=lambda s: s["annual_savings_eur"])
    return scenarios, optimum["power_kwp"], max_savings["power_kwp"]


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
    # La confianza depende de cuántos MESES REALES de consumo se cubren, no de
    # cuántos ficheros se suban: una sola factura anual con su detalle mensual
    # aporta 12 meses reales. La producción (PVGIS) es fiable de por sí y los
    # precios de mercado son orientativos; el feed de proveedores suma pero no
    # es condición necesaria.
    real_months = len(set(observed_months))
    seasonal_spread = real_months >= 2

    if real_months >= 12 or (priced_bill_count >= 2 and seasonal_spread):
        level = "high"
    elif priced_bill_count >= 1 or (
        consumption_summary is not None and price_source in {"manual", "bills"}
    ):
        level = "medium"
    else:
        level = "low"

    hints = []
    # Con un año completo de datos reales no tiene sentido pedir más meses.
    if level != "high" and real_months < 12:
        if priced_bill_count == 0:
            hints.append("add_priced_bills")
        elif priced_bill_count < 2 or not seasonal_spread:
            hints.append("add_seasonal_bills")

    return {
        "level": level,
        "bill_count": bill_count,
        "priced_bill_count": priced_bill_count,
        "real_months": real_months,
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
        # El nº de paneles es entero: la potencia instalada por paneles puede
        # diferir de la analizada hasta el valor de un panel.
        expected_kwp = panels["count"] * panels["panel_power_w"] / 1000
        panel_kwp = panels["panel_power_w"] / 1000
        if abs(expected_kwp - panels["total_kwp"]) > panel_kwp + 0.01:
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
                "Actualmente SolarVento solo ofrece estimaciones para ubicaciones "
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

    # Precio (no depende de la potencia analizada): explícito > facturas > país.
    price, price_source, price_bill_count = _resolve_electricity_price(
        req,
        consumption_summary,
        price_quote.get("electricity_price_kwh") or settings.electricity_price_eur_kwh,
    )
    # El término de energía de las facturas va sin impuestos: cada kWh
    # autoconsumido evita también impuesto eléctrico + IVA (coste marginal
    # evitado). Los tipos se derivan de la factura o de la tabla normativa; los
    # precios por defecto ya los incluyen y el manual se asume final.
    if price_source == "bills":
        marginal_price_factor = (
            (consumption_summary or {}).get("marginal_price_factor")
            or price_quote.get("electricity_tax_factor", 1.0)
        )
    else:
        marginal_price_factor = 1.0
    effective_price = round(price * marginal_price_factor, 4)
    # Precio marginal evitado del periodo valle (energía valle × factor fiscal),
    # con el que se valora la energía servida por la batería: desplaza consumo
    # nocturno de valle, más barato que el precio medio. None si la factura no
    # trae el precio por periodo → la batería se valora al precio medio (sin cambio).
    valle_price = (consumption_summary or {}).get("valle_price_eur_kwh") if (
        price_source == "bills"
    ) else None
    battery_discharge_price = (
        round(valle_price * marginal_price_factor, 4)
        if valle_price and valle_price > 0
        else None
    )
    _attach_consumption_costs(consumption_summary, effective_price)
    surplus_price = (
        req.surplus_price_eur_kwh
        if req.surplus_price_eur_kwh is not None
        else price_quote["surplus_price_eur_kwh"]
    )
    export_scheme = price_quote.get("export_scheme", "capped_compensation")
    # El excedente se paga a su tarifa de compensación (con tope mensual); el
    # factor fiscal solo aplica al kWh autoconsumido evitado.
    effective_surplus = surplus_price
    subsidy = req.subsidy_eur or 0.0

    # --- Ayudas autonómicas (config versionada; guarda de vigencia) ---
    # La comunidad se resuelve del CP; el registro puede estar sin verificar →
    # no se aplica nada (grant 0) y se muestra "consultar". Grant POR ESCENARIO.
    subsidy_region = subsidies_mod.region_from_postal_code(req.postal_code)
    subsidy_record = subsidies_mod.get_region_record(subsidy_region)
    subsidy_today = date.today()

    def _subsidy_grant(kwp: float, cost_for_kwp: float) -> float:
        if not subsidy_record:
            return 0.0
        return subsidies_mod.compute_subsidy(
            subsidy_record,
            power_kwp=kwp,
            system_cost_eur=cost_for_kwp,
            today=subsidy_today,
        )["grant_eur"]

    # --- Dimensionado: recomendación de cobertura + barrido económico ---
    panels = None
    analysis_power_kwp = req.peak_power_kwp
    sizing_analysis = None
    cons_profile = None
    if annual_consumption is not None:
        per_kwp = selected["annual_production_kwh"] / req.peak_power_kwp
        panels = calculations.recommended_panels(
            annual_consumption, per_kwp, req.panel_power_w
        )
        recommended_production = per_kwp * panels["total_kwp"]
        recommended_coverage = _coverage_pct(recommended_production, annual_consumption)
        panels["coverage_pct"] = recommended_coverage
        panels["production_to_consumption_pct"] = recommended_coverage
        # Tamaño de cobertura del 100% (escenario 'máximo ahorro'); el titular
        # puede ser menor (óptimo económico). Se guarda para el barrido y como
        # 'needed_kwp' informativo.
        coverage_kwp = panels["total_kwp"]

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
            # Barrido de tamaños solo cuando el coste se estima (no si el usuario
            # fijó un coste total para un sistema concreto).
            if req.installation_cost_eur is None:
                per_kwp_hourly = _normalize_hourly_profile(hourly_production, per_kwp)

                def _size_cost(kwp: float) -> float:
                    return calculate_system_cost(
                        price_quote,
                        power_kwp=kwp,
                        panel_power_w=req.panel_power_w,
                        battery_options_kwh=[],
                        cost_per_kwp=req.cost_per_kwp_eur,
                    )["system_cost_range"]["medium"]

                size_list, optimum_kwp, max_savings_kwp = _size_scenarios(
                    per_kwp_hourly=per_kwp_hourly,
                    cons_profile=cons_profile,
                    price=effective_price,
                    surplus_price=effective_surplus,
                    export_scheme=export_scheme,
                    annual_consumption=annual_consumption,
                    subsidy=subsidy,
                    om_pct=cashflow.OM_PCT_PER_YEAR,
                    inverter_per_kwp=price_quote["inverter_price_per_kwp"]["medium"],
                    cost_fn=_size_cost,
                    coverage_kwp=panels["total_kwp"],
                    step_kwp=max(0.5, req.panel_power_w / 1000),
                    grant_fn=_subsidy_grant,
                )
                sizing_analysis = {
                    "scenarios": size_list,
                    "economic_optimum_kwp": optimum_kwp,
                    "max_savings_kwp": max_savings_kwp,
                }
                # El titular por defecto es el ÓPTIMO ECONÓMICO (mejor VAN), no
                # la cobertura del 100% (que minimiza ROI/payback). El slider
                # ROI↔Independencia interpola entre el óptimo y el máximo ahorro.
                if req.auto_size_power:
                    if req.sizing_bias is not None and max_savings_kwp > optimum_kwp:
                        bias = min(100.0, max(0.0, req.sizing_bias)) / 100.0
                        analysis_power_kwp = round(
                            optimum_kwp + (max_savings_kwp - optimum_kwp) * bias, 2
                        )
                    else:
                        analysis_power_kwp = optimum_kwp

    if abs(analysis_power_kwp - req.peak_power_kwp) > 1e-9:
        optimal = _scale_system(optimal, analysis_power_kwp, req.peak_power_kwp)
        if user_system is not None:
            user_system = _scale_system(user_system, analysis_power_kwp, req.peak_power_kwp)
    selected = user_system or optimal

    # La serie horaria (pedida a 1 kWp) se reescala a la producción del sistema
    # analizado que se muestra en producción, ahorro y payback.
    if hourly_production is not None:
        hourly_production = _normalize_hourly_profile(
            hourly_production, selected["annual_production_kwh"]
        )

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
        # cons_profile ya se construyó en el bloque de dimensionado (mismo perfil)
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
            battery_discharge_price_eur_kwh=battery_discharge_price,
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
                battery_discharge_price_eur_kwh=battery_discharge_price,
            )
            for s in scenarios
        }
        base_analysis = None
        for s in scenarios:
            analysis = cashflow.cashflow_analysis(
                scenario_yearly[s["battery_kwh"]],
                investment_eur=s["investment_eur"],
                subsidy_eur=subsidy,
                om_eur_per_year=om_eur,
                replacements=replacements,
            )
            # payback_years = del SISTEMA COMPLETO (multi-año); se muestra como
            # columna aparte. El payback INCREMENTAL de la batería (simple) lo
            # calcula battery_scenarios y NO se sobrescribe aquí.
            s["payback_years"] = analysis["payback_years"]
            s["npv_eur"] = analysis["npv_eur"]
            if s["battery_kwh"] == 0:
                base_analysis = analysis
        warranty_years = settings.battery_warranty_years
        useful_life_years = settings.battery_useful_life_years
        recommended_kwh, recommendation = _battery_recommendation(
            scenarios, useful_life_years
        )
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
        # Techo estructural del valor de CUALQUIER batería: solo puede desplazar
        # el excedente actual del precio de exportación al coste marginal evitado.
        base_surplus = base_scenario["exported_kwh"]
        max_battery_value = round(
            max(0.0, base_surplus * (effective_price - effective_surplus)), 0
        )
        battery_analysis = {
            "scenarios": scenarios,
            "recommended_battery_kwh": recommended_kwh,
            "recommendation": recommendation,
            "battery_warranty_years": warranty_years,
            "battery_useful_life_years": useful_life_years,
            "base_self_consumption_pct": base_scenario["self_consumption_pct"],
            "base_surplus_kwh": base_surplus,
            "max_battery_value_eur": max_battery_value,
            "marginal_avoided_cost_eur_kwh": effective_price,
            "export_scheme": export_scheme,
            "surplus_price_eur_kwh": surplus_price,
            "battery_cost_per_kwh_eur": battery_cost_per_kwh,
            "battery_cost_range_eur_per_kwh": cost_details[
                "battery_cost_per_kwh"
            ],
        }
        # Autosuficiencia estacional (misma fuente horaria; sin re-simular):
        # revela la baja cobertura invernal que el % anual esconde.
        winter_ss, summer_ss = _seasonal_self_sufficiency(hourly_production, cons_profile)
        annual_energy["winter_self_sufficiency_pct"] = winter_ss
        annual_energy["summer_self_sufficiency_pct"] = summer_ss
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
    # --- Fuente única del sistema recomendado (REFACTOR K) ---
    # Todo lo que muestra el "sistema recomendado" (tarjeta de paneles, titular)
    # se deriva de este objeto, calculado UNA vez a la potencia analizada. Nada
    # se recalcula por separado en el frontend.
    recommended_system = None
    if panels is not None:
        panel_count = max(1, round(analysis_power_kwp * 1000 / req.panel_power_w))
        installed_kwp = round(analysis_power_kwp, 2)
        coverage_ratio = _coverage_pct(
            selected["annual_production_kwh"], annual_consumption
        )
        recommended_system = {
            "kwp": installed_kwp,
            "panel_count": panel_count,
            "panel_power_w": req.panel_power_w,
            "inverter_kw": installed_kwp,
            "annual_production_kwh": selected["annual_production_kwh"],
            "roof_area_m2": round(panel_count * 2.2 * 1.15, 1),
            "self_consumption_pct": annual_energy.get("self_consumption_pct"),
            "self_sufficiency_pct": annual_energy.get("self_sufficiency_pct"),
            "savings_per_year_eur": savings,
            "payback_years": payback,
            "roi_pct": roi_pct,
            "production_to_consumption_pct": coverage_ratio,
            "scenario_name": (
                "economic_optimum"
                if sizing_analysis and req.auto_size_power
                else "as_entered"
            ),
        }
        # La tarjeta de paneles se DERIVA del sistema recomendado (no del tamaño
        # de cobertura del 100%): así no puede contradecir al titular.
        panels = {
            "count": panel_count,
            "total_kwp": installed_kwp,
            "needed_kwp": coverage_kwp,
            "panel_power_w": req.panel_power_w,
            "roof_area_m2": recommended_system["roof_area_m2"],
            "coverage_pct": coverage_ratio,
            "production_to_consumption_pct": coverage_ratio,
        }
        panels["explanation"] = _panels_explanation(panels)

    _validate_estimate_consistency(
        selected=selected,
        annual_energy=annual_energy,
        economics=economics,
        panels=panels,
        analysis_power_kwp=analysis_power_kwp,
    )

    # Aviso informativo de límites de red: recomendar un inversor que roza o
    # supera la potencia contratada o el techo de la tarifa 2.0TD (15 kW) tiene
    # consecuencias (límites de inyección, tipo de trámite de conexión).
    TARIFF_THRESHOLD_KW = 15.0  # techo de la tarifa 2.0TD (por encima → 3.0TD)
    grid_limits = None
    contracted_power_kw = (consumption_summary or {}).get("contracted_power_kw")
    if contracted_power_kw:
        # Marca cada escenario de tamaño que roza/supera la potencia contratada o
        # el techo 2.0TD (implica cambio de tarifa y de trámite de conexión).
        if sizing_analysis:
            for scenario in sizing_analysis["scenarios"]:
                p = scenario["power_kwp"]
                scenario["exceeds_contracted"] = p > contracted_power_kw
                scenario["exceeds_tariff"] = p > TARIFF_THRESHOLD_KW
        candidate_powers = [analysis_power_kwp]
        if sizing_analysis:
            candidate_powers.append(sizing_analysis["max_savings_kwp"])
        if panels:
            candidate_powers.append(panels["total_kwp"])
        recommended_power = max(candidate_powers)
        if recommended_power >= contracted_power_kw or recommended_power >= 0.9 * TARIFF_THRESHOLD_KW:
            grid_limits = {
                "contracted_power_kw": contracted_power_kw,
                "tariff_threshold_kw": TARIFF_THRESHOLD_KW,
                "recommended_power_kwp": round(recommended_power, 2),
                "exceeds_contracted": recommended_power > contracted_power_kw,
                "exceeds_tariff": recommended_power > TARIFF_THRESHOLD_KW,
            }

    # --- Objeto de ayudas para la respuesta (headline = sistema recomendado) ---
    subsidies_info = None
    if subsidy_record and annual_consumption is not None:
        head = subsidies_mod.compute_subsidy(
            subsidy_record,
            power_kwp=analysis_power_kwp,
            system_cost_eur=cost,
            today=subsidy_today,
        )
        subsidies_info = {
            "region": subsidy_region,
            "organismo": head.get("organismo"),
            "status": head["status"],
            "applicable": head["applicable"],
            "verified_on": head.get("verified_on"),
            "source_url": head.get("source_url"),
            "grant_eur": head["grant_eur"],
            "irpf": head.get("irpf"),
        }

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
        recommended_system=recommended_system,
        consumption=consumption_summary,
        annual_energy=annual_energy,
        battery_analysis=battery_analysis,
        sizing_analysis=sizing_analysis,
        subsidies=subsidies_info,
        grid_limits=grid_limits,
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
