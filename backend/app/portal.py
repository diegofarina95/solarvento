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
import logging
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import blog_schedule, translate_blog
from .config import get_settings

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND = REPO_ROOT / "frontend"
CONTENT_BLOG = FRONTEND / "content" / "blog"
PUBLIC_BLOG = FRONTEND / "public" / "blog"
PUBLIC_SITEMAP = FRONTEND / "public" / "sitemap.xml"
GENERATE_SCRIPT = FRONTEND / "scripts" / "generate-static-pages.mjs"
ENV_FILE = REPO_ROOT / ".env"

# Borradores de OTROS grupos apartados durante una publicación selectiva.
DRAFTS_ASIDE = REPO_ROOT / ".drafts-aside"

ORIGIN = "https://solarvento.es"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# Idiomas de traducción (el original siempre es es); mismo orden que el blog.
TRANSLATION_LANGS = ("en", "ca", "gl", "eu")

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


# --- planificador: publica a la hora programada con el portal en marcha -----
# (referencia a publish_group/restore_aside definidas más abajo: Python las
# resuelve en tiempo de llamada, siempre tras cargar el módulo entero)

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


app = FastAPI(
    title="SolarVento — portal del blog", docs_url=None, redoc_url=None, lifespan=lifespan
)

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


PUBLIC_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def public_slug(content_file: Path) -> str:
    """Slug público (URL) = campo «slug» del frontmatter; si falta o no es
    válido, el nombre del archivo (mismo contrato que scripts/blog.mjs)."""
    slug = parse_frontmatter(content_file.read_text()).get("slug", "")
    return slug if PUBLIC_SLUG_RE.match(slug) else content_file.stem


def parse_ref(ref: str) -> tuple[str, str] | None:
    """Referencia de las rutas del portal → (lang, stem).

    "factura" → ("es", "factura"); "en/factura" → ("en", "factura")."""
    parts = ref.strip("/").split("/")
    if len(parts) == 1:
        lang, stem = "es", parts[0]
    elif len(parts) == 2 and parts[0] in TRANSLATION_LANGS:
        lang, stem = parts
    else:
        return None
    return (lang, stem) if valid_filename(f"{stem}.html") else None


def content_path(lang: str, stem: str) -> Path:
    base = CONTENT_BLOG if lang == "es" else CONTENT_BLOG / lang
    return base / f"{stem}.html"


def public_url(lang: str, slug: str) -> str:
    return f"{ORIGIN}/blog/{slug}/" if lang == "es" else f"{ORIGIN}/blog/{lang}/{slug}/"


def generated_page(lang: str, slug: str) -> Path:
    base = PUBLIC_BLOG if lang == "es" else PUBLIC_BLOG / lang
    return base / slug / "index.html"


def draft_refs() -> set[str]:
    """Borradores = archivos sin trackear en content/blog (sobreviven reinicios).

    Devuelve referencias del portal: "factura" (es) o "en/factura"."""
    proc = git("status", "--porcelain", "--untracked-files=all", "--", str(CONTENT_BLOG))
    refs = set()
    for line in proc.stdout.splitlines():
        if not line.startswith("??") or not line.strip().endswith(".html"):
            continue
        path = Path(line[3:].strip())
        if not path.is_absolute():
            path = REPO_ROOT / path
        rel = path.resolve().relative_to(CONTENT_BLOG.resolve())
        refs.add(str(rel.with_suffix("")))
    return refs


def list_groups() -> list[dict]:
    """Artículos agrupados: original es + estado de cada traducción."""
    drafts = draft_refs()
    groups = []
    for f in sorted(CONTENT_BLOG.glob("*.html")):
        meta = parse_frontmatter(f.read_text())
        tr = {}
        for lang in TRANSLATION_LANGS:
            tf = content_path(lang, f.stem)
            tr[lang] = (
                {"slug": public_slug(tf), "draft": f"{lang}/{f.stem}" in drafts}
                if tf.exists()
                else None
            )
        groups.append(
            {
                "stem": f.stem,  # nombre en disco: clave de las rutas del portal
                "slug": public_slug(f),  # slug público del original
                "title": meta.get("title", f.stem),
                "date": meta.get("date", "¿?"),
                "draft": f.stem in drafts,
                "tr": tr,
            }
        )
    groups.sort(key=lambda a: a["date"], reverse=True)
    return groups


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


