// Guardas del blog estático (/blog): fuente única en content/blog/*.html,
// salida en public/blog/. Mismo espíritu que staticPages.test.mjs:
// 1) El HTML servido lleva el contenido COMPLETO (requisito SEO: nada de
//    renderizado por JavaScript).
// 2) Metadatos completos: canonical, OG, JSON-LD Article, robots index.
// 3) El índice y el sitemap se regeneran leyendo la carpeta de artículos.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { articlePage, blogOutputs, blogSitemapEntries, loadArticles, loadBlog } from '../scripts/blog.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const BLOG_SRC = join(ROOT, 'content', 'blog')
const ORIGIN = 'https://solarvento.es'
const BLOG_LANGS = ['es', 'en', 'ca', 'gl', 'eu']

const readPublic = (name) => readFileSync(join(ROOT, 'public', name), 'utf-8')
// Slug público de un artículo fuente: campo «slug» del frontmatter o, si
// falta, el nombre del archivo (mismo contrato que scripts/blog.mjs).
const slugOf = (dir, file) => {
  const src = readFileSync(join(dir, file), 'utf-8')
  return src.match(/^slug:\s*(\S+)/m)?.[1] ?? file.replace(/\.html$/, '')
}
// Todas las fuentes del blog: es en la raíz, traducciones en subcarpetas.
const allSources = () => {
  const out = []
  for (const lang of BLOG_LANGS) {
    const dir = lang === 'es' ? BLOG_SRC : join(BLOG_SRC, lang)
    if (!existsSync(dir)) continue
    for (const file of readdirSync(dir).filter((f) => f.endsWith('.html'))) {
      out.push({ lang, dir, file, slug: slugOf(dir, file) })
    }
  }
  return out
}
const urlPath = (lang, slug) => (lang === 'es' ? `blog/${slug}/` : `blog/${lang}/${slug}/`)
const ldBlocks = (html) =>
  [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) =>
    JSON.parse(m[1]),
  )

test('public/blog está sincronizado con content/blog (generador --check)', () => {
  execFileSync(process.execPath, [join(ROOT, 'scripts', 'generate-static-pages.mjs'), '--check'], {
    stdio: 'pipe',
  })
})

test('cada artículo (todos los idiomas) lleva metadatos SEO completos y su contenido íntegro', () => {
  const sources = allSources()
  assert.ok(sources.length >= 1, 'no hay artículos en content/blog')
  for (const { lang, dir, file, slug } of sources) {
    const path = urlPath(lang, slug)
    const html = readPublic(join('blog', ...(lang === 'es' ? [slug] : [lang, slug]), 'index.html'))

    // Canonical exacto (URL limpia, sin .html), idioma y robots indexable
    assert.match(html, new RegExp(`rel="canonical" href="${ORIGIN}/${path}"`))
    assert.ok(html.includes(`<html lang="${lang}">`), `${path}: <html lang> incorrecto`)
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
    assert.equal(article.mainEntityOfPage, `${ORIGIN}/${path}`)
    assert.ok(article.headline && article.datePublished, `${slug}: Article incompleto`)
    const crumbs = lds.find((ld) => ld['@type'] === 'BreadcrumbList')
    assert.ok(crumbs, `${slug}: falta BreadcrumbList`)
    assert.equal(crumbs.itemListElement.length, 3) // portada → blog → artículo

    // El contenido de la fuente viaja entero en el HTML servido (SEO crítico):
    // todos los párrafos del cuerpo deben estar en la página (la indentación
    // que añade el generador no cuenta: se compara con espacios normalizados).
    const src = readFileSync(join(dir, file), 'utf-8')
    const body = src.split(/^---$/m)[2] ?? ''
    const paragraphs = [...body.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/g)].map((m) => m[1])
    assert.ok(paragraphs.length > 0, `${slug}: la fuente no tiene párrafos`)
    const squash = (s) => s.replace(/\s+/g, ' ').trim()
    const servedText = squash(html)
    for (const p of paragraphs) {
      assert.ok(servedText.includes(squash(p)), `${slug}: falta contenido en el HTML servido`)
    }

    // Embudo: CTA hacia la calculadora y footer con las páginas del sitio EN SU IDIOMA
    assert.match(html, /class="cta-block"/)
    const suffix = lang === 'es' ? '' : `-${lang}`
    for (const target of [`/faq${suffix}.html`, '/ayudas.html', `/privacidad${suffix}.html`]) {
      assert.ok(html.includes(`href="${target}"`), `${path}: falta enlace a ${target}`)
    }
  }
})

