"""Almacén de programaciones de publicación del blog (portal).

Un JSON plano en la raíz del repo (gitignored, como .env): una entrada por
grupo de artículo, clave = stem (nombre en disco). Estados:

- pending: esperando su hora.
- stale:   la hora pasó ANTES de arrancar el servicio (portal caído en T);
           espera confirmación manual en el dashboard.
- error:   un intento de publicar falló; guarda el mensaje y espera manual.

Sin dependencias del portal: piezas puras sobre disco, fáciles de testear.
Diseño: docs/superpowers/specs/2026-07-07-blog-scheduled-publishing-design.md
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE_FILE = REPO_ROOT / ".blog-schedule.json"

STATES = ("pending", "stale", "error")


def parse_local(value: str | None) -> datetime | None:
    """Hora naive local en formato datetime-local (YYYY-MM-DDTHH:MM)."""
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def load() -> dict[str, dict]:
    """Lee el archivo tolerando corrupción: lo ilegible se trata como vacío."""
    try:
        data = json.loads(SCHEDULE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for stem, entry in data.items():
        if (
            isinstance(entry, dict)
            and parse_local(entry.get("publish_at")) is not None
            and entry.get("state") in STATES
        ):
            out[stem] = {
                "publish_at": entry["publish_at"],
                "state": entry["state"],
                "error": entry.get("error"),
            }
    return out


def _save(data: dict[str, dict]) -> None:
    tmp = SCHEDULE_FILE.with_name(SCHEDULE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(SCHEDULE_FILE)  # escritura atómica: nunca medio archivo


def get(stem: str) -> dict | None:
    return load().get(stem)


def set_schedule(stem: str, publish_at: str) -> None:
    """Crea o sobrescribe (reprogramar limpia stale/error)."""
    data = load()
    data[stem] = {"publish_at": publish_at, "state": "pending", "error": None}
    _save(data)


def remove(stem: str) -> None:
    data = load()
    if stem in data:
        del data[stem]
        _save(data)


def due(now: datetime) -> list[str]:
    """Stems pending cuya hora ya llegó, en orden estable."""
    return sorted(
        stem
        for stem, entry in load().items()
        if entry["state"] == "pending" and parse_local(entry["publish_at"]) <= now
    )


def mark_stale_before(boot: datetime) -> None:
    """Al arrancar: lo que venció con el portal caído espera confirmación manual."""
    data = load()
    changed = False
    for entry in data.values():
        if entry["state"] == "pending" and parse_local(entry["publish_at"]) < boot:
            entry["state"] = "stale"
            changed = True
    if changed:
        _save(data)


def mark_error(stem: str, message: str) -> None:
    data = load()
    if stem in data:
        data[stem]["state"] = "error"
        data[stem]["error"] = message
        _save(data)
