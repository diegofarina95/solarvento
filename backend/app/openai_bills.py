"""OpenAI-backed electricity bill extraction."""

from __future__ import annotations

import base64
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from .bills import (
    BillParseError,
    MAX_BILL_KWH,
    _to_float,
    reconcile_annual_consumption,
    validate_bill_consumption,
)
from .pricing.countries import COUNTRIES, normalize_country_code


SYSTEM_PROMPT = """\
You extract structured data from residential electricity bills for SolVento.

Return the schema exactly. Use null when a value is absent or uncertain.
Rules:
- EVERY numeric field is a STRING: copy the number EXACTLY as printed on the bill, keeping its original
  digit-group separators and decimal mark and NOTHING else (no units, no currency symbol). Examples:
  "6.551", "13.800", "1.689,65", "0,241". Do NOT convert, round or reformat — the app normalises them.
  This matters because Spanish bills use "." as the thousands separator ("6.551" = 6551, not 6.551).
- Extract electricity consumption for the billed period in kWh. Do not use cumulative meter readings
  (e.g. "lectura anterior 50.210 / lectura actual 64.010"): those are meter indexes, not consumption.
- Multi-period bills (2.0TD/3.0TD) are the NORM, not the exception. Read the TOTAL consumption column
  ("Consumo del periodo" / "Consumo total" / the total row), which is the SUM of every tariff period.
  NEVER report a single period column (P1/Punta alone) as the total. If a labelled total is shown, use
  it and confirm it equals P1+P2+P3; if they disagree, prefer the labelled total.
- Also report the per-period split in consumption_periods: {punta (P1), llano (P2), valle (P3)} in kWh,
  so the app can reconcile the total and value battery time-shift at the right tariff period. Use null
  for periods the bill does not show. Numbers use Spanish format: "13.800" = 13800, "2.086,92" = 2086.92.
- Report the per-period ENERGY UNIT PRICE in consumption_period_prices: {punta, llano, valle} in
  currency per kWh (e.g. valle ≈ 0.112). These value the battery at the (cheaper) valle price it
  actually displaces. Use null for periods without a shown unit price.
- Ignore gas, water, telecoms, taxes expressed as percentages, and meter serials. Do not use the
  contracted power (kW) as consumption, but DO report it separately in contracted_power_kw.
- Extract the variable electricity energy charge separately from fixed charges and taxes when visible.
- Extract the final amount to pay including taxes as total_eur and amount_eur. Field names ending
  in _eur are historical; keep numeric amounts in the bill currency.
- Extract the bill currency as an ISO 4217 code such as EUR, GBP, PLN, HUF, SEK.
- Extract the billing period start and end dates as YYYY-MM-DD. Set month to the midpoint month of
  that period, or the invoice month if no period is clear.
- Extract the country of the supply/invoice as an ISO 3166-1 alpha-2 code. Use GB for the United Kingdom.
- Extract the SUPPLY-POINT address ("dirección/lugar/punto de suministro"), the place where the
  electricity is consumed. If the bill shows both a supply address and a billing/fiscal address
  ("dirección fiscal / de facturación"), ALWAYS use the supply one — they can differ. Never use the
  supplier's office address. Do not invent an address.
- Extract postal code, city and region/state if clear. Use null when absent or uncertain.
- Extract the main language as a two-letter code when clear.
- Extract the contracted-power charge (término de potencia) as power_eur, the electricity excise
  (Impuesto especial sobre la electricidad / impuesto eléctrico) as iee_eur ONLY when itemised on its
  own line (null if it is lumped with other regulated charges), the VAT amount as iva_eur, the VAT
  rate as a fraction (e.g. 0.21 or 0.10) as iva_rate, and the VAT taxable base (base imponible) as
  vat_base_eur. These let the app compute the tax-inclusive avoided cost per kWh.
- Extract the monthly consumption history/detail table as consumption_history: a list of
  {month: 1-12, kwh, eur}. This includes "Histórico de consumo" / "Histórico reciente de consumo"
  charts AND the "Detalle mensual consolidado" table on annual/consolidated bills (month, kWh and
  the monthly importe). Fill eur with the monthly amount when the table shows it, else null. Return
  an empty list when there is no such table.
- Add short warnings for uncertain values, missing values, mixed utilities, or non-electricity invoices.
"""


