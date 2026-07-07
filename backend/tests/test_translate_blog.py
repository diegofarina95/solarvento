"""Tests del traductor de artículos del blog (app/translate_blog.py).

La llamada a OpenAI se sustituye por un transporte httpx falso: aquí se prueba
el contrato (payload, parseo, validación) — nunca la red.
"""

import json

import httpx
import pytest

from app import portal, translate_blog

META = {
    "title": "Cómo leer tu factura",
    "description": "Guía de la factura",
    "keywords": "factura, luz",
    "date": "2026-07-07",
    "excerpt": "La factura sin jerga.",
}
BODY = '<p class="lead">Hola</p>\n<h2>Sección</h2>\n<p>Texto.</p>'

GOOD = {
    "title": "How to read your bill",
    "description": "Bill guide",
    "keywords": "electricity bill, spain",
    "excerpt": "Your bill, plain and simple.",
    "slug": "how-to-read-your-electricity-bill",
    "body_html": '<p class="lead">Hello</p>\n<h2>Section</h2>\n<p>Text.</p>',
}


def fake_client(reply: dict, capture: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["payload"] = json.loads(request.content)
        return httpx.Response(200, json=reply)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/v1")


def test_traduce_y_valida():
    capture = {}
    reply = {"status": "completed", "output_text": json.dumps(GOOD)}
    out = translate_blog.translate_article(
        META, BODY, "en", api_key="sk-test", client=fake_client(reply, capture)
    )
    assert out["slug"] == "how-to-read-your-electricity-bill"
    payload = capture["payload"]
    assert payload["text"]["format"]["strict"] is True
    assert "BODY_HTML" in payload["input"][1]["content"]
    assert "inglés" in payload["input"][1]["content"]


def test_slug_invalido_se_rechaza():
    bad = {**GOOD, "slug": "Con Espacios"}
    reply = {"status": "completed", "output_text": json.dumps(bad)}
    with pytest.raises(translate_blog.BlogTranslationError, match="slug"):
        translate_blog.translate_article(META, BODY, "en", api_key="k", client=fake_client(reply))


def test_http_error_se_convierte_en_error_propio():
    def handler(request):
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/v1")
    with pytest.raises(translate_blog.BlogTranslationError, match="HTTP 500"):
        translate_blog.translate_article(META, BODY, "en", api_key="k", client=client)


def test_idioma_no_soportado():
    with pytest.raises(translate_blog.BlogTranslationError, match="idioma"):
        translate_blog.translate_article(META, BODY, "fr", api_key="k")


def test_compose_file_es_parseable_por_el_portal():
    text = translate_blog.compose_file(META, GOOD, "en")
    meta = portal.parse_frontmatter(text)
    assert meta["title"] == GOOD["title"]
    assert meta["slug"] == GOOD["slug"]
    assert meta["lang"] == "en"
    assert meta["date"] == META["date"]  # la fecha se hereda del original
    assert text.rstrip().endswith("<p>Text.</p>")


def test_compose_file_aplana_saltos_de_linea():
    tr = {**GOOD, "title": "Line\nbreaks\nhere"}
    text = translate_blog.compose_file(META, tr, "en")
    assert portal.parse_frontmatter(text)["title"] == "Line breaks here"
