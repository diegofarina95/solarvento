"""Inspector de lo que el parser ENVIARÍA a OpenAI para una factura dada.

Reproduce las mismas rutas de código que /api/parse-bill (mismas funciones:
extract_pdf_text_safe → redact_pii, o ocr_redact.redact_for_vision) pero SIN
llamar a OpenAI: vuelca a una carpeta los artefactos exactos que viajarían,
para poder auditarlos a ojo con facturas reales.

Uso (desde backend/, con el venv):
    .venv/bin/python -m app.preview_redaction ~/Descargas/factura.pdf
    .venv/bin/python -m app.preview_redaction foto-factura.jpg --out /tmp/preview

Salida (carpeta redaction-preview/<nombre>/ por defecto):
  Vía TEXTO (PDF con capa de texto):
    enviado-texto.txt    ← lo ÚNICO que se envía (texto anonimizado, tope 20k)
    local-texto.txt      ← el texto original SIN anonimizar (no sale de aquí)
  Vía VISIÓN (foto / PDF escaneado):
    enviado-pagina-N.jpg ← las imágenes que se envían (PII tapada en negro)
    enviado-hint.txt     ← texto OCR anonimizado que acompaña a las imágenes
    local-ocr.txt        ← OCR sin anonimizar (no sale de aquí)

.txt como entrada se trata como si fuera la capa de texto de un PDF (cómodo
para probar la redacción de texto sin fabricar un PDF).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import bills, ocr_redact

_IMAGE_EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

_TEXT_INSTRUCTION = (
    "Extract the electricity bill contract for SolarVento from the following "
    "plain-text layer of the bill PDF:"
)
_VISION_INSTRUCTION = "Extract the electricity bill contract for SolarVento."


def _summary_of_redaction(original: str, redacted: str) -> str:
    n = redacted.count(bills._PII_PLACEHOLDER)
    return f"{n} sustitución(es) {bills._PII_PLACEHOLDER}; {len(original)} → {len(redacted)} caracteres"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", help="factura: .pdf, .jpg/.jpeg, .png, .webp (o .txt para simular la capa de texto)")
    parser.add_argument("--out", help="carpeta de salida (por defecto redaction-preview/<nombre>)")
    args = parser.parse_args()

    src = Path(args.file).expanduser()
    if not src.exists():
        print(f"No existe: {src}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else Path("redaction-preview") / src.stem
    out.mkdir(parents=True, exist_ok=True)
    content = src.read_bytes()
    ext = src.suffix.lower()

    print(f"Factura: {src.name} ({len(content) / 1024:.0f} KiB)")

    # --- decidir la vía, igual que /api/parse-bill ---
    text_hint = None
    if ext == ".pdf":
        text_hint = bills.extract_pdf_text_safe(content)
    elif ext == ".txt":
        text_hint = content.decode("utf-8", errors="replace")
    elif ext not in _IMAGE_EXTS:
        print(f"Extensión no soportada: {ext} (la web solo acepta PDF/JPG/PNG/WebP)", file=sys.stderr)
        return 2

    if text_hint and text_hint.strip():
        # ================= VÍA TEXTO =================
        redacted = bills.redact_pii(text_hint)
        sent = f"{_TEXT_INSTRUCTION}\n\n{redacted[:20000]}"
        (out / "enviado-texto.txt").write_text(sent, encoding="utf-8")
        (out / "local-texto.txt").write_text(text_hint, encoding="utf-8")
        print("Vía: TEXTO (PDF con capa de texto) — el fichero NO se envía, solo este texto")
        print(f"Anonimización: {_summary_of_redaction(text_hint, redacted)}")
        print(f"→ Revisa {out}/enviado-texto.txt (esto es EXACTAMENTE lo que sale)")
        print(f"→ Compara con {out}/local-texto.txt (original; no sale de esta máquina)")
        print("Nota: si la vía texto fallara en el modelo, se degradaría a visión con")
        print("las páginas rasterizadas y tapadas (misma redacción que abajo).")
        return 0

    # ================= VÍA VISIÓN =================
    content_type = _IMAGE_EXTS.get(ext, "application/pdf")
    payload = ocr_redact.redact_for_vision(content, content_type)
    if payload is None:
        print("¡OJO! La redacción devolvió None (OCR no disponible o fichero ilegible):")
        print("en producción se enviaría EL ORIGINAL tal cual (con un aviso en el log).")
        return 1
    for i, jpeg in enumerate(payload.images, start=1):
        (out / f"enviado-pagina-{i}.jpg").write_bytes(jpeg)
    hint = bills.redact_pii(payload.ocr_text) or ""
    (out / "enviado-hint.txt").write_text(f"{_VISION_INSTRUCTION}\n\n{hint[:12000]}", encoding="utf-8")
    (out / "local-ocr.txt").write_text(payload.ocr_text, encoding="utf-8")
    print(f"Vía: VISIÓN ({content_type}) — {len(payload.images)} página(s), "
          f"{payload.redacted_boxes} zona(s) tapadas en negro")
    print(f"→ Abre {out}/enviado-pagina-*.jpg (EXACTAMENTE lo que se envía)")
    print(f"→ Y {out}/enviado-hint.txt (el texto auxiliar anonimizado que lo acompaña)")
    print(f"→ Compara con {out}/local-ocr.txt (OCR sin anonimizar; no sale de aquí)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