BILL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kwh": {
            "type": ["string", "null"],
            "description": "Electricity consumed during the billing period in kWh.",
        },
        "amount_eur": {
            "type": ["string", "null"],
            "description": "Final bill amount including taxes, numeric value in the invoice currency.",
        },
        "energy_eur": {
            "type": ["string", "null"],
            "description": "Variable energy charge for consumed electricity, excluding fixed charges and taxes.",
        },
        "fixed_eur": {
            "type": ["string", "null"],
            "description": "Fixed charges such as contracted power, standing charge or meter rental.",
        },
        "taxes_eur": {
            "type": ["string", "null"],
            "description": "Taxes and VAT shown on the bill.",
        },
        "power_eur": {
            "type": ["string", "null"],
            "description": "Contracted-power charge (término de potencia).",
        },
        "iee_eur": {
            "type": ["string", "null"],
            "description": "Electricity excise (impuesto eléctrico), only if itemised alone.",
        },
        "iva_eur": {
            "type": ["string", "null"],
            "description": "VAT amount shown on the bill.",
        },
        "iva_rate": {
            "type": ["string", "null"],
            "description": "VAT rate as a fraction, e.g. 0.21 or 0.10.",
        },
        "vat_base_eur": {
            "type": ["string", "null"],
            "description": "VAT taxable base (base imponible).",
        },
        "contracted_power_kw": {
            "type": ["string", "null"],
            "description": "Contracted power in kW (potencia contratada); the higher of peak/valley.",
        },
        "consumption_history": {
            "type": ["array", "null"],
            "description": "Monthly consumption history: list of {month, kwh}.",
            "items": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "description": "Month number 1-12."},
                    "kwh": {"type": "string", "description": "Consumption in kWh, as printed on the bill."},
                    "eur": {
                        "type": ["string", "null"],
                        "description": "Amount for that month, if the table shows it.",
                    },
                },
                "required": ["month", "kwh", "eur"],
                "additionalProperties": False,
            },
        },
        "consumption_periods": {
            "type": ["object", "null"],
            "description": "Per-tariff-period consumption in kWh: P1=punta, P2=llano, P3=valle.",
            "properties": {
                "punta": {"type": ["string", "null"], "description": "P1 (punta) kWh."},
                "llano": {"type": ["string", "null"], "description": "P2 (llano) kWh."},
                "valle": {"type": ["string", "null"], "description": "P3 (valle) kWh."},
            },
            "required": ["punta", "llano", "valle"],
            "additionalProperties": False,
        },
        "consumption_period_prices": {
            "type": ["object", "null"],
            "description": "Per-tariff-period energy unit price in currency/kWh (P1/P2/P3).",
            "properties": {
                "punta": {"type": ["string", "null"], "description": "P1 (punta) €/kWh."},
                "llano": {"type": ["string", "null"], "description": "P2 (llano) €/kWh."},
                "valle": {"type": ["string", "null"], "description": "P3 (valle) €/kWh."},
            },
            "required": ["punta", "llano", "valle"],
            "additionalProperties": False,
        },
        "total_eur": {
            "type": ["string", "null"],
            "description": "Final bill amount including taxes, numeric value in the invoice currency.",
        },
        "currency": {
            "type": ["string", "null"],
            "description": "ISO 4217 bill currency code, e.g. EUR, GBP, PLN, HUF or SEK.",
        },
        "month": {
            "type": ["integer", "null"],
            "description": "Representative month number, 1-12.",
        },
        "start_date": {
            "type": ["string", "null"],
            "description": "Billing period start date as YYYY-MM-DD.",
        },
        "end_date": {
            "type": ["string", "null"],
            "description": "Billing period end date as YYYY-MM-DD.",
        },
        "country_code": {
            "type": ["string", "null"],
            "description": "ISO 3166-1 alpha-2 billing or supply country code.",
        },
        "country_name": {
            "type": ["string", "null"],
            "description": "Country name as written or inferred from the bill.",
        },
        "supply_address": {
            "type": ["string", "null"],
            "description": "Full electricity supply/service address, not the supplier office address.",
        },
        "postal_code": {
            "type": ["string", "null"],
            "description": "Postal code for the electricity supply/service address.",
        },
        "city": {
            "type": ["string", "null"],
            "description": "City/town for the electricity supply/service address.",
        },
        "region": {
            "type": ["string", "null"],
            "description": "Region/state/province for the electricity supply/service address.",
        },
        "language": {
            "type": ["string", "null"],
            "description": "Main bill language as a two-letter code.",
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short warnings about missing or uncertain extraction.",
        },
    },
    "required": [
        "kwh",
        "amount_eur",
        "energy_eur",
        "fixed_eur",
        "taxes_eur",
        "power_eur",
        "iee_eur",
        "iva_eur",
        "iva_rate",
        "vat_base_eur",
        "contracted_power_kw",
        "consumption_history",
        "consumption_periods",
        "consumption_period_prices",
        "total_eur",
        "currency",
        "month",
        "start_date",
        "end_date",
        "country_code",
        "country_name",
        "supply_address",
        "postal_code",
        "city",
        "region",
        "language",
        "warnings",
    ],
    "additionalProperties": False,
}

