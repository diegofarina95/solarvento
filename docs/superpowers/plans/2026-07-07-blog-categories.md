# Categorías del blog — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Campo `category` opcional en el frontmatter (guia/analisis/divulgacion) que aplica etiqueta y color día/noche en artículo e índice, con fallback neutro y migración de los publicados a GUÍA.

**Architecture:** `CATEGORIES` en `blog.mjs` (parse tolerante + herencia del es en `loadBlog` + etiqueta/clase en plantillas); 6 variables CSS enganchadas a `:root`/`:root[data-theme='night']` de `blog.css` (mecanismo solar existente); migración única con el baile de apartar borradores (los 5 archivos sin trackear no deben entrar en el commit ni llegar a prod).

**Tech Stack:** Node (`cd frontend && npm test` = `node --test tests/*.test.mjs`), generador `generate-static-pages.mjs`, pytest para el toque del portal.

**Spec:** `docs/superpowers/specs/2026-07-07-blog-categories-design.md`

## Global Constraints

- Categoría inválida o ausente NUNCA lanza error: `undefined` → render neutro idéntico al actual (sin clase, sin etiqueta, sin borde).
- Etiquetas exactas: `GUÍA`, `ANÁLISIS`, `DIVULGACIÓN` — iguales en todos los idiomas.
- Colores exactos del brief; día en `:root`, noche en `:root[data-theme='night']`. Nada de `prefers-color-scheme` (el test del tema lo vigila).
- La migración/sync NO debe publicar los borradores pendientes (`horas-valle-luz-barata` y las 4 traducciones de `merecen-la-pena-placas-solares-espana`): apartar antes de commit+rsync, restaurar después.
- Un commit por tarea. Parar el servicio del portal durante la migración (su planificador comparte el árbol).

---

### Task C1: Generador — parse, herencia y plantillas

**Files:**
- Modify: `frontend/scripts/blog.mjs` (parseArticle ~línea 157; loadBlog ~205; articlePage ~391; blogIndexPage ~447)
- Test: `frontend/tests/blog.test.mjs` (añadir al final)

**Interfaces:**
- Produces: `export const CATEGORIES = { guia: 'GUÍA', analisis: 'ANÁLISIS', divulgacion: 'DIVULGACIÓN' }`; `a.category: 'guia'|'analisis'|'divulgacion'|undefined` en artículos parseados; clases `cat-<key>` y `<p|span class="cat-label">` en el HTML.

- [ ] **Step 1: Tests que fallan**

Añadir al final de `frontend/tests/blog.test.mjs`:

```js
// --- Categorías: parse tolerante, herencia y presentación ---

import { CATEGORIES, blogIndexPage } from '../scripts/blog.mjs'

test('category válida se parsea; inválida o ausente queda undefined sin romper', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'a.html'), article('category: analisis\n'))
  writeFileSync(join(dir, 'b.html'), article('category: Otra Cosa\n'))
  writeFileSync(join(dir, 'c.html'), article(''))
  const byStem = new Map(loadArticles(dir).map((a) => [a.stem, a]))
  assert.equal(byStem.get('a').category, 'analisis')
  assert.equal(byStem.get('b').category, undefined)
  assert.equal(byStem.get('c').category, undefined)
  assert.equal(CATEGORIES.analisis, 'ANÁLISIS')
})

test('la traducción hereda la categoría del original español', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'factura.html'), FM('category: guia\n'))
  mkdirSync(join(dir, 'en'))
  writeFileSync(join(dir, 'en', 'factura.html'), FM('lang: en\n'))
  const g = loadBlog(dir).get('factura')
  assert.equal(g.es.category, 'guia')
  assert.equal(g.tr.en.category, 'guia')
})

const BASE_ART = {
  slug: 's', title: 't', description: 'd', keywords: 'k',
  date: '2026-07-07', updated: '2026-07-07', excerpt: 'e', lang: 'es',
  bodyHtml: '<p>x</p>',
}

test('el artículo categorizado lleva clase y etiqueta sobre el título; el neutro no', () => {
  const con = articlePage({ ...BASE_ART, category: 'divulgacion' }, '')
  assert.ok(con.includes('<article class="cat-divulgacion">'))
  const label = con.indexOf('<p class="eyebrow cat-label">DIVULGACIÓN</p>')
  const h1 = con.indexOf('<h1>')
  assert.ok(label !== -1 && label < h1, 'la etiqueta debe ir sobre el título')
  const sin = articlePage(BASE_ART, '')
  assert.ok(sin.includes('<article>'))
  assert.ok(!sin.includes('cat-label'))
})

test('la card del índice lleva clase y etiqueta junto a la fecha; la neutra queda intacta', () => {
  const html = blogIndexPage(
    [{ ...BASE_ART, category: 'guia' }, { ...BASE_ART, slug: 'otro' }], '', 'es', '')
  assert.ok(html.includes('<article class="card cat-guia">'))
  assert.match(html, /<time[^>]*>[^<]+<\/time><span class="cat-label">GUÍA<\/span>/)
  assert.ok(html.includes('<article class="card">'))  // la neutra, sin clase extra
})
```

