"""Layer 1 — Contrato tipado de extracción de facturas (OpenAI structured outputs).

El modelo PROPONE (transcribe verbatim); las guardas deterministas DISPONEN
(normalización + reconciliación en bill_normalise). Cada campo numérico es una
STRING con el número TAL CUAL impreso ("6.551", "1.689,65"); la app lo normaliza.
Esquema STRICT (todas las propiedades en required, sin extras) y — crítico —
POR DEBAJO del límite de 100 propiedades de structured-outputs de OpenAI: un
esquema demasiado grande se rechaza con 400 y ninguna factura se parsea.
"""

from __future__ import annotations

from typing import Any


def _num(description: str) -> dict[str, Any]:
    """Campo numérico = STRING verbatim (la app normaliza el formato español)."""
    return {
        "type": ["string", "null"],
        "description": (
            f"{description}. VERBATIM as printed, keeping the Spanish number format "
            "('6.551', '1.689,65', '0,241'); no units, no currency symbol. null if absent."
        ),
    }


def _nullable_string(description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


def _object(properties: dict[str, Any], description: str) -> dict[str, Any]:
    return {
        "type": ["object", "null"],
        "description": description,
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# Split por periodo horario 2.0TD: P1 punta / P2 llano / P3 valle.
_PERIOD_SPLIT = _object(
    {
        "p1_punta": _num("P1 (punta) consumption in kWh, its own column"),
        "p2_llano": _num("P2 (llano) consumption in kWh, its own column"),
        "p3_valle": _num("P3 (valle) consumption in kWh, its own column"),
    },
    "Per-tariff-period consumption columns (kWh), each as its OWN candidate. Do not sum them.",
)

_PERIOD_SPLIT_PRICES = _object(
    {
        "p1_punta": _num("P1 (punta) energy unit price in currency/kWh"),
        "p2_llano": _num("P2 (llano) energy unit price in currency/kWh"),
        "p3_valle": _num("P3 (valle) energy unit price in currency/kWh"),
    },
    "Per-tariff-period energy unit prices (currency/kWh); used to value battery time-shift.",
)

_MONTHLY_HISTORY = {
    "type": ["array", "null"],
    "description": (
        "The embedded 12-month 'Histórico de consumo' chart/table — OFTEN A FULL YEAR of real "
        "data in one bill; capture EVERY row. Each {month 1-12, kwh}. Do NOT sum into an annual "
        "total — return the rows; the app sums and reconciles."
    ),
    "items": {
        "type": "object",
        "properties": {
            "month": {"type": ["integer", "null"], "description": "Month number 1-12."},
            "kwh": _num("That month's consumption in kWh"),
        },
        "required": ["month", "kwh"],
        "additionalProperties": False,
    },
}

_BILLING_PERIOD = _object(
    {
        "start": _nullable_string("Billing period start date YYYY-MM-DD."),
        "end": _nullable_string("Billing period end date YYYY-MM-DD."),
        "days": _num("Number of days billed (nº días), if printed"),
    },
    "Billing period covered by this bill.",
)

_METER_READINGS = _object(
    {
        "initial": _num("Initial meter reading (lectura anterior) — an INDEX, not consumption"),
        "final": _num("Final meter reading (lectura actual) — an INDEX, not consumption"),
    },
    "Accumulated meter index readings. NEVER use these as period consumption.",
)

_SELF_CONSUMPTION = _object(
    {
        "present": {
            "type": ["boolean", "null"],
            "description": (
                "true ONLY if the bill shows ACTUAL self-consumption/surplus with a NON-ZERO "
                "value (exported kWh > 0 or a compensation amount > 0). The boilerplate line "
                "'Compensación de excedentes 0,00 €' printed on ordinary regulated bills WITHOUT "
                "PV must be treated as false."
            ),
        },
        "exported_kwh": _num("Exported/surplus energy in kWh (energía excedentaria/vertida), 0 if none"),
        "compensated_eur": _num(
            "Surplus COMPENSATION AMOUNT in currency from the 'Compensación de excedentes' line "
            "(the € figure, often 0,00 on bills without PV), 0 if none"
        ),
        "compensation_eur_per_kwh": _num("Surplus compensation UNIT price (€/kWh), if printed"),
    },
    "Existing photovoltaic self-consumption block, if the supply already has PV.",
)

_SUPPLY_ADDRESS = _object(
    {
        "street": _nullable_string("Supply-point street address (not the supplier office)."),
        "cp": _nullable_string("Supply-point postal code (código postal)."),
        "municipio": _nullable_string("Supply-point municipality/town."),
        "provincia": _nullable_string("Supply-point province."),
    },
    "SUPPLY-POINT address (where electricity is consumed); prefer it over any fiscal address.",
)


# Contrato completo — mantener < 100 propiedades (límite de OpenAI structured outputs).
BILL_CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bill_type_hint": _nullable_string(
            "Best guess of the bill kind: 'annual', 'monthly', 'monthly_with_history', "
            "'consolidated_annual', 'sub_period'. Just a hint; the app decides."
        ),
        "annual_consumption_kwh": _num(
            "Headline billed consumption ('consumo activa/facturado/del periodo') as printed"
        ),
        "rolling_annual_kwh": _num(
            "Printed rolling-year total: 'Consumo acumulado del último año' / 'Consumo anual' / "
            "'Tu consumo en los últimos 12 meses' (kWh). This is the REAL yearly consumption; null if absent"
        ),
        "period_total_kwh": _num("TOTAL row of the tariff-period table (sum printed), if shown"),
        "period_split": _PERIOD_SPLIT,
        "period_split_prices": _PERIOD_SPLIT_PRICES,
        "monthly_history": _MONTHLY_HISTORY,
        "meter_readings": _METER_READINGS,
        "self_consumption_block": _SELF_CONSUMPTION,
        "contracted_power_kw": {
            "type": ["array", "null"],
            "description": "Contracted power(s) in kW (potencia contratada), one per period if several.",
            "items": _num("A contracted power value in kW"),
        },
        "tariff": _nullable_string("Access tariff: 2.0TD, 3.0TD, etc."),
        "bono_social": {
            "type": ["boolean", "null"],
            "description": (
                "true if the bill applies the Spanish social discount: any of 'PVPC con bono "
                "social', 'Descuento por Bono Social', 'Bono Social de Electricidad'. With it the "
                "effective €/kWh is legitimately much lower."
            ),
        },
        "billing_period": _BILLING_PERIOD,
        "energy_term_eur": _num("Variable energy charge (término de energía), amount"),
        "energy_term_eur_per_kwh": _num("Energy unit price (currency/kWh) if printed"),
        "total_amount_eur": _num("Final total amount to pay, including taxes"),
        "electricity_tax_eur": _num("Electricity excise (IEE), only if itemised alone"),
        "vat_eur": _num("VAT amount (IVA)"),
        "vat_rate": _num("VAT rate as a fraction, e.g. 0,21"),
        "currency": _nullable_string("ISO 4217 currency code, e.g. EUR."),
        "country_code": _nullable_string("ISO 3166-1 alpha-2 supply country, e.g. ES."),
        "language": _nullable_string("Main bill language, two-letter code."),
        "supply_address": _SUPPLY_ADDRESS,
        "cups": _nullable_string("CUPS (supply point universal code) if present."),
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short notes on uncertain/absent values, mixed utilities, or non-electricity invoices.",
        },
    },
    "required": [
        "bill_type_hint",
        "annual_consumption_kwh",
        "rolling_annual_kwh",
        "period_total_kwh",
        "period_split",
        "period_split_prices",
        "monthly_history",
        "meter_readings",
        "self_consumption_block",
        "contracted_power_kw",
        "tariff",
        "bono_social",
        "billing_period",
        "energy_term_eur",
        "energy_term_eur_per_kwh",
        "total_amount_eur",
        "electricity_tax_eur",
        "vat_eur",
        "vat_rate",
        "currency",
        "country_code",
        "language",
        "supply_address",
        "cups",
        "warnings",
    ],
    "additionalProperties": False,
}


