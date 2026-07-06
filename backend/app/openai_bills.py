"""Layer 2 — extracción de facturas con un modelo LLM (OpenAI, con visión).

Vía ÚNICA de ingesta: PDF-texto, escaneo y foto entran igual y salen como el
contrato tipado de bill_contract (raw_text por campo). El modelo PROPONE; la
normalización y las guardas deterministas DISPONEN en bill_normalise (Layer 3).
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from .bill_contract import BILL_CONTRACT_SCHEMA, EXTRACTION_SYSTEM_PROMPT
from .bills import BillParseError

logger = logging.getLogger(__name__)


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

    async def extract_contract(
        self,
        content: bytes,
        filename: str | None = None,
        content_type: str = "application/pdf",
        text_hint: str | None = None,
        *,
        page_images: list[bytes] | None = None,
        page_image_type: str = "image/jpeg",
        vision_hint: str | None = None,
    ) -> dict[str, Any]:
        """Extrae el CONTRATO tipado (bill_contract) de cualquier factura, blindado.

        Estrategia robusta:
          1) PDF con capa de texto → se analiza el TEXTO PLANO (más fiable y barato
             que subir el fichero; lo que pidió el usuario);
          2) imagen/escaneo, o PDF sin texto, o si el texto falla → VISIÓN.
        PRIVACIDAD: en la vía visión, si la llamada aporta `page_images` (páginas
        ya redactadas por ocr_redact) se envían ESAS en lugar del documento
        original; `vision_hint` es el texto OCR ya anonimizado. Si el texto de un
        PDF falla y hay que degradar a visión sin páginas preparadas, se intenta
        redactar aquí mismo antes de recurrir al original (último recurso).
        Structured outputs STRICT. Determinismo por caché de fichero (no por
        temperature: los modelos de razonamiento no aceptan ese parámetro)."""
        is_image = content_type.startswith("image/")
        has_text = bool(text_hint and text_hint.strip())

        # 1) Vía texto plano (PDF con capa de texto).
        if not is_image and has_text:
            try:
                return await self._request(_text_user_content(text_hint), why="text")
            except BillParseError as exc:
                logger.warning("bill extraction: text path failed (%s); trying vision", exc)
            if page_images is None:
                # Degradación rara (texto falló): redactar en píxeles AHORA para no
                # mandar el PDF original con PII. Si tampoco se puede, original.
                page_images, page_image_type, vision_hint = await _late_redaction(
                    content, "application/pdf"
                )

        # 2) Vía visión (imagen, escaneo, o PDF sin texto / con texto fallido).
        if page_images:
            user_content = _pages_user_content(
                page_images, page_image_type, text_hint or vision_hint
            )
        else:
            user_content = _file_user_content(content, filename, content_type, text_hint)
        return await self._request(user_content, why="vision")

    async def _request(self, user_content: list[dict[str, Any]], *, why: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "electricity_bill_contract",
                    "schema": BILL_CONTRACT_SCHEMA,
                    "strict": True,
                }
            },
        }
        logger.info("bill extraction: POST /responses model=%s via=%s", self.model, why)
        try:
            response = await self._client.post("/responses", json=payload)
        except httpx.HTTPError as exc:
            logger.warning("bill extraction: transport error (%s): %s", why, exc)
            raise BillParseError("OpenAI no pudo analizar la factura") from exc

        if response.status_code >= 400:
            logger.warning(
                "bill extraction: HTTP %s (%s) body=%s", response.status_code, why, response.text[:800]
            )
            raise BillParseError("OpenAI no pudo analizar la factura")

        data = response.json()
        logger.info("bill extraction: HTTP %s (%s) status=%s", response.status_code, why, data.get("status"))
        if data.get("status") == "incomplete":
            raise BillParseError("OpenAI devolvió un análisis incompleto de la factura")
        text = _extract_output_text(data)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("bill extraction: non-JSON output (%s): %s", why, text[:400])
            raise BillParseError("OpenAI devolvió una respuesta no válida") from exc


def _text_user_content(text_hint: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "input_text",
            "text": (
                "Extract the electricity bill contract for SolarVento from the following "
                "plain-text layer of the bill PDF:\n\n" + text_hint[:20000]
            ),
        }
    ]


async def _late_redaction(
    content: bytes, content_type: str
) -> tuple[list[bytes] | None, str, str | None]:
    """Redacción tardía para el fallback texto→visión (import perezoso, en hilo)."""
    try:
        from anyio import to_thread

        from . import bills, ocr_redact

        payload = await to_thread.run_sync(ocr_redact.redact_for_vision, content, content_type)
        if payload is not None:
            return payload.images, payload.image_type, bills.redact_pii(payload.ocr_text)
    except Exception as exc:  # pragma: no cover - defensa; no debe tumbar la extracción
        logger.warning("bill extraction: late redaction failed (%s)", exc)
    return None, "image/jpeg", None


def _pages_user_content(
    page_images: list[bytes], image_type: str, hint: str | None
) -> list[dict[str, Any]]:
    """Contenido de usuario con las PÁGINAS redactadas (una input_image por página)."""
    parts: list[dict[str, Any]] = [
        {
            "type": "input_image",
            "image_url": f"data:{image_type};base64,{base64.b64encode(img).decode('utf-8')}",
        }
        for img in page_images
    ]
    parts.append(
        {"type": "input_text", "text": "Extract the electricity bill contract for SolarVento."}
    )
    if hint and hint.strip():
        parts.append({
            "type": "input_text",
            "text": f"Auxiliary text layer (rendered pages are authoritative):\n{hint[:12000]}",
        })
    return parts


def _file_user_content(
    content: bytes, filename: str | None, content_type: str, text_hint: str | None
) -> list[dict[str, Any]]:
    encoded = base64.b64encode(content).decode("utf-8")
    if content_type.startswith("image/"):
        file_content: dict[str, Any] = {
            "type": "input_image",
            "image_url": f"data:{content_type};base64,{encoded}",
        }
    else:
        file_content = {
            "type": "input_file",
            "filename": _safe_pdf_filename(filename),
            "file_data": f"data:application/pdf;base64,{encoded}",
        }
    parts: list[dict[str, Any]] = [
        file_content,
        {"type": "input_text", "text": "Extract the electricity bill contract for SolarVento."},
    ]
    if text_hint and text_hint.strip():
        parts.append({
            "type": "input_text",
            "text": f"Auxiliary text layer (rendered pages are authoritative):\n{text_hint[:12000]}",
        })
    return parts


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


def _safe_pdf_filename(filename: str | None) -> str:
    name = Path(filename or "bill.pdf").name
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name
