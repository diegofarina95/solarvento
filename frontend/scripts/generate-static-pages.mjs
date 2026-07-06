#!/usr/bin/env node
// Generador de las páginas estáticas multiidioma (FAQ y política de privacidad)
// y del sitemap. FUENTE ÚNICA: frontend/content/src/<lang>.json (+ estilos en
// frontend/content/styles/). Corre en el prebuild de npm, así que public/
// siempre refleja la fuente; editar los .html generados a mano no sirve de nada.
//
// Uso:
//   node scripts/generate-static-pages.mjs           # escribe en public/
//   node scripts/generate-static-pages.mjs --check   # compara sin escribir (exit 1 si hay deriva)

import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'content', 'src')
const STYLES = join(ROOT, 'content', 'styles')
const PUBLIC = join(ROOT, 'public')

const ORIGIN = 'https://solarvento.es'
// Orden de idiomas: fija el orden de los hreflang (es primero, luego el resto).
const LANGS = ['es', 'en', 'gl', 'ca', 'eu', 'fr', 'pt']
const LASTMOD = '2026-07-06' // actualizar al cambiar el contenido de las páginas

const BANNER =
  '<!-- GENERADO por frontend/scripts/generate-static-pages.mjs a partir de frontend/content/src/*.json — NO EDITAR A MANO -->'

const pagePath = (base, lang) => (lang === 'es' ? `${base}.html` : `${base}-${lang}.html`)

function hreflangBlock(base) {
  const lines = LANGS.map(
    (l) => `    <link rel="alternate" hreflang="${l}" href="${ORIGIN}/${pagePath(base, l)}" />`,
  )
  lines.push(
    `    <link rel="alternate" hreflang="x-default" href="${ORIGIN}/${pagePath(base, 'es')}" />`,
  )
  return lines.join('\n')
}

function indentCss(css) {
  return css
    .trimEnd()
    .split('\n')
    .map((line) => (line ? '      ' + line : ''))
    .join('\n')
}

function faqPage(content, css) {
  const { lang, faq } = content
  const path = pagePath('faq', lang)
  const ld = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faq.questions.map((q) => ({
      '@type': 'Question',
      name: q.ldQ,
      acceptedAnswer: { '@type': 'Answer', text: q.ldA },
    })),
  }
  const body = faq.questions.map((q) => `      <h2>${q.q}</h2>\n      <p>${q.aHtml}</p>`).join('\n\n')
  return `<!doctype html>
${BANNER}
<html lang="${lang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${faq.title}</title>
    <meta name="description" content="${faq.description}" />
    <meta name="keywords" content="${faq.keywords}" />
    <meta name="robots" content="index, follow, max-image-preview:large" />
    <link rel="canonical" href="${ORIGIN}/${path}" />
${hreflangBlock('faq')}
    <link rel="icon" href="/favicon.ico" sizes="any" />
    <style>
${indentCss(css)}
    </style>
    <script type="application/ld+json">
${JSON.stringify(ld, null, 2)}
    </script>
  </head>
  <body>
    <main class="wrap">
      <a class="back" href="/">${faq.back}</a>
      <h1>${faq.h1}</h1>
      <p class="lead">${faq.leadHtml}</p>
      <a class="cta" href="/">${faq.cta}</a>

${body}

      <p class="disc">${faq.disclaimer}</p>

      <a class="cta" href="/">${faq.cta}</a>

      <footer>${faq.footerHtml}</footer>
    </main>
  </body>
</html>
`
}

function privacyPage(content, css) {
  const { lang, privacy } = content
  const path = pagePath('privacidad', lang)
  const body = privacy.sections
    .map((s) => `      <h2>${s.h2}</h2>\n${s.bodyHtml.trim().replace(/^/gm, '      ')}`)
    .join('\n\n')
  return `<!doctype html>
${BANNER}
<html lang="${lang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${privacy.title}</title>
    <meta name="description" content="${privacy.description}" />
    <meta name="robots" content="index, follow" />
    <link rel="canonical" href="${ORIGIN}/${path}" />
${hreflangBlock('privacidad')}
    <link rel="icon" href="/favicon.ico" sizes="any" />
    <style>
${indentCss(css)}
    </style>
  </head>
  <body>
    <main class="wrap">
      <a class="back" href="/">${privacy.back}</a>
      <h1>${privacy.h1}</h1>
      <p class="updated">${privacy.updated}</p>

      <p>${privacy.introHtml}</p>

${body}

      <footer>${privacy.footerHtml}</footer>
    </main>
  </body>
</html>
`
}

