# Traducción automática al subir — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /upload` genera las 4 traducciones (EN/CA/GL/EU) en el mismo paso, sin bloquear la subida si OpenAI falla; el preview muestra los chips de idiomas.

**Architecture:** Extraer el motor de traducción de la ruta `/translate` a un helper compartido `generate_missing_translations(stem)` (escribe borradores, no ejecuta el generador, devuelve `(escritos, errores)`); `upload()` lo llama tras validar el español y regenera; el preview reutiliza `lang_chips()` del índice.

**Tech Stack:** FastAPI, pytest 9 (`cd backend && .venv/bin/pytest`), OpenAI vía `translate_blog.py` (siempre simulado en tests).

**Spec:** `docs/superpowers/specs/2026-07-07-blog-auto-translate-upload-design.md`

## Global Constraints

- Fallos de traducción NUNCA bloquean la subida (ni cambian su código de respuesta 303).
- Sin `OPENAI_API_KEY`: el helper devuelve `([], {"*": "sin OPENAI_API_KEY en backend/.env"})` sin llamar a nada; la subida sigue.
- El helper asume el LOCK cogido por el caller y NO ejecuta `run_generate()`.
- OJO en tests: la máquina de dev tiene clave real de OpenAI en el entorno — todo test que pase por una subida con éxito DEBE monkeypatchear `generate_missing_translations` o `translate_blog.translate_article`, nunca dejar la llamada real.
- Texto de UI en español; comentarios en español; un commit por tarea.

---

### Task 1: Helper `generate_missing_translations` + refactor de `/translate`

**Files:**
- Modify: `backend/app/portal.py` (nuevo helper junto a `publish_group`; la ruta `/translate` pasa a usarlo)
- Test: `backend/tests/test_portal.py` (añadir al final)

**Interfaces:**
- Consumes: `content_path`, `parse_frontmatter`, `TRANSLATION_LANGS`, `get_settings`, `translate_blog.translate_article/compose_file/BlogTranslationError` (existentes).
- Produces (usado por Task 2): `generate_missing_translations(stem: str) -> tuple[list[str], dict[str, str]]` — `(idiomas_escritos, errores_por_idioma)`; escribe `content/blog/<lang>/<stem>.html` de los que salgan bien.

- [ ] **Step 1: Tests que fallan**

Añadir al final de `backend/tests/test_portal.py`:

```python
# --- Helper de traducción compartido (subida automática + botón Traducir) ---

class FakeSettingsConClave:
    resolved_openai_api_key = "sk-test"
    openai_base_url = "https://test/v1"


class FakeSettingsSinClave:
    resolved_openai_api_key = None
    openai_base_url = "https://test/v1"


@pytest.fixture
def grupo_es(monkeypatch, tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    (content / "factura.html").write_text(FM.format(t="Factura"))
    monkeypatch.setattr(portal, "CONTENT_BLOG", content)
    return content


def fake_translate_ok(meta, body, lang, **kwargs):
    return {"title": f"T {lang}", "description": "d", "keywords": "k",
            "excerpt": "e", "slug": f"slug-{lang}", "body_html": "<p>tr</p>"}


def test_helper_traduce_los_que_faltan(grupo_es, monkeypatch):
    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettingsConClave())
    monkeypatch.setattr(portal.translate_blog, "translate_article", fake_translate_ok)
    written, errors = portal.generate_missing_translations("factura")
    assert sorted(written) == ["ca", "en", "eu", "gl"]
    assert errors == {}
    for lang in ("en", "ca", "gl", "eu"):
        assert (grupo_es / lang / "factura.html").exists()


def test_helper_fallo_parcial_escribe_el_resto(grupo_es, monkeypatch):
    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettingsConClave())

    def translate(meta, body, lang, **kwargs):
        if lang == "gl":
            raise portal.translate_blog.BlogTranslationError("gl: la API dijo no")
        return fake_translate_ok(meta, body, lang)

    monkeypatch.setattr(portal.translate_blog, "translate_article", translate)
    written, errors = portal.generate_missing_translations("factura")
    assert sorted(written) == ["ca", "en", "eu"]
    assert "gl" in errors
    assert not (grupo_es / "gl" / "factura.html").exists()


def test_helper_sin_clave_no_intenta_nada(grupo_es, monkeypatch):
    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettingsSinClave())
    monkeypatch.setattr(
        portal.translate_blog, "translate_article",
        lambda *a, **k: pytest.fail("no debe llamarse sin clave"),
    )
    written, errors = portal.generate_missing_translations("factura")
    assert written == []
    assert "*" in errors


def test_helper_sin_idiomas_pendientes(grupo_es, monkeypatch):
    for lang in ("en", "ca", "gl", "eu"):
        d = grupo_es / lang
        d.mkdir()
        (d / "factura.html").write_text(FM.format(t=f"T {lang}"))
    written, errors = portal.generate_missing_translations("factura")
    assert (written, errors) == ([], {})
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -k helper -v`
Expected: FAIL — `AttributeError: module 'app.portal' has no attribute 'generate_missing_translations'`