- [ ] **Step 2: Verificar que fallan**

Run: `cd /home/diego/taller-projects/solvento/frontend && npm test 2>&1 | tail -20`
Expected: FAIL — `CATEGORIES` no exportado (SyntaxError de import) 

- [ ] **Step 3: Implementar en blog.mjs**

Tras `export const BLOG_LANGS…` (línea 34):

```js
// Categorías del blog: clave del frontmatter → etiqueta visible (idéntica en
// todos los idiomas). Valor no reconocido = sin categoría (render neutro).
export const CATEGORIES = { guia: 'GUÍA', analisis: 'ANÁLISIS', divulgacion: 'DIVULGACIÓN' }
```

En `parseArticle`, en el objeto de retorno, junto a `lang`:

```js
    category: CATEGORIES[(meta.category || '').trim().toLowerCase()]
      ? (meta.category || '').trim().toLowerCase()
      : undefined,
```

En `loadBlog`, tras `g.tr[lang] = a` (línea 229):

```js
      a.category = g.es.category // la categoría es del grupo: manda el original
```

En `articlePage`, antes del `return`:

```js
  const catClass = a.category ? ` class="cat-${a.category}"` : ''
  const catLabel = a.category
    ? `        <p class="eyebrow cat-label">${CATEGORIES[a.category]}</p>\n`
    : ''
```

y en el HTML: `<article${catClass}>` (era `<article>`) y la línea de la etiqueta
justo antes de `<h1>${a.title}</h1>`:

```js
      <article${catClass}>
${catLabel}        <h1>${a.title}</h1>
```

En `blogIndexPage`, la card pasa a:

```js
    .map(
      (a) => `        <article class="card${a.category ? ` cat-${a.category}` : ''}">
          <h2><a href="/${articleUrl(a)}">${a.title}</a></h2>
          <p class="meta"><time datetime="${a.date}">${humanDate(a.date, lang)}</time>${
            a.category ? `<span class="cat-label">${CATEGORIES[a.category]}</span>` : ''
          }</p>
          <p class="excerpt">${a.excerpt}</p>
        </article>`,
    )
```

- [ ] **Step 4: Verificar que pasan**

Run: `cd /home/diego/taller-projects/solvento/frontend && npm test 2>&1 | tail -6`
Expected: los 4 tests nuevos pasan. El test `--check` puede fallar todavía si algo cambió el HTML de páginas sin categoría — NO debe cambiar: con `category` ausente el output es byte-idéntico (si el --check falla aquí, hay un bug en el paso 3).

- [ ] **Step 5: Commit**

```bash
cd /home/diego/taller-projects/solvento
git add frontend/scripts/blog.mjs frontend/tests/blog.test.mjs
git commit -m "Blog: campo category en el generador (parse tolerante, herencia, etiqueta)"
```

---

### Task C2: CSS día/noche de categorías

**Files:**
- Modify: `frontend/content/styles/blog.css` (variables en `:root` línea 12 y `:root[data-theme='night']` línea 26; reglas nuevas al final del bloque de índice)
- Test: `frontend/tests/blog.test.mjs`

**Interfaces:**
- Consumes: clases `cat-*` y `.cat-label` de Task C1.
- Produces: variables `--cat-*` día/noche y reglas escopadas; `public/` regenerado.

- [ ] **Step 1: Test que falla**

Añadir a `frontend/tests/blog.test.mjs`:

