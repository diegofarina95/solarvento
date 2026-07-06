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
const LANGS = ['es', 'en', 'gl', 'ca', 'eu', 'fr', 'pt']
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
      const langs = [...html.matchAll(/hreflang="([^"]+)"/g)].map((m) => m[1])
      assert.deepEqual(langs.sort(), [...LANGS, 'x-default'].sort(), `${base}/${lang}`)
    }
  }
})