- [ ] **Step 3: Implementar el helper y refactorizar `/translate`**

Añadir en `backend/app/portal.py`, después de `restore_aside()`:

```python
def generate_missing_translations(stem: str) -> tuple[list[str], dict[str, str]]:
    """Traduce en paralelo los idiomas que falten del grupo y escribe borradores.

    Compartido por la subida (automática) y el botón «Traducir» (reintento).
    Asume el LOCK cogido y NO ejecuta el generador (eso es del caller).
    Devuelve (idiomas_escritos, errores_por_idioma); sin clave de API no
    intenta nada — la subida no debe bloquearse por OpenAI."""
    missing = [lang for lang in TRANSLATION_LANGS if not content_path(lang, stem).exists()]
    if not missing:
        return [], {}
    settings = get_settings()
    api_key = settings.resolved_openai_api_key
    if not api_key:
        return [], {"*": "sin OPENAI_API_KEY en backend/.env"}
    raw = content_path("es", stem).read_text()
    meta = parse_frontmatter(raw)
    body = re.sub(r"^---\r?\n[\s\S]*?\r?\n---\r?\n", "", raw).strip()

    def one(lang: str):
        result = translate_blog.translate_article(
            meta, body, lang, api_key=api_key, base_url=settings.openai_base_url
        )
        return lang, translate_blog.compose_file(meta, result, lang)

    outcomes: dict[str, str] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(missing)) as pool:
        for future in [pool.submit(one, lang) for lang in missing]:
            try:
                lang, content = future.result()
                outcomes[lang] = content
            except translate_blog.BlogTranslationError as exc:
                errors[str(exc).split(":", 1)[0]] = str(exc)
    written = []
    for lang, content in outcomes.items():
        path = content_path(lang, stem)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(lang)
    return written, errors
```

Reescribir el cuerpo de la ruta `/translate` (mantiene su comportamiento externo):

```python
@app.post("/translate/{stem}", response_class=HTMLResponse)
def translate(stem: str):
    """Genera con OpenAI los borradores de los idiomas que falten."""
    src = content_path("es", stem)
    if not valid_filename(f"{stem}.html") or not src.exists():
        return error_page("No encontrado", f"No existe el artículo «{stem}».", 404)
    if not [lang for lang in TRANSLATION_LANGS if not content_path(lang, stem).exists()]:
        return error_page("Nada que traducir", "Ya existe en todos los idiomas.", 409)
    if not get_settings().resolved_openai_api_key:
        return error_page("Sin clave de OpenAI", "No hay OPENAI_API_KEY en backend/.env.", 500)
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        written, errors = generate_missing_translations(stem)
        if written:
            ok, out = run_generate()
            if not ok:
                for lang in written:
                    content_path(lang, stem).unlink(missing_ok=True)
                run_generate()
                return error_page("El generador rechazó las traducciones", out, 422)
    finally:
        LOCK.release()
    chips = " · ".join(
        f'<a href="/preview/{lang}/{stem}">{lang.upper()} ✏️</a>' for lang in written
    )
    fails = "".join(f"<pre>{html.escape(e)}</pre>" for e in errors.values())
    return page(
        "Traducciones generadas",
        f"""<h1>Traducciones generadas</h1>
<p>Borradores listos para revisar: {chips or "ninguno"}</p>
{fails}
<p class="meta">Revisa cada preview y usa «Publicar todo lo pendiente» cuando estén bien.</p>
<p><a href="/">← Volver al portal</a></p>""",
        200 if written else 502,
    )
```

