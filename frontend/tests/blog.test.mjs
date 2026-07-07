// Guardas del blog estático (/blog): fuente única en content/blog/*.html,
// salida en public/blog/. Mismo espíritu que staticPages.test.mjs:
// 1) El HTML servido lleva el contenido COMPLETO (requisito SEO: nada de
//    renderizado por JavaScript).
// 2) Metadatos completos: canonical, OG, JSON-LD Article, robots index.
// 3) El índice y el sitemap se regeneran leyendo la carpeta de artículos.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { loadArticles } from '../scripts/blog.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const BLOG_SRC = join(ROOT, 'content', 'blog')
const ORIGIN = 'https://solarvento.es'

const readPublic = (name) => readFileSync(join(ROOT, 'public', name), 'utf-8')
const ldBlocks = (html) =>
  [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) =>
    JSON.parse(m[1]),
  )

test('public/blog está sincronizado con content/blog (generador --check)', () => {
  execFileSync(process.execPath, [join(ROOT, 'scripts', 'generate-static-pages.mjs'), '--check'], {
    stdio: 'pipe',
  })
})

test('cada artículo lleva metadatos SEO completos y su contenido íntegro', () => {
  const sources = readdirSync(BLOG_SRC).filter((f) => f.endsWith('.html'))
  assert.ok(sources.length >= 1, 'no hay artículos en content/blog')
  for (const file of sources) {
    const slug = file.replace(/\.html$/, '')
    const html = readPublic(join('blog', `${slug}.html`))

    // Canonical exacto y robots indexable
    assert.match(html, new RegExp(`rel="canonical" href="${ORIGIN}/blog/${slug}\\.html"`))
    assert.match(html, /name="robots" content="index, follow/)

    // OG de artículo coherente con el canonical
    const canonical = html.match(/rel="canonical" href="([^"]+)"/)?.[1]
    assert.equal(html.match(/property="og:url" content="([^"]+)"/)?.[1], canonical)
    assert.match(html, /property="og:type" content="article"/)
    assert.match(html, /property="article:published_time" content="\d{4}-\d{2}-\d{2}"/)
    for (const prop of ['og:title', 'og:description', 'og:image']) {
      assert.match(html, new RegExp(`property="${prop}" content="[^"]+"`), `falta ${prop}`)
    }

    // JSON-LD Article + BreadcrumbList parseables
    const lds = ldBlocks(html)
    const article = lds.find((ld) => ld['@type'] === 'Article')
    assert.ok(article, `${slug}: falta JSON-LD Article`)
    assert.equal(article.mainEntityOfPage, `${ORIGIN}/blog/${slug}.html`)
    assert.ok(article.headline && article.datePublished, `${slug}: Article incompleto`)
    const crumbs = lds.find((ld) => ld['@type'] === 'BreadcrumbList')
    assert.ok(crumbs, `${slug}: falta BreadcrumbList`)
    assert.equal(crumbs.itemListElement.length, 3) // portada → blog → artículo

    // El contenido de la fuente viaja entero en el HTML servido (SEO crítico):
    // todos los párrafos del cuerpo deben estar en la página (la indentación
    // que añade el generador no cuenta: se compara con espacios normalizados).
    const src = readFileSync(join(BLOG_SRC, file), 'utf-8')
    const body = src.split(/^---$/m)[2] ?? ''
    const paragraphs = [...body.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/g)].map((m) => m[1])
    assert.ok(paragraphs.length > 0, `${slug}: la fuente no tiene párrafos`)
    const squash = (s) => s.replace(/\s+/g, ' ').trim()
    const servedText = squash(html)
    for (const p of paragraphs) {
      assert.ok(servedText.includes(squash(p)), `${slug}: falta contenido en el HTML servido`)
    }

    // Embudo: CTA hacia la calculadora y footer con las páginas del sitio
    assert.match(html, /class="cta-block"/)
    for (const target of ['/faq.html', '/ayudas.html', '/privacidad.html']) {
      assert.ok(html.includes(`href="${target}"`), `${slug}: falta enlace a ${target}`)
    }
  }
})

