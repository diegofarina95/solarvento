# Publicación programada del blog — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Programar por artículo la hora de publicación en el portal del blog: a la hora T el portal publica el grupo (español + traducciones existentes) solo, con recuperación manual si el portal estaba caído o el intento falló.

**Architecture:** Un módulo nuevo `blog_schedule.py` (almacén JSON puro, sin FastAPI) + cambios en `portal.py`: publicación selectiva de grupo (`publish_group`, apartando el resto de borradores a `.drafts-aside/`), un hilo planificador arrancado por lifespan que hace tick cada 30 s, tres rutas nuevas y el widget de programación en índice y preview.

**Tech Stack:** FastAPI 0.139 / Starlette 1.3, pytest 9 (TestClient sin context manager NO ejecuta lifespan → el hilo no arranca en tests), threading, JSON en disco.

**Spec:** `docs/superpowers/specs/2026-07-07-blog-scheduled-publishing-design.md`

## Global Constraints

- Los tests se ejecutan desde `backend/`: `.venv/bin/pytest tests/... -v` (los `integration` quedan excluidos por `addopts`).
- Horas: strings naive `YYYY-MM-DDTHH:MM` (formato `datetime-local`), hora local de la máquina. Nunca zonas horarias explícitas.
- Estados de programación: `pending`, `stale`, `error` — exactamente esos.
- Archivos de estado: `.blog-schedule.json` y `.drafts-aside/` en la RAÍZ del repo, ambos gitignored.
- Todo texto de UI en español, mismo estilo que el portal actual.
- El portal mantiene su invariante: una operación de escritura a la vez vía `LOCK` (`threading.Lock` módulo-global). `publish_group()` se llama SIEMPRE con el LOCK ya cogido por el caller.
- Comentarios de código en español, como el resto de `portal.py`.
- Un commit por tarea.

---

### Task 1: Almacén de programaciones (`blog_schedule.py`)

**Files:**
- Create: `backend/app/blog_schedule.py`
- Test: `backend/tests/test_blog_schedule.py`
- Modify: `.gitignore` (raíz del repo)

**Interfaces:**
- Produces (usado por Tasks 3–5):
  - `SCHEDULE_FILE: Path` (module-global, monkeypatcheable)
  - `parse_local(value: str) -> datetime | None`
  - `load() -> dict[str, dict]` — `{stem: {"publish_at": str, "state": str, "error": str | None}}`
  - `get(stem: str) -> dict | None`
  - `set_schedule(stem: str, publish_at: str) -> None` (crea o sobrescribe, estado `pending`)
  - `remove(stem: str) -> None`
  - `due(now: datetime) -> list[str]` (stems `pending` con hora vencida, orden alfabético)
  - `mark_stale_before(boot: datetime) -> None`
  - `mark_error(stem: str, message: str) -> None`

- [ ] **Step 1: Añadir a `.gitignore`**

Añadir al final del bloque `# App` de `/home/diego/taller-projects/solvento/.gitignore`:

```
# Portal del blog: programaciones y borradores apartados durante publish_group
.blog-schedule.json
.drafts-aside/
```

- [ ] **Step 2: Escribir los tests que fallan**

Crear `backend/tests/test_blog_schedule.py`:

```python
"""Tests del almacén de programaciones del blog (app/blog_schedule.py)."""

from datetime import datetime

import pytest

from app import blog_schedule


@pytest.fixture(autouse=True)
def schedule_file(monkeypatch, tmp_path):
    f = tmp_path / "schedule.json"
    monkeypatch.setattr(blog_schedule, "SCHEDULE_FILE", f)
    return f


def test_parse_local():
    assert blog_schedule.parse_local("2026-07-09T09:00") == datetime(2026, 7, 9, 9, 0)
    assert blog_schedule.parse_local("2026-07-09 09:00") is None
    assert blog_schedule.parse_local("") is None
    assert blog_schedule.parse_local(None) is None


def test_set_get_remove():
    blog_schedule.set_schedule("factura", "2026-07-09T09:00")
    assert blog_schedule.get("factura") == {
        "publish_at": "2026-07-09T09:00", "state": "pending", "error": None,
    }
    blog_schedule.remove("factura")
    assert blog_schedule.get("factura") is None
    blog_schedule.remove("factura")  # idempotente


def test_set_sobrescribe_y_resetea_estado():
    blog_schedule.set_schedule("factura", "2026-07-09T09:00")
    blog_schedule.mark_error("factura", "rsync caído")
    blog_schedule.set_schedule("factura", "2026-07-10T09:00")  # reprogramar limpia el error
    assert blog_schedule.get("factura") == {
        "publish_at": "2026-07-10T09:00", "state": "pending", "error": None,
    }


def test_load_sin_archivo_es_vacio():
    assert blog_schedule.load() == {}


def test_load_json_corrupto_es_vacio(schedule_file):
    schedule_file.write_text("{no es json")
    assert blog_schedule.load() == {}
    schedule_file.write_text('["lista", "no", "dict"]')
    assert blog_schedule.load() == {}


def test_load_filtra_entradas_invalidas(schedule_file):
    schedule_file.write_text(
        '{"buena": {"publish_at": "2026-07-09T09:00", "state": "pending"},'
        ' "sin-hora": {"state": "pending"},'
        ' "hora-mala": {"publish_at": "mañana", "state": "pending"},'
        ' "estado-malo": {"publish_at": "2026-07-09T09:00", "state": "volando"},'
        ' "no-dict": 7}'
    )
    assert list(blog_schedule.load()) == ["buena"]


def test_due_solo_pending_vencidas():
    blog_schedule.set_schedule("b-luego", "2026-07-09T09:00")
    blog_schedule.set_schedule("a-ya", "2026-07-08T09:00")
    blog_schedule.set_schedule("c-ya", "2026-07-08T08:00")
    blog_schedule.mark_error("c-ya", "boom")  # error: nunca due
    assert blog_schedule.due(datetime(2026, 7, 8, 12, 0)) == ["a-ya"]
    assert blog_schedule.due(datetime(2026, 7, 9, 9, 0)) == ["a-ya", "b-luego"]


def test_mark_stale_before_solo_pending_anteriores():
    blog_schedule.set_schedule("vieja", "2026-07-08T09:00")
    blog_schedule.set_schedule("futura", "2026-07-10T09:00")
    blog_schedule.mark_stale_before(datetime(2026, 7, 9, 0, 0))
    assert blog_schedule.get("vieja")["state"] == "stale"
    assert blog_schedule.get("futura")["state"] == "pending"
    # una stale no vuelve a transicionar ni entra en due()
    assert blog_schedule.due(datetime(2026, 7, 30, 0, 0)) == ["futura"]


def test_mark_error_guarda_mensaje():
    blog_schedule.set_schedule("factura", "2026-07-09T09:00")
    blog_schedule.mark_error("factura", "rsync: connection refused")
    entry = blog_schedule.get("factura")
    assert entry["state"] == "error"
    assert entry["error"] == "rsync: connection refused"
    blog_schedule.mark_error("no-existe", "x")  # no crea entradas fantasma
    assert blog_schedule.get("no-existe") is None
```