COUNTRY_NAME_ALIASES = {
    "SPAIN": "ES",
    "ESPANA": "ES",
    "ESPAÑA": "ES",
    "FRANCE": "FR",
    "ITALY": "IT",
    "ITALIA": "IT",
    "GERMANY": "DE",
    "DEUTSCHLAND": "DE",
    "PORTUGAL": "PT",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "REINO UNIDO": "GB",
}


class OpenAIBillParser:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-5.5",
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def parse_pdf(
        self,
        content: bytes,
        filename: str | None = None,
        content_type: str = "application/pdf",
    ) -> dict[str, Any]:
        encoded = base64.b64encode(content).decode("utf-8")
        # PDFs van como input_file; las fotos de factura como input_image.
        if content_type.startswith("image/"):
            file_content = {
                "type": "input_image",
                "image_url": f"data:{content_type};base64,{encoded}",
            }
        else:
            file_content = {
                "type": "input_file",
                "filename": _safe_pdf_filename(filename),
                "file_data": f"data:application/pdf;base64,{encoded}",
            }
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        file_content,
                        {
                            "type": "input_text",
                            "text": "Extract the electricity bill fields for SolVento.",
                        },
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "electricity_bill_parse",
                    "schema": BILL_SCHEMA,
                    "strict": True,
                }
            },
        }

        try:
            response = await self._client.post("/responses", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BillParseError("OpenAI no pudo analizar la factura") from exc

        data = response.json()
        if data.get("status") == "incomplete":
            raise BillParseError("OpenAI devolvió un análisis incompleto de la factura")

        text = _extract_output_text(data)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BillParseError("OpenAI devolvió una respuesta no válida") from exc

        return _normalize_openai_bill(parsed)


def _extract_output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str) and response["output_text"].strip():
        return response["output_text"]

    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise BillParseError("OpenAI rechazó analizar la factura")
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]

    raise BillParseError("OpenAI no devolvió datos de factura")


def _normalize_openai_bill(parsed: dict[str, Any]) -> dict[str, Any]:
    warnings = [str(w) for w in parsed.get("warnings", []) if str(w).strip()]
    kwh = _optional_float(parsed.get("kwh"))
    amount = _optional_float(parsed.get("amount_eur"))
    total = _optional_float(parsed.get("total_eur")) or amount
    amount = amount or total
    energy = _optional_float(parsed.get("energy_eur"))
    fixed = _optional_float(parsed.get("fixed_eur"))
    taxes = _optional_float(parsed.get("taxes_eur"))
    month = _optional_month(parsed.get("month"))
    country_code = _optional_country(parsed.get("country_code"))
    language = _optional_language(parsed.get("language"))
    currency = _optional_currency(parsed.get("currency"))

    if kwh is not None and not (0 < kwh <= MAX_BILL_KWH):
        warnings.append("Consumo fuera del rango esperado; revisa los kWh.")
        kwh = None

    periods = _optional_periods(parsed.get("consumption_periods"))

    if amount is not None and amount <= 0:
        amount = None

    if kwh is None:
        warnings.append("No se detectó el consumo en kWh")
    if amount is None:
        warnings.append("No se detectó el importe de la factura")

    bill = {
        "kwh": kwh,
        "amount_eur": amount,
        "energy_eur": energy,
        "fixed_eur": fixed,
        "taxes_eur": taxes,
        "power_eur": _optional_float(parsed.get("power_eur")),
        "iee_eur": _optional_float(parsed.get("iee_eur")),
        "iva_eur": _optional_float(parsed.get("iva_eur")),
        "iva_rate": _optional_float(parsed.get("iva_rate")),
        "vat_base_eur": _optional_float(parsed.get("vat_base_eur")),
        "contracted_power_kw": _optional_float(parsed.get("contracted_power_kw")),
        "consumption_history": _optional_history(parsed.get("consumption_history")),
        "consumption_periods": periods or None,
        "consumption_period_prices": _optional_period_prices(
            parsed.get("consumption_period_prices")
        ) or None,
        "total_eur": total,
        "currency": currency,
        "month": month,
        "start_date": _optional_date_text(parsed.get("start_date")),
        "end_date": _optional_date_text(parsed.get("end_date")),
        "country_code": country_code,
        "country_name": _optional_text(parsed.get("country_name")),
        "supply_address": _optional_text(parsed.get("supply_address")),
        "postal_code": _optional_text(parsed.get("postal_code")),
        "city": _optional_text(parsed.get("city")),
        "region": _optional_text(parsed.get("region")),
        "language": language,
        "parser": "openai",
    }

    # Reconciliación de fuentes (misma cifra en tarjeta destacada / suma de
    # periodos / histórico): si dos coinciden, se corrige la que discrepe y la
    # factura calcula; solo si ninguna se corrobora se deja para revisión. Luego
    # la guarda de precio efectivo como backstop independiente.
    corrected_kwh, correction_note, review_reasons = reconcile_annual_consumption(bill)
    bill["kwh"] = corrected_kwh
    if correction_note:
        warnings.append(correction_note)
    review_reasons = review_reasons + validate_bill_consumption(bill)
    if review_reasons:
        bill["needs_review"] = True
        bill["review_reasons"] = review_reasons
        warnings.extend(review_reasons)
    else:
        bill["needs_review"] = False
        bill["review_reasons"] = []
    bill["warnings"] = _dedupe(warnings)
    return bill


