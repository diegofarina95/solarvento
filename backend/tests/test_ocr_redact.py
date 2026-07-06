"""Tests de la redacción de PII en píxeles (vía visión).

Tres niveles:
1. Lógica pura de clasificación de líneas (rápido, sin OCR).
2. E2E sintético: se genera una factura-imagen con PIL, se redacta, y se
   VUELVE A PASAR OCR sobre el resultado para comprobar que la PII desapareció
   y que el CUPS/consumo siguen legibles (se salta si RapidOCR no está).
3. Plumbing de main._extract_bill_contract: páginas redactadas + hint
   anonimizado llegan al parser; el OCR no se repite en cache-hit.
"""

from __future__ import annotations

import hashlib
import io
import re

import pytest

from app import ocr_redact
from app.ocr_redact import VisionPayload, line_is_bare_label, line_is_pii
from app.openai_bills import _pages_user_content


class TestLineClassification:
    def test_dni_line(self):
        assert line_is_pii("NIF: 12345678Z")
        assert line_is_pii("DNI 12345678-Z del titular")

    def test_nie_and_cif(self):
        assert line_is_pii("NIE: X-1234567-L")
        assert line_is_pii("CIF A58818501")

    def test_iban_with_and_without_spaces(self):
        assert line_is_pii("IBAN: ES91 2100 0418 4502 0005 1332")
        assert line_is_pii("Domiciliación ES9121000418450200051332")

    def test_name_after_label(self):
        assert line_is_pii("Titular: JUAN PEREZ GARCIA")
        assert line_is_pii("Titular del contrato: MARIA LOPEZ")
        assert line_is_pii("Cliente: ACME SL")
        assert line_is_pii("Nom i cognoms: JORDI PUIG")

    def test_cups_line_is_preserved(self):
        assert not line_is_pii("CUPS: ES0031406512345678JN")
        assert not line_is_pii("CUPS ES 0031 4065 1234 5678 JN")

    def test_benign_lines(self):
        assert not line_is_pii("Consumo facturado: 250 kWh")
        assert not line_is_pii("Dirección de suministro: CALLE MAYOR 5, A ESTRADA")
        assert not line_is_pii("Nombre del producto: Tarifa Estable")
        assert not line_is_pii("Total factura: 87,50 €")
        assert not line_is_pii("")

    def test_bare_label(self):
        assert line_is_bare_label("Titular:")
        assert line_is_bare_label("  Cliente ")
        assert not line_is_bare_label("Titular: JUAN")
        assert not line_is_bare_label("Consumo:")


class TestPagesUserContent:
    def test_multiple_pages_and_hint(self):
        parts = _pages_user_content([b"aaa", b"bbb"], "image/jpeg", "hola")
        images = [p for p in parts if p["type"] == "input_image"]
        texts = [p for p in parts if p["type"] == "input_text"]
        assert len(images) == 2
        assert all(p["image_url"].startswith("data:image/jpeg;base64,") for p in images)
        assert any("Auxiliary text layer" in p["text"] for p in texts)
        assert not any(p.get("type") == "input_file" for p in parts)

    def test_no_hint(self):
        parts = _pages_user_content([b"aaa"], "image/jpeg", None)
        assert sum(p["type"] == "input_text" for p in parts) == 1


def test_garbage_inputs_fall_back_to_none_and_count_it():
    before = ocr_redact.status()["documents_unredacted_fallback"]
    assert ocr_redact.redact_for_vision(b"not an image", "image/png") is None
    assert ocr_redact.redact_for_vision(b"not a pdf", "application/pdf") is None
    status = ocr_redact.status()
    # La degradación al original queda contada (la expone /api/health).
    assert status["documents_unredacted_fallback"] == before + 2
    assert {"engine", "documents_redacted", "documents_unredacted_fallback"} <= set(status)


async def test_health_exposes_redaction_status():
    from app import main as main_mod

    body = await main_mod.health()
    assert body["status"] == "ok"
    assert "documents_unredacted_fallback" in body["vision_redaction"]


# ---------------------------------------------------------------------------
# E2E sintético (OCR real)
# ---------------------------------------------------------------------------

_LINES = [
    "Titular: JUAN PEREZ GARCIA",
    "NIF: 12345678Z",
    "IBAN: ES91 2100 0418 4502 0005 1332",
    "CUPS: ES0031406512345678JN",
    "Consumo facturado: 250 kWh",
]


