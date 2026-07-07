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
    monkeypatch.setattr(portal, "draft_refs", lambda: set())
    monkeypatch.setattr(
        portal,
        "list_groups",
        lambda: [
            {"stem": "uno", "slug": "uno-largo-seo", "title": "Uno",
             "date": "2026-07-01", "draft": False,
             "tr": {"en": {"slug": "one-long", "draft": True}, "ca": None, "gl": None, "eu": None}},
        ],
    )
    r = client.get("/")
    assert r.status_code == 200
    assert "Uno" in r.text
    assert "https://solarvento.es/blog/uno-largo-seo/" in r.text  # URL limpia, sin .html
    assert 'action="/delete/uno"' in r.text  # las rutas del portal van por stem
    assert 'href="/preview/en/uno"' in r.text  # borrador EN enlazado
    assert 'action="/translate/uno"' in r.text  # faltan ca/gl/eu → botón Traducir


# --- Referencias (idioma, archivo) de las rutas del portal ---

@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("factura", ("es", "factura")),
        ("en/factura", ("en", "factura")),
        ("eu/otro-articulo", ("eu", "otro-articulo")),
        ("fr/factura", None),  # idioma no soportado
        ("en/Sub/x", None),
        ("en/../../etc", None),
        ("", None),
    ],
)
def test_parse_ref(ref, expected):
    assert portal.parse_ref(ref) == expected


def test_content_path_y_public_url(monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    assert portal.content_path("es", "x") == tmp_path / "x.html"
    assert portal.content_path("en", "x") == tmp_path / "en" / "x.html"
    assert portal.public_url("es", "mi-slug") == "https://solarvento.es/blog/mi-slug/"
    assert portal.public_url("en", "my-slug") == "https://solarvento.es/blog/en/my-slug/"


def test_translate_escribe_borradores(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))

    class FakeSettings:
        resolved_openai_api_key = "sk-test"
        openai_base_url = "https://test/v1"

    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettings())
    (tmp_path / "factura.html").write_text(
        "---\ntitle: T\ndescription: d\nkeywords: k\ndate: 2026-07-07\nexcerpt: e\n---\n<p>x</p>"
    )

    def fake_translate(meta, body, lang, **kwargs):
        return {"title": f"T {lang}", "description": "d", "keywords": "k",
                "excerpt": "e", "slug": f"slug-{lang}", "body_html": "<p>tr</p>"}

    monkeypatch.setattr(portal.translate_blog, "translate_article", fake_translate)
    r = client.post("/translate/factura")
    assert r.status_code == 200
    for lang in ("en", "ca", "gl", "eu"):
        text = (tmp_path / lang / "factura.html").read_text()
        assert f"lang: {lang}" in text
        assert f"slug: slug-{lang}" in text
    assert 'href="/preview/en/factura"' in r.text


