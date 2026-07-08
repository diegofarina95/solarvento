# Idiomas FR/PT fuera + blog consciente del idioma + selector — plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web solo en es/en/gl/ca/eu; enlace «Blog» de la app al índice del idioma activo; nav de idiomas en índices y artículos del blog.

**Architecture:** Tres cortes independientes: (L1) nav de idiomas en `blog.mjs` + CSS + tests; (L2) enlace del blog en `App.jsx`; (L3) retirada de fr/pt (translations.js, generate-static-pages.mjs, jsons, páginas públicas huérfanas, tests). Regenerar y validar suites + build al final.

**Spec:** `docs/superpowers/specs/2026-07-07-langs-fr-pt-blog-nav-design.md`

## Global Constraints

- Idiomas finales exactos: `['es', 'en', 'gl', 'ca', 'eu']` en TODAS las listas.
- Nav del blog: idioma actual `<strong>`, resto `<a hreflang lang>`; solo idiomas con contenido; con un único idioma no se emite nav.
- El generador no borra huérfanos: `git rm` explícito de faq-fr/pt y privacidad-fr/pt.
- Tests: `cd frontend && npm test` y `cd backend && .venv/bin/pytest`; build `cd frontend && npm run build`.

---

### Task L1: Nav de idiomas en el blog

**Files:** `frontend/scripts/blog.mjs`, `frontend/content/styles/blog.css`; Test: `frontend/tests/blog.test.mjs`

- [ ] Tests que fallan (añadir al final de blog.test.mjs):

```js
// --- Nav de idiomas del blog ---

test('índices y artículos llevan nav de idiomas a las versiones existentes', () => {
  const out = blogOutputs(loadBlog(tmpBlog()), '')
  const idxEs = out.get('index.html')
  assert.match(idxEs, /<nav class="langs"[^>]*>/)
  assert.ok(idxEs.includes('<strong>Español</strong>'))
  assert.ok(idxEs.includes('href="/blog/en/" hreflang="en"'))
  const artEn = out.get(join('en', 'how-to-read-your-bill', 'index.html'))
  assert.ok(artEn.includes('<strong>English</strong>'))
  assert.ok(artEn.includes('href="/blog/como-leer-la-factura/" hreflang="es"'))
  assert.ok(!artEn.includes('hreflang="ca"'))  // no existe esa versión
})

test('con un solo idioma no hay nav de idiomas', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'solo.html'), FM(''))
  const out = blogOutputs(loadBlog(dir), '')
  assert.ok(!out.get('index.html').includes('class="langs"'))
  assert.ok(!out.get(join('solo', 'index.html')).includes('class="langs"'))
})
```

- [ ] Implementar en `blog.mjs`:
  - `STRINGS[lang].langLabel`: es/gl/ca «Idioma», en «Language», eu «Hizkuntza».
  - Constante `const LANG_NAMES = { es: 'Español', en: 'English', ca: 'Català', gl: 'Galego', eu: 'Euskara' }`.
  - Helper:

```js
// Nav de idiomas: versión actual sin enlace, resto enlazadas (complementa el
// hreflang del <head> con enlaces visibles y rastreables).
function langNav(current, versions) {
  if (versions.length < 2) return ''
  const items = versions.map(([lang, href]) =>
    lang === current
      ? `<strong>${LANG_NAMES[lang]}</strong>`
      : `<a href="${href}" hreflang="${lang}" lang="${lang}">${LANG_NAMES[lang]}</a>`,
  )
  return `      <nav class="langs" aria-label="${STRINGS[current].langLabel}">${items.join(' · ')}</nav>\n`
}
```

  - `articlePage(a, css, hreflang = '', versions = [])`: nuevo parámetro con
    `[[lang, '/'+articleUrl(v)], …]` del grupo; insertar `${nav}` entre el
    header y `<article>`. `blogOutputs` construye versions con
    `[g.es, ...TRANSLATION_LANGS.map((l) => g.tr[l]).filter(Boolean)]`.
  - `blogIndexPage(articles, css, lang, hreflang, indexLangs = [])`: versions
    de índices `[[l, '/'+blogHome(l)]]`; `blogOutputs` pasa la lista `langs`
    ya calculada. Nav bajo el header, antes del `<h1>`.
- [ ] CSS en blog.css (tras el bloque de header):

```css
/* Selector de idiomas (como FAQ/privacidad): visible, discreto */
.langs { font-size: .78rem; color: #78716c; margin: 1rem 0 0;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }
.langs a { color: #78716c; }
.langs strong { color: #1c1917; }
[data-theme='night'] .langs, [data-theme='night'] .langs a { color: #a8a29e; }
[data-theme='night'] .langs strong { color: #e7e5e4; }
```

- [ ] `node scripts/generate-static-pages.mjs && npm test` → verde. Commit.

### Task L2: Enlace «Blog» según idioma activo

**Files:** `frontend/src/App.jsx:566`

- [ ] Cambiar `href="/blog/"` por `` href={language === 'es' ? '/blog/' : `/blog/${language}/`} `` (patrón del enlace de privacidad de dos líneas más abajo). `npm run build` en verde. Commit.

### Task L3: Retirar FR y PT

**Files:** `frontend/src/i18n/translations.js`, `frontend/scripts/generate-static-pages.mjs`, `frontend/tests/staticPages.test.mjs`; borrar `frontend/content/src/{fr,pt}.json` y `git rm` de `frontend/public/{faq,privacidad}-{fr,pt}.html`

- [ ] `translations.js`: quitar fr/pt de `LANGUAGE_OPTIONS`; borrar `sharedMonths.fr` y los bloques `fr:` y `pt:` completos de `translations`.
- [ ] `generate-static-pages.mjs`: `LANGS = ['es', 'en', 'gl', 'ca', 'eu']`; quitar fr/pt de `OG_LOCALES`, `LANG_NAMES`, `LANG_NAV_LABEL`.
- [ ] `staticPages.test.mjs`: `LANGS = ['es', 'en', 'gl', 'ca', 'eu']`.
- [ ] `rm frontend/content/src/fr.json frontend/content/src/pt.json` y `git rm frontend/public/faq-fr.html frontend/public/faq-pt.html frontend/public/privacidad-fr.html frontend/public/privacidad-pt.html`.
- [ ] Regenerar + `npm test` + `npm run build` + `.venv/bin/pytest` → todo verde. Commit.

### Task L4: Verificación y cierre

- [ ] `grep -rn "'fr'\|'pt'" frontend/src frontend/scripts frontend/tests frontend/content/src` → sin restos de idioma (cuidado con falsos positivos tipo «offr»).
- [ ] Sitemap sin faq-fr/pt; índice del blog con `.langs`; capturas no necesarias (cambio tipográfico menor).
- [ ] Avisar a Diego: hace falta **deploy completo** (bundle de la app) para que llegue a prod; las URLs fr/pt pasarán a 404 a propósito.