test('el tema día/noche sigue al sol de España, no al modo del sistema', () => {
  // Mismo criterio que la portada (App.jsx + SunArc.jsx): data-theme="night"
  // por ecuación solar en Europe/Madrid. Si el blog escuchara
  // prefers-color-scheme podría verse oscuro mientras la calculadora está en
  // claro (o al revés).
  const sources = allSources()
  const langsWithArticles = BLOG_LANGS.filter((l) => sources.some((s) => s.lang === l))
  const pages = [
    ...langsWithArticles.map((l) =>
      join('blog', ...(l === 'es' ? [] : [l]), 'index.html'),
    ),
    ...sources.map(({ lang, slug }) =>
      join('blog', ...(lang === 'es' ? [slug] : [lang, slug]), 'index.html'),
    ),
  ]
  for (const page of pages) {
    const html = readPublic(page)
    assert.ok(!html.includes('prefers-color-scheme'), `${page}: usa el modo del sistema`)
    assert.match(html, /\[data-theme='night'\]/, `${page}: falta la paleta de noche`)
    assert.match(html, /setAttribute\('data-theme', ?'night'\)/, `${page}: falta el cálculo solar`)
    for (const token of ['Europe/Madrid', '40.4168', '2451545']) {
      assert.ok(html.includes(token), `${page}: la ecuación solar no es la de la portada (${token})`)
    }
  }
})

test('cada idioma con artículos tiene su índice con enlaces y extractos', () => {
  const sources = allSources()
  for (const lang of BLOG_LANGS) {
    const ofLang = sources.filter((s) => s.lang === lang)
    if (!ofLang.length) continue
    const home = lang === 'es' ? 'blog/' : `blog/${lang}/`
    const html = readPublic(join('blog', ...(lang === 'es' ? [] : [lang]), 'index.html'))
    assert.match(html, new RegExp(`rel="canonical" href="${ORIGIN}/${home}"`))
    assert.match(html, /name="robots" content="index, follow/)
    assert.ok(html.includes(`<html lang="${lang}">`), `índice ${lang}: <html lang> incorrecto`)

    const lds = ldBlocks(html)
    assert.ok(lds.some((ld) => ld['@type'] === 'Blog'), `índice ${lang}: falta JSON-LD Blog`)

    for (const { dir, file, slug } of ofLang) {
      assert.ok(html.includes(`href="/${urlPath(lang, slug)}"`), `índice ${lang} sin enlace a ${slug}`)
      const src = readFileSync(join(dir, file), 'utf-8')
      const excerpt = src.match(/^excerpt:\s*(.+)$/m)?.[1]?.trim()
      assert.ok(excerpt && html.includes(excerpt), `índice ${lang} sin extracto de ${slug}`)
    }
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

const article = (extra) =>
  `---\ntitle: T\ndescription: d\nkeywords: k\ndate: 2026-07-07\nexcerpt: e\n${extra}---\n<p>x</p>\n`

test('el slug del frontmatter manda sobre el nombre del archivo', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'corto.html'), article('slug: url-descriptiva-para-seo\n'))
  const [a] = loadArticles(dir)
  assert.equal(a.slug, 'url-descriptiva-para-seo')
})

test('un slug inválido en el frontmatter se rechaza', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'a.html'), article('slug: Con Mayúsculas\n'))
  assert.throws(() => loadArticles(dir), /slug/)
})

test('el template añade el cta-block si el artículo no trae el suyo', () => {
  const base = {
    slug: 's', title: 't', description: 'd', keywords: 'k',
    date: '2026-07-07', updated: '2026-07-07', excerpt: 'e', lang: 'es',
  }
  // Sin cta propio: el template pone el estándar (el embudo nunca se pierde)
  const sin = articlePage({ ...base, bodyHtml: '<p>x</p>' }, '')
  assert.equal(sin.match(/class="cta-block"/g)?.length, 1)
  // Con cta propio: se respeta y no se duplica
  const con = articlePage(
    { ...base, bodyHtml: '<p>x</p><div class="cta-block"><a class="cta" href="/">Ir</a></div>' },
    '',
  )
  assert.equal(con.match(/class="cta-block"/g)?.length, 1)
})

test('dos artículos con el mismo slug público se rechazan', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'uno.html'), article('slug: repetido\n'))
  writeFileSync(join(dir, 'repetido.html'), article(''))
  assert.throws(() => loadArticles(dir), /repetido/)
})

