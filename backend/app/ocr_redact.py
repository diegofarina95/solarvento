"""Redacción de PII en PÍXELES para la vía visión (foto de factura / PDF escaneado).

Paridad con redact_pii() de bills.py (vía texto): antes de enviar el documento a
OpenAI se tapan con rectángulos opacos las líneas que contienen DNI/NIE/CIF/IBAN
y el nombre del titular (etiquetado). El CUPS, el consumo y la dirección de
suministro se conservan (hacen falta para el cálculo y la geolocalización).

Cómo: OCR local (RapidOCR/ONNX, sin binarios de sistema) → cajas de texto por
línea → clasificación con los MISMOS patrones que la vía texto → tapado con
PIL → reencodado JPEG. Los PDF sin capa de texto se rasterizan con pypdfium2 y
se envían como imágenes de página ya redactadas (en lugar del PDF original).

Degradación explícita: si el OCR no está disponible o falla, se devuelve None y
la llamada envía el documento ORIGINAL (comportamiento previo a esta capa). Es
best-effort: un nombre sin etiqueta, o un token que el OCR lea mal, pueden
colarse; la política de privacidad lo declara así.

Limitaciones conocidas (documentadas, no silenciosas):
- PII partida en dos cajas OCR (p.ej. IBAN a mitad) puede no detectarse.
- Solo se procesan las primeras `max_pages` páginas de un PDF escaneado (los
  datos de consumo van al principio; se registra en el log si se recorta).
- Coste: el OCR añade varios segundos por página y se SERIALIZA (_WORK_LOCK);
  los límites de subida (10/IP y 100 global al día) acotan el abuso.
- HEIC/HEIF no se aceptan en la subida (main._IMAGE_TYPES): al no anunciarlos
  en el accept, iOS transcodifica a JPEG y la redacción aplica.
"""

from __future__ import annotations

import io
import logging
import re
import threading
import time
from dataclasses import dataclass

from .bills import _CIF_RE, _DNI_RE, _IBAN_RE, _NAME_LABELS, _NIE_RE

logger = logging.getLogger(__name__)

# PDFium y la sesión ONNX se serializan: el volumen de facturas es bajo y así
# no dependemos de la thread-safety de las libs nativas.
_WORK_LOCK = threading.Lock()
_OCR_LOCK = threading.Lock()
_ocr_engine = None
# Si la carga del OCR falla no se reintenta en cada factura (podría ser una dep
# ausente) pero TAMPOCO se fija para siempre: un fallo transitorio (presión de
# memoria al cargar ONNX) se reintenta pasado un rato.
_ocr_failed_at: float | None = None
_OCR_RETRY_SECONDS = 600.0

# Lado mayor máximo antes de OCR/envío: acota el coste del OCR (~proporcional a
# los píxeles) y del payload; OpenAI reescala de todos modos las imágenes
# grandes, y a ~180 dpi el texto de una factura sigue siendo legible.
_MAX_SIDE = 2000
_JPEG_QUALITY = 88
_BOX_PADDING = 3

# Etiqueta de titular CON valor en la misma línea (variante sin anclas de la de
# bills.py: las "líneas" del OCR ya vienen troceadas). \b evita que "nom" o
# "cliente" casen dentro de otra palabra.
_LABEL_WITH_VALUE_RE = re.compile(
    r"(?i)\b(?:" + _NAME_LABELS + r")\s*[:\-]\s*\S+"
)
# Etiqueta de titular SOLA (el valor está en la caja de al lado / de debajo).
_LABEL_ONLY_RE = re.compile(
    r"(?i)^\W*(?:" + _NAME_LABELS + r")\s*[:\-]?\s*$"
)
# Protección del CUPS: si la línea es la del CUPS no se aplican DNI/CIF (un OCR
# que trocee el CUPS con espacios podría imitar un DNI y taparíamos la línea
# que necesita la geolocalización). El IBAN sí se comprueba siempre (22 dígitos
# tras ES: no colisiona con el CUPS, que lleva letras finales).
_CUPS_HINT_RE = re.compile(r"(?i)\bCUPS\b|\bES\d{16}[A-Z0-9]{2,6}\b")


