"""Layer 3+5+6 — normalización determinista, reconciliación like-with-like y ruteo.

Convierte el contrato que PROPONE el modelo en el dict que consume el calculador
(forma de ParsedBill). Guardas que DISPONEN:
  - normalización española única (safe_to_float) sobre CADA raw_text;
  - reconciliación LIKE-WITH-LIKE del consumo de ESTA factura (columnas de periodo
    vs total de periodo vs cabecera vs diferencia de lecturas) — NO contra el anual;
  - resolución del ANUAL por separado (bill_resolver, Layer 4);
  - precio efectivo con importe÷consumo emparejados (periodo÷periodo o anual÷anual);
  - ruteo de autoconsumo existente (Layer 6): no dimensionar sobre consumo de red.
El resolutor UNIFICA: el resto de la app consume annual_kwh + splits.
"""

from __future__ import annotations

import logging
from typing import Any

from . import bill_messages, bill_resolver, bills

logger = logging.getLogger(__name__)

_LOW_CONFIDENCE = 0.4
# 2.0TD residencial: P1 punta / P2 llano / P3 valle.
_PERIOD_MAP = {"p1_punta": "punta", "p2_llano": "llano", "p3_valle": "valle"}
_PROFILE_PERIODS = ("punta", "llano", "valle")


def _norm(field: Any) -> dict[str, Any]:
    """Normaliza un campo numérico con safe_to_float.

    Acepta el formato actual (STRING verbatim, p. ej. "6.551") y, por
    compatibilidad, el sobre antiguo {raw_text,value,source_label,confidence}."""
    if field is None:
        return {"raw_text": None, "value": None, "source_label": None, "confidence": None}
    if isinstance(field, (str, int, float)):
        raw = None if field == "" else field
        return {
            "raw_text": raw if isinstance(raw, str) else (str(raw) if raw is not None else None),
            "value": bills.safe_to_float(raw),
            "source_label": None,
            "confidence": None,
        }
    if isinstance(field, dict):
        raw = field.get("raw_text")
        value = bills.safe_to_float(raw) if raw not in (None, "") else None
        if value is None and isinstance(field.get("value"), (int, float)):
            value = float(field["value"])
        return {
            "raw_text": raw,
            "value": value,
            "source_label": field.get("source_label"),
            "confidence": field.get("confidence"),
        }
    return {"raw_text": None, "value": None, "source_label": None, "confidence": None}


def _val(field: Any) -> float | None:
    return _norm(field)["value"]


def _rate(field: Any) -> float | None:
    """Tipo impositivo como FRACCIÓN. "21" o "21%" → 0,21; "0,21" → 0,21.

    El modelo transcribe el IVA tal cual ("21%"), así que un valor >1 es un
    porcentaje. Fuera de un rango sensato (0–0,5) se descarta para no romper el
    cálculo: el backend usa los tipos normativos si falta."""
    value = _val(field)
    if value is None:
        return None
    if value > 1:
        value = value / 100
    return round(value, 4) if 0 <= value <= 0.5 else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _all_periods(split: Any) -> dict[str, float]:
    """Todos los periodos presentes (P1..P6) normalizados, ceros/nulos ignorados."""
    if not isinstance(split, dict):
        return {}
    out: dict[str, float] = {}
    for key, canonical in _PERIOD_MAP.items():
        value = _val(split.get(key))
        if value is not None and 0 < value <= bills.MAX_BILL_KWH:
            out[canonical] = value
    return out


def _period_prices(split: Any) -> dict[str, float]:
    if not isinstance(split, dict):
        return {}
    out: dict[str, float] = {}
    for key, canonical in _PERIOD_MAP.items():
        if canonical not in _PROFILE_PERIODS:
            continue
        value = _val(split.get(key))
        if value is not None and 0 < value <= 10:
            out[canonical] = value
    return out


def _history(rows: Any) -> list[dict[str, float]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, float]] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        month = row.get("month")
        kwh = _val(row.get("kwh"))
        if isinstance(month, int) and 1 <= month <= 12 and month not in seen:
            if kwh is not None and 0 < kwh <= bills.MAX_BILL_KWH:
                out.append({"month": month, "kwh": kwh})
                seen.add(month)
    return sorted(out, key=lambda r: r["month"])


def _power_max(value: Any) -> float | None:
    """Potencia contratada: array de sobres → la mayor (o un sobre suelto)."""
    if isinstance(value, list):
        powers = [v for v in (_val(f) for f in value) if v and v > 0]
        return max(powers) if powers else None
    return _val(value)