- [ ] **Step 3: Ejecutar y ver que fallan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_blog_schedule.py -v`
Expected: ERROR de colección — `ModuleNotFoundError: No module named 'app.blog_schedule'`

- [ ] **Step 4: Implementar el módulo**

Crear `backend/app/blog_schedule.py`:

```python
"""Almacén de programaciones de publicación del blog (portal).

Un JSON plano en la raíz del repo (gitignored, como .env): una entrada por
grupo de artículo, clave = stem (nombre en disco). Estados:

- pending: esperando su hora.
- stale:   la hora pasó ANTES de arrancar el servicio (portal caído en T);
           espera confirmación manual en el dashboard.
- error:   un intento de publicar falló; guarda el mensaje y espera manual.

Sin dependencias del portal: piezas puras sobre disco, fáciles de testear.
Diseño: docs/superpowers/specs/2026-07-07-blog-scheduled-publishing-design.md
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE_FILE = REPO_ROOT / ".blog-schedule.json"

STATES = ("pending", "stale", "error")


def parse_local(value: str | None) -> datetime | None:
    """Hora naive local en formato datetime-local (YYYY-MM-DDTHH:MM)."""
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def load() -> dict[str, dict]:
    """Lee el archivo tolerando corrupción: lo ilegible se trata como vacío."""
    try:
        data = json.loads(SCHEDULE_FILE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for stem, entry in data.items():
        if (
            isinstance(entry, dict)
            and parse_local(entry.get("publish_at")) is not None
            and entry.get("state") in STATES
        ):
            out[stem] = {
                "publish_at": entry["publish_at"],
                "state": entry["state"],
                "error": entry.get("error"),
            }
    return out


def _save(data: dict[str, dict]) -> None:
    tmp = SCHEDULE_FILE.with_name(SCHEDULE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(SCHEDULE_FILE)  # escritura atómica: nunca medio archivo


def get(stem: str) -> dict | None:
    return load().get(stem)


def set_schedule(stem: str, publish_at: str) -> None:
    """Crea o sobrescribe (reprogramar limpia stale/error)."""
    data = load()
    data[stem] = {"publish_at": publish_at, "state": "pending", "error": None}
    _save(data)


def remove(stem: str) -> None:
    data = load()
    if stem in data:
        del data[stem]
        _save(data)


def due(now: datetime) -> list[str]:
    """Stems pending cuya hora ya llegó, en orden estable."""
    return sorted(
        stem
        for stem, entry in load().items()
        if entry["state"] == "pending" and parse_local(entry["publish_at"]) <= now
    )


def mark_stale_before(boot: datetime) -> None:
    """Al arrancar: lo que venció con el portal caído espera confirmación manual."""
    data = load()
    changed = False
    for entry in data.values():
        if entry["state"] == "pending" and parse_local(entry["publish_at"]) < boot:
            entry["state"] = "stale"
            changed = True
    if changed:
        _save(data)


def mark_error(stem: str, message: str) -> None:
    data = load()
    if stem in data:
        data[stem]["state"] = "error"
        data[stem]["error"] = message
        _save(data)
```

- [ ] **Step 5: Ejecutar y ver que pasan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_blog_schedule.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add .gitignore backend/app/blog_schedule.py backend/tests/test_blog_schedule.py
git commit -m "Portal: almacén de programaciones del blog (.blog-schedule.json)"
```

---

### Task 2: Publicación selectiva de un grupo (`publish_group`)

**Files:**
- Modify: `backend/app/portal.py` (imports ~línea 17-36; helpers nuevos tras `commit_paths`, ~línea 284)
- Test: `backend/tests/test_portal.py` (añadir al final)

**Interfaces:**
- Consumes: `draft_refs()`, `parse_ref()`, `content_path()`, `public_slug()`, `generated_page()`, `run_generate()`, `commit_paths()`, `sync_to_prod()`, `parse_frontmatter()`, `TRANSLATION_LANGS` (ya existen en portal.py).
- Produces (usado por Tasks 3–4):
  - `DRAFTS_ASIDE: Path` (module-global, monkeypatcheable)
  - `group_refs(stem: str) -> list[str]` — refs de borrador del grupo (p. ej. `["en/factura", "factura"]`)
  - `group_langs(stem: str) -> list[str]` — idiomas con archivo en content (commiteado o borrador)
  - `publish_group(stem: str, scheduled: bool) -> tuple[bool, str, list[tuple[str, str, str]]]` — `(ok, detalle, [(title, lang, slug), ...])`; el CALLER debe tener el LOCK
  - `restore_aside() -> None` — recuperación al arrancar

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `backend/tests/test_portal.py`:

```python
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
    assert not any(aside.rglob("*.html"))  # aside vacío al terminar
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
    monkeypatch.setattr(portal, "commit_paths", lambda msg: (calls.append("commit"), (True, "sin cambios que commitear"))[1])
    monkeypatch.setattr(portal, "sync_to_prod", lambda: (calls.append("sync"), (True, "sincronizado"))[1])
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
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v -k "group or aside"`
Expected: FAIL/ERROR — `AttributeError: module 'app.portal' has no attribute 'DRAFTS_ASIDE'` (y análogos)

- [ ] **Step 3: Implementar en portal.py**

En los imports de `backend/app/portal.py`, la línea `from pathlib import Path` ya existe; no hay imports nuevos en esta tarea.

Añadir tras la constante `ENV_FILE = REPO_ROOT / ".env"` (línea 44):

```python
# Borradores de OTROS grupos apartados durante una publicación selectiva.
DRAFTS_ASIDE = REPO_ROOT / ".drafts-aside"
```

Añadir después de `commit_paths()` (tras la línea 283):

```python
# --- publicación selectiva de un grupo (programación por artículo) ----------

def group_refs(stem: str) -> list[str]:
    """Refs de borrador que pertenecen al grupo `stem` (es + traducciones)."""
    out = []
    for ref in draft_refs():
        parsed = parse_ref(ref)
        if parsed and parsed[1] == stem:
            out.append(ref)
    return sorted(out)


def group_langs(stem: str) -> list[str]:
    """Idiomas con archivo en content para el grupo (borrador o commiteado)."""
    return [l for l in ("es", *TRANSLATION_LANGS) if content_path(l, stem).exists()]


def publish_group(stem: str, scheduled: bool) -> tuple[bool, str, list[tuple[str, str, str]]]:
    """Publica SOLO el grupo `stem`: es + traducciones tal como estén.

    Aparta los borradores de OTROS grupos a .drafts-aside/ (y borra sus páginas
    generadas) para que el generador no los meta en índices/sitemap ni acaben
    en git/prod; el finally los restaura pase lo que pase. El caller debe
    tener el LOCK. Devuelve (ok, detalle, [(title, lang, slug), ...])."""
    others = [r for r in draft_refs() if parse_ref(r) and parse_ref(r)[1] != stem]
    aside: list[tuple[Path, Path]] = []
    try:
        for ref in others:
            lang, other = parse_ref(ref)
            src = content_path(lang, other)
            slug = public_slug(src)
            dst = DRAFTS_ASIDE / src.relative_to(CONTENT_BLOG)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            aside.append((src, dst))
            shutil.rmtree(generated_page(lang, slug).parent, ignore_errors=True)
        ok, out = run_generate()
        if not ok:
            return False, f"generador: {out}", []
        published = []
        for lang in group_langs(stem):
            src = content_path(lang, stem)
            published.append(
                (parse_frontmatter(src.read_text()).get("title", stem), lang, public_slug(src))
            )
        title = published[0][0] if published else stem
        langs = ", ".join(lang for _, lang, _ in published)
        origin = "programado, portal" if scheduled else "portal"
        ok, out = commit_paths(f"Blog: publica «{title}» [{langs}] ({origin})")
        if not ok:
            return False, f"git commit: {out}", []
        synced, sync_out = sync_to_prod()
        if not synced:
            return False, f"sync a prod: {sync_out}", published
        return True, "publicado", published
    finally:
        for src, dst in aside:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
        if aside:
            shutil.rmtree(DRAFTS_ASIDE, ignore_errors=True)
            run_generate()  # las previews de los borradores restaurados vuelven


def restore_aside() -> None:
    """Al arrancar: recupera borradores apartados por un crash a mitad de publicación."""
    if not DRAFTS_ASIDE.is_dir():
        return
    moved = False
    for f in sorted(DRAFTS_ASIDE.rglob("*.html")):
        dst = CONTENT_BLOG / f.relative_to(DRAFTS_ASIDE)
        if dst.exists():
            f.unlink()  # ya restaurado por el finally: esto es un resto duplicado
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dst))
        moved = True
    shutil.rmtree(DRAFTS_ASIDE, ignore_errors=True)
    if moved:
        run_generate()
```

- [ ] **Step 4: Ejecutar y ver que pasan (los nuevos y TODOS los del portal)**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v`
Expected: todos passed (los ~30 existentes + 6 nuevos)

- [ ] **Step 5: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: publicación selectiva de un grupo (publish_group) con borradores apartados"
```

---

### Task 3: Hilo planificador y lifespan

**Files:**
- Modify: `backend/app/portal.py` (imports; lifespan antes de `app = FastAPI(...)` línea 65; tick/loop tras `restore_aside`)
- Test: `backend/tests/test_portal.py` (añadir al final)

**Interfaces:**
- Consumes: `blog_schedule.due/remove/mark_error/mark_stale_before` (Task 1), `publish_group`, `restore_aside`, `LOCK` (Task 2).
- Produces:
  - `SCHEDULER_INTERVAL = 30` (segundos)
  - `scheduler_tick(now: datetime) -> None` — testeable sin hilo ni esperas
  - `lifespan(app)` — restaura aside, marca stale, arranca el hilo demonio

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `backend/tests/test_portal.py`:

```python
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
```

Nota: el fixture `schedule_file` es `autouse=True` a nivel de módulo — protege TODOS los tests del portal de tocar el `.blog-schedule.json` real.

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v -k tick`
Expected: FAIL — `AttributeError: module 'app.portal' has no attribute 'scheduler_tick'`

- [ ] **Step 3: Implementar tick, loop y lifespan**

En `backend/app/portal.py`, ampliar imports (líneas 17-33). Añadir:

```python
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
```

(`timedelta` se usa en Task 5 para el valor por defecto del selector; entra ya para no retocar imports dos veces.)

Y en la línea del import relativo, añadir `blog_schedule`:

```python
from . import blog_schedule, translate_blog
```

Añadir tras `restore_aside()` (final del bloque de publicación selectiva):

```python
# --- planificador: publica a la hora programada con el portal en marcha -----

SCHEDULER_INTERVAL = 30  # segundos entre ticks


def scheduler_tick(now: datetime) -> None:
    """Un tick: publica los grupos pending cuya hora llegó.

    Si el LOCK está ocupado (otra operación en curso) NO cambia nada: el
    siguiente tick lo reintenta. Éxito → la entrada sale del JSON; fallo →
    state=error y sin reintentos automáticos (confirmación manual)."""
    for stem in blog_schedule.due(now):
        if not LOCK.acquire(blocking=False):
            return
        try:
            ok, detail, _ = publish_group(stem, scheduled=True)
        finally:
            LOCK.release()
        if ok:
            blog_schedule.remove(stem)
        else:
            blog_schedule.mark_error(stem, detail)


def _scheduler_loop(stop: threading.Event) -> None:
    while not stop.wait(SCHEDULER_INTERVAL):
        try:
            scheduler_tick(datetime.now())
        except Exception:  # un fallo puntual no debe matar el hilo
            logging.exception("planificador del blog")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Orden: primero recuperar borradores de un crash, luego marcar vencidas
    # (regla de Diego: lo que venció con el portal caído espera confirmación).
    restore_aside()
    blog_schedule.mark_stale_before(datetime.now())
    stop = threading.Event()
    threading.Thread(
        target=_scheduler_loop, args=(stop,), daemon=True, name="blog-scheduler"
    ).start()
    yield
    stop.set()
```

Cambiar la creación de la app (línea 65) a:

```python
app = FastAPI(
    title="SolarVento — portal del blog", docs_url=None, redoc_url=None, lifespan=lifespan
)
```

UBICACIÓN: `lifespan` debe existir como nombre ANTES de `app = FastAPI(...)` (línea 65). Colocar el bloque completo del planificador (`SCHEDULER_INTERVAL`, `scheduler_tick`, `_scheduler_loop`, `lifespan`) justo DESPUÉS de la constante `LOCK` (línea 63) y ANTES de `app = FastAPI(...)`. Que `scheduler_tick` y `lifespan` referencien funciones definidas más abajo (`publish_group`, `restore_aside`) es correcto: Python resuelve nombres en tiempo de llamada, y solo se llaman tras el arranque, con el módulo ya cargado entero.

Los tests existentes NO arrancan el hilo: `TestClient(portal.app)` sin context manager no ejecuta el lifespan (Starlette 1.3).

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v`
Expected: todos passed

- [ ] **Step 5: Arranque real de humo**

Run: `cd /home/diego/taller-projects/solvento/backend && timeout 10 .venv/bin/python -c "
from fastapi.testclient import TestClient
from app import portal
with TestClient(portal.app):  # con context manager SÍ corre el lifespan
    import threading
    assert any(t.name == 'blog-scheduler' for t in threading.enumerate())
print('lifespan OK: hilo blog-scheduler arrancado')
"`
Expected: `lifespan OK: hilo blog-scheduler arrancado`

- [ ] **Step 6: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: hilo planificador de publicaciones programadas (tick 30 s, stale al arrancar)"
```

---

### Task 4: Rutas /schedule, /unschedule, /publish-group + limpieza en discard/delete

**Files:**
- Modify: `backend/app/portal.py` (import `Form`; rutas nuevas tras `/translate`; dos líneas en `/discard` y `/delete`)
- Test: `backend/tests/test_portal.py` (añadir al final)

**Interfaces:**
- Consumes: `blog_schedule` (Task 1), `group_refs`, `publish_group` (Task 2).
- Produces (usado por Task 5): rutas `POST /schedule/{stem}` (form `publish_at`), `POST /unschedule/{stem}`, `POST /publish-group/{stem}`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `backend/tests/test_portal.py`:

```python
# --- Rutas de programación ---

@pytest.fixture
def grupo_con_borrador(monkeypatch, tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    (content / "factura.html").write_text(FM.format(t="Factura"))
    monkeypatch.setattr(portal, "CONTENT_BLOG", content)
    monkeypatch.setattr(portal, "draft_refs", lambda: {"factura"})
    return content


def test_schedule_crea_entrada(client, grupo_con_borrador):
    r = client.post(
        "/schedule/factura", data={"publish_at": "2030-01-01T09:00"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert blog_schedule.get("factura")["state"] == "pending"


def test_schedule_sobrescribe(client, grupo_con_borrador):
    client.post("/schedule/factura", data={"publish_at": "2030-01-01T09:00"})
    client.post("/schedule/factura", data={"publish_at": "2030-02-02T10:00"})
    assert blog_schedule.get("factura")["publish_at"] == "2030-02-02T10:00"


def test_schedule_rechaza_hora_pasada(client, grupo_con_borrador):
    r = client.post("/schedule/factura", data={"publish_at": "2020-01-01T09:00"})
    assert r.status_code == 400
    assert blog_schedule.get("factura") is None


def test_schedule_rechaza_hora_invalida(client, grupo_con_borrador):
    r = client.post("/schedule/factura", data={"publish_at": "mañana por la tarde"})
    assert r.status_code == 400


def test_schedule_rechaza_grupo_sin_borradores(client, grupo_con_borrador, monkeypatch):
    monkeypatch.setattr(portal, "draft_refs", lambda: set())
    r = client.post("/schedule/factura", data={"publish_at": "2030-01-01T09:00"})
    assert r.status_code == 400


def test_schedule_rechaza_grupo_inexistente(client, grupo_con_borrador):
    r = client.post("/schedule/no-existe", data={"publish_at": "2030-01-01T09:00"})
    assert r.status_code == 404


def test_unschedule_elimina(client, grupo_con_borrador):
    client.post("/schedule/factura", data={"publish_at": "2030-01-01T09:00"})
    r = client.post("/unschedule/factura", follow_redirects=False)
    assert r.status_code == 303
    assert blog_schedule.get("factura") is None


def test_publish_group_route_publica_y_limpia(client, grupo_con_borrador, monkeypatch):
    blog_schedule.set_schedule("factura", "2026-07-08T09:00")
    blog_schedule.mark_error("factura", "sync caído")
    monkeypatch.setattr(
        portal, "publish_group",
        lambda stem, scheduled: (True, "publicado", [("Factura", "es", "factura")]),
    )
    r = client.post("/publish-group/factura")
    assert r.status_code == 200
    assert "https://solarvento.es/blog/factura/" in r.text
    assert blog_schedule.get("factura") is None


def test_publish_group_route_fallo_marca_error(client, grupo_con_borrador, monkeypatch):
    blog_schedule.set_schedule("factura", "2030-01-01T09:00")
    monkeypatch.setattr(
        portal, "publish_group", lambda stem, scheduled: (False, "git commit: boom", [])
    )
    r = client.post("/publish-group/factura")
    assert r.status_code == 502
    assert blog_schedule.get("factura")["state"] == "error"


def test_publish_group_route_sin_borradores_ni_entrada(client, grupo_con_borrador, monkeypatch):
    monkeypatch.setattr(portal, "draft_refs", lambda: set())
    r = client.post("/publish-group/factura")
    assert r.status_code == 409


def test_publish_group_route_reintento_sin_borradores(client, grupo_con_borrador, monkeypatch):
    # commit hecho + sync fallido en el pasado: sin borradores pero CON entrada
    monkeypatch.setattr(portal, "draft_refs", lambda: set())
    blog_schedule.set_schedule("factura", "2026-07-08T09:00")
    blog_schedule.mark_error("factura", "sync caído")
    monkeypatch.setattr(
        portal, "publish_group",
        lambda stem, scheduled: (True, "publicado", [("Factura", "es", "factura")]),
    )
    r = client.post("/publish-group/factura")
    assert r.status_code == 200
    assert blog_schedule.get("factura") is None


def test_discard_limpia_la_programacion(client, grupo_con_borrador, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "PUBLIC_BLOG", tmp_path / "public")
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    blog_schedule.set_schedule("factura", "2030-01-01T09:00")
    r = client.post("/discard/factura", follow_redirects=False)
    assert r.status_code == 303
    assert blog_schedule.get("factura") is None


def test_delete_limpia_la_programacion(client, grupo_con_borrador, monkeypatch, tmp_path):
    content = grupo_con_borrador
    (content / "segundo.html").write_text(FM.format(t="Segundo"))  # no es el último
    monkeypatch.setattr(portal, "PUBLIC_BLOG", tmp_path / "public")
    monkeypatch.setattr(portal, "run_generate", lambda: (True, ""))
    monkeypatch.setattr(portal, "commit_paths", lambda msg: (True, "ok"))
    monkeypatch.setattr(portal, "sync_to_prod", lambda: (True, "ok"))
    blog_schedule.set_schedule("factura", "2030-01-01T09:00")
    r = client.post("/delete/factura")
    assert r.status_code == 200
    assert blog_schedule.get("factura") is None
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v -k "schedule or publish_group_route or limpia"`
Expected: FAIL — 404 en `/schedule/...` (ruta inexistente), asserts de limpieza

- [ ] **Step 3: Implementar rutas y limpieza**

En `backend/app/portal.py`, ampliar el import de FastAPI (línea 31):

```python
from fastapi import FastAPI, Form, Request, UploadFile
```

Añadir tras la ruta `/translate` (después de la línea 739):

```python
@app.post("/schedule/{stem}")
def schedule(stem: str, publish_at: str = Form(...)):
    """Programa (o reprograma) la publicación del grupo a una hora futura."""
    if not valid_filename(f"{stem}.html") or not content_path("es", stem).exists():
        return error_page("No encontrado", f"No existe el artículo «{stem}».", 404)
    if not group_refs(stem):
        return error_page(
            "Nada que programar", "El grupo no tiene borradores pendientes.", 400
        )
    when = blog_schedule.parse_local(publish_at)
    if when is None:
        return error_page(
            "Hora inválida", f"«{publish_at}» no tiene formato AAAA-MM-DDTHH:MM.", 400
        )
    if when <= datetime.now():
        return error_page("Hora pasada", "La hora programada debe ser futura.", 400)
    blog_schedule.set_schedule(stem, publish_at)
    return RedirectResponse("/", status_code=303)


@app.post("/unschedule/{stem}")
def unschedule(stem: str):
    blog_schedule.remove(stem)
    return RedirectResponse("/", status_code=303)


@app.post("/publish-group/{stem}", response_class=HTMLResponse)
def publish_group_route(stem: str):
    """«Publicar ahora»: dispara la publicación selectiva del grupo a mano.

    Válido con borradores pendientes O con entrada en el JSON (stale/error):
    tras un fallo de solo-sync el commit ya está hecho y no quedan borradores,
    pero el reintento debe poder ejecutar el rsync."""
    if not valid_filename(f"{stem}.html") or not content_path("es", stem).exists():
        return error_page("No encontrado", f"No existe el artículo «{stem}».", 404)
    entry = blog_schedule.get(stem)
    if not group_refs(stem) and entry is None:
        return error_page(
            "Nada que publicar",
            "El grupo no tiene borradores ni programación pendiente.",
            409,
        )
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        ok, detail, published = publish_group(stem, scheduled=False)
    finally:
        LOCK.release()
    if not ok:
        if entry is not None:
            blog_schedule.mark_error(stem, detail)
        return error_page("La publicación falló", detail, 502)
    blog_schedule.remove(stem)
    lives = [check_live_url(public_url(lang, slug)) for _, lang, slug in published]
    items = "".join(
        f'<li><a href="{public_url(lang, slug)}" target="_blank">{public_url(lang, slug)}</a>'
        f" — {html.escape(live)}</li>"
        for (_, lang, slug), live in zip(published, lives)
    )
    return page(
        "Publicado",
        f"""<h1 class="ok">Publicado ✅</h1>
