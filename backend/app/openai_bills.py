"""Layer 2 — extracción de facturas con un modelo LLM (OpenAI, con visión).

Vía ÚNICA de ingesta: PDF-texto, escaneo y foto entran igual y salen como el
contrato tipado de bill_contract (raw_text por campo). El modelo PROPONE; la
normalización y las guardas deterministas DISPONEN en bill_normalise (Layer 3).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from .bill_contract import BILL_CONTRACT_SCHEMA, EXTRACTION_SYSTEM_PROMPT
from .bills import BillParseError


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
    ) -> dict[str, Any]:
        """Extrae el CONTRATO tipado (bill_contract) de cualquier factura.

        Se envía el fichero a un modelo con visión (la API renderiza las páginas
        del PDF), con el texto del PDF como señal auxiliar cuando existe. Structured
        outputs STRICT, temperature 0. Devuelve el contrato en crudo (raw_text por
        campo); la normalización y la reconciliación son deterministas en Layer 3."""
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

        user_content: list[dict[str, Any]] = [
            file_content,
            {"type": "input_text", "text": "Extract the electricity bill contract for SolVento."},
        ]
        if text_hint and text_hint.strip():
            user_content.append({
                "type": "input_text",
                "text": (
                    "Auxiliary PDF text layer (may be noisy; the rendered pages are "
                    f"authoritative):\n{text_hint[:12000]}"
                ),
            })

        payload = {
            "model": self.model,
            "temperature": 0,
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
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise BillParseError("OpenAI devolvió una respuesta no válida") from exc


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
