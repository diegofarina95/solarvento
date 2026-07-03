"""Motor de ayudas autonómicas al autoconsumo (config versionada en subsidies.yaml).

Genérico; poblado solo Galicia (y de momento sin importes verificados). Disciplina
como la guarda fiscal: si la convocatoria no está abierta/verificada o venció, NO
se aplica ninguna ayuda y se muestra "consultar" — nunca una cifra inventada.

Tres capas SEPARADAS:
  (a) subvención autonómica → reduce inversión neta inicial (por escenario).
  (b) deducción IRPF → flujo recuperado en años, sobre base limitada neta de (a).
  (c) IBI/ICIO municipal → v1: nota, no cálculo.
"""

from __future__ import annotations

import functools
from datetime import date
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "subsidies.yaml"

# CP (2 primeros dígitos) → comunidad autónoma. La primera cifra del CP fija la
# provincia (01–52) y de ahí la comunidad.
_CP2_TO_REGION: dict[str, str] = {
    "01": "PAIS_VASCO", "20": "PAIS_VASCO", "48": "PAIS_VASCO",
    "02": "CASTILLA_LA_MANCHA", "13": "CASTILLA_LA_MANCHA", "16": "CASTILLA_LA_MANCHA",
    "19": "CASTILLA_LA_MANCHA", "45": "CASTILLA_LA_MANCHA",
    "03": "COMUNIDAD_VALENCIANA", "12": "COMUNIDAD_VALENCIANA", "46": "COMUNIDAD_VALENCIANA",
    "04": "ANDALUCIA", "11": "ANDALUCIA", "14": "ANDALUCIA", "18": "ANDALUCIA",
    "21": "ANDALUCIA", "23": "ANDALUCIA", "29": "ANDALUCIA", "41": "ANDALUCIA",
    "05": "CASTILLA_Y_LEON", "09": "CASTILLA_Y_LEON", "24": "CASTILLA_Y_LEON",
    "34": "CASTILLA_Y_LEON", "37": "CASTILLA_Y_LEON", "40": "CASTILLA_Y_LEON",
    "42": "CASTILLA_Y_LEON", "47": "CASTILLA_Y_LEON", "49": "CASTILLA_Y_LEON",
    "06": "EXTREMADURA", "10": "EXTREMADURA",
    "07": "BALEARES",
    "08": "CATALUNA", "17": "CATALUNA", "25": "CATALUNA", "43": "CATALUNA",
    "15": "GALICIA", "27": "GALICIA", "32": "GALICIA", "36": "GALICIA",
    "22": "ARAGON", "44": "ARAGON", "50": "ARAGON",
    "26": "LA_RIOJA",
    "28": "MADRID",
    "30": "MURCIA",
    "31": "NAVARRA",
    "33": "ASTURIAS",
    "35": "CANARIAS", "38": "CANARIAS",
    "39": "CANTABRIA",
    "51": "CEUTA", "52": "MELILLA",
}


def region_from_postal_code(postal_code: str | None) -> str | None:
    """Comunidad autónoma a partir del CP español; None si no es válido."""
    if not postal_code:
        return None
    digits = "".join(ch for ch in str(postal_code) if ch.isdigit())
    if len(digits) < 4:
        return None
    return _CP2_TO_REGION.get(digits[:2].zfill(2))


@functools.lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_region_record(region_code: str | None, config: dict | None = None) -> dict | None:
    """Registro de la comunidad (o el marcador _default); None sin comunidad."""
    if not region_code:
        return None
    cfg = config if config is not None else _load_config()
    regions = cfg.get("regions", {})
    return regions.get(region_code) or regions.get("_default")


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def effective_status(record: dict, today: date) -> str:
    """Estado real hoy: unverified/closed/exhausted, expired (venció), not_yet o open."""
    status = (record.get("status") or "unverified").lower()
    if status in ("closed", "exhausted", "unverified"):
        return status
    end = _parse_date(record.get("window_end"))
    start = _parse_date(record.get("window_start"))
    if end and today > end:
        return "expired"
    if start and today < start:
        return "not_yet"
    # 'open' de verdad exige importes: sin €/kWp no hay nada que aplicar.
    if record.get("eur_per_kwp") in (None, ""):
        return "unverified"
    return "open"


def compute_subsidy(
    record: dict,
    *,
    power_kwp: float,
    system_cost_eur: float,
    battery_kwh: float = 0.0,
    today: date,
) -> dict:
    """Ayuda para UN escenario. GRANT=0 si no es aplicable (guarda de vigencia).

    El tope max_subsidised_kwp limita la potencia elegible, por lo que un sistema
    grande recibe menos por kWp efectivo que uno pequeño (favorece el óptimo).
    """
    status = effective_status(record, today)
    meta = {
        "status": status,
        "organismo": record.get("organismo"),
        "convocatoria_id": record.get("convocatoria_id"),
        "verified_on": record.get("verified_on"),
        "source_url": record.get("source_url"),
        "window_end": record.get("window_end"),
    }
    if status != "open":
        # Guarda: nada se aplica; se muestran los números SIN ayuda.
        return {**meta, "applicable": False, "grant_eur": 0.0, "eligible_kwp": 0.0, "irpf": None}

    eur_per_kwp = float(record["eur_per_kwp"])
    max_kwp = record.get("max_subsidised_kwp")
    eligible_kwp = min(power_kwp, float(max_kwp)) if max_kwp else power_kwp
    grant = eligible_kwp * eur_per_kwp
    battery_rate = record.get("eur_per_kwh_battery")
    if battery_rate:
        grant += battery_kwh * float(battery_rate)
    if record.get("cap_absolute_eur"):
        grant = min(grant, float(record["cap_absolute_eur"]))
    if record.get("cap_pct_of_cost"):
        grant = min(grant, float(record["cap_pct_of_cost"]) * system_cost_eur)
    grant = round(min(grant, system_cost_eur), 2)

    # Capa (b) IRPF: deducción sobre base limitada, NETA de la subvención (a),
    # recuperada en varios años. Se expone aparte, no se funde con la subvención.
    irpf = None
    if record.get("irpf_deduction_pct"):
        base = system_cost_eur - grant
        cap = record.get("irpf_base_cap_eur")
        if cap:
            base = min(base, float(cap))
        irpf = {
            "deduction_pct": float(record["irpf_deduction_pct"]),
            "recoverable_eur": round(max(0.0, base) * float(record["irpf_deduction_pct"]), 2),
            "years": record.get("irpf_years"),
        }
    return {
        **meta,
        "applicable": True,
        "grant_eur": grant,
        "eligible_kwp": round(eligible_kwp, 2),
        "irpf": irpf,
    }