test('el sitemap incluye los índices del blog y cada artículo (todos los idiomas)', () => {
  const xml = readPublic('sitemap.xml')
  assert.ok(xml.includes(`<loc>${ORIGIN}/blog/</loc>`), 'sitemap sin /blog/')
  for (const { lang, dir, file, slug } of allSources()) {
    const loc = `<loc>${ORIGIN}/${urlPath(lang, slug)}</loc>`
    assert.ok(xml.includes(loc), `sitemap sin ${lang}/${slug}`)
    if (lang !== 'es')
      assert.ok(xml.includes(`<loc>${ORIGIN}/blog/${lang}/</loc>`), `sitemap sin índice /blog/${lang}/`)
    const date = readFileSync(join(dir, file), 'utf-8').match(/^date:\s*(\S+)/m)?.[1]
    const entry = xml.split(loc)[1]?.split('</url>')[0] ?? ''
    assert.ok(entry.includes(`<lastmod>${date}</lastmod>`), `${lang}/${slug}: lastmod ≠ date`)
  }
})

// --- Multiidioma: agrupado, hreflang e índices ---

const FM = (extra) =>
  `---\ntitle: T\ndescription: d\nkeywords: k\ndate: 2026-07-07\nexcerpt: e\n${extra}---\n<p>x</p>\n`

function tmpBlog() {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'factura.html'), FM('slug: como-leer-la-factura\n'))
  mkdirSync(join(dir, 'en'))
  writeFileSync(join(dir, 'en', 'factura.html'), FM('slug: how-to-read-your-bill\nlang: en\n'))
  return dir
}

test('loadBlog agrupa el original con sus traducciones por nombre de archivo', () => {
  const groups = loadBlog(tmpBlog())
  const g = groups.get('factura')
  assert.equal(g.es.slug, 'como-leer-la-factura')
  assert.equal(g.tr.en.slug, 'how-to-read-your-bill')
})

test('una traducción huérfana o con lang equivocado se rechaza', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'a.html'), FM(''))
  mkdirSync(join(dir, 'en'))
  writeFileSync(join(dir, 'en', 'otro.html'), FM('lang: en\n'))
  assert.throws(() => loadBlog(dir), /huérfana/)

  const dir2 = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir2, 'a.html'), FM(''))
  mkdirSync(join(dir2, 'en'))
  writeFileSync(join(dir2, 'en', 'a.html'), FM('lang: ca\n'))
  assert.throws(() => loadBlog(dir2), /no coincide/)
})

test('blogOutputs emite páginas por idioma, hreflang recíproco e índices', () => {
  const out = blogOutputs(loadBlog(tmpBlog()), '')
  const es = out.get(join('como-leer-la-factura', 'index.html'))
  const en = out.get(join('en', 'how-to-read-your-bill', 'index.html'))
  assert.ok(es && en, 'faltan páginas de artículo')
  for (const html of [es, en]) {
    assert.ok(html.includes(`hreflang="es" href="${ORIGIN}/blog/como-leer-la-factura/"`))
    assert.ok(html.includes(`hreflang="en" href="${ORIGIN}/blog/en/how-to-read-your-bill/"`))
    assert.ok(html.includes(`hreflang="x-default" href="${ORIGIN}/blog/como-leer-la-factura/"`))
  }
  // Índices: /blog/ (es) y /blog/en/, enlazados por hreflang
  const idxEs = out.get('index.html')
  const idxEn = out.get(join('en', 'index.html'))
  assert.ok(idxEs.includes('href="/blog/como-leer-la-factura/"'))
  assert.ok(idxEn.includes('href="/blog/en/how-to-read-your-bill/"'))
  assert.ok(idxEn.includes('<html lang="en">'))
  assert.ok(idxEn.includes(`hreflang="es" href="${ORIGIN}/blog/"`))
  // La carcasa del artículo EN va traducida (CTA del template)
  assert.ok(en.includes('Calculate my savings'))
})

test('sin traducciones no se emite hreflang ni índices extra', () => {
  const dir = mkdtempSync(join(tmpdir(), 'blog-'))
  writeFileSync(join(dir, 'solo.html'), FM(''))
  const out = blogOutputs(loadBlog(dir), '')
  assert.equal([...out.keys()].length, 2) // artículo + índice es
  assert.ok(!out.get(join('solo', 'index.html')).includes('hreflang'))
})

test('el sitemap multiidioma lista índices y artículos de cada lengua', () => {
  const lines = blogSitemapEntries(loadBlog(tmpBlog())).join('\n')
  assert.ok(lines.includes(`<loc>${ORIGIN}/blog/</loc>`))
  assert.ok(lines.includes(`<loc>${ORIGIN}/blog/en/</loc>`))
  assert.ok(lines.includes(`<loc>${ORIGIN}/blog/como-leer-la-factura/</loc>`))
  assert.ok(lines.includes(`<loc>${ORIGIN}/blog/en/how-to-read-your-bill/</loc>`))
})

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