function sitemap() {
  const verbose = (loc, changefreq, priority) =>
    `  <url>\n    <loc>${loc}</loc>\n    <lastmod>${LASTMOD}</lastmod>\n    <changefreq>${changefreq}</changefreq>\n    <priority>${priority}</priority>\n  </url>`
  const compact = (loc, changefreq, priority) =>
    `  <url><loc>${loc}</loc><lastmod>${LASTMOD}</lastmod><changefreq>${changefreq}</changefreq><priority>${priority}</priority></url>`
  const others = LANGS.filter((l) => l !== 'es')
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    verbose(`${ORIGIN}/`, 'weekly', '1.0'),
    verbose(`${ORIGIN}/faq.html`, 'monthly', '0.8'),
    verbose(`${ORIGIN}/ayudas.html`, 'monthly', '0.7'),
    verbose(`${ORIGIN}/privacidad.html`, 'yearly', '0.3'),
    ...others.map((l) => compact(`${ORIGIN}/${pagePath('faq', l)}`, 'monthly', '0.7')),
    ...others.map((l) => compact(`${ORIGIN}/${pagePath('privacidad', l)}`, 'yearly', '0.2')),
    '</urlset>',
    '',
  ]
  return lines.join('\n')
}

function main() {
  const check = process.argv.includes('--check')
  const faqCss = readFileSync(join(STYLES, 'faq.css'), 'utf-8')
  const privacyCss = readFileSync(join(STYLES, 'privacy.css'), 'utf-8')
  const langsOnDisk = readdirSync(SRC).filter((f) => f.endsWith('.json'))
  const outputs = new Map()

  for (const lang of LANGS) {
    const file = `${lang}.json`
    if (!langsOnDisk.includes(file)) throw new Error(`Falta content/src/${file}`)
    const content = JSON.parse(readFileSync(join(SRC, file), 'utf-8'))
    if (content.faq.questions.length === 0) throw new Error(`${file}: FAQ sin preguntas`)
    outputs.set(pagePath('faq', lang), faqPage(content, faqCss))
    outputs.set(pagePath('privacidad', lang), privacyPage(content, privacyCss))
  }
  outputs.set('sitemap.xml', sitemap())

  // Paridad: mismas preguntas/secciones en todos los idiomas que en es.
  const ref = JSON.parse(readFileSync(join(SRC, 'es.json'), 'utf-8'))
  for (const lang of LANGS) {
    const c = JSON.parse(readFileSync(join(SRC, `${lang}.json`), 'utf-8'))
    if (c.faq.questions.length !== ref.faq.questions.length)
      throw new Error(`${lang}: nº de preguntas FAQ distinto de es`)
    if (c.privacy.sections.length !== ref.privacy.sections.length)
      throw new Error(`${lang}: nº de secciones de privacidad distinto de es`)
  }

  let drift = 0
  for (const [name, html] of outputs) {
    const target = join(PUBLIC, name)
    if (check) {
      const current = existsSync(target) ? readFileSync(target, 'utf-8') : null
      if (current !== html) {
        drift += 1
        console.error(`DERIVA: public/${name} no coincide con lo generado desde la fuente`)
      }
    } else {
      writeFileSync(target, html)
    }
  }
  if (check) {
    if (drift) {
      console.error(
        `\n${drift} fichero(s) desincronizados. Ejecuta: node scripts/generate-static-pages.mjs`,
      )
      process.exit(1)
    }
    console.log(`OK: ${outputs.size} ficheros generados coinciden con public/`)
  } else {
    console.log(`Generados ${outputs.size} ficheros estáticos en public/`)
  }
}

main()