def _optional_periods(value: Any) -> dict[str, float]:
    """Normaliza el split por periodo del parser IA a {punta,llano,valle} en kWh."""
    if not isinstance(value, dict):
        return {}
    periods: dict[str, float] = {}
    for key in ("punta", "llano", "valle"):
        kwh = _optional_float(value.get(key))
        if kwh is not None and 0 < kwh <= MAX_BILL_KWH:
            periods[key] = kwh
    return periods


def _optional_period_prices(value: Any) -> dict[str, float]:
    """Normaliza el precio €/kWh por periodo del parser IA (0 < precio <= 10)."""
    if not isinstance(value, dict):
        return {}
    prices: dict[str, float] = {}
    for key in ("punta", "llano", "valle"):
        price = _optional_float(value.get(key))
        if price is not None and 0 < price <= 10:
            prices[key] = price
    return prices


def _optional_history(value: Any) -> list[dict[str, float]]:
    """Normaliza el histórico mensual del parser IA a [{month, kwh}, ...]."""
    if not isinstance(value, list):
        return []
    entries: dict[int, dict[str, float]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        month = _optional_month(item.get("month"))
        kwh = _optional_float(item.get("kwh"))
        if month is not None and kwh is not None and 0 < kwh <= MAX_BILL_KWH:
            entry: dict[str, float] = {"month": month, "kwh": kwh}
            eur = _optional_float(item.get("eur"))
            if eur is not None:
                entry["eur"] = eur
            entries[month] = entry
    return [entries[m] for m in sorted(entries)]


def _optional_float(value: Any) -> float | None:
    """Normaliza CUALQUIER campo numérico del parser IA con la MISMA función
    canónica que el parser local (_to_float): así ningún campo se salta la
    normalización de formato español ("6.551"=6551, "1.689,65"=1689,65).

    El esquema pide los números como texto tal cual aparecen en la factura,
    porque un `number` JSON ya resuelve mal el separador de miles español
    ("6.551" -> 6.551) antes de que lleguen aquí. Se acepta también int/float
    por compatibilidad (valores sin ambigüedad de miles ya vienen bien)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    if isinstance(value, str):
        return _float_from_text(value)
    return None


def _float_from_text(text: str) -> float | None:
    """Extrae el primer token numérico (con separadores) y lo pasa por _to_float,
    ignorando unidades y símbolos ('6.551 kWh', '1.689,65 €', '0,241000 €/kWh')."""
    match = re.search(r"-?\d[\d.,\s\u00a0]*\d|-?\d", text)
    if not match:
        return None
    try:
        return round(_to_float(match.group(0)), 4)
    except ValueError:
        return None


def _optional_month(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if 1 <= result <= 12 else None


def _optional_currency(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    code = text.upper()
    return code if len(code) == 3 and code.isalpha() else None


def _optional_country(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    alias = COUNTRY_NAME_ALIASES.get(text.upper())
    if alias:
        return alias
    for code, country in COUNTRIES.items():
        if text.casefold() == country.name.casefold():
            return code
    return normalize_country_code(text)


def _optional_language(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    code = text.split("-")[0].lower()
    return code if len(code) == 2 else None


def _optional_date_text(value: Any) -> str | None:
    text = _optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _safe_pdf_filename(filename: str | None) -> str:
    name = Path(filename or "bill.pdf").name
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