@dataclass(frozen=True)
class VisionPayload:
    """Resultado de la redacción para la vía visión."""

    images: list[bytes]  # JPEG por página, ya redactadas
    image_type: str  # "image/jpeg"
    ocr_text: str  # texto OCR SIN redactar (solo uso LOCAL: augment/heurísticas)
    redacted_boxes: int


def _get_ocr():
    """Carga perezosa del motor OCR (una sola instancia; ~1-2 s la primera vez)."""
    global _ocr_engine, _ocr_failed_at
    if _ocr_engine is not None:
        return _ocr_engine
    with _OCR_LOCK:
        if _ocr_engine is not None:
            return _ocr_engine
        if _ocr_failed_at is not None and time.monotonic() - _ocr_failed_at < _OCR_RETRY_SECONDS:
            return None
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ocr_engine = RapidOCR()
            _ocr_failed_at = None
        except Exception:  # pragma: no cover - depende del entorno
            logger.warning(
                "ocr_redact: RapidOCR no disponible; sin redacción de imágenes "
                "(reintento en %.0f s)",
                _OCR_RETRY_SECONDS,
            )
            _ocr_failed_at = time.monotonic()
    return _ocr_engine


def line_is_pii(text: str) -> bool:
    """True si una línea de OCR contiene PII que debe taparse entera.

    Lógica pura (sin OCR) para poder testearla rápido. Misma semántica que la
    vía texto: IBAN/NIE/DNI/CIF por patrón + nombre tras etiqueta de titular.
    """
    if not text or not text.strip():
        return False
    if _IBAN_RE.search(text):
        return True
    if not _CUPS_HINT_RE.search(text):
        for pattern in (_NIE_RE, _DNI_RE, _CIF_RE):
            if pattern.search(text):
                return True
    return bool(_LABEL_WITH_VALUE_RE.search(text))


def line_is_bare_label(text: str) -> bool:
    """True si la línea es SOLO una etiqueta de titular ("Titular:") sin valor."""
    return bool(text and _LABEL_ONLY_RE.match(text.strip()))


def _quad_to_rect(box) -> tuple[float, float, float, float]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def _value_neighbor(label_rect, rects: list[tuple[float, float, float, float]]) -> int | None:
    """Índice de la caja que más pinta tiene de ser el VALOR de una etiqueta sola.

    Primero a la DERECHA en la misma fila (solape vertical ≥ 50%); si no hay,
    justo DEBAJO (solape horizontal y hueco < 1.2 alturas). None si nada encaja.
    """
    lx0, ly0, lx1, ly1 = label_rect
    lh = max(ly1 - ly0, 1.0)
    best_right: tuple[float, int] | None = None
    best_below: tuple[float, int] | None = None
    for i, (x0, y0, x1, y1) in enumerate(rects):
        if (x0, y0, x1, y1) == label_rect:
            continue
        overlap_y = min(ly1, y1) - max(ly0, y0)
        if overlap_y >= 0.5 * min(lh, max(y1 - y0, 1.0)) and x0 >= lx1 - 5:
            gap = x0 - lx1
            if best_right is None or gap < best_right[0]:
                best_right = (gap, i)
        overlap_x = min(lx1, x1) - max(lx0, x0)
        if overlap_x > 0.3 * (lx1 - lx0) and 0 <= y0 - ly1 < 1.2 * lh:
            gap = y0 - ly1
            if best_below is None or gap < best_below[0]:
                best_below = (gap, i)
    if best_right is not None:
        return best_right[1]
    if best_below is not None:
        return best_below[1]
    return None