<ul>{items}</ul>
<p class="meta">Commit en git hecho; el próximo deploy completo regenerará exactamente lo mismo.</p>
<p><a href="/">← Volver al portal</a></p>""",
    )
```

En `discard()` (línea 611), tras `src.unlink()` añadir:

```python
        blog_schedule.remove(stem)  # descartar un borrador anula su programación
```

En `delete()` (línea 630), tras el bucle `for vlang, vsrc in victims:` (después de la línea 658) añadir:

```python
        blog_schedule.remove(stem)  # borrar el grupo anula su programación
```

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v`
Expected: todos passed

- [ ] **Step 5: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: rutas de programación (/schedule, /unschedule, /publish-group)"
```

---

### Task 5: Widget de programación en índice y preview

**Files:**
- Modify: `backend/app/portal.py` (helpers de formato + `schedule_widget` + `group_card` refactor de `index()` + widget en `preview()`)
- Test: `backend/tests/test_portal.py` (añadir al final)

**Interfaces:**
- Consumes: rutas de Task 4, `blog_schedule.load/get`.
- Produces:
  - `format_local(dtstr: str) -> str` — «mié 9 jul, 09:00» (nombres en español hardcodeados: la locale del servicio no es fiable)
  - `schedule_widget(stem: str, entry: dict | None, has_drafts: bool) -> str`
  - `group_card(g: dict, entry: dict | None) -> str` (absorbe el HTML de tarjeta que hoy vive inline en `index()`)

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `backend/tests/test_portal.py`:

```python
# --- Widget de programación en la UI ---

def test_format_local():
    assert portal.format_local("2026-07-09T09:00") == "jue 9 jul, 09:00"
    assert portal.format_local("2026-12-01T18:30") == "mar 1 dic, 18:30"


GRUPO_BORRADOR = {
    "stem": "uno", "slug": "uno", "title": "Uno", "date": "2026-07-01",
    "draft": True, "tr": {"en": None, "ca": None, "gl": None, "eu": None},
}


def test_index_borrador_sin_programar_ofrece_programar(client, monkeypatch):
    monkeypatch.setattr(portal, "draft_refs", lambda: {"uno"})
    monkeypatch.setattr(portal, "list_groups", lambda: [dict(GRUPO_BORRADOR)])
    r = client.get("/")
    assert 'action="/schedule/uno"' in r.text
    assert 'type="datetime-local"' in r.text


def test_index_pendiente_muestra_hora_y_cancelar(client, monkeypatch):
    monkeypatch.setattr(portal, "draft_refs", lambda: {"uno"})
    monkeypatch.setattr(portal, "list_groups", lambda: [dict(GRUPO_BORRADOR)])
    blog_schedule.set_schedule("uno", "2026-07-09T09:00")
    r = client.get("/")
    assert "⏰ sale el jue 9 jul, 09:00" in r.text
    assert 'action="/unschedule/uno"' in r.text
    assert 'action="/schedule/uno"' not in r.text  # programado: sin selector


def test_index_vencida_ofrece_publicar_ahora(client, monkeypatch):
    monkeypatch.setattr(portal, "draft_refs", lambda: {"uno"})
    monkeypatch.setattr(portal, "list_groups", lambda: [dict(GRUPO_BORRADOR)])
    blog_schedule.set_schedule("uno", "2026-07-01T09:00")
    blog_schedule.mark_stale_before(datetime(2026, 7, 2, 0, 0))
    r = client.get("/")
    assert "venció" in r.text
    assert 'action="/publish-group/uno"' in r.text
    assert 'action="/unschedule/uno"' in r.text


def test_index_error_muestra_motivo(client, monkeypatch):
    monkeypatch.setattr(portal, "draft_refs", lambda: {"uno"})
    monkeypatch.setattr(portal, "list_groups", lambda: [dict(GRUPO_BORRADOR)])
    blog_schedule.set_schedule("uno", "2026-07-01T09:00")
    blog_schedule.mark_error("uno", "sync a prod: <caído>")
    r = client.get("/")
    assert "falló al publicar" in r.text
    assert "&lt;caído&gt;" in r.text  # el motivo va escapado
    assert 'action="/publish-group/uno"' in r.text


def test_index_publicado_sin_borradores_no_ofrece_programar(client, monkeypatch):
    publicado = dict(GRUPO_BORRADOR, draft=False)
    monkeypatch.setattr(portal, "draft_refs", lambda: set())
    monkeypatch.setattr(portal, "list_groups", lambda: [publicado])
    r = client.get("/")
    assert 'action="/schedule/uno"' not in r.text


def test_preview_muestra_el_widget(client, monkeypatch, tmp_path):
    content, public = tmp_path / "content", tmp_path / "public"
    content.mkdir()
    (content / "factura.html").write_text(FM.format(t="Factura"))
    monkeypatch.setattr(portal, "CONTENT_BLOG", content)
    monkeypatch.setattr(portal, "PUBLIC_BLOG", public)
    monkeypatch.setattr(portal, "draft_refs", lambda: {"factura"})
    r = client.get("/preview/factura")
    assert r.status_code == 200
    assert 'action="/schedule/factura"' in r.text
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v -k "widget or format_local or index_ or preview_muestra"`
Expected: FAIL — `AttributeError: format_local` y asserts de HTML

- [ ] **Step 3: Implementar el widget y refactorizar la tarjeta**

En `backend/app/portal.py`, añadir antes de `lang_chips()` (línea 407):

```python
# Nombres en español hardcodeados: la locale del servicio systemd no es fiable.
DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MESES = ("ene", "feb", "mar", "abr", "may", "jun",
         "jul", "ago", "sep", "oct", "nov", "dic")


def format_local(dtstr: str) -> str:
    dt = blog_schedule.parse_local(dtstr)
    return f"{DIAS[dt.weekday()]} {dt.day} {MESES[dt.month - 1]}, {dt:%H:%M}"


def schedule_widget(stem: str, entry: dict | None, has_drafts: bool) -> str:
    """Programar / pendiente / vencida / error, según el estado del grupo."""
    cancel = (
        f'<form class="inline" method="post" action="/unschedule/{stem}">'
        "<button>Cancelar programación</button></form>"
    )
    publish_now = (
        f'<form class="inline" method="post" action="/publish-group/{stem}">'
        '<button class="primary">Publicar ahora</button></form>'
    )
    if entry is None:
        if not has_drafts:
            return ""
        default = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT09:00")
        return (
            f'<form class="inline" method="post" action="/schedule/{stem}">'
            f'<input type="datetime-local" name="publish_at" value="{default}" required /> '
            "<button>Programar</button></form>"
        )
    when = format_local(entry["publish_at"])
    if entry["state"] == "pending":
        return f'<span class="meta">⏰ sale el {when}</span> {cancel}'
    if entry["state"] == "stale":
        return (
            f'<span class="bad">⏰ venció el {when} con el portal parado</span> '
            f"{publish_now} {cancel}"
        )
    reason = html.escape(entry.get("error") or "error desconocido")
    return f'<span class="bad">⚠️ falló al publicar: {reason}</span> {publish_now} {cancel}'


def group_card(g: dict, entry: dict | None) -> str:
    has_drafts = g["draft"] or any(t and t["draft"] for t in g["tr"].values())
    head = (
        "<strong>" + html.escape(g["title"]) + "</strong>"
        if g["draft"]
        else f'<a href="{public_url("es", g["slug"])}" target="_blank">{html.escape(g["title"])}</a>'
    )
    action = (
        f'<a href="/preview/{g["stem"]}"><button class="primary">Revisar y publicar</button></a>'
        if g["draft"]
        else f'''<form class="inline" method="post" action="/delete/{g["stem"]}"
        onsubmit="return confirm('¿Borrar «{html.escape(g["title"])}» y TODAS sus traducciones del blog y de prod?')">
    <button class="danger">Borrar</button>
  </form>'''
    )
    widget = schedule_widget(g["stem"], entry, has_drafts)
    schedule_row = f'<div class="row">{widget}</div>' if widget else ""
    return f"""<div class="card">
  <div class="row">
    <div>{head}
      <div class="meta">{html.escape(g["date"])} · /blog/{g["slug"]}/{" · borrador pendiente" if g["draft"] else ""}</div></div>
    {action}
  </div>
  <div class="row">{lang_chips(g)}</div>
  {schedule_row}