```js
test('las variables de categoría existen en día y en noche en las páginas servidas', () => {
  const html = readPublic(join('blog', 'index.html'))
  // Día (en :root)
  for (const v of ['--cat-guia: #f59e0b', '--cat-analisis: #3f7f8f', '--cat-divulgacion: #c2703d']) {
    assert.ok(html.includes(v), `falta ${v} (día)`)
  }
  // Noche (dentro del bloque [data-theme='night'])
  const night = html.slice(html.indexOf("[data-theme='night']"))
  for (const v of ['--cat-guia: #f0b95d', '--cat-analisis: #6bb0be', '--cat-divulgacion: #d99668']) {
    assert.ok(night.includes(v), `falta ${v} (noche)`)
  }
  assert.ok(html.includes('.cat-label'), 'faltan las reglas de la etiqueta')
})
```

- [ ] **Step 2: Verificar que falla**

Run: `cd /home/diego/taller-projects/solvento/frontend && npm test 2>&1 | tail -6`
Expected: FAIL — variables ausentes en `public/blog/index.html`

- [ ] **Step 3: Implementar el CSS y regenerar**

En `:root` (tras `--gridline: #ece6d9;`):

```css
  /* Categorías del blog (acento; el ámbar de marca sigue dominando) */
  --cat-guia: #f59e0b;
  --cat-analisis: #3f7f8f;
  --cat-divulgacion: #c2703d;
```

En `:root[data-theme='night']` (tras `--gridline: #2a2f3a;`):

```css
  /* De noche, más claras y desaturadas: los vivos cansan sobre fondo oscuro */
  --cat-guia: #f0b95d;
  --cat-analisis: #6bb0be;
  --cat-divulgacion: #d99668;
```

Tras el bloque `/* Índice del blog */ … .card p.excerpt { … }` añadir:

```css
/* Categorías: la clase solo fija --cat; etiqueta, punto del eyebrow y borde
   de card la usan. Sin categoría no existe la clase y nada de esto aplica. */
.cat-guia { --cat: var(--cat-guia); }
.cat-analisis { --cat: var(--cat-analisis); }
.cat-divulgacion { --cat: var(--cat-divulgacion); }
.cat-label { color: var(--cat); }
article[class*='cat-'] .eyebrow::before {
  background: radial-gradient(circle at 35% 35%, color-mix(in srgb, var(--cat) 75%, #fff), var(--cat));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cat) 18%, transparent);
}
article[class*='cat-'] > .eyebrow.cat-label { margin: 1.6rem 0 -0.6rem; }
.card[class*='cat-'] { border-left: 4px solid var(--cat); }
```

Regenerar: `cd /home/diego/taller-projects/solvento/frontend && node scripts/generate-static-pages.mjs`

- [ ] **Step 4: Verificar que pasa todo**

Run: `cd /home/diego/taller-projects/solvento/frontend && npm test 2>&1 | tail -4`
Expected: todos los tests pasan (incluido el `--check`, porque acabamos de regenerar).

- [ ] **Step 5: Commit (solo fuente y tests — public/ regenerado va en la migración)**

```bash
cd /home/diego/taller-projects/solvento
git add frontend/content/styles/blog.css frontend/tests/blog.test.mjs
git commit -m "Blog: colores de categoría día/noche enganchados al tema solar"
```

---

### Task C3: Mención en el portal

**Files:**
- Modify: `backend/app/portal.py` (FRONTMATTER_TEMPLATE y ayuda del índice)
- Test: `backend/tests/test_portal.py`

- [ ] **Step 1: Test que falla**

