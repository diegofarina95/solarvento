"""Tests del portal de publicación del blog (app/portal.py).

El portal es una herramienta SOLO de la máquina de dev, atada a Tailscale;
aquí se prueban las piezas puras (validación de nombres, guard de IPs,
parsers) y las rutas con las operaciones de disco/git/rsync sustituidas.
"""

import pytest
from fastapi.testclient import TestClient

from app import portal


# --- Validación del nombre de archivo (slug) ---

@pytest.mark.parametrize(
    "name",
    [
        "como-leer-tu-factura-de-la-luz.html",
        "a.html",
        "articulo-2026.html",
    ],
)
def test_nombre_valido(name):
    assert portal.valid_filename(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "sin-extension",
        "Mayusculas.html",
        "con espacio.html",
        "acentuación.html",
        "../fuera.html",
        "sub/dir.html",
        ".html",
        "-empieza-con-guion.html",
        "doble..html",
        "articulo.htm",
    ],
)
def test_nombre_invalido(name):
    assert not portal.valid_filename(name)


# --- Guard de IPs: solo Tailscale y loopback ---

@pytest.mark.parametrize(
    "ip",
    ["100.64.0.1", "100.71.97.110", "100.127.255.254", "127.0.0.1", "::1",
     "fd7a:115c:a1e0::9001:6170"],
)
def test_ip_permitida(ip):
    assert portal.client_allowed(ip)


@pytest.mark.parametrize(
    "ip",
    ["192.168.1.10", "10.10.1.38", "8.8.8.8", "100.128.0.1", "100.63.255.255",
     "2001:db8::1", "testclient", "", None],
)
def test_ip_rechazada(ip):
    assert not portal.client_allowed(ip)


def test_middleware_rechaza_cliente_desconocido():
    # TestClient se presenta como "testclient" (no es una IP de la tailnet):
    # el middleware debe cortar ANTES de llegar a cualquier ruta.
    client = TestClient(portal.app)
    r = client.get("/")
    assert r.status_code == 403


# --- Parser del .env (formato "CLAVE: valor", igual que deploy.sh) ---

def test_read_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "SSH_ADDRESS: 10.10.1.38\n"
        "SSH_PORT: 22\n"
        "SSH_USER: diego\n"
        "SSH_PASSWORD: se:creto con espacios\n"
        "PATH: /home/diego/solvento\n"
        "# comentario\n"
        "\n"
    )
    got = portal.read_env(env)
    assert got["SSH_ADDRESS"] == "10.10.1.38"
    assert got["SSH_PASSWORD"] == "se:creto con espacios"
    assert got["PATH"] == "/home/diego/solvento"
    assert "# comentario" not in got


# --- Frontmatter mínimo para el listado ---

def test_parse_frontmatter():
    text = (
        "---\n"
        "title: Mi título\n"
        "description: Desc\n"
        "date: 2026-07-07\n"
        "---\n"
        "<p>Cuerpo</p>"
    )
    meta = portal.parse_frontmatter(text)
    assert meta["title"] == "Mi título"
    assert meta["date"] == "2026-07-07"


def test_parse_frontmatter_invalido():
    assert portal.parse_frontmatter("<p>sin frontmatter</p>") == {}


# --- Normalización de subidas: BOM y líneas en blanco iniciales ---

def test_normalize_quita_bom_y_blancos():
    raw = "﻿\n  \n---\ntitle: x\n---\n<p>x</p>".encode("utf-8")
    text = portal.normalize_upload(raw)
    assert text.startswith("---\n")
    assert portal.parse_frontmatter(text)["title"] == "x"


def test_normalize_no_toca_lo_que_no_es_frontmatter():
    raw = "<!doctype html><p>x</p>".encode("utf-8")
    assert portal.normalize_upload(raw) == "<!doctype html><p>x</p>"


# --- Rutas con cliente permitido y efectos secundarios sustituidos ---

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(portal, "client_allowed", lambda ip: True)
    return TestClient(portal.app)


