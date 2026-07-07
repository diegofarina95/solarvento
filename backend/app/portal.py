"""Portal de publicación del blog — SOLO máquina de dev, SOLO Tailscale.

Mini-app FastAPI independiente del backend público (se arranca aparte, ver
deploy/solvento-portal.sh). Flujo: subes un .html con el frontmatter del blog
(mismo formato que frontend/content/blog/), el generador existente lo valida y
produce la página; tras el preview, «Publicar» commitea en git (fuente de
verdad) y sincroniza SOLO los HTML del blog + sitemap al dist/ de prod por
rsync (gitignored allí: no ensucia el guard de deploy.sh). StaticFiles de prod
lee de disco, así que no hace falta reiniciar nada.

Seguridad: el launcher hace bind a la IP de Tailscale; este módulo añade un
middleware de defensa en profundidad que rechaza clientes fuera de la tailnet
(100.64.0.0/10, fd7a:115c:a1e0::/48) y loopback. Diseño:
docs/superpowers/specs/2026-07-07-blog-portal-design.md
"""

from __future__ import annotations

import html
import ipaddress
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND = REPO_ROOT / "frontend"
CONTENT_BLOG = FRONTEND / "content" / "blog"
PUBLIC_BLOG = FRONTEND / "public" / "blog"
PUBLIC_SITEMAP = FRONTEND / "public" / "sitemap.xml"
GENERATE_SCRIPT = FRONTEND / "scripts" / "generate-static-pages.mjs"
ENV_FILE = REPO_ROOT / ".env"

ORIGIN = "https://solarvento.es"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# Nombre de archivo = slug público: minúsculas/dígitos separados por guiones.
FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.html$")

ALLOWED_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT de Tailscale
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),  # IPv6 de Tailscale
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)

# Una operación de escritura (subir/publicar/borrar/sync) a la vez.
LOCK = threading.Lock()

app = FastAPI(title="SolarVento — portal del blog", docs_url=None, redoc_url=None)

if (FRONTEND / "public" / "fonts").is_dir():  # tipografía de marca en el preview
    app.mount("/fonts", StaticFiles(directory=FRONTEND / "public" / "fonts"))


# --- piezas puras -----------------------------------------------------------

def valid_filename(name: str | None) -> bool:
    return bool(name) and FILENAME_RE.match(name) is not None


def client_allowed(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in net for net in ALLOWED_NETS)


