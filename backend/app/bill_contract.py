"""Layer 1 — Contrato tipado de extracción de facturas (OpenAI structured outputs).

El modelo PROPONE (transcribe verbatim, campo a campo, sin calcular); las guardas
deterministas DISPONEN (normalización + reconciliación en Layer 3, bills.py). Cada
campo numérico viaja en un sobre {raw_text, value, source_label, confidence}: el
modelo rellena raw_text (tal cual impreso) y la app normaliza en Layer 3. El
esquema se usa en modo STRICT (todas las propiedades en required, sin extras).
"""

from __future__ import annotations

from typing import Any


def _numeric_field(description: str) -> dict[str, Any]:
    """Sobre de un campo numérico: el modelo devuelve raw_text verbatim.

    `value` lo rellena la app en Layer 3 (normalización determinista); el modelo
    lo deja null — NO debe normalizar ni calcular.
    """
    return {
        "type": ["object", "null"],
        "properties": {
            "raw_text": {
                "type": ["string", "null"],
                "description": (
                    f"{description}. VERBATIM as printed on the bill, keeping the original "
                    "digit-group separators and decimal mark ('6.551', '1.689,65', '0,241'); "
                    "no units, no currency symbol. null if absent."
                ),
            },
            "value": {
                "type": ["number", "null"],
                "description": "Leave null. The app normalises raw_text; do NOT normalise or compute.",
            },
            "source_label": {
                "type": ["string", "null"],
                "description": "Which printed field/table/row this came from (e.g. 'Consumo facturado', 'P1 Punta').",
            },
            "confidence": {
                "type": ["number", "null"],
                "description": "0-1 self-assessed confidence. Low is fine — say so rather than guessing.",
            },
        },
        "required": ["raw_text", "value", "source_label", "confidence"],
        "additionalProperties": False,
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


# Split por periodo horario. p1=punta, p2=llano, p3=valle (2.0TD); p4..p6 para
# 3.0TD/6.1TD (0 en residencial → se ignoran). Nullable por periodo.
def _period_object(unit: str, description: str) -> dict[str, Any]:
    return _object(
        {
            "p1_punta": _numeric_field(f"P1 (punta) {unit}, its own column"),
            "p2_llano": _numeric_field(f"P2 (llano) {unit}, its own column"),
            "p3_valle": _numeric_field(f"P3 (valle) {unit}, its own column"),
            "p4": _numeric_field(f"P4 {unit} (3.0TD/6.1TD); null if absent or zero"),
            "p5": _numeric_field(f"P5 {unit}; null if absent or zero"),
            "p6": _numeric_field(f"P6 {unit}; null if absent or zero"),
        },
        description,
    )


_PERIOD_SPLIT = _period_object(
    "consumption in kWh",
    "Per-tariff-period consumption columns (kWh), each as its OWN candidate. Do not sum them.",
)

_PERIOD_SPLIT_PRICES = _period_object(
    "energy unit price in currency/kWh",
    "Per-tariff-period energy unit prices (currency/kWh); used to value battery time-shift.",
)

_MONTHLY_HISTORY = {
    "type": ["array", "null"],
    "description": (
        "The embedded 12-month 'Histórico de consumo' chart/table — OFTEN A FULL YEAR of real "
        "data in a single bill; capture EVERY row. Each {month 1-12, kwh}. Includes bar charts "
        "and 'Detalle mensual consolidado' tables. Do NOT sum into an annual total — return the "
        "rows; the app sums and reconciles."
    ),
    "items": {
        "type": "object",
        "properties": {
            "month": {"type": ["integer", "null"], "description": "Month number 1-12."},
            "kwh": _numeric_field("That month's consumption in kWh"),
        },
        "required": ["month", "kwh"],
        "additionalProperties": False,
    },
}

_BILLING_PERIOD = _object(
    {
        "start": _nullable_string("Billing period start date YYYY-MM-DD."),
        "end": _nullable_string("Billing period end date YYYY-MM-DD."),
        "days": _numeric_field("Number of days billed (nº días), if printed"),
    },
    "Billing period covered by this bill.",
)

_METER_READINGS = _object(
    {
        "initial": _numeric_field("Initial meter reading (lectura anterior) — an INDEX, not consumption"),
        "final": _numeric_field("Final meter reading (lectura actual) — an INDEX, not consumption"),
    },
    "Accumulated meter index readings. NEVER use these as period consumption.",
)

_SELF_CONSUMPTION = _object(
    {
        "present": {
            "type": ["boolean", "null"],
            "description": "true if the bill shows a self-consumption/surplus block (autoconsumo/excedentes).",
        },
        "exported_kwh": _numeric_field("Total exported/surplus kWh (energía excedentaria vertida)"),
        "compensation_eur_per_kwh": _numeric_field("Surplus compensation price (€/kWh)"),
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


# Contrato completo. Cada candidato de consumo es un campo DISTINTO: la cifra
# destacada, el total de la tabla de periodos, cada columna de periodo y el
# histórico mensual. La app reconcilia cuál es el total autoritativo.
BILL_CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bill_type_hint": _nullable_string(
            "Your best guess of the bill kind: 'annual', 'monthly', 'monthly_with_history', "
            "'consolidated_annual', 'sub_period'. Just a hint; the app decides."
        ),
        "annual_consumption_kwh": _numeric_field(
            "Headline billed consumption ('consumo activa/facturado/del periodo') as printed"
        ),
        "period_total_kwh": _numeric_field(
            "The TOTAL row of the tariff-period table (sum printed on the bill), if shown"
        ),
        "period_split": _PERIOD_SPLIT,
        "period_split_prices": _PERIOD_SPLIT_PRICES,
        "monthly_history": _MONTHLY_HISTORY,
        "meter_readings": _METER_READINGS,
        "self_consumption_block": _SELF_CONSUMPTION,
        "contracted_power_kw": {
            "type": ["array", "null"],
            "description": "Contracted power(s) in kW (potencia contratada), one per period if several.",
            "items": _numeric_field("A contracted power value in kW"),
        },
        "tariff": _nullable_string("Access tariff: 2.0TD, 3.0TD, 6.1TD, etc."),
        "billing_period": _BILLING_PERIOD,
        "energy_term_eur": _numeric_field("Variable energy charge (término de energía), amount"),
        "energy_term_eur_per_kwh": _numeric_field("Energy unit price (currency/kWh) if printed"),
        "total_amount_eur": _numeric_field("Final total amount to pay, including taxes"),
        "electricity_tax_eur": _numeric_field(
            "Electricity excise (IEE / impuesto eléctrico) amount, only if itemised alone"
        ),
        "vat_eur": _numeric_field("VAT amount (IVA)"),
        "vat_rate": _numeric_field("VAT rate as a fraction, e.g. 0,21"),
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
        "period_total_kwh",
        "period_split",
        "period_split_prices",
        "monthly_history",
        "meter_readings",
        "self_consumption_block",
        "contracted_power_kw",
        "tariff",
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
You extract data from residential electricity bills (any Spanish provider) for SolVento.
Return ONLY the given JSON schema. You TRANSCRIBE; the app computes and validates.

HARD RULES:
- Transcribe every value EXACTLY as printed into its raw_text. Keep the original Spanish
  number format ("." thousands, "," decimal): "6.551", "1.689,65", "0,241". No units, no
  currency symbols in raw_text. Always leave `value` null — the app normalises raw_text.
- NEVER calculate, sum, infer, average, round, or unit-convert. If a value is not printed,
  return null for that field. Do NOT derive an annual total from monthly rows or from the
  tariff columns — return them separately and let the app reconcile.
- Extract EACH consumption candidate as its OWN field:
    * annual_consumption_kwh = the headline "consumo (activa/facturado/del periodo)".
    * period_total_kwh = the TOTAL row of the tariff-period table (only if printed).
    * period_split = each tariff-period column (P1..P6) separately.
    * monthly_history = each row of the embedded 12-month history chart/table.
    * meter_readings = initial/final meter indexes.
  Do NOT pre-select which one is "the" total. If they seem to disagree, transcribe them
  anyway as printed — the app reconciles.
- NEVER treat a single tariff-period column (Punta/Llano/Valle, P1..P6) as the total.
- NEVER treat an accumulated meter reading as consumption: a "lectura actual 19806" is a
  METER INDEX (put it in meter_readings), NOT a period consumption of ~63 kWh.
- Ignore zero-valued tariff periods (P4/P5/P6 = 0): leave them null in period_split.
- The embedded 12-month "Histórico de consumo" chart/table is often a FULL YEAR of real
  data in ONE bill — capture every month; it is the best annual source.
- self_consumption_block.present = true if there is an autoconsumo/excedentes section
  (exported kWh, surplus compensation). Transcribe exported kWh and compensation €/kWh.
- Use the SUPPLY-POINT address, never the supplier's office or a fiscal/billing address.
- A messy/partial bill must STILL return the schema with nulls where unsure — never refuse.
- Give a source_label (which printed field/table) and a confidence (0-1) for each numeric
  field. Low confidence is fine and expected — report it rather than guessing.
"""