</div>"""
```

En `index()` (línea 430), sustituir el bloque `cards = "".join(...)` completo (líneas 434-447, desde `cards = "".join(` hasta el `)` que cierra el join) por:

```python
    sched = blog_schedule.load()
    cards = "".join(group_card(g, sched.get(g["stem"])) for g in groups)
```

En `preview()` (línea 523), sustituir el bloque `<div class="actions">…</div>` del HTML por:

```python
        f"""
<h1>Preview: {html.escape(title)}</h1>
<p class="meta">Así quedará en {public_url(lang, slug)} (índice, hreflang y sitemap se actualizan solos).</p>
<div class="actions">
  <form class="inline" method="post" action="/publish">
    <button class="primary">Publicar TODO lo pendiente en solarvento.es</button>
  </form>
  <form class="inline" method="post" action="/discard/{ref}">
    <button class="danger">Descartar este borrador</button>
  </form>
</div>
<div class="actions">{schedule_widget(stem, blog_schedule.get(stem), True)}</div>
<iframe src="/draft/{ref}"></iframe>
""",
```

(Es el mismo cuerpo actual con una línea nueva: el `<div class="actions">` del widget antes del iframe. En el preview de una traducción `en/factura`, `stem` es `factura`: la programación es del grupo.)

- [ ] **Step 4: Ejecutar y ver que pasan**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -v`
Expected: todos passed (incluido `test_index_lista_articulos`, que no debe romperse con el refactor de la tarjeta)

- [ ] **Step 5: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: widget de programación en índice y preview"
```

---

### Task 6: Verificación completa y despliegue del servicio

**Files:**
- Ninguno nuevo (verificación + reinicio del servicio del portal)

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: portal en marcha con la feature visible en `http://mockwebsite-diego.tailfc8d71.ts.net:8130`.

- [ ] **Step 1: Suite completa del backend**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest`
Expected: todo passed (441+ tests previos + los nuevos), 0 failed

- [ ] **Step 2: Reiniciar el portal (servicio de usuario en esta máquina de dev)**

```bash
systemctl --user list-units --type=service | grep -i portal   # confirmar el nombre exacto
systemctl --user restart solvento-portal
systemctl --user --no-pager status solvento-portal | head -12
```

Expected: `active (running)` sin trazas de error.

- [ ] **Step 3: Humo contra el portal vivo**

```bash
IP=$(tailscale ip -4 | head -n1)
curl -s "http://$IP:8130/" | grep -o 'datetime-local\|Programar' | sort -u
```

Expected: si hay algún borrador pendiente, aparece `datetime-local` y `Programar`; si no hay borradores, la página carga (HTTP 200) sin el widget — comprobar entonces subiendo un borrador de prueba y descartándolo después.

- [ ] **Step 4: Prueba funcional del ciclo corto (opcional pero recomendada)**

Subir un borrador de prueba desde el navegador, programarlo a 2 minutos vista, esperar el tick y comprobar que se publica solo y desaparece del JSON; después borrar el artículo de prueba desde el portal (esto lo retira también de prod). Si no se quiere tocar prod, saltarse este paso: los tests ya cubren el ciclo con dobles.

- [ ] **Step 5: Commit final (si quedó algo suelto) y cierre**

```bash
cd /home/diego/taller-projects/solvento
git status --short   # debe estar limpio; si no, commitear los restos con mensaje descriptivo
```