# Prompt de disciplina de extracción: el modelo TRANSCRIBE, no razona.
EXTRACTION_SYSTEM_PROMPT = """\
You extract data from residential electricity bills (any Spanish provider) for SolarVento.
Return ONLY the given JSON schema. You TRANSCRIBE; the app computes and validates.

HARD RULES:
- Every numeric field is a STRING with the number EXACTLY as printed. Keep the Spanish
  format ("." thousands, "," decimal): "6.551", "1.689,65", "0,241". No units, no currency
  symbols. If a value is not printed, use null. NEVER calculate, sum, infer, or convert.
- Extract EACH consumption candidate separately, do NOT pre-pick "the" total:
    * annual_consumption_kwh = the headline "consumo (activa/facturado/del periodo)".
    * rolling_annual_kwh = the printed rolling-year total if present ("Consumo acumulado del
      último año", "Consumo anual", "últimos 12 meses"). This is the real yearly figure.
    * period_total_kwh = the TOTAL row of the tariff-period table (only if printed).
    * period_split = each tariff-period column (P1/P2/P3) separately.
    * monthly_history = each row of the embedded 12-month history chart/table.
    * meter_readings = initial/final meter indexes.
- NEVER treat a single tariff-period column (Punta/Llano/Valle) as the total.
- NEVER treat an accumulated meter reading as consumption: "lectura actual 19806" is a
  METER INDEX (meter_readings), NOT a ~63 kWh period consumption.
- The embedded 12-month "Histórico de consumo" is often a FULL YEAR in one bill — capture it.
- self_consumption_block: set present=true ONLY with REAL surplus (exported_kwh > 0 or a
  compensation amount > 0). 'Compensación de excedentes 0,00 €' on an ordinary bill = false.
  Always transcribe exported_kwh and compensated_eur (use "0" / "0,00" if the line shows zero).
- bono_social = true if the bill mentions the social discount (PVPC con bono social / Descuento
  por Bono Social); it legitimately lowers the €/kWh.
- Use the SUPPLY-POINT address, never the supplier office or fiscal/billing address.
- A messy/partial bill must STILL return the schema with nulls where unsure — never refuse.
"""
