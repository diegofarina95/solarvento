"""Layer 3 — normalización determinista + validación del contrato de extracción.

Convierte el contrato tipado que PROPONE el modelo (bill_contract) en el dict que
consume el calculador (forma de ParsedBill), aplicando las guardas que DISPONEN:
  - normalización española única (safe_to_float) sobre CADA raw_text;
  - reconciliación de las varias fuentes de consumo (corrige o deja en revisión);
  - plausibilidad de precio efectivo.
El modelo nunca elige "el" total ni normaliza números: eso pasa aquí, determinista.
"""

from __future__ import annotations

from typing import Any

from . import bills

# Confianza por debajo de la cual un candidato de consumo se considera dudoso y,
# si además no hay reconciliación, empuja a revisión.
_LOW_CONFIDENCE = 0.4


def _norm(field: Any) -> dict[str, Any]:
    """Normaliza un sobre numérico {raw_text,value,source_label,confidence}.

    value = safe_to_float(raw_text) (determinista); si el recibo ya imprimía un
    número plano y no hay raw_text, se acepta ese value. Devuelve el sobre con
    `value` resuelto (para la reconciliación y para mostrarlo en revisión)."""
    if not isinstance(field, dict):
        return {"raw_text": None, "value": None, "source_label": None, "confidence": None}
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


def _val(field: Any) -> float | None:
    return _norm(field)["value"]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _periods(split: Any) -> dict[str, float]:
    if not isinstance(split, dict):
        return {}
    mapping = {"p1_punta": "punta", "p2_llano": "llano", "p3_valle": "valle"}
    out: dict[str, float] = {}
    for key, canonical in mapping.items():
        value = _val(split.get(key))
        if value is not None and 0 < value <= bills.MAX_BILL_KWH:
            out[canonical] = value
    return out


def _period_prices(split: Any) -> dict[str, float]:
    if not isinstance(split, dict):
        return {}
    mapping = {"p1_punta": "punta", "p2_llano": "llano", "p3_valle": "valle"}
    out: dict[str, float] = {}
    for key, canonical in mapping.items():
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


def _consumption_candidates(contract: dict) -> list[dict[str, Any]]:
    """Cada candidato de consumo con su origen y raw_text, para mostrarlo en revisión."""
    candidates: list[dict[str, Any]] = []

    def add(label: str, field: Any) -> None:
        norm = _norm(field)
        if norm["raw_text"] is not None or norm["value"] is not None:
            candidates.append({"candidate": label, **norm})

    add("headline", contract.get("annual_consumption_kwh"))
    add("period_total_printed", contract.get("period_total_kwh"))
    split = contract.get("period_split") or {}
    for key in ("p1_punta", "p2_llano", "p3_valle"):
        add(f"period_{key}", split.get(key) if isinstance(split, dict) else None)
    history = _history(contract.get("monthly_history"))
    if history:
        candidates.append({
            "candidate": "monthly_history_sum",
            "raw_text": None,
            "value": round(sum(h["kwh"] for h in history), 1),
            "source_label": f"{len(history)} filas de histórico mensual",
            "confidence": None,
        })
    return candidates


def _min_consumption_confidence(contract: dict) -> float | None:
    confidences: list[float] = []
    for field in (contract.get("annual_consumption_kwh"), contract.get("period_total_kwh")):
        if isinstance(field, dict) and isinstance(field.get("confidence"), (int, float)):
            confidences.append(float(field["confidence"]))
    return min(confidences) if confidences else None


def contract_to_bill(contract: dict) -> dict:
    """Contrato del modelo → dict de factura (forma ParsedBill) ya normalizado y validado.

    Devuelve el dict con needs_review/review_reasons/consumption_candidates listos:
    si las fuentes de consumo reconcilian y el precio efectivo es plausible, calcula;
    si no, queda en estado de revisión con los candidatos a la vista."""
    if not isinstance(contract, dict):
        return _review_bill(["El extractor no devolvió un contrato válido."], [])

    warnings = [str(w) for w in (contract.get("warnings") or []) if str(w).strip()]
    address = contract.get("supply_address") or {}
    billing = contract.get("billing_period") or {}

    total = _val(contract.get("total_amount_eur"))
    bill: dict[str, Any] = {
        "kwh": _val(contract.get("annual_consumption_kwh")),
        "period_total_kwh": _val(contract.get("period_total_kwh")),
        "consumption_periods": _periods(contract.get("period_split")) or None,
        "consumption_period_prices": _period_prices(contract.get("period_split_prices")) or None,
        "consumption_history": _history(contract.get("monthly_history")),
        "contracted_power_kw": _val(contract.get("contracted_power_kw")),
        "energy_eur": _val(contract.get("energy_term_eur")),
        "total_eur": total,
        "amount_eur": total,
        "iee_eur": _val(contract.get("electricity_tax_eur")),
        "iva_eur": _val(contract.get("vat_eur")),
        "iva_rate": _val(contract.get("vat_rate")),
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
        "parser": "openai-contract",
    }

    candidates = _consumption_candidates(contract)

    # Reconciliación (corrige la fuente que discrepe) + guarda de precio efectivo.
    corrected_kwh, note, review = bills.reconcile_annual_consumption(bill)
    bill["kwh"] = corrected_kwh
    if note:
        warnings.append(note)
    review = review + bills.validate_bill_consumption(bill)

    # Campo crítico ausente o de baja confianza sin reconciliar → revisión.
    if bill["kwh"] is None:
        review.append("No se detectó el consumo anual; revísalo.")
    else:
        min_conf = _min_consumption_confidence(contract)
        if note is None and min_conf is not None and min_conf < _LOW_CONFIDENCE and len(
            [c for c in candidates if c["value"]]
        ) < 2:
            review.append(
                f"Baja confianza en el consumo ({min_conf:.0%}) y sin otra fuente que lo "
                "corrobore; confírmalo."
            )

    bill["consumption_candidates"] = candidates
    bill["needs_review"] = bool(review)
    bill["review_reasons"] = review
    if review:
        warnings.extend(review)
    bill["warnings"] = _dedupe(warnings)
    return bill


def _review_bill(reasons: list[str], candidates: list[dict]) -> dict:
    return {
        "kwh": None,
        "parser": "openai-contract",
        "consumption_candidates": candidates,
        "needs_review": True,
        "review_reasons": reasons,
        "warnings": list(reasons),
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