def check_live_url(url: str) -> str:
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
  form.schedule { display:inline-flex; align-items:center; gap:8px; flex-wrap:wrap; }
  input[type=datetime-local] { font:inherit; font-size:14px; color:var(--ink);
    background:var(--card); border:1px solid var(--line); border-radius:8px;
    padding:7px 10px; }
  input[type=datetime-local]:hover, button:hover { border-color:var(--amber); }
  button.primary:hover { background:#92400e; border-color:#92400e; }
  button.danger:hover { border-color:var(--bad); }
  input:focus-visible, button:focus-visible { outline:2px solid var(--amber);
    outline-offset:2px; }
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
<p>Plantilla exacta (además admite <code>slug: url-para-seo</code> opcional para que
la URL pública no dependa del nombre del archivo):</p>
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
            f'<form class="schedule" method="post" action="/schedule/{stem}">'
            '<span class="meta">⏰ Sale el</span>'
            f'<input type="datetime-local" name="publish_at" value="{default}" required />'
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


def lang_chips(g: dict) -> str:
    """Estado por idioma de un artículo: publicado (enlace), borrador o «Traducir»."""
    chips = []
    for lang in TRANSLATION_LANGS:
        t = g["tr"][lang]
        label = lang.upper()
        if t is None:
            chips.append(f"<span>{label}: —</span>")
        elif t["draft"]:
            chips.append(f'<a href="/preview/{lang}/{g["stem"]}">{label}: borrador ✏️</a>')
        else:
            chips.append(f'<a href="{public_url(lang, t["slug"])}" target="_blank">{label} ✓</a>')
    missing = [lang for lang in TRANSLATION_LANGS if g["tr"][lang] is None]
    translate_btn = (
        f"""<form class="inline" method="post" action="/translate/{g["stem"]}">
    <button title="Traduce con OpenAI a: {", ".join(l.upper() for l in missing)}">Traducir ({len(missing)})</button>
  </form>"""
        if missing
        else ""
    )
    return f'<div class="meta">{" · ".join(chips)}</div>{translate_btn}'


@app.get("/", response_class=HTMLResponse)
def index():
    groups = list_groups()
    drafts = sorted(draft_refs())
    sched = blog_schedule.load()
    cards = "".join(group_card(g, sched.get(g["stem"])) for g in groups)
    publish_all = (
        f"""<form class="inline" method="post" action="/publish">
  <button class="primary">Publicar todo lo pendiente ({len(drafts)})</button>
</form>"""
        if drafts
        else ""
    )
    return page(
        "Portal",
        f"""
<h1>Publicar un artículo</h1>
<p class="meta">Sube un <code>.html</code> con el frontmatter del blog
(<code>--- title/description/keywords/date/excerpt ---</code> + cuerpo HTML).
La URL pública usa el campo opcional <code>slug:</code> del frontmatter; si no lo hay,
el nombre del archivo (<code>minusculas-con-guiones.html</code>). Al subir se
generan solas las traducciones (EN/CA/GL/EU) — tarda un minuto —; si alguna
falla, el botón «Traducir» la reintenta.</p>
<form class="card" method="post" action="/upload" enctype="multipart/form-data">
  <div class="row">
    <input type="file" name="file" accept=".html" required />
    <button class="primary">Subir, traducir y previsualizar</button>
  </div>
</form>
<h2>Artículos ({len(groups)})</h2>
{cards or '<p class="meta">Ningún artículo todavía.</p>'}
<div class="actions">
{publish_all}
<form class="inline" method="post" action="/sync">
  <button title="Vuelve a copiar blog+sitemap al dist de prod">Sincronizar con prod</button>
</form>
</div>
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
        # Traducción automática: el grupo nace completo; los fallos no
        # bloquean (quedan pendientes para el botón «Traducir»).
        written, _errors = generate_missing_translations(target.stem)
        if written:
            ok, out = run_generate()
            if not ok:
                for lang in written:
                    content_path(lang, target.stem).unlink(missing_ok=True)
                run_generate()
    finally:
        LOCK.release()
    return RedirectResponse(f"/preview/{target.stem}", status_code=303)


@app.get("/preview/{ref:path}", response_class=HTMLResponse)
def preview(ref: str):
    parsed = parse_ref(ref)
    if not parsed or not content_path(*parsed).exists():
        return error_page("No encontrado", f"No hay borrador «{ref}».", 404)
    lang, stem = parsed
    src = content_path(lang, stem)
    title = parse_frontmatter(src.read_text()).get("title", stem)
    slug = public_slug(src)
    return page(
        f"Preview · {title}",
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
    )


@app.get("/draft/{ref:path}", response_class=HTMLResponse)
def draft(ref: str):
    parsed = parse_ref(ref)
    if not parsed or not content_path(*parsed).exists():
        return error_page("No encontrado", f"No hay borrador «{ref}».", 404)
    lang, stem = parsed
    f = generated_page(lang, public_slug(content_path(lang, stem)))
    if not f.exists():
        return error_page("No encontrado", f"No hay página generada para «{ref}».", 404)
    return HTMLResponse(f.read_text())


@app.post("/publish", response_class=HTMLResponse)
def publish():
    """Publica TODO lo pendiente de una vez (un commit, un sync).

    El generador siempre regenera índices/hreflang/sitemap con todos los
    borradores presentes, así que publicar por partes dejaría medias verdades:
    aquí git y prod avanzan juntos al estado completo del árbol."""
    refs = sorted(draft_refs())
    if not refs:
        return error_page("Nada que publicar", "No hay borradores pendientes.", 404)
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        published = []
        for ref in refs:
            lang, stem = parse_ref(ref)
            src = content_path(lang, stem)
            published.append((parse_frontmatter(src.read_text()).get("title", stem), lang, public_slug(src)))
        titles = "; ".join(f"{t} [{lang}]" for t, lang, _ in published)
        ok, out = commit_paths(f"Blog: publica {titles} (portal)")
        if not ok:
            return error_page("git commit falló", out, 500)
        synced, sync_out = sync_to_prod()
        lives = [check_live_url(public_url(lang, slug)) for _, lang, slug in published] if synced else []
    finally:
        LOCK.release()
    if not synced:
        return page(
            "Commit hecho, sync pendiente",
            f"""<h1 class="bad">Commit hecho, pero el sync a prod falló</h1>
<p>Los artículos están en git (fuente de verdad); solo falta copiarlos a prod.</p>
<pre>{html.escape(sync_out)}</pre>
<form class="inline" method="post" action="/sync"><button class="primary">Reintentar sincronización</button></form>
<p><a href="/">← Volver al portal</a></p>""",
            502,
        )
    items = "".join(
        f'<li><a href="{public_url(lang, slug)}" target="_blank">{public_url(lang, slug)}</a> — {html.escape(live)}</li>'
        for (_, lang, slug), live in zip(published, lives)
    )
    return page(
        "Publicado",
        f"""<h1 class="ok">Publicado ✅</h1>
<ul>{items}</ul>
<p class="meta">Commit en git hecho; el próximo deploy completo regenerará exactamente lo mismo.</p>
<p><a href="/">← Volver al portal</a></p>""",
    )


@app.post("/discard/{ref:path}")
def discard(ref: str):
    parsed = parse_ref(ref)
    if not parsed or not content_path(*parsed).exists():
        return error_page("No encontrado", f"No hay borrador «{ref}».", 404)
    lang, stem = parsed
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        src = content_path(lang, stem)
        slug = public_slug(src)
        src.unlink()
        blog_schedule.remove(stem)  # descartar un borrador anula su programación
        shutil.rmtree(generated_page(lang, slug).parent, ignore_errors=True)
        run_generate()  # índice/hreflang/sitemap vuelven al estado del último commit
    finally:
        LOCK.release()
    return RedirectResponse("/", status_code=303)


@app.post("/delete/{ref:path}", response_class=HTMLResponse)
def delete(ref: str):
    parsed = parse_ref(ref)
    if not parsed or not content_path(*parsed).exists():
        return error_page("No encontrado", f"No existe el artículo «{ref}».", 404)
    lang, stem = parsed
    if lang == "es" and len(list(CONTENT_BLOG.glob("*.html"))) <= 1:
        return error_page(
            "No se puede borrar el último artículo",
            "El blog necesita al menos un artículo (el generador lo exige). "
            "Sube el sustituto antes de borrar este.",
            409,
        )
    if not LOCK.acquire(blocking=False):
        return error_page("Ocupado", "Hay otra operación en curso; reintenta.", 423)
    try:
        src = content_path(lang, stem)
        title = parse_frontmatter(src.read_text()).get("title", stem)
        # Borrar el original arrastra sus traducciones (una traducción huérfana
        # rompería el generador y dejaría hreflang colgando).
        victims = [(lang, src)] if lang != "es" else [
            (l, content_path(l, stem))
            for l in ("es", *TRANSLATION_LANGS)
            if content_path(l, stem).exists()
        ]
        for vlang, vsrc in victims:
            slug = public_slug(vsrc)
            vsrc.unlink()
            shutil.rmtree(generated_page(vlang, slug).parent, ignore_errors=True)
        blog_schedule.remove(stem)  # borrar el grupo anula su programación
        ok, out = run_generate()
        if not ok:
            return error_page("El generador falló tras borrar", out, 500)
        ok, out = commit_paths(f"Blog: retira «{title}» [{', '.join(v for v, _ in victims)}] (portal)")
        if not ok:
            return error_page("git commit falló", out, 500)
        synced, sync_out = sync_to_prod()
    finally:
        LOCK.release()
    status = "✅ retirado también de prod" if synced else f"⚠️ sync a prod falló:\n{sync_out}"
    return page(
        "Borrado",
        f"""<h1>Artículo borrado</h1>
<p><strong>{html.escape(title)}</strong> se ha retirado del blog ({len(victims)} versión(es)).</p>
<pre>{html.escape(status)}</pre>
<p><a href="/">← Volver al portal</a></p>""",
    )


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