def read_env(path: Path) -> dict[str, str]:
    """Parsea el .env del proyecto (formato «CLAVE: valor», como deploy.sh)."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def normalize_upload(data: bytes) -> str:
    """Tolera BOM y líneas en blanco iniciales delante del frontmatter."""
    text = data.decode("utf-8", errors="replace")
    stripped = text.lstrip("\ufeff \t\r\n")
    return stripped if stripped.startswith("---") else text


def parse_frontmatter(text: str) -> dict[str, str]:
    """Frontmatter mínimo para listar (la validación real la hace el generador)."""
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n", text)
    if not m:
        return {}
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^(\w+):\s*(.*)$", line)
        if kv:
            meta[kv.group(1)] = kv.group(2).strip()
    return meta


# --- subprocesos: generador, git, rsync -------------------------------------

def _node() -> str:
    node = shutil.which("node")
    if node:
        return node
    # fnm instala fuera del PATH de systemd: usa la versión más reciente.
    candidates = sorted(
        Path.home().glob(".local/share/fnm/node-versions/*/installation/bin/node")
    )
    if candidates:
        return str(candidates[-1])
    raise RuntimeError("node no encontrado (¿PATH del servicio?)")


def run_generate() -> tuple[bool, str]:
    """Regenera páginas estáticas + blog + sitemap con el generador real."""
    proc = subprocess.run(
        [_node(), str(GENERATE_SCRIPT)],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def draft_slugs() -> set[str]:
    """Borradores = archivos sin trackear en content/blog (sobreviven reinicios)."""
    proc = git("status", "--porcelain", "--untracked-files=all", "--", str(CONTENT_BLOG))
    slugs = set()
    for line in proc.stdout.splitlines():
        if line.startswith("??") and line.strip().endswith(".html"):
            slugs.add(Path(line[3:].strip()).stem)
    return slugs


def list_articles() -> list[dict]:
    drafts = draft_slugs()
    items = []
    for f in sorted(CONTENT_BLOG.glob("*.html")):
        meta = parse_frontmatter(f.read_text())
        items.append(
            {
                "slug": f.stem,
                "title": meta.get("title", f.stem),
                "date": meta.get("date", "¿?"),
                "draft": f.stem in drafts,
            }
        )
    items.sort(key=lambda a: a["date"], reverse=True)
    return items


def sync_to_prod() -> tuple[bool, str]:
    """rsync de public/blog/ y sitemap.xml al dist/ de prod (y solo eso)."""
    try:
        env_cfg = read_env(ENV_FILE)
        addr, user = env_cfg["SSH_ADDRESS"], env_cfg["SSH_USER"]
        port = env_cfg.get("SSH_PORT", "22")
        password = env_cfg["SSH_PASSWORD"]
        remote = env_cfg["PATH"]
    except (OSError, KeyError) as e:
        return False, f"credenciales de prod no disponibles en .env: {e!r}"
    ssh = f"ssh -o StrictHostKeyChecking=no -p {port}"
    jobs = [
        (f"{PUBLIC_BLOG}/", f"{user}@{addr}:{remote}/frontend/dist/blog/", ["--delete"]),
        (str(PUBLIC_SITEMAP), f"{user}@{addr}:{remote}/frontend/dist/sitemap.xml", []),
    ]
    log = []
    for src, dst, extra in jobs:
        proc = subprocess.run(
            ["sshpass", "-e", "rsync", "-az", *extra, "-e", ssh, src, dst],
            capture_output=True,
            text=True,
            timeout=120,
            env={"SSHPASS": password, "PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        log.append((proc.stdout + proc.stderr).strip())
        if proc.returncode != 0:
            return False, "\n".join(filter(None, log)) or f"rsync falló ({proc.returncode})"
    return True, "\n".join(filter(None, log)) or "sincronizado"


def check_live(slug: str) -> str:
    url = f"{ORIGIN}/blog/{slug}.html"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return f"✅ {url} responde {resp.status}"
    except urllib.error.HTTPError as e:
        return f"⚠️ {url} responde {e.code}"
    except OSError as e:
        return f"⚠️ no se pudo comprobar {url}: {e}"


def commit_paths(message: str) -> tuple[bool, str]:
    git("add", "-A", "--", str(CONTENT_BLOG), str(PUBLIC_BLOG), str(PUBLIC_SITEMAP))
    if not git("diff", "--cached", "--quiet").returncode:
        return True, "sin cambios que commitear"
    proc = git("commit", "-m", message)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


# --- HTML del portal ---------------------------------------------------------

CSS = """
  :root { --paper:#faf7f2; --ink:#292524; --muted:#78716c; --line:#e7e5e4;
          --amber:#b45309; --card:#ffffff; --ok:#047857; --bad:#b91c1c; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
         font:16px/1.6 system-ui, sans-serif; }
  .wrap { max-width:860px; margin:0 auto; padding:24px 20px 64px; }
  header.site { display:flex; justify-content:space-between; align-items:baseline;
                border-bottom:1px solid var(--line); padding-bottom:12px; margin-bottom:24px; }
  .brand { font-weight:700; font-size:20px; text-decoration:none; color:var(--ink); }
  .brand span { color:var(--amber); }
  .brand small { color:var(--muted); font-weight:400; margin-left:8px; }
  .tag { color:var(--muted); font-size:13px; }
  h1 { font-size:22px; } h2 { font-size:17px; margin-top:32px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:16px 18px; margin:10px 0; }
  .row { display:flex; justify-content:space-between; align-items:center; gap:12px; }
  .meta { color:var(--muted); font-size:13px; }
  a { color:var(--amber); }
  button { border:1px solid var(--line); border-radius:8px; padding:8px 14px;
           background:var(--card); color:var(--ink); cursor:pointer; font-size:14px; }
  button.primary { background:var(--amber); border-color:var(--amber); color:#fff; }
  button.danger { color:var(--bad); }
  form.inline { display:inline; }
  input[type=file] { font-size:14px; }
  .ok { color:var(--ok); } .bad { color:var(--bad); }
  pre { background:#1c1917; color:#e7e5e4; padding:12px; border-radius:8px;
        overflow-x:auto; font-size:13px; white-space:pre-wrap; }
  iframe { width:100%; height:70vh; border:1px solid var(--line); border-radius:10px;
           background:#fff; }
  .actions { display:flex; gap:10px; margin:16px 0; }
"""


def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>{html.escape(title)} · Portal del blog</title>
<style>{CSS}</style>
</head>
<body><main class="wrap">
<header class="site">
  <a class="brand" href="/">Solar<span>Vento</span><small>portal del blog</small></a>
  <span class="tag">solo Tailscale</span>
</header>
{body}
</main></body></html>""",
        status_code=status,
    )


def error_page(title: str, detail: str, status: int) -> HTMLResponse:
    return page(
        title,
        f"<h1>{html.escape(title)}</h1><pre>{html.escape(detail)}</pre>"
        '<p><a href="/">← Volver al portal</a></p>',
        status,
    )


FRONTMATTER_TEMPLATE = """---
title: Título SEO del artículo
description: Meta-descripción para Google (una frase)
keywords: palabra1, palabra2, palabra3
date: 2026-07-07
excerpt: Extracto para la tarjeta del índice del blog.
---
<p class="lead">Primer párrafo…</p>
<h2>Primera sección</h2>
<p>Cuerpo del artículo en HTML plano.</p>"""


def frontmatter_help_page(name: str) -> HTMLResponse:
    return page(
        "Falta el frontmatter",
        f"""<h1>«{html.escape(name)}» no empieza por el frontmatter</h1>
<p>La <strong>primera línea</strong> del archivo debe ser <code>---</code>, seguida de los
metadatos y otra línea <code>---</code>; debajo va el cuerpo del artículo en HTML plano.
Un documento HTML completo (con <code>&lt;!doctype&gt;</code>, <code>&lt;head&gt;</code>,
<code>&lt;body&gt;</code>…) no vale: pega solo el contenido del artículo bajo el frontmatter.</p>
<p>Plantilla exacta:</p>
<pre>{html.escape(FRONTMATTER_TEMPLATE)}</pre>
<p><a href="/">← Volver al portal</a></p>""",
        422,
    )


def generator_error_summary(out: str) -> str:
    """Primera línea «Error: …» del generador, para no enseñar solo un stack trace."""
    for line in out.splitlines():
        if "Error:" in line:
            return line.strip()
    return ""


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """Cualquier fallo no previsto sale como página legible, no un 500 pelado."""
    return error_page("Error inesperado del portal", f"{type(exc).__name__}: {exc}", 500)


# --- middleware: solo tailnet -------------------------------------------------

@app.middleware("http")
async def tailnet_only(request: Request, call_next):
    host = request.client.host if request.client else None
    if not client_allowed(host):
        return PlainTextResponse("403: solo accesible desde la tailnet", status_code=403)
    return await call_next(request)


# --- rutas --------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    articles = list_articles()
    drafts = [a for a in articles if a["draft"]]
    published = [a for a in articles if not a["draft"]]

    draft_html = "".join(
        f"""<div class="card row">
  <div><strong>{html.escape(a["title"])}</strong>
    <div class="meta">borrador pendiente · {html.escape(a["date"])}</div></div>
  <a href="/preview/{a["slug"]}"><button class="primary">Revisar y publicar</button></a>
</div>"""
        for a in drafts
    )
    pub_html = "".join(
        f"""<div class="card row">
  <div><a href="{ORIGIN}/blog/{a["slug"]}.html" target="_blank">{html.escape(a["title"])}</a>
    <div class="meta">{html.escape(a["date"])} · {a["slug"]}.html</div></div>
  <form class="inline" method="post" action="/delete/{a["slug"]}"
        onsubmit="return confirm('¿Borrar «{html.escape(a["title"])}» del blog y de prod?')">
    <button class="danger">Borrar</button>
  </form>
</div>"""
        for a in published
    )
    return page(
        "Portal",
        f"""
<h1>Publicar un artículo</h1>
<p class="meta">Sube un <code>.html</code> con el frontmatter del blog
(<code>--- title/description/keywords/date/excerpt ---</code> + cuerpo HTML).
El nombre del archivo será el slug público: <code>minusculas-con-guiones.html</code>.</p>
<form class="card" method="post" action="/upload" enctype="multipart/form-data">
  <div class="row">
    <input type="file" name="file" accept=".html" required />
    <button class="primary">Subir y previsualizar</button>
  </div>
</form>
{f"<h2>Borradores</h2>{draft_html}" if drafts else ""}
<h2>Publicados ({len(published)})</h2>
{pub_html or '<p class="meta">Ningún artículo publicado todavía.</p>'}
<form class="inline" method="post" action="/sync">
  <button title="Vuelve a copiar blog+sitemap al dist de prod">Sincronizar con prod</button>
</form>
""",
    )


@app.post("/upload")
async def upload(file: UploadFile):
    data = await file.read()
    name = file.filename or ""
    if not valid_filename(name):
        return error_page(
            "Nombre de archivo inválido",
            f"«{name}»: usa minúsculas, dígitos y guiones, terminado en .html "
            "(será el slug público, p. ej. baterias-virtuales.html).",
            400,
        )
    if len(data) > MAX_UPLOAD_BYTES:
        return error_page("Archivo demasiado grande", "Máximo 2 MB.", 413)
    text = normalize_upload(data)
    if not parse_frontmatter(text):
        return frontmatter_help_page(name)
    target = CONTENT_BLOG / name
    if target.exists():
        return error_page(
            "El slug ya existe",
            f"Ya hay un artículo «{name}». Para actualizarlo: bórralo y vuelve a subirlo.",
            409,
        )
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        # git rm del último artículo poda también el directorio: recréalo.
        CONTENT_BLOG.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        ok, out = run_generate()
        if not ok:
            target.unlink(missing_ok=True)
            run_generate()  # restaura índice/sitemap del estado anterior
            summary = generator_error_summary(out)
            detail = f"{summary}\n\n— salida completa —\n{out}" if summary else out
            return error_page("El generador rechazó el artículo", detail, 422)
    finally:
        LOCK.release()
    return RedirectResponse(f"/preview/{target.stem}", status_code=303)


@app.get("/preview/{slug}", response_class=HTMLResponse)
def preview(slug: str):
    if not valid_filename(f"{slug}.html") or not (CONTENT_BLOG / f"{slug}.html").exists():
        return error_page("No encontrado", f"No hay borrador «{slug}».", 404)
    meta = parse_frontmatter((CONTENT_BLOG / f"{slug}.html").read_text())
    title = meta.get("title", slug)
    return page(
        f"Preview · {title}",
        f"""
<h1>Preview: {html.escape(title)}</h1>
<p class="meta">Así quedará en {ORIGIN}/blog/{slug}.html (índice y sitemap se actualizan solos).</p>
<div class="actions">
  <form class="inline" method="post" action="/publish/{slug}">
    <button class="primary">Publicar en solarvento.es</button>
  </form>
  <form class="inline" method="post" action="/discard/{slug}">
    <button class="danger">Descartar borrador</button>
  </form>
</div>
<iframe src="/draft/{slug}"></iframe>
""",
    )


@app.get("/draft/{slug}", response_class=HTMLResponse)
def draft(slug: str):
    f = PUBLIC_BLOG / f"{slug}.html"
    if not valid_filename(f"{slug}.html") or not f.exists():
        return error_page("No encontrado", f"No hay página generada para «{slug}».", 404)
    return HTMLResponse(f.read_text())


@app.post("/publish/{slug}", response_class=HTMLResponse)
def publish(slug: str):
    src = CONTENT_BLOG / f"{slug}.html"
    if not valid_filename(f"{slug}.html") or not src.exists():
        return error_page("No encontrado", f"No hay borrador «{slug}».", 404)
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        title = parse_frontmatter(src.read_text()).get("title", slug)
        ok, out = commit_paths(f"Blog: {title} (publicado desde el portal)")
        if not ok:
            return error_page("git commit falló", out, 500)
        synced, sync_out = sync_to_prod()
        live = check_live(slug) if synced else ""
    finally:
        LOCK.release()
    if not synced:
        return page(
            "Commit hecho, sync pendiente",
            f"""<h1 class="bad">Commit hecho, pero el sync a prod falló</h1>
<p>El artículo está en git (fuente de verdad); solo falta copiarlo a prod.</p>
<pre>{html.escape(sync_out)}</pre>
<form class="inline" method="post" action="/sync"><button class="primary">Reintentar sincronización</button></form>
<p><a href="/">← Volver al portal</a></p>""",
            502,
        )
    return page(
        "Publicado",
        f"""<h1 class="ok">Publicado ✅</h1>
<p><strong>{html.escape(title)}</strong> ya está en
<a href="{ORIGIN}/blog/{slug}.html" target="_blank">{ORIGIN}/blog/{slug}.html</a></p>
<p>{html.escape(live)}</p>
<p class="meta">Commit en git hecho; el próximo deploy completo regenerará exactamente lo mismo.</p>
<p><a href="/">← Volver al portal</a></p>""",
    )


@app.post("/discard/{slug}")
def discard(slug: str):
    src = CONTENT_BLOG / f"{slug}.html"
    if not valid_filename(f"{slug}.html") or not src.exists():
        return error_page("No encontrado", f"No hay borrador «{slug}».", 404)
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        src.unlink()
        (PUBLIC_BLOG / f"{slug}.html").unlink(missing_ok=True)
        run_generate()  # índice/sitemap vuelven al estado del último commit
    finally:
        LOCK.release()
    return RedirectResponse("/", status_code=303)


@app.post("/delete/{slug}", response_class=HTMLResponse)
def delete(slug: str):
    src = CONTENT_BLOG / f"{slug}.html"
    if not valid_filename(f"{slug}.html") or not src.exists():
        return error_page("No encontrado", f"No existe el artículo «{slug}».", 404)
    if len(list(CONTENT_BLOG.glob("*.html"))) <= 1:
        return error_page(
            "No se puede borrar el último artículo",
            "El blog necesita al menos un artículo (el generador lo exige). "
            "Sube el sustituto antes de borrar este.",
            409,
        )
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        title = parse_frontmatter(src.read_text()).get("title", slug)
        src.unlink()
        (PUBLIC_BLOG / f"{slug}.html").unlink(missing_ok=True)
        ok, out = run_generate()
        if not ok:
            return error_page("El generador falló tras borrar", out, 500)
        ok, out = commit_paths(f"Blog: retira «{title}» (borrado desde el portal)")
        if not ok:
            return error_page("git commit falló", out, 500)
        synced, sync_out = sync_to_prod()
    finally:
        LOCK.release()
    status = "✅ retirado también de prod" if synced else f"⚠️ sync a prod falló:\n{sync_out}"
    return page(
        "Borrado",
        f"""<h1>Artículo borrado</h1>
<p><strong>{html.escape(title)}</strong> se ha retirado del blog.</p>
<pre>{html.escape(status)}</pre>
<p><a href="/">← Volver al portal</a></p>""",
    )


@app.post("/sync", response_class=HTMLResponse)
def sync():
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        ok, out = sync_to_prod()
    finally:
        LOCK.release()
    if not ok:
        return error_page("El sync a prod falló", out, 502)
    return page(
        "Sincronizado",
        f"""<h1 class="ok">Sincronizado con prod ✅</h1>
<pre>{html.escape(out or "sin cambios")}</pre>
<p><a href="/">← Volver al portal</a></p>""",
    )
