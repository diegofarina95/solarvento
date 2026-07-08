// Guardas de la FUENTE ÚNICA de páginas estáticas (content/src/*.json):
// 1) public/ no puede derivar de la fuente (alguien editó un .html generado
//    a mano, o cambió la fuente sin regenerar) — el generador en --check.
// 2) Cada FAQ generada lleva un JSON-LD FAQPage parseable con las mismas
//    preguntas en todos los idiomas.
// 3) Los hreflang están completos en las 14 páginas.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const LANGS = ['es', 'en', 'gl', 'ca', 'eu']
const pagePath = (base, lang) => (lang === 'es' ? `${base}.html` : `${base}-${lang}.html`)

test('public/ está sincronizado con content/src (generador --check)', () => {
  execFileSync(process.execPath, [join(ROOT, 'scripts', 'generate-static-pages.mjs'), '--check'], {
    stdio: 'pipe',
  })
})

test('cada FAQ lleva un FAQPage válido con el mismo nº de preguntas', () => {
  let expected = null
  for (const lang of LANGS) {
    const html = readFileSync(join(ROOT, 'public', pagePath('faq', lang)), 'utf-8')
    const m = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)
    assert.ok(m, `${lang}: falta el JSON-LD`)
    const ld = JSON.parse(m[1])
    assert.equal(ld['@type'], 'FAQPage', lang)
    expected ??= ld.mainEntity.length
    assert.equal(ld.mainEntity.length, expected, `${lang}: nº de preguntas distinto`)
    assert.ok(expected >= 10, 'FAQ sospechosamente corta')
  }
})

test('las 14 páginas llevan hreflang completo (7 idiomas + x-default)', () => {
  for (const base of ['faq', 'privacidad']) {
    for (const lang of LANGS) {
      const html = readFileSync(join(ROOT, 'public', pagePath(base, lang)), 'utf-8')
      // Solo los <link rel="alternate"> de la cabecera: el selector de idiomas
      // del cuerpo también lleva hreflang y no forma parte de esta guarda.
      const langs = [...html.matchAll(/rel="alternate" hreflang="([^"]+)"/g)].map((m) => m[1])
      assert.deepEqual(langs.sort(), [...LANGS, 'x-default'].sort(), `${base}/${lang}`)
    }
  }
})

test('las 14 páginas llevan Open Graph coherente y Twitter Card', () => {
  for (const base of ['faq', 'privacidad']) {
    for (const lang of LANGS) {
      const page = pagePath(base, lang)
      const html = readFileSync(join(ROOT, 'public', page), 'utf-8')
      const canonical = html.match(/rel="canonical" href="([^"]+)"/)?.[1]
      const ogUrl = html.match(/property="og:url" content="([^"]+)"/)?.[1]
      assert.equal(ogUrl, canonical, `${page}: og:url debe coincidir con el canonical`)
      for (const prop of ['og:title', 'og:description', 'og:image', 'og:locale']) {
        assert.match(html, new RegExp(`property="${prop}" content="[^"]+"`), `${page}: falta ${prop}`)
      }
      assert.match(html, /name="twitter:card" content="summary_large_image"/, `${page}: falta twitter:card`)
    }
  }
})

test('las 14 páginas llevan selector de idiomas con las otras 6 versiones', () => {
  for (const base of ['faq', 'privacidad']) {
    for (const lang of LANGS) {
      const page = pagePath(base, lang)
      const html = readFileSync(join(ROOT, 'public', page), 'utf-8')
      const nav = html.match(/<nav class="langs"[^>]*>([\s\S]*?)<\/nav>/)
      assert.ok(nav, `${page}: falta el selector de idiomas`)
      const links = [...nav[1].matchAll(/href="\/([^"]+)"/g)].map((m) => m[1])
      const expected = LANGS.filter((l) => l !== lang).map((l) => pagePath(base, l))
      assert.deepEqual(links.sort(), expected.sort(), `${page}: enlaces del selector`)
      assert.match(nav[1], /<strong>[^<]+<\/strong>/, `${page}: idioma actual sin resaltar`)
    }
  }
})

test('las 14 páginas llevan BreadcrumbList con 2 niveles', () => {
  for (const base of ['faq', 'privacidad']) {
    for (const lang of LANGS) {
      const page = pagePath(base, lang)
      const html = readFileSync(join(ROOT, 'public', page), 'utf-8')
      const blocks = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
      const breadcrumb = blocks
        .map((m) => JSON.parse(m[1]))
        .find((ld) => ld['@type'] === 'BreadcrumbList')
      assert.ok(breadcrumb, `${page}: falta el BreadcrumbList`)
      assert.equal(breadcrumb.itemListElement.length, 2, `${page}: breadcrumb con niveles inesperados`)
      assert.equal(breadcrumb.itemListElement[1].item, `https://solarvento.es/${page}`, page)
    }
  }
})