def _synthetic_bill_image():
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36
        )
    except OSError:  # pragma: no cover - entorno sin DejaVu
        font = ImageFont.load_default(size=36)
    img = Image.new("RGB", (1400, 700), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(_LINES):
        draw.text((60, 60 + i * 110), line, fill="black", font=font)
    return img


def _ocr_text_of(jpeg_bytes: bytes) -> str:
    import numpy as np
    from PIL import Image

    engine = ocr_redact._get_ocr()
    result = engine(np.array(Image.open(io.BytesIO(jpeg_bytes))))
    return "\n".join(getattr(result, "txts", None) or ())


def _assert_redacted(payload: VisionPayload) -> None:
    assert payload is not None
    assert payload.image_type == "image/jpeg"
    assert payload.redacted_boxes >= 3  # nombre + NIF + IBAN
    text = _ocr_text_of(payload.images[0])
    compact = re.sub(r"\s", "", text)
    # PII fuera:
    assert "12345678Z" not in compact
    assert "PEREZ" not in compact.upper()
    assert "0418" not in compact  # tramo interior del IBAN
    # Lo útil sigue legible:
    assert "ES0031" in compact
    assert "250" in compact
    # Y el texto OCR (uso local) sí contiene el consumo:
    assert "250" in payload.ocr_text


@pytest.mark.ocr
def test_redact_image_end_to_end():
    pytest.importorskip("rapidocr")
    buf = io.BytesIO()
    _synthetic_bill_image().save(buf, "PNG")
    payload = ocr_redact.redact_for_vision(buf.getvalue(), "image/png")
    _assert_redacted(payload)


@pytest.mark.ocr
def test_redact_scanned_pdf_end_to_end():
    pytest.importorskip("rapidocr")
    pytest.importorskip("pypdfium2")
    buf = io.BytesIO()
    _synthetic_bill_image().save(buf, "PDF")  # PDF de una imagen: sin capa de texto
    payload = ocr_redact.redact_for_vision(buf.getvalue(), "application/pdf")
    assert payload is not None
    assert len(payload.images) == 1
    _assert_redacted(payload)


# ---------------------------------------------------------------------------
# Plumbing: main._extract_bill_contract usa las páginas redactadas y cachea OCR
# ---------------------------------------------------------------------------


class _StubParser:
    def __init__(self):
        self.calls: list[dict] = []

    async def extract_contract(
        self, content, filename=None, content_type="application/pdf", text_hint=None, **kwargs
    ):
        self.calls.append({"text_hint": text_hint, **kwargs})
        return {}


@pytest.fixture()
def _bill_cache(monkeypatch):
    from app.cache import TTLCache
    from app.main import app

    cache = TTLCache(":memory:", ttl_seconds=60)
    monkeypatch.setattr(app.state, "bill_cache", cache, raising=False)
    return cache


async def test_extract_uses_redacted_pages_and_caches_ocr(monkeypatch, _bill_cache):
    from app import main as main_mod

    fake = VisionPayload(
        images=[b"page1"],
        image_type="image/jpeg",
        ocr_text="Titular: JUAN PEREZ\nConsumo anual: 3450 kWh",
        redacted_boxes=2,
    )
    monkeypatch.setattr(main_mod.ocr_redact, "redact_for_vision", lambda *a, **k: fake)
    parser = _StubParser()

    bill, local_text = await main_mod._extract_bill_contract(
        parser, b"fakeimg", "foto.jpg", "image/jpeg", None, "sess1"
    )
    assert len(parser.calls) == 1
    call = parser.calls[0]
    # Las páginas redactadas viajan al parser; el hint va ANONIMIZADO.
    assert call["page_images"] == [b"page1"]
    assert "[REDACTADO]" in call["vision_hint"]
    assert "PEREZ" not in call["vision_hint"]
    # El texto local (refuerzos deterministas) también va anonimizado pero
    # conserva lo útil (consumo).
    assert "3450" in local_text
    assert "PEREZ" not in local_text
    # El refuerzo determinista leyó el consumo anual del OCR.
    assert bill.get("rolling_annual_kwh") == 3450.0
    # Y lo que queda EN DISCO (caché) no contiene PII.
    key = f"billsess:sess1:{hashlib.sha256(b'fakeimg').hexdigest()}"
    cached = _bill_cache.get(key)
    assert "PEREZ" not in cached["ocr_text"]
    assert "[REDACTADO]" in cached["ocr_text"]

    # Cache-hit: no se repite ni el OCR ni la llamada al parser.
    monkeypatch.setattr(
        main_mod.ocr_redact,
        "redact_for_vision",
        lambda *a, **k: pytest.fail("OCR repetido en cache-hit"),
    )
    bill2, local_text2 = await main_mod._extract_bill_contract(
        parser, b"fakeimg", "foto.jpg", "image/jpeg", None, "sess1"
    )
    assert len(parser.calls) == 1
    assert local_text2 == local_text


async def test_extract_falls_back_to_original_when_ocr_unavailable(monkeypatch, _bill_cache):
    from app import main as main_mod

    monkeypatch.setattr(main_mod.ocr_redact, "redact_for_vision", lambda *a, **k: None)
    parser = _StubParser()
    _bill, local_text = await main_mod._extract_bill_contract(
        parser, b"otraimg", "foto.jpg", "image/jpeg", None, "sess2"
    )
    call = parser.calls[0]
    assert "page_images" not in call  # sin páginas: el parser envía el original
    assert local_text is None


async def test_kill_switch_disables_ocr(monkeypatch, _bill_cache):
    """SOLVENTO_BILL_VISION_REDACTION=false debe saltarse el OCR por completo.

    Es el interruptor de emergencia para un OCR colgado en producción: si un
    refactor pierde la condición, este test lo delata."""
    from app import main as main_mod

    monkeypatch.setattr(main_mod.settings, "bill_vision_redaction", False)
    monkeypatch.setattr(
        main_mod.ocr_redact,
        "redact_for_vision",
        lambda *a, **k: pytest.fail("se llamó al OCR con el interruptor apagado"),
    )
    parser = _StubParser()
    _bill, local_text = await main_mod._extract_bill_contract(
        parser, b"imgK", "foto.jpg", "image/jpeg", None, "sessK"
    )
    assert "page_images" not in parser.calls[0]
    assert local_text is None


async def test_old_cache_format_entry_still_readable(_bill_cache):
    """Entradas pre-envoltorio (solo el contrato a pelo) siguen siendo cache-hit.

    El .db sobrevive a los deploys (rsync excluye *.db) y el TTL es de 24h: la
    rama de compatibilidad tiene que existir hasta que caduquen."""
    from app import main as main_mod

    content = b"legacy-bill"
    key = f"billsess:sessL:{hashlib.sha256(content).hexdigest()}"
    _bill_cache.set(key, {"algún_campo_de_contrato": "x"})  # formato antiguo
    parser = _StubParser()
    _bill, local_text = await main_mod._extract_bill_contract(
        parser, content, "f.jpg", "image/jpeg", None, "sessL"
    )
    assert parser.calls == []  # cache-hit: ni modelo ni OCR
    assert local_text is None


@pytest.mark.ocr
async def test_late_redaction_on_text_fallback_sends_images_not_pdf(monkeypatch):
    """Fallback texto→visión: el PDF se rasteriza y redacta EN ese momento.

    Sin este test, una regresión en _late_redaction degradaría en silencio al
    PDF original con PII (el fallback al original es indistinguible del éxito
    para el resto de la suite)."""
    pytest.importorskip("rapidocr")
    pytest.importorskip("pypdfium2")
    from app.bills import BillParseError
    from app.openai_bills import OpenAIBillParser

    buf = io.BytesIO()
    _synthetic_bill_image().save(buf, "PDF")
    parser = OpenAIBillParser(api_key="test")
    calls = []

    async def fake_request(user_content, *, why):
        calls.append((why, user_content))
        if len(calls) == 1:
            raise BillParseError("texto falló")
        return {}

    monkeypatch.setattr(parser, "_request", fake_request)
    try:
        await parser.extract_contract(
            buf.getvalue(), "f.pdf", "application/pdf", text_hint="capa de texto cualquiera"
        )
    finally:
        await parser.close()
    assert [why for why, _ in calls] == ["text", "vision"]
    types = [part["type"] for part in calls[1][1]]
    assert "input_image" in types
    assert "input_file" not in types  # el PDF original con PII NO viaja


@pytest.mark.ocr
def test_redact_multipage_pdf_and_max_pages():
    """PDF escaneado de 2 páginas: la PII de la página 2 también se tapa; y
    max_pages recorta de verdad."""
    pytest.importorskip("rapidocr")
    pytest.importorskip("pypdfium2")
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except OSError:  # pragma: no cover
        font = ImageFont.load_default(size=36)
    page1 = Image.new("RGB", (1400, 500), "white")
    ImageDraw.Draw(page1).text((60, 60), "Consumo facturado: 250 kWh", fill="black", font=font)
    page2 = Image.new("RGB", (1400, 500), "white")
    d2 = ImageDraw.Draw(page2)
    d2.text((60, 60), "NIF: 12345678Z", fill="black", font=font)
    d2.text((60, 170), "IBAN: ES91 2100 0418 4502 0005 1332", fill="black", font=font)
    buf = io.BytesIO()
    page1.save(buf, "PDF", save_all=True, append_images=[page2])
    pdf_bytes = buf.getvalue()

    payload = ocr_redact.redact_for_vision(pdf_bytes, "application/pdf")
    assert payload is not None
    assert len(payload.images) == 2
    compact_p2 = re.sub(r"\s", "", _ocr_text_of(payload.images[1]))
    assert "12345678Z" not in compact_p2
    assert "0418" not in compact_p2
    compact_p1 = re.sub(r"\s", "", _ocr_text_of(payload.images[0]))
    assert "250" in compact_p1

    trimmed = ocr_redact.redact_for_vision(pdf_bytes, "application/pdf", max_pages=1)
    assert trimmed is not None
    assert len(trimmed.images) == 1