- [ ] **Step 4: Verificar que pasan (nuevos + los de /translate existentes)**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v`
Expected: todos passed (incluido `test_translate_escribe_borradores`)

- [ ] **Step 5: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: motor de traducción extraído a generate_missing_translations"
```

---

### Task 2: La subida traduce automáticamente

**Files:**
- Modify: `backend/app/portal.py` (ruta `/upload`; copy del formulario en `index()`)
- Test: `backend/tests/test_portal.py` (nuevos + blindar los de subida existentes)

**Interfaces:**
- Consumes: `generate_missing_translations(stem) -> tuple[list[str], dict[str, str]]` (Task 1).
- Produces: `POST /upload` traduce en el mismo paso; misma respuesta 303 → `/preview/{stem}` pase lo que pase con OpenAI.

- [ ] **Step 1: Blindar los tests de subida existentes**

Los dos tests de subida con éxito no deben tocar OpenAI real. En
`test_upload_con_bom_se_normaliza` y `test_upload_crea_directorio_si_falta`,
añadir tras el monkeypatch de `run_generate`:

```python
    monkeypatch.setattr(portal, "generate_missing_translations", lambda stem: ([], {}))
```

- [ ] **Step 2: Tests nuevos que fallan**

Añadir al final de `backend/tests/test_portal.py`:

```python
# --- Subida con traducción automática ---

RAW_OK = b"---\ntitle: x\ndescription: d\nkeywords: k\ndate: 2026-07-07\nexcerpt: e\n---\n<p>x</p>"


def test_upload_genera_traducciones(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettingsConClave())
    monkeypatch.setattr(portal.translate_blog, "translate_article", fake_translate_ok)
    r = client.post("/upload", files={"file": ("nuevo.html", RAW_OK)}, follow_redirects=False)
    assert r.status_code == 303
    for lang in ("en", "ca", "gl", "eu"):
        assert (tmp_path / lang / "nuevo.html").exists()


def test_upload_traduccion_parcial_no_bloquea(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettingsConClave())

    def translate(meta, body, lang, **kwargs):
        if lang in ("gl", "eu"):
            raise portal.translate_blog.BlogTranslationError(f"{lang}: caído")
        return fake_translate_ok(meta, body, lang)

    monkeypatch.setattr(portal.translate_blog, "translate_article", translate)
    r = client.post("/upload", files={"file": ("nuevo.html", RAW_OK)}, follow_redirects=False)
    assert r.status_code == 303
    assert (tmp_path / "en" / "nuevo.html").exists()
    assert not (tmp_path / "gl" / "nuevo.html").exists()


def test_upload_sin_clave_sube_sin_traducir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettingsSinClave())
    r = client.post("/upload", files={"file": ("nuevo.html", RAW_OK)}, follow_redirects=False)
    assert r.status_code == 303
    assert (tmp_path / "nuevo.html").exists()
    assert not (tmp_path / "en").exists()


def test_upload_rollback_si_generador_rechaza_traducciones(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    monkeypatch.setattr(portal, "get_settings", lambda: FakeSettingsConClave())
    monkeypatch.setattr(portal.translate_blog, "translate_article", fake_translate_ok)
    gen = iter([(True, ""), (False, "Error: hreflang roto"), (True, "")])
    monkeypatch.setattr(portal, "run_generate", lambda: next(gen))
    r = client.post("/upload", files={"file": ("nuevo.html", RAW_OK)}, follow_redirects=False)
    assert r.status_code == 303  # la subida del español NO se pierde
    assert (tmp_path / "nuevo.html").exists()
    assert not (tmp_path / "en" / "nuevo.html").exists()  # traducciones revertidas
```