def _redact_page(img) -> tuple[bytes, str, int]:
    """OCR + tapado sobre una página PIL. Devuelve (jpeg, texto_ocr, nº cajas)."""
    import numpy as np
    from PIL import ImageDraw, ImageOps

    img = ImageOps.exif_transpose(img)  # fotos de móvil: aplicar la rotación EXIF
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > _MAX_SIDE:
        ratio = _MAX_SIDE / max(img.size)
        img = img.resize((round(img.width * ratio), round(img.height * ratio)))

    ocr = _get_ocr()
    if ocr is None:
        raise RuntimeError("OCR no disponible")
    result, _elapse = ocr(np.array(img))
    lines = result or []

    rects = [_quad_to_rect(box) for box, _text, _score in lines]
    texts = [text for _box, text, _score in lines]

    to_redact: set[int] = set()
    for i, text in enumerate(texts):
        if line_is_pii(text):
            to_redact.add(i)
        elif line_is_bare_label(text):
            neighbor = _value_neighbor(rects[i], rects)
            if neighbor is not None and not _CUPS_HINT_RE.search(texts[neighbor]):
                to_redact.add(neighbor)

    if to_redact:
        draw = ImageDraw.Draw(img)
        for i in to_redact:
            x0, y0, x1, y1 = rects[i]
            draw.rectangle(
                (
                    max(x0 - _BOX_PADDING, 0),
                    max(y0 - _BOX_PADDING, 0),
                    min(x1 + _BOX_PADDING, img.width),
                    min(y1 + _BOX_PADDING, img.height),
                ),
                fill="black",
            )

    # Texto en orden de lectura aproximado (arriba→abajo, izquierda→derecha).
    order = sorted(range(len(lines)), key=lambda i: (rects[i][1], rects[i][0]))
    ocr_text = "\n".join(texts[i] for i in order)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue(), ocr_text, len(to_redact)


def _pdf_pages(content: bytes, max_pages: int):
    """Rasteriza un PDF (sin capa de texto) a imágenes PIL, hasta ~200 DPI.

    El scale se RECORTA por página para que el lado mayor renderizado no supere
    _MAX_SIDE: un PDF con MediaBox gigante (hasta 14400×14400 pt permite el
    spec) pediría gigas de RAM en el render si no; con el recorte, un PDF de
    pocos KB no puede convertirse en una bomba de memoria."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(content)
    try:
        total = len(pdf)
        if total > max_pages:
            logger.info("ocr_redact: PDF de %s páginas; se procesan las %s primeras", total, max_pages)
        for i in range(min(total, max_pages)):
            page = pdf[i]
            try:
                page_w, page_h = page.get_size()  # en puntos (1/72")
                scale = min(200 / 72, _MAX_SIDE / max(page_w, page_h, 1.0))
                yield page.render(scale=scale).to_pil()
            finally:
                page.close()
    finally:
        pdf.close()


def redact_for_vision(
    content: bytes, content_type: str, *, max_pages: int = 4
) -> VisionPayload | None:
    """Prepara el documento para la vía visión con la PII tapada.

    Devuelve None si no se puede (OCR/render no disponible, formato no
    soportado, error inesperado): la llamada debe usar entonces el documento
    original, como antes de existir esta capa.
    """
    try:
        with _WORK_LOCK:
            if content_type.startswith("image/"):
                from PIL import Image

                pages = [Image.open(io.BytesIO(content))]
            else:
                pages = _pdf_pages(content, max_pages)

            images: list[bytes] = []
            texts: list[str] = []
            boxes = 0
            for page in pages:
                jpeg, text, n = _redact_page(page)
                images.append(jpeg)
                texts.append(text)
                boxes += n
        if not images:
            return None
        payload = VisionPayload(
            images=images,
            image_type="image/jpeg",
            ocr_text="\n\n".join(texts),
            redacted_boxes=boxes,
        )
        logger.info(
            "ocr_redact: %s página(s), %s zona(s) tapadas (%s)",
            len(images),
            boxes,
            content_type,
        )
        return payload
    except Exception as exc:
        # Best-effort: no se bloquea el servicio por un fallo del OCR; se envía
        # el original (estado previo) y queda constancia en el log.
        logger.warning("ocr_redact: sin redacción (%s: %s); se envía el original", type(exc).__name__, exc)
        return None
