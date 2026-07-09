"""Banco de pruebas A/B de modelos de OpenAI para la extracción de facturas.

NO es un test de CI (hace llamadas REALES y de pago a OpenAI y necesita clave).
Se ejecuta a mano para decidir qué modelo usar:

    cd backend && .venv/bin/python -m tests.model_compare

Pregunta que responde: ¿un modelo más barato produce el MISMO output NORMALIZADO
(consumo anual, reparto por periodos, potencia, tarifa y decisión calcular/revisar)
que gpt-5.5? Compara la salida DETERMINISTA (contract_to_bill), no el JSON crudo:
lo que importa a efectos de la calculadora son los euros/kWh finales, no cómo el
modelo redacte los campos.

Material: facturas SINTÉTICAS (texto e imagen renderizada) que replican las formas
del corpus de regresión. Cubre la vía texto (PDF con capa) y una comprobación de la
vía VISIÓN (imagen) — que es donde un modelo barato puede no soportar visión o
structured outputs. NO sustituye a un A/B con fotos reales de móvil (más ruidosas):
para eso hace falta recapturar facturas reales.
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bill_normalise import contract_to_bill  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.openai_bills import OpenAIBillParser  # noqa: E402
from app.bills import BillParseError  # noqa: E402

MODELS = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"]

# Facturas sintéticas: mismas formas que tests/corpus. Cada una con su salida
# normalizada esperada (annual/split/power/tariff/outcome).
BILLS = [
    {
        "name": "anual_simple",
        "text": (
            "IBERDROLA CLIENTES — Factura de electricidad\n"
            "Titular del contrato: (cliente)\n"
            "CUPS: ES0031400000000000AB   Dirección de suministro: C/ Real 12, 36001 Pontevedra\n"
            "Peaje de acceso: 2.0TD\n"
            "Potencia contratada: Punta 5,75 kW / Valle 5,75 kW\n"
            "Periodo de facturación: 01/01/2026 a 31/12/2026 (365 días)\n"
            "Consumo total del periodo: 2.902 kWh\n"
            "Término de energía: 497,91 €\n"
            "Impuesto sobre la electricidad: 25,41 €\n"
            "IVA (21%): 109,79 €\n"
            "TOTAL IMPORTE FACTURA: 725,50 €\n"
        ),
        "expected": {
            "outcome": "compute",
            "annual": 2902,
            "power": 5.75,
            "tariff": "2.0TD",
            "split": None,
        },
    },
    {
        "name": "multiperiodo_valle",
        "text": (
            "ENDESA ENERGÍA — Detalle de la factura\n"
            "Peaje de acceso: 2.0TD   Potencia contratada: 6,9 kW\n"
            "Dirección de suministro: Rúa do Foxo 4, 36680 A Estrada\n"
            "Periodo facturado: 01/01/2026 - 31/12/2026\n"
            "Consumo de energía por periodos (kWh):\n"
            "  P1 Punta ....... 2.150\n"
            "  P2 Llano ....... 2.820\n"
            "  P3 Valle ....... 8.830\n"
            "Consumo total del periodo: 13.800 kWh\n"
            "Importe término de energía: 2.180,40 €\n"
            "TOTAL FACTURA: 3.022,20 €\n"
        ),
        "expected": {
            "outcome": "compute",
            "annual": 13800,
            "power": 6.9,
            "tariff": "2.0TD",
            "split": {"punta": 2150, "llano": 2820, "valle": 8830},
        },
    },
    {
        "name": "mensual_historico",
        "text": (
            "LUZNORTE COMERCIALIZADORA — Tu factura de la luz\n"
            "Tarifa: 2.0TD   Potencia contratada: 4,6 kW\n"
            "Dirección: Rúa do Hórreo 20, 15701 Santiago de Compostela\n"
            "Periodo facturado: 01/01/2026 - 31/12/2026 (365 días)\n"
            "Consumo anual total: 6.551 kWh\n"
            "Reparto por periodos (kWh): Punta 950 / Llano 1.450 / Valle 4.151\n"
            "Histórico de consumo — últimos 12 meses (kWh):\n"
            "  ene 610, feb 540, mar 505, abr 470, may 455, jun 480,\n"
            "  jul 560, ago 590, sep 505, oct 520, nov 600, dic 716 (suma 6.551)\n"
            "TOTAL FACTURA: 942,10 €\n"
        ),
        "expected": {
            "outcome": "compute",
            "annual": 6551,
            "power": 4.6,
            "tariff": "2.0TD",
            "split": {"punta": 950, "llano": 1450, "valle": 4151},
        },
    },
    {
        "name": "revision_precio_imposible",
        "text": (
            "COMERCIALIZADORA — Factura\n"
            "Tarifa: 2.0TD   Potencia contratada: 5,75 kW\n"
            "Consumo facturado: 2.150 kWh\n"
            "TOTAL A PAGAR: 3.027,14 €\n"
            "(Sin desglose por periodos ni histórico de consumo.)\n"
        ),
        "expected": {"outcome": "review"},
    },
]

# Factura que además se prueba por la vía VISIÓN (imagen renderizada).
VISION_BILL = "multiperiodo_valle"


def _close(a, b, tol_pct=0.02, tol_abs=20.0):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol_pct * max(abs(a), abs(b)), tol_abs)


def _render_png(text: str) -> bytes:
    """Renderiza el texto de la factura a PNG (para ejercitar la vía visión)."""
    from PIL import Image, ImageDraw, ImageFont

    lines = text.split("\n")
    font = ImageFont.load_default()
    w, line_h, pad = 900, 22, 24
    img = Image.new("RGB", (w, pad * 2 + line_h * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((pad, pad + i * line_h), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _grade(bill: dict, contract: dict) -> tuple[str, list[str]]:
    """Clasifica la salida NORMALIZADA del modelo frente a lo esperado."""
    exp = bill["expected"]
    result = contract_to_bill(contract)
    computed = not result["needs_review"]
    if exp["outcome"] == "review":
        return ("correct" if not computed else "computed_should_review", [])
    if not computed:
        return ("review_should_compute", [])
    diffs = []
    annual = (result.get("consumption_resolution") or {}).get("annual_kwh")
    if not _close(annual, exp["annual"]):
        diffs.append(f"annual={annual}≠{exp['annual']}")
    if exp.get("split"):
        periods = result.get("consumption_periods") or {}
        for k, v in exp["split"].items():
            if not _close(periods.get(k), v, tol_abs=2):
                diffs.append(f"{k}={periods.get(k)}≠{v}")
    if exp.get("power") and not _close(result.get("contracted_power_kw"), exp["power"], tol_abs=0.1):
        diffs.append(f"power={result.get('contracted_power_kw')}≠{exp['power']}")
    return ("correct" if not diffs else "wrong_but_computed", diffs)


async def _run_model(parser: OpenAIBillParser) -> list[dict]:
    rows = []
    for bill in BILLS:
        try:
            contract = await parser.extract_contract(
                b"", content_type="application/pdf", text_hint=bill["text"]
            )
            outcome, diffs = _grade(bill, contract)
        except BillParseError as exc:
            outcome, diffs = "ERROR", [str(exc)]
        rows.append({"bill": bill["name"], "via": "texto", "outcome": outcome, "diffs": diffs})
    # Vía visión: una factura renderizada a imagen.
    vbill = next(b for b in BILLS if b["name"] == VISION_BILL)
    try:
        png = _render_png(vbill["text"])
        contract = await parser.extract_contract(png, content_type="image/png")
        outcome, diffs = _grade(vbill, contract)
    except BillParseError as exc:
        outcome, diffs = "ERROR", [str(exc)]
    except Exception as exc:  # visión no soportada, etc.
        outcome, diffs = "ERROR", [f"{type(exc).__name__}: {exc}"]
    rows.append({"bill": vbill["name"], "via": "visión", "outcome": outcome, "diffs": diffs})
    return rows


async def main() -> None:
    settings = get_settings()
    api_key = settings.resolved_openai_api_key
    if not api_key:
        print("No hay OPENAI_API_KEY; no puedo comparar modelos.")
        raise SystemExit(1)

    print("=== COMPARATIVA DE MODELOS (extracción de facturas) ===")
    print("Compara el output NORMALIZADo (annual/split/power/outcome), no el JSON crudo.\n")
    all_rows: dict[str, list[dict]] = {}
    for model in MODELS:
        parser = OpenAIBillParser(api_key, base_url=settings.openai_base_url, model=model, timeout=120.0)
        try:
            print(f"— {model} …", flush=True)
            rows = await _run_model(parser)
        finally:
            await parser.close()
        all_rows[model] = rows
        for r in rows:
            diff = f"  {', '.join(r['diffs'])}" if r["diffs"] else ""
            print(f"    {r['bill']:26} {r['via']:7} {r['outcome']:22}{diff}")

    print("\n=== RESUMEN ===")
    for model in MODELS:
        rows = all_rows[model]
        ok = sum(1 for r in rows if r["outcome"] == "correct")
        print(f"  {model:16} correctas {ok}/{len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