```python
def test_ayuda_menciona_category(client, monkeypatch, tmp_path):
    monkeypatch.setattr(portal, "CONTENT_BLOG", tmp_path)
    r = client.post("/upload", files={"file": ("x.html", b"<p>sin frontmatter</p>")})
    assert r.status_code == 422
    assert "category" in r.text
```

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py -k menciona -v` → FAIL

- [ ] **Step 2: Implementar**

En `FRONTMATTER_TEMPLATE`, añadir tras la línea `excerpt: …`:

```
category: guia
```

En `frontmatter_help_page`, ampliar el párrafo de la plantilla: donde dice
«(además admite <code>slug: url-para-seo</code> opcional …)» añadir
«y <code>category: guia | analisis | divulgacion</code> opcional para la
etiqueta y el color de la categoría».

En la ayuda del índice (`index()`), tras la frase del slug añadir:
«El campo opcional <code>category</code> (<code>guia | analisis |
divulgacion</code>) pone etiqueta y color al artículo.»

- [ ] **Step 3: Verificar y commitear**

Run: `cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest tests/test_portal.py 2>&1 | tail -2` → todos passed

```bash
cd /home/diego/taller-projects/solvento
git add backend/app/portal.py backend/tests/test_portal.py
git commit -m "Portal: documenta el campo category en plantilla y ayuda"
```

---

### Task C4: Migración a GUÍA + publicación + verificación visual

**Files:**
- Modify: los 4 artículos ES publicados en `frontend/content/blog/` (añadir `category: guia`)
- Script one-off en el scratchpad (no se commitea)

- [ ] **Step 1: Añadir `category: guia`**

En el frontmatter de estos 4 archivos (línea nueva tras `excerpt:` — NO tocar
`horas-valle-luz-barata.html` ni los borradores de traducción):

- `frontend/content/blog/como-leer-tu-factura-de-la-luz.html`
- `frontend/content/blog/que-electrodomesticos-gastan-mas.html`
- `frontend/content/blog/coche-electrico-y-placas-solares.html`
- `frontend/content/blog/merecen-la-pena-placas-solares-espana.html`

- [ ] **Step 2: Tests con el contenido real**

Run: `cd /home/diego/taller-projects/solvento/frontend && node scripts/generate-static-pages.mjs && npm test 2>&1 | tail -4`
Expected: todo en verde; `public/blog/index.html` contiene `cat-guia`.

- [ ] **Step 3: Migración publicada con el baile de borradores**

Parar el portal (su planificador comparte árbol y LOCK de proceso distinto):

```bash
systemctl --user stop solvento-portal
```

Script one-off (scratchpad, ejecutar con `backend/.venv/bin/python`): apartar
TODOS los borradores y sus páginas generadas, regenerar, commit, sync,
restaurar, regenerar — la misma secuencia de `publish_group` pero para el
árbol completo y con mensaje propio:

```python
import shutil
from app import portal

refs = sorted(portal.draft_refs())
aside = []
for ref in refs:
    lang, stem = portal.parse_ref(ref)
    src = portal.content_path(lang, stem)
    slug = portal.public_slug(src)
    dst = portal.DRAFTS_ASIDE / src.relative_to(portal.CONTENT_BLOG)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    aside.append((src, dst))
    shutil.rmtree(portal.generated_page(lang, slug).parent, ignore_errors=True)
try:
    ok, out = portal.run_generate()
    assert ok, out
    ok, out = portal.commit_paths("Blog: categorías — publicados migrados a GUÍA")
    assert ok, out
    synced, sync_out = portal.sync_to_prod()
    assert synced, sync_out
finally:
    for src, dst in aside:
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
    shutil.rmtree(portal.DRAFTS_ASIDE, ignore_errors=True)
    portal.run_generate()
print("migración publicada")
```

Reiniciar: `systemctl --user start solvento-portal`

- [ ] **Step 4: Verificación en vivo y visual**

```bash
curl -s https://solarvento.es/blog/ | grep -c 'cat-guia'          # ≥ 4 cards
curl -s https://solarvento.es/blog/ | grep -c 'horas-valle'       # 0 (borrador NO publicado)
curl -s https://solarvento.es/blog/como-leer-tu-factura-de-la-luz/ | grep -c 'cat-label'
```

Visual día/noche: captura con Playwright si hay navegador instalado
(`npx playwright screenshot --viewport-size=800,900 <url> dia.png` y lo mismo
con `--full-page` forzando noche vía `page.evaluate` en un script corto); si no
hay navegador disponible, inspección de CSS y aviso a Diego con los dos hex
para que juzgue el contraste de GUÍA en día.

- [ ] **Step 5: Backend + frontend suites completas, y cierre**

```bash
cd /home/diego/taller-projects/solvento/backend && .venv/bin/pytest 2>&1 | tail -2
cd /home/diego/taller-projects/solvento/frontend && npm test 2>&1 | tail -3
git -C /home/diego/taller-projects/solvento status --short  # solo los 5 borradores sin trackear
```
