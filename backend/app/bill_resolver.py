"""Layer 4 — resolutor del consumo ANUAL (mata la suposición 'la factura es anual').

Una factura de un solo mes con el histórico de 12 meses embebido YA da un año real:
no hace falta pedir más. Una factura sub-anual es entrada NORMAL, no un error. La
prioridad es por MESES DE DATO REAL cubiertos, no por número de ficheros:

  1. histórico de 12 meses embebido → sumarlo (method="history", conf alta);
  2. total anual declarado (factura consolidada / periodo ~anual) → usarlo;
  3. varios ficheros → los fusiona aguas abajo aggregate_bills (mismo mapa 12m);
  4. pocos meses, sin histórico → estimación por perfil estacional (NO plano
     ×365/días, que sobreestima un periodo corto), method="annualised_estimate".

Umbral de confianza: ≥10 meses reales → alta; <10 → se calcula pero con aviso de
'estimación'. El resto de la app consume solo annual_kwh + splits.
"""

from __future__ import annotations

from datetime import date

from .profiles import DAYS_PER_MONTH, MONTHLY_WEIGHTS

HIGH_CONFIDENCE_MONTHS = 10


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        year, month, day = str(value).split("-")
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None


def _history_monthly_map(history: list[dict]) -> list[float]:
    """12 valores mes→kWh a partir del histórico (último dato gana por mes)."""
    monthly = [0.0] * 12
    for row in history:
        month = row.get("month")
        kwh = row.get("kwh")
        if isinstance(month, int) and 1 <= month <= 12 and isinstance(kwh, (int, float)):
            monthly[month - 1] = float(kwh)
    return monthly


def _seasonal_annualise(
    period_kwh: float, start: date | None, end: date | None, days: float | None
) -> tuple[float | None, float]:
    """Anualiza un periodo corto por PERFIL ESTACIONAL, no plano ×365/días.

    La cuota anual del periodo = suma de pesos diarios estacionales cubiertos /
    total. Un septiembre de 22 días no se extrapola como si todos los meses
    consumieran igual. Devuelve (annual_kwh|None, meses_reales)."""
    parts: list[tuple[int, float]] = []
    if start and end and end > start:
        current = start
        while current < end:
            month = current.month
            # días de este mes dentro del periodo
            if month == 12:
                month_end = date(current.year + 1, 1, 1)
            else:
                month_end = date(current.year, month + 1, 1)
            chunk_end = min(end, month_end)
            parts.append((month, (chunk_end - current).days))
            current = chunk_end
    if not parts:
        if days and days > 0:
            return round(period_kwh / days * 365.25, 1), round(days / 30.4, 1)
        return None, 0.0

    covered_weight = sum(
        MONTHLY_WEIGHTS[m - 1] / DAYS_PER_MONTH[m - 1] * d for m, d in parts
    )
    total_days = sum(d for _m, d in parts)
    if covered_weight <= 0:
        return None, 0.0
    annual = period_kwh / covered_weight * sum(MONTHLY_WEIGHTS)
    return round(annual, 1), round(total_days / 30.4, 1)


def resolve_annual_consumption(
    *,
    bill_period_kwh: float | None,
    history: list[dict],
    start=None,
    end=None,
    days: float | None = None,
    bill_type_hint: str | None = None,
) -> dict:
    """Resuelve el consumo anual y devuelve annual_kwh + method + months_real + confidence."""
    real_months = sorted({r["month"] for r in history if r.get("kwh")})
    start_d, end_d = _parse_date(start), _parse_date(end)
    if days is None and start_d and end_d:
        days = (end_d - start_d).days

    # 1) Histórico de 12 meses embebido: un año real en una sola factura.
    if len(real_months) >= 11:
        monthly_map = _history_monthly_map(history)
        return {
            "annual_kwh": round(sum(monthly_map), 1),
            "monthly_map": monthly_map,
            "months_real": len(real_months),
            "method": "history",
            "confidence": "high",
        }

    hint = (bill_type_hint or "").lower()
    # 2) Total anual declarado (consolidada / periodo ~anual).
    if bill_period_kwh and ((days and days >= 330) or "annual" in hint or "consolid" in hint):
        return {
            "annual_kwh": round(bill_period_kwh, 1),
            "monthly_map": None,
            "months_real": 12,
            "method": "declared_annual",
            "confidence": "high",
        }

    # Histórico parcial (algunos meses) → súmalo y anualiza por media mensual.
    if real_months:
        monthly_map = _history_monthly_map(history)
        observed = sum(monthly_map)
        if observed > 0:
            annual = round(observed / len(real_months) * 12, 1)
            return {
                "annual_kwh": annual,
                "monthly_map": monthly_map,
                "months_real": len(real_months),
                "method": "annualised_estimate",
                "confidence": "high" if len(real_months) >= HIGH_CONFIDENCE_MONTHS else "low",
            }

    # 4) Periodo corto con fechas → estimación estacional (no plano ×365/días).
    if bill_period_kwh and days and days < 330 and start_d and end_d:
        annual, months_real = _seasonal_annualise(bill_period_kwh, start_d, end_d, days)
        if annual:
            confidence = "high" if months_real >= HIGH_CONFIDENCE_MONTHS else "low"
            return {
                "annual_kwh": annual,
                "monthly_map": None,
                "months_real": months_real,
                "method": "annualised_estimate",
                "confidence": confidence,
            }

    # Sin fechas ni histórico no se puede detectar sub-anual: se asume que la cifra
    # de la factura es la de referencia (el caso común de subida única). El precio
    # efectivo es la guarda que atrapa un consumo implausible.
    if bill_period_kwh:
        return {
            "annual_kwh": round(bill_period_kwh, 1),
            "monthly_map": None,
            "months_real": 12,
            "method": "declared_annual",
            "confidence": "high",
        }

    return {
        "annual_kwh": None,
        "monthly_map": None,
        "months_real": 0,
        "method": "insufficient",
        "confidence": "none",
    }