def _meter_diff(readings: Any) -> float | None:
    """Consumo por diferencia de lecturas (nunca una lectura suelta como consumo)."""
    if not isinstance(readings, dict):
        return None
    initial, final = _val(readings.get("initial")), _val(readings.get("final"))
    if initial is None or final is None:
        return None
    diff = final - initial
    return diff if 0 < diff <= bills.MAX_BILL_KWH else None


def _period_meter_diffs(readings: Any) -> dict[str, float]:
    """Reparto punta/llano/valle por DIFERENCIA de lecturas por periodo.

    Si el contador es por periodo (P1/P2/P3 con su propia lectura anterior/actual),
    el consumo de cada periodo = final − inicial. Es una fuente dura del reparto,
    no una estimación."""
    if not isinstance(readings, dict):
        return {}
    out: dict[str, float] = {}
    for prefix, canonical in (("p1", "punta"), ("p2", "llano"), ("p3", "valle")):
        initial = _val(readings.get(f"{prefix}_initial"))
        final = _val(readings.get(f"{prefix}_final"))
        if initial is None or final is None:
            continue
        diff = final - initial
        if 0 < diff <= bills.MAX_BILL_KWH:
            out[canonical] = round(diff, 1)
    return out


def _reconcile_period(sources: dict[str, float], profile_periods: dict) -> tuple[float | None, str | None, list[str]]:
    """Reconciliación LIKE-WITH-LIKE del consumo de ESTA factura.

    Corrobora entre sí las lecturas del MISMO periodo (cabecera, total de periodos,
    suma de columnas, diferencia de lecturas). ≥2 coincidentes mandan; una sola
    columna tomada por total se repara; sin corroboración y con discrepancia →
    revisión. NUNCA mezcla el anual aquí (eso lo hace el resolutor)."""
    values = list(sources.values())
    authoritative: float | None = None
    best = 1
    for candidate in values:
        agree = [w for w in values if bills._values_close(candidate, w)]
        if len(agree) >= 2 and len(agree) > best:
            authoritative = round(sum(agree) / len(agree), 1)
            best = len(agree)

    head = sources.get("headline")
    if authoritative is None:
        matches_single = any(
            bills._values_close(head, v) for v in profile_periods.values()
        )
        period_total = sources.get("period_total_printed") or sources.get("period_sum")
        if period_total and matches_single and period_total > (head or 0) * 1.2:
            authoritative = period_total

    if authoritative is None:
        if len(sources) >= 2:
            detail = ", ".join(f"{k}={v:.0f}" for k, v in sources.items())
            return (
                head if head else (values[0] if values else None),
                None,
                [bill_messages.note("sources_disagree", detail=detail)],
            )
        return (values[0] if values else None), None, []

    note = None
    if head is None or not bills._values_close(head, authoritative):
        note = bill_messages.note(
            "consumption_corrected", value=authoritative, detected=head
        )
    return authoritative, note, []