def test_translate_sin_original_da_404(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    r = client.post("/translate/no-existe")
    assert r.status_code == 404


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
    monkeypatch.setattr(portal, "list_groups", lambda: 1 / 0)
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


# --- Publicación selectiva de un grupo (publish_group) ---

FM = "---\ntitle: {t}\ndescription: d\nkeywords: k\ndate: 2026-07-07\nexcerpt: e\n---\n<p>x</p>"


@pytest.fixture
def blog_fs(monkeypatch, tmp_path):
    """content/ con dos grupos (factura con EN, otro solo es) + aside/ + public/."""
    content, public, aside = tmp_path / "content", tmp_path / "public", tmp_path / "aside"
    content.mkdir(), public.mkdir()
    (content / "factura.html").write_text(FM.format(t="Factura"))
    (content / "en").mkdir()
    (content / "en" / "factura.html").write_text(FM.format(t="Bill") + "\n")
    (content / "otro.html").write_text(FM.format(t="Otro"))
    monkeypatch.setattr(portal, "CONTENT_BLOG", content)
    monkeypatch.setattr(portal, "PUBLIC_BLOG", public)
    monkeypatch.setattr(portal, "DRAFTS_ASIDE", aside)
    monkeypatch.setattr(portal, "draft_refs", lambda: {"factura", "en/factura", "otro"})
    return content, public, aside


def test_group_refs_y_group_langs(blog_fs, monkeypatch):
    assert portal.group_refs("factura") == ["en/factura", "factura"]
    assert portal.group_refs("otro") == ["otro"]
    assert portal.group_refs("no-existe") == []
    assert portal.group_langs("factura") == ["es", "en"]
    assert portal.group_langs("otro") == ["es"]


def test_publish_group_aparta_otros_y_los_restaura(blog_fs, monkeypatch):
    content, public, aside = blog_fs
    seen: dict = {}

    def fake_generate():
        # dentro de la publicación, «otro» debe estar apartado y el grupo presente
        seen.setdefault("otro_fuera", not (content / "otro.html").exists())
        seen.setdefault("grupo_dentro", (content / "factura.html").exists())
        return True, ""

    def fake_commit(msg):
        seen["msg"] = msg
        return True, "ok"

    monkeypatch.setattr(portal, "run_generate", fake_generate)
    monkeypatch.setattr(portal, "commit_paths", fake_commit)
    monkeypatch.setattr(portal, "sync_to_prod", lambda: (True, "sincronizado"))

    ok, detail, published = portal.publish_group("factura", scheduled=True)

    assert ok
    assert seen["otro_fuera"] and seen["grupo_dentro"]
    assert (content / "otro.html").exists()  # restaurado
    assert not any(aside.rglob("*.html")) if aside.exists() else True  # aside vacío al terminar
    assert [(t, lang) for t, lang, _ in published] == [("Factura", "es"), ("Bill", "en")]
    assert "programado, portal" in seen["msg"]
    assert "«Factura»" in seen["msg"] and "[es, en]" in seen["msg"]


def test_publish_group_restaura_si_falla_el_commit(blog_fs, monkeypatch):
    content, public, aside = blog_fs
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    monkeypatch.setattr(portal, "commit_paths", lambda msg: (False, "boom"))
    monkeypatch.setattr(portal, "sync_to_prod", lambda: (True, ""))
    ok, detail, published = portal.publish_group("factura", scheduled=False)
    assert not ok
    assert "boom" in detail
    assert (content / "otro.html").exists()  # restaurado pese al fallo


def test_publish_group_sin_borradores_reintenta_solo_sync(blog_fs, monkeypatch):
    # tras un fallo de solo-sync el grupo ya está commiteado (sin borradores):
    # el reintento debe regenerar + commit no-op + rsync, sin apartar nada.
    monkeypatch.setattr(portal, "draft_refs", lambda: set())
    calls: list[str] = []
    monkeypatch.setattr(portal, "run_generate", lambda: (calls.append("gen"), (True, ""))[1])
    monkeypatch.setattr(
        portal, "commit_paths",
        lambda msg: (calls.append("commit"), (True, "sin cambios que commitear"))[1],
    )
    monkeypatch.setattr(
        portal, "sync_to_prod", lambda: (calls.append("sync"), (True, "sincronizado"))[1]
    )
    ok, detail, published = portal.publish_group("factura", scheduled=False)
    assert ok
    assert calls == ["gen", "commit", "sync"]
    assert [lang for _, lang, _ in published] == ["es", "en"]


def test_restore_aside_recupera_borradores(blog_fs, monkeypatch):
    content, public, aside = blog_fs
    calls: list[str] = []
    monkeypatch.setattr(portal, "run_generate", lambda: (calls.append("gen"), (True, ""))[1])
    (aside / "en").mkdir(parents=True)
    (aside / "en" / "perdido.html").write_text("x")
    portal.restore_aside()
    assert (content / "en" / "perdido.html").exists()
    assert not aside.exists()
    assert calls == ["gen"]


def test_restore_aside_sin_restos_no_regenera(blog_fs, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(portal, "run_generate", lambda: (calls.append("gen"), (True, ""))[1])
    portal.restore_aside()  # aside/ ni siquiera existe
    assert calls == []


# --- Planificador: tick sin hilo ni esperas ---

from datetime import datetime

from app import blog_schedule


@pytest.fixture(autouse=True)
def schedule_file(monkeypatch, tmp_path):
    monkeypatch.setattr(blog_schedule, "SCHEDULE_FILE", tmp_path / "schedule.json")


def test_tick_publica_lo_vencido_y_limpia(monkeypatch):
    blog_schedule.set_schedule("factura", "2026-07-08T09:00")
    blog_schedule.set_schedule("futura", "2030-01-01T09:00")
    calls = []
    monkeypatch.setattr(
        portal, "publish_group",
        lambda stem, scheduled: (calls.append((stem, scheduled)), (True, "publicado", []))[1],
    )
    portal.scheduler_tick(datetime(2026, 7, 8, 9, 0, 30))
    assert calls == [("factura", True)]
    assert blog_schedule.get("factura") is None  # publicada → fuera del JSON
    assert blog_schedule.get("futura")["state"] == "pending"  # aún no toca


def test_tick_fallo_marca_error_sin_reintentar(monkeypatch):
    blog_schedule.set_schedule("factura", "2026-07-08T09:00")
    monkeypatch.setattr(
        portal, "publish_group", lambda stem, scheduled: (False, "sync a prod: caído", [])
    )
    portal.scheduler_tick(datetime(2026, 7, 8, 9, 1))
    entry = blog_schedule.get("factura")
    assert entry["state"] == "error"
    assert "caído" in entry["error"]
    # el siguiente tick NO reintenta (error no está en due)
    monkeypatch.setattr(portal, "publish_group", lambda *a, **k: pytest.fail("no debe llamarse"))
    portal.scheduler_tick(datetime(2026, 7, 8, 9, 2))


def test_tick_respeta_el_lock(monkeypatch):
    blog_schedule.set_schedule("factura", "2026-07-08T09:00")
    monkeypatch.setattr(portal, "publish_group", lambda *a, **k: pytest.fail("no debe llamarse"))
    assert portal.LOCK.acquire(blocking=False)
    try:
        portal.scheduler_tick(datetime(2026, 7, 8, 9, 1))
    finally:
        portal.LOCK.release()
    assert blog_schedule.get("factura")["state"] == "pending"  # intacta: reintenta luego