def test_index_lista_articulos(client, monkeypatch):
    # stem = nombre en disco (clave del portal); slug = URL pública (frontmatter)
    monkeypatch.setattr(
        portal,
        "list_articles",
        lambda: [
            {"stem": "uno", "slug": "uno-largo-seo", "title": "Uno",
             "date": "2026-07-01", "draft": False},
        ],
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "Uno" in r.text
    assert "https://solarvento.es/blog/uno-largo-seo/" in r.text  # URL limpia, sin .html
    assert 'action="/delete/uno"' in r.text  # las rutas del portal van por stem


def test_public_slug_frontmatter_y_fallback(tmp_path):
    con = tmp_path / "corto.html"
    con.write_text("---\ntitle: t\nslug: url-larga-seo\n---\n<p>x</p>")
    assert portal.public_slug(con) == "url-larga-seo"
    sin = tmp_path / "sin-slug.html"
    sin.write_text("---\ntitle: t\n---\n<p>x</p>")
    assert portal.public_slug(sin) == "sin-slug"
    malo = tmp_path / "malo.html"
    malo.write_text("---\ntitle: t\nslug: ../fuera\n---\n<p>x</p>")
    assert portal.public_slug(malo) == "malo"  # slug inválido no sale del dir


def test_draft_resuelve_slug_del_frontmatter(client, monkeypatch, tmp_path):
    content, public = tmp_path / "content", tmp_path / "public"
    content.mkdir(), public.mkdir()
    (content / "corto.html").write_text("---\ntitle: t\nslug: url-larga-seo\n---\n<p>x</p>")
    (public / "url-larga-seo").mkdir()
    (public / "url-larga-seo" / "index.html").write_text("<html>GENERADO</html>")
    monkeypatch.setattr(portal, "CONTENT_BLOG", content)
    monkeypatch.setattr(portal, "PUBLIC_BLOG", public)
    r = client.get("/draft/corto")
    assert r.status_code == 200
    assert "GENERADO" in r.text


def test_upload_rechaza_nombre_invalido(client):
    r = client.post(
        "/upload",
        files={"file": ("Malo Con Espacios.html", b"---\ntitle: x\n---\n<p>x</p>")},
    )
    assert r.status_code == 400
    assert "nombre" in r.text.lower()


def test_upload_rechaza_slug_existente(client, monkeypatch, tmp_path):
    (tmp_path / "existe.html").write_text("x")
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    r = client.post(
        "/upload",
        files={"file": ("existe.html", b"---\ntitle: x\n---\n<p>x</p>")},
    )
    assert r.status_code == 409
    assert "existe" in r.text.lower()


def test_upload_sin_frontmatter_da_ayuda(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    r = client.post(
        "/upload",
        files={"file": ("blog-factura.html", b"<!doctype html><p>articulo</p>")},
    )
    assert r.status_code == 422
    assert "frontmatter" in r.text
    assert "title: T" in r.text  # la plantilla aparece en la ayuda
    assert list(tmp_path.iterdir()) == []  # no se escribió nada


def test_upload_con_bom_se_normaliza(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    raw = "﻿---\ntitle: x\ndescription: d\nkeywords: k\ndate: 2026-07-07\nexcerpt: e\n---\n<p>x</p>".encode("utf-8")
    r = client.post(
        "/upload", files={"file": ("con-bom.html", raw)}, follow_redirects=False
    )
    assert r.status_code == 303
    saved = (tmp_path / "con-bom.html").read_text(encoding="utf-8")
    assert saved.startswith("---\n")  # sin BOM


def test_upload_crea_directorio_si_falta(client, monkeypatch, tmp_path):
    # git rm del último artículo borra también content/blog/ (git no guarda
    # directorios vacíos): la subida debe recrearlo, no dar un 500.
    dest = tmp_path / "content" / "blog"
    monkeypatch.setattr(portal, "CONTENT_BLOG", dest)
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    raw = b"---\ntitle: x\ndescription: d\nkeywords: k\ndate: 2026-07-07\nexcerpt: e\n---\n<p>x</p>"
    r = client.post("/upload", files={"file": ("nuevo.html", raw)}, follow_redirects=False)
    assert r.status_code == 303
    assert (dest / "nuevo.html").exists()


def test_error_inesperado_da_pagina_legible(monkeypatch):
    monkeypatch.setattr(portal, "client_allowed", lambda ip: True)
    monkeypatch.setattr(portal, "list_articles", lambda: 1 / 0)
    client = TestClient(portal.app, raise_server_exceptions=False)
    r = client.get("/")
    assert r.status_code == 500
    assert "ZeroDivisionError" in r.text


def test_upload_rechaza_archivo_grande(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    big = b"x" * (portal.MAX_UPLOAD_BYTES + 1)
    r = client.post("/upload", files={"file": ("grande.html", big)})
    assert r.status_code == 413


def test_delete_rechaza_ultimo_articulo(client, monkeypatch, tmp_path):
    (tmp_path / "unico.html").write_text("x")
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    r = client.post("/delete/unico")
    assert r.status_code == 409
    assert "último" in r.text.lower() or "ultimo" in r.text.lower()


def test_delete_rechaza_slug_inexistente(client, monkeypatch, tmp_path):
    (tmp_path / "a.html").write_text("x")
    (tmp_path / "b.html").write_text("x")
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    r = client.post("/delete/no-esta")
    assert r.status_code == 404
