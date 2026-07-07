"""Traducción de artículos del blog con OpenAI (en/ca/gl/eu).

La llama el portal (app/portal.py) UNA VEZ por artículo e idioma al pulsar
«Traducir»: el resultado se guarda como archivo fuente en
frontend/content/blog/<lang>/ y entra al flujo normal (preview → publicar).
El generador de páginas nunca llama a esta API: sigue siendo determinista.

Mismo endpoint y patrón que openai_bills (POST /responses con structured
outputs STRICT), pero síncrono: corre dentro de una petición del portal.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

MODEL = "gpt-5.5"
TIMEOUT_SECONDS = 240.0

LANG_NAMES = {
    "en": "inglés",
    "ca": "catalán (formas centrales)",
    "gl": "gallego (normativa RAG)",
    "eu": "euskera batua",
}

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class BlogTranslationError(Exception):
    pass


TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "description", "keywords", "excerpt", "slug", "body_html"],
    "properties": {
        "title": {"type": "string", "description": "Título traducido con intención SEO"},
        "description": {"type": "string", "description": "Meta-description traducida"},
        "keywords": {"type": "string", "description": "Keywords traducidas, separadas por comas"},
        "excerpt": {"type": "string", "description": "Extracto traducido para la tarjeta del índice"},
        "slug": {
            "type": "string",
            "description": "Slug en el idioma destino: minúsculas y dígitos separados por guiones, sin acentos",
        },
        "body_html": {"type": "string", "description": "Cuerpo HTML traducido, estructura intacta"},
    },
}

SYSTEM_PROMPT = """Eres traductor profesional de contenidos sobre autoconsumo solar y el mercado \
eléctrico español, para el blog de SolarVento (una calculadora de ahorro solar).

Reglas:
- Traduce con naturalidad e intención SEO en el idioma destino; nada de traducción literal rígida. \
Mantén el tuteo y el tono cercano pero riguroso del original.
- CONSERVA EXACTAMENTE la estructura HTML del cuerpo: mismas etiquetas, en el mismo orden, con los \
mismos atributos y clases (lead, callout, anatomy, hint, cta-block, cta...). Traduce solo el texto.
- NO traduzcas: SolarVento, CUPS, PVPC, 2.0TD, kWh, kW, Wp, ni nombres de organismos (BOE, IDAE, \
Red Eléctrica…).
- Términos regulados del mercado español (punta, llano, valle, término de potencia, peaje de \
acceso…): usa el equivalente natural del idioma destino y, la primera vez que aparezca cada uno, \
añade el término español entre paréntesis.
- El slug: el título traducido en minúsculas-con-guiones, sin acentos ni caracteres especiales, \
conciso y descriptivo.
- Las keywords: tradúcelas pensando en qué buscaría un hablante de ese idioma, no palabra a palabra."""


def translate_article(
    meta: dict[str, str],
    body_html: str,
    lang: str,
    *,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    model: str = MODEL,
    client: httpx.Client | None = None,
) -> dict[str, str]:
    """Traduce un artículo al idioma dado y devuelve los campos traducidos."""
    if lang not in LANG_NAMES:
        raise BlogTranslationError(f"idioma no soportado: {lang}")
    user_content = f"""Traduce este artículo al {LANG_NAMES[lang]}.

TITLE: {meta.get("title", "")}
DESCRIPTION: {meta.get("description", "")}
KEYWORDS: {meta.get("keywords", "")}
EXCERPT: {meta.get("excerpt", "")}

BODY_HTML:
{body_html}"""
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "blog_article_translation",
                "schema": TRANSLATION_SCHEMA,
                "strict": True,
            }
        },
    }
    own_client = client is None
    if own_client:
        client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
    try:
        try:
            response = client.post("/responses", json=payload)
        except httpx.HTTPError as exc:
            raise BlogTranslationError(f"{lang}: error de red hablando con OpenAI: {exc}") from exc
        if response.status_code >= 400:
            raise BlogTranslationError(
                f"{lang}: OpenAI devolvió HTTP {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        if data.get("status") == "incomplete":
            raise BlogTranslationError(f"{lang}: OpenAI devolvió una traducción incompleta")
        result = json.loads(_output_text(data, lang))
    finally:
        if own_client:
            client.close()

    slug = result.get("slug", "")
    if not SLUG_RE.match(slug):
        raise BlogTranslationError(f"{lang}: slug traducido inválido: «{slug}»")
    if not result.get("body_html", "").strip():
        raise BlogTranslationError(f"{lang}: el cuerpo traducido llegó vacío")
    return result


def _output_text(response: dict[str, Any], lang: str) -> str:
    if isinstance(response.get("output_text"), str) and response["output_text"].strip():
        return response["output_text"]
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise BlogTranslationError(f"{lang}: OpenAI rechazó traducir el artículo")
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise BlogTranslationError(f"{lang}: OpenAI no devolvió la traducción")


def _line(value: str) -> str:
    """Los valores del frontmatter son de una línea."""
    return " ".join(value.split())


def compose_file(meta_es: dict[str, str], translated: dict[str, str], lang: str) -> str:
    """Compone el archivo fuente de la traducción (frontmatter + cuerpo).

    date/updated se copian del original: la traducción hereda su historia.
    """
    lines = [
        "---",
        f"title: {_line(translated['title'])}",
        f"description: {_line(translated['description'])}",
        f"keywords: {_line(translated['keywords'])}",
        f"date: {meta_es['date']}",
        f"excerpt: {_line(translated['excerpt'])}",
        f"slug: {translated['slug']}",
        f"lang: {lang}",
    ]
    if meta_es.get("updated"):
        lines.append(f"updated: {meta_es['updated']}")
    lines.append("---")
    return "\n".join(lines) + "\n" + translated["body_html"].strip() + "\n"