- [ ] **Step 3: Verificar que fallan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -k "upload_genera or upload_traduccion or upload_sin_clave or upload_rollback" -v`
Expected: FAIL — no existen los archivos de traducción (la subida aún no traduce)

- [ ] **Step 4: Implementar en `upload()` y actualizar el copy**

En `upload()`, dentro del bloque del LOCK, tras el `if not ok:` del primer
`run_generate()` (después del `return error_page(...)` 422), añadir:

```python
        # Traducción automática: el grupo nace completo; los fallos no
        # bloquean (quedan pendientes para el botón «Traducir»).
        written, _errors = generate_missing_translations(target.stem)
        if written:
            ok, out = run_generate()
            if not ok:
                for lang in written:
                    content_path(lang, target.stem).unlink(missing_ok=True)
                run_generate()
```

En `index()`, actualizar el formulario y la ayuda:

- Botón: `Subir y previsualizar` → `Subir, traducir y previsualizar`.
- En el párrafo de ayuda, sustituir «Las traducciones (EN/CA/GL/EU) se generan
  con el botón «Traducir» y se revisan antes de publicar.» por «Al subir se
  generan solas las traducciones (EN/CA/GL/EU); si alguna falla, el botón
  «Traducir» la reintenta.»

- [ ] **Step 5: Verificar que pasan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v`
Expected: todos passed

- [ ] **Step 6: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: la subida traduce automáticamente a EN/CA/GL/EU (fallos no bloqueantes)"
```

---

### Task 3: Chips de idiomas en el preview + verificación completa y despliegue

**Files:**
- Modify: `backend/app/portal.py` (ruta `preview()`)
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Consumes: `lang_chips(g)`, `list_groups()` (existentes).
- Produces: el preview muestra el estado por idioma del grupo.

- [ ] **Step 1: Test que falla**

```python
def test_preview_muestra_chips_de_idiomas(client, monkeypatch, tmp_path):
    content = tmp_path / "content"
    (content / "en").mkdir(parents=True)
    (content / "factura.html").write_text(FM.format(t="Factura"))
    (content / "en" / "factura.html").write_text(FM.format(t="Bill"))
    monkeypatch.setattr(portal, "CONTENT_BLOG", content)
    monkeypatch.setattr(portal, "PUBLIC_BLOG", tmp_path / "public")
    monkeypatch.setattr(portal, "draft_refs", lambda: {"factura", "en/factura"})
    r = client.get("/preview/factura")
    assert r.status_code == 200
    assert 'href="/preview/en/factura"' in r.text  # chip del borrador EN
    assert "Traducir (3)" in r.text  # faltan ca/gl/eu → reintento a mano
```

- [ ] **Step 2: Verificar que falla**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -k chips_de_idiomas -v`
Expected: FAIL — el preview no contiene los chips

- [ ] **Step 3: Implementar**

En `preview()`, localizar el grupo y añadir la fila de chips antes del iframe
(entre el `<div class="actions">` del widget de programación y el `<iframe>`):

```python
    g = next((x for x in list_groups() if x["stem"] == stem), None)
    chips_row = f'<div class="actions">{lang_chips(g)}</div>' if g else ""
```

y en el HTML de la página:

```python
<div class="actions">{schedule_widget(stem, blog_schedule.get(stem), True)}</div>
{chips_row}
<iframe src="/draft/{ref}"></iframe>
```

- [ ] **Step 4: Suite completa**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest`
Expected: todo passed, 0 failed

- [ ] **Step 5: Commit + reinicio + humo**

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: chips de idiomas en el preview"
systemctl --user restart solvento-portal
sleep 3
curl -s "http://$(tailscale ip -4 | head -n1):8130/" | grep -c "Subir, traducir y previsualizar"
```

Expected: `1` (el copy nuevo se sirve). NO subir artículos de prueba: hay un
borrador real pendiente y la subida ahora consume API de OpenAI.