def _consumption_candidates(contract: dict, period_sum: float | None, meter_diff: float | None,
                            history: list, meter_period_sum: float | None = None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def add(label, field):
        norm = _norm(field)
        if norm["raw_text"] is not None or norm["value"] is not None:
            candidates.append({"candidate": label, **norm})

    add("headline", contract.get("annual_consumption_kwh"))
    add("period_total_printed", contract.get("period_total_kwh"))
    split = contract.get("period_split") or {}
    for key in ("p1_punta", "p2_llano", "p3_valle", "p4", "p5", "p6"):
        add(f"period_{key}", split.get(key) if isinstance(split, dict) else None)
    if period_sum:
        candidates.append({"candidate": "period_sum", "raw_text": None, "value": period_sum,
                           "source_label": "suma de columnas de periodo", "confidence": None})
    if meter_period_sum:
        candidates.append({"candidate": "period_meter_sum", "raw_text": None,
                           "value": meter_period_sum,
                           "source_label": "suma de diferencias de lectura por periodo",
                           "confidence": None})
    if meter_diff:
        candidates.append({"candidate": "meter_diff", "raw_text": None, "value": meter_diff,
                           "source_label": "lectura final - inicial", "confidence": None})
    if history:
        candidates.append({"candidate": "monthly_history_sum", "raw_text": None,
                           "value": round(sum(h["kwh"] for h in history), 1),
                           "source_label": f"{len(history)} filas de histórico mensual",
                           "confidence": None})
    return candidates


def _min_confidence(contract: dict) -> float | None:
    confs = []
    for field in (contract.get("annual_consumption_kwh"), contract.get("period_total_kwh")):
        if isinstance(field, dict) and isinstance(field.get("confidence"), (int, float)):
            confs.append(float(field["confidence"]))
    return min(confs) if confs else None


def contract_to_bill(contract: dict) -> dict:
    """Contrato del modelo → dict de factura (ParsedBill) normalizado, reconciliado y ruteado."""
    if not isinstance(contract, dict):
        return _review_bill([bill_messages.note("extractor_invalid")])

    # Avisos del MODELO (texto libre): son RAZONAMIENTO interno del extractor
    # ("the schema has single meter fields, so...", "el IVA se transcribe sin el
    # símbolo"...). NUNCA se muestran al usuario; solo se registran para depurar.
    # A la UI solo llegan avisos tipados (códigos del catálogo, traducidos).
    model_notes = [str(w) for w in (contract.get("warnings") or []) if str(w).strip()]
    if model_notes:
        logger.info("Extractor notes (not shown to user): %s", " | ".join(model_notes))
    warning_notes: list[dict] = []
    review_notes: list[dict] = []
    address = contract.get("supply_address") or {}
    billing = contract.get("billing_period") or {}

    all_periods = _all_periods(contract.get("period_split"))
    # Reparto por diferencia de lecturas por periodo (fuente dura, no estimada).
    # Si faltan columnas de periodo, se rellena con estas; el split impreso manda.
    meter_periods = _period_meter_diffs(contract.get("meter_readings"))
    merged_periods = {**meter_periods, **all_periods}
    profile_periods = {k: v for k, v in merged_periods.items() if k in _PROFILE_PERIODS}
    period_sum = round(sum(all_periods.values()), 1) if all_periods else None
    # Total por suma de lecturas por periodo (solo si están los 3 periodos).
    meter_period_sum = (
        round(sum(meter_periods.values()), 1) if len(meter_periods) >= 3 else None
    )
    meter_diff = _meter_diff(contract.get("meter_readings"))
    history = _history(contract.get("monthly_history"))
    total = _val(contract.get("total_amount_eur"))
    days = _val((billing or {}).get("days"))

    # (Layer 5) Reconciliación like-with-like del consumo de ESTA factura.
    period_sources: dict[str, float] = {}
    headline = _val(contract.get("annual_consumption_kwh"))
    if headline:
        period_sources["headline"] = headline
    printed_total = _val(contract.get("period_total_kwh"))
    if printed_total:
        period_sources["period_total_printed"] = printed_total
    if period_sum:
        period_sources["period_sum"] = period_sum
    if meter_period_sum:
        period_sources["period_meter_sum"] = meter_period_sum
    if meter_diff:
        period_sources["meter_diff"] = meter_diff
    bill_period_kwh, recon_note, recon_review = _reconcile_period(period_sources, profile_periods)
    if recon_note:
        warning_notes.append(recon_note)
    review_notes.extend(recon_review)

    # (Layer 6) Autoconsumo REAL, no la línea de plantilla. "Compensación de
    # excedentes 0,00 €" sale en TODAS las facturas reguladas sin placas; solo
    # hay autoconsumo si hay excedente vertido (>0 kWh) o compensación (>0 €).
    sc_block = contract.get("self_consumption_block") or {}
    sc_exported = _val(sc_block.get("exported_kwh"))
    sc_compensated = _val(sc_block.get("compensated_eur"))
    existing_pv = bool((sc_exported and sc_exported > 0) or (sc_compensated and sc_compensated > 0))

    # (Layer 5) Bono social: el precio efectivo puede ser legítimamente muy bajo.
    bono_social = bool(contract.get("bono_social"))

    bill: dict[str, Any] = {
        "kwh": bill_period_kwh,
        "period_total_kwh": printed_total,
        "consumption_periods": profile_periods or None,
        "consumption_period_prices": _period_prices(contract.get("period_split_prices")) or None,
        "consumption_history": history,
        "contracted_power_kw": _power_max(contract.get("contracted_power_kw")),
        "energy_eur": _val(contract.get("energy_term_eur")),
        "total_eur": total,
        "amount_eur": total,
        "iee_eur": _val(contract.get("electricity_tax_eur")),
        "iva_eur": _val(contract.get("vat_eur")),
        "iva_rate": _rate(contract.get("vat_rate")),
        "currency": (_text(contract.get("currency")) or "").upper()[:3] or None,
        "country_code": (_text(contract.get("country_code")) or "").upper()[:2] or None,
        "language": _text(contract.get("language")),
        "tariff": _text(contract.get("tariff")),
        "cups": _text(contract.get("cups")),
        "supply_address": _text(address.get("street")),
        "postal_code": _text(address.get("cp")),
        "city": _text(address.get("municipio")),
        "region": _text(address.get("provincia")),
        "start_date": _text(billing.get("start")),
        "end_date": _text(billing.get("end")),
        "existing_pv": existing_pv,
        "bono_social": bono_social,
        "parser": "openai-contract",
    }

    # (Layer 4) Resolutor del ANUAL — anual impreso > histórico > declarado > estimación.
    rolling_annual = _val(contract.get("rolling_annual_kwh"))
    if rolling_annual is not None and not (0 < rolling_annual <= bills.MAX_BILL_KWH):
        rolling_annual = None
    bill["rolling_annual_kwh"] = rolling_annual
    resolution = bill_resolver.resolve_annual_consumption(
        bill_period_kwh=bill_period_kwh,
        history=history,
        start=bill["start_date"],
        end=bill["end_date"],
        days=days,
        bill_type_hint=_text(contract.get("bill_type_hint")),
        rolling_annual_kwh=rolling_annual,
    )
    bill["consumption_resolution"] = {
        "annual_kwh": resolution["annual_kwh"],
        "method": resolution["method"],
        "months_real": resolution["months_real"],
        "confidence": resolution["confidence"],
        "single_month": resolution.get("single_month", False),
        "monthly_kwh": bill_period_kwh if resolution.get("single_month") else None,
    }

    # (Layer 5) Precio efectivo LIKE-WITH-LIKE: importe de la factura ÷ consumo de
    # la MISMA factura (kwh ya es el del propio periodo, no el anual).
    review_notes.extend(bills.validate_bill_consumption(bill))

    # (Layer 4) Sin consumo anual resoluble → revisión.
    if resolution["annual_kwh"] is None:
        review_notes.append(bill_messages.note("no_annual_resolved"))
    elif resolution.get("single_month"):
        # Una sola factura mensual NO permite dimensionar con fiabilidad: la
        # estacionalidad (calefacción/AA) hace que un mes no represente el año.
        warning_notes.append(bill_messages.note("single_month"))
    elif resolution["confidence"] == "low":
        warning_notes.append(
            bill_messages.note("estimate_few_months", months=resolution["months_real"])
        )

    # Baja confianza del modelo sin corroboración → revisión.
    if bill_period_kwh is not None:
        min_conf = _min_confidence(contract)
        corroborated = len([v for v in period_sources.values()]) >= 2 or recon_note is not None
        if min_conf is not None and min_conf < _LOW_CONFIDENCE and not corroborated:
            review_notes.append(
                bill_messages.note("low_confidence_consumption", conf=min_conf)
            )

    # (Layer 6) Autoconsumo existente: no dimensionar sobre el consumo de red.
    if existing_pv:
        review_notes.append(bill_messages.note("existing_pv"))

    # (Layer 5) Bono social: aviso de que el ahorro puede ser bajo (precio ya
    # subvencionado); si se pierde el bono, el solar compensa más.
    if bono_social:
        warning_notes.append(bill_messages.note("bono_social_savings"))

    bill["consumption_candidates"] = _consumption_candidates(
        contract, period_sum, meter_diff, history, meter_period_sum
    )
    review = [bill_messages.text_es(n["code"], **n["params"]) for n in review_notes]
    bill["needs_review"] = bool(review_notes)
    bill["review_reasons"] = review
    bill["review_notes"] = review_notes
    # Estado explícito (máquina de 3 estados). VALID solo si hay consumo anual
    # resuelto Y ninguna guarda objeta.
    if resolution["annual_kwh"] is None and not review_notes:
        bill["state"] = "extraction_failed"
    else:
        bill["state"] = "needs_review" if review_notes else "valid"
    # warning_notes = SOLO avisos informativos (el frontend los muestra aparte de
    # los de revisión). El texto `warnings` (logs/compat) los junta con los de
    # revisión, como hasta ahora.
    bill["warning_notes"] = warning_notes
    bill["warnings"] = _dedupe(
        [bill_messages.text_es(n["code"], **n["params"]) for n in warning_notes + review_notes]
    )
    return bill


def _review_bill(notes: list[dict]) -> dict:
    reasons = [bill_messages.text_es(n["code"], **n["params"]) for n in notes]
    return {
        "kwh": None,
        "parser": "openai-contract",
        "existing_pv": False,
        "consumption_candidates": [],
        "consumption_resolution": None,
        "state": "extraction_failed",
        "needs_review": True,
        "review_reasons": reasons,
        "review_notes": notes,
        "warnings": list(reasons),
        "warning_notes": notes,
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