test('el tema día/noche sigue al sol de España, no al modo del sistema', () => {
  // Mismo criterio que la portada (App.jsx + SunArc.jsx): data-theme="night"
  // por ecuación solar en Europe/Madrid. Si el blog escuchara
  // prefers-color-scheme podría verse oscuro mientras la calculadora está en
  // claro (o al revés).
  const pages = ['index.html', ...readdirSync(BLOG_SRC).filter((f) => f.endsWith('.html'))]
  for (const page of pages) {
    const html = readPublic(join('blog', page))
    assert.ok(!html.includes('prefers-color-scheme'), `${page}: usa el modo del sistema`)
    assert.match(html, /\[data-theme='night'\]/, `${page}: falta la paleta de noche`)
    assert.match(html, /setAttribute\('data-theme', ?'night'\)/, `${page}: falta el cálculo solar`)
    for (const token of ['Europe/Madrid', '40.4168', '2451545']) {
      assert.ok(html.includes(token), `${page}: la ecuación solar no es la de la portada (${token})`)
    }
  }
})

test('el índice /blog/ lista todos los artículos con título, fecha y extracto', () => {
  const html = readPublic(join('blog', 'index.html'))
  assert.match(html, new RegExp(`rel="canonical" href="${ORIGIN}/blog/"`))
  assert.match(html, /name="robots" content="index, follow/)

  const lds = ldBlocks(html)
  assert.ok(lds.some((ld) => ld['@type'] === 'Blog'), 'falta JSON-LD Blog')

  for (const file of readdirSync(BLOG_SRC).filter((f) => f.endsWith('.html'))) {
    const slug = file.replace(/\.html$/, '')
    assert.ok(html.includes(`href="/blog/${slug}.html"`), `índice sin enlace a ${slug}`)
    const src = readFileSync(join(BLOG_SRC, file), 'utf-8')
    const excerpt = src.match(/^excerpt:\s*(.+)$/m)?.[1]?.trim()
    assert.ok(excerpt && html.includes(excerpt), `índice sin extracto de ${slug}`)
  }
})

test('loadArticles ordena por fecha descendente y deriva el slug del archivo', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  const write = (name, date) =>
    writeFileSync(
      join(dir, name),
      `---\ntitle: T ${name}\ndescription: d\nkeywords: k\ndate: ${date}\nexcerpt: e\n---\n<p>cuerpo</p>\n`,
    )
  write('viejo.html', '2026-01-10')
  write('nuevo.html', '2026-07-01')
  write('medio.html', '2026-03-15')
  const articles = loadArticles(dir)
  assert.deepEqual(
    articles.map((a) => a.slug),
    ['nuevo', 'medio', 'viejo'],
  )
  assert.equal(articles[0].title, 'T nuevo.html')
})

test('el sitemap incluye el índice del blog y cada artículo con su lastmod', () => {
  const xml = readPublic('sitemap.xml')
  assert.ok(xml.includes(`<loc>${ORIGIN}/blog/</loc>`), 'sitemap sin /blog/')
  for (const file of readdirSync(BLOG_SRC).filter((f) => f.endsWith('.html'))) {
    const slug = file.replace(/\.html$/, '')
    assert.ok(xml.includes(`<loc>${ORIGIN}/blog/${slug}.html</loc>`), `sitemap sin ${slug}`)
    const date = readFileSync(join(BLOG_SRC, file), 'utf-8').match(/^date:\s*(\S+)/m)?.[1]
    const entry = xml.split(`<loc>${ORIGIN}/blog/${slug}.html</loc>`)[1]?.split('</url>')[0] ?? ''
    assert.ok(entry.includes(`<lastmod>${date}</lastmod>`), `${slug}: lastmod ≠ date del artículo`)
  }
})
