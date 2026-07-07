// Blog estático de SolarVento (/blog). FUENTE ÚNICA: frontend/content/blog/,
// un archivo HTML por artículo con frontmatter delimitado por "---":
//
//   ---
//   title: Título SEO
//   description: meta-description
//   keywords: coma, separadas
//   date: 2026-07-07
//   excerpt: Extracto para la tarjeta del índice.
//   lang: es            (opcional; preparado para PT futuro)
//   updated: 2026-07-08 (opcional; si no, date)
//   ---
//   <p>Cuerpo en HTML…</p>
//
// El slug es el nombre del archivo. Para publicar: añadir el archivo y
// regenerar (npm run generate); el índice y el sitemap se rehacen solos.
// Este módulo lo consume generate-static-pages.mjs, que aporta el modo
// --check anti-deriva y escribe en public/blog/.

import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const ORIGIN = 'https://solarvento.es'

const MONTHS_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]

function humanDate(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return `${d} de ${MONTHS_ES[m - 1]} de ${y}`
}

function parseArticle(dir, file) {
  const raw = readFileSync(join(dir, file), 'utf-8')
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/)
  if (!m) throw new Error(`${file}: falta el frontmatter delimitado por ---`)
  const meta = {}
  for (const line of m[1].split(/\r?\n/)) {
    if (!line.trim()) continue
    const kv = line.match(/^(\w+):\s*(.*)$/)
    if (!kv) throw new Error(`${file}: línea de frontmatter inválida: "${line}"`)
    meta[kv[1]] = kv[2].trim()
  }
  for (const key of ['title', 'description', 'keywords', 'date', 'excerpt']) {
    if (!meta[key]) throw new Error(`${file}: falta "${key}" en el frontmatter`)
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(meta.date)) throw new Error(`${file}: date debe ser AAAA-MM-DD`)
  return {
    slug: file.replace(/\.html$/, ''),
    title: meta.title,
    description: meta.description,
    keywords: meta.keywords,
    date: meta.date,
    updated: meta.updated || meta.date,
    excerpt: meta.excerpt,
    lang: meta.lang || 'es',
    bodyHtml: m[2].trim(),
  }
}

export function loadArticles(dir) {
  const files = readdirSync(dir).filter((f) => f.endsWith('.html'))
  const articles = files.map((f) => parseArticle(dir, f))
  articles.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.slug < b.slug ? -1 : 1))
  return articles
}

function indentCss(css) {
  return css
    .trimEnd()
    .split('\n')
    .map((line) => (line ? '      ' + line : ''))
    .join('\n')
}

// Cabecera y pie comunes: logo con "Vento" en ámbar, CTA a la calculadora y
// footer con el resto del sitio (mismos destinos que la app principal).
const SITE_HEADER = `      <header class="site">
        <a class="brand" href="/blog/">Solar<span>Vento</span> · Blog</a>
        <a class="cta" href="/">Calcular mi ahorro</a>
      </header>`

const SITE_FOOTER = `      <footer>
        <a href="/">Calculadora solar</a>
        <span> · </span>
        <a href="/blog/">Blog</a>
        <span> · </span>
        <a href="/faq.html">Preguntas frecuentes</a>
        <span> · </span>
        <a href="/ayudas.html">Ayudas por comunidad</a>
        <span> · </span>
        <a href="/privacidad.html">Privacidad</a>
        <p>SolarVento ofrece estimaciones orientativas basadas en datos oficiales; no sustituyen a un estudio técnico en tu tejado.</p>
      </footer>`

function socialBlock(path, title, description, extra = '') {
  return `    <meta property="og:type" content="${extra ? 'article' : 'website'}" />
    <meta property="og:site_name" content="SolarVento" />
    <meta property="og:locale" content="es_ES" />
    <meta property="og:url" content="${ORIGIN}/${path}" />
    <meta property="og:title" content="${title}" />
    <meta property="og:description" content="${description}" />
    <meta property="og:image" content="${ORIGIN}/og-image.png" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
${extra}    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="${title}" />
    <meta name="twitter:description" content="${description}" />
    <meta name="twitter:image" content="${ORIGIN}/og-image.png" />`
}

function articleLd(a) {
  return {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: a.title,
    description: a.description,
    datePublished: a.date,
    dateModified: a.updated,
    inLanguage: a.lang,
    mainEntityOfPage: `${ORIGIN}/blog/${a.slug}.html`,
    image: `${ORIGIN}/og-image.png`,
    author: { '@type': 'Organization', name: 'SolarVento', url: `${ORIGIN}/` },
    publisher: {
      '@type': 'Organization',
      name: 'SolarVento',
      url: `${ORIGIN}/`,
      logo: { '@type': 'ImageObject', url: `${ORIGIN}/logo-mark.png` },
    },
  }
}

function breadcrumbLd(items) {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map(([name, item], i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name,
      item,
    })),
  }
}

export function articlePage(a, css) {
  const path = `blog/${a.slug}.html`
  const published = `    <meta property="article:published_time" content="${a.date}" />
    <meta property="article:modified_time" content="${a.updated}" />
`
  const crumbs = breadcrumbLd([
    ['SolarVento', `${ORIGIN}/`],
    ['Blog', `${ORIGIN}/blog/`],
    [a.title, `${ORIGIN}/${path}`],
  ])
  return `<!doctype html>
<!-- GENERADO por frontend/scripts/generate-static-pages.mjs a partir de frontend/content/blog/ — NO EDITAR A MANO -->
<html lang="${a.lang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${a.title} | SolarVento</title>
    <meta name="description" content="${a.description}" />
    <meta name="keywords" content="${a.keywords}" />
    <meta name="robots" content="index, follow, max-image-preview:large" />
    <link rel="canonical" href="${ORIGIN}/${path}" />
${socialBlock(path, `${a.title} | SolarVento`, a.description, published)}
    <link rel="icon" href="/favicon.ico" sizes="any" />
    <style>
${indentCss(css)}
    </style>
    <script type="application/ld+json">
${JSON.stringify(articleLd(a), null, 2)}
    </script>
    <script type="application/ld+json">
${JSON.stringify(crumbs, null, 2)}
    </script>
  </head>
  <body>
    <main class="wrap">
${SITE_HEADER}
      <article>
        <h1>${a.title}</h1>
        <p class="meta"><time datetime="${a.date}">${humanDate(a.date)}</time></p>
${a.bodyHtml.replace(/^/gm, '        ')}
      </article>
${SITE_FOOTER}
    </main>
  </body>
</html>
`
}

export function blogIndexPage(articles, css) {
  const ld = {
    '@context': 'https://schema.org',
    '@type': 'Blog',
    name: 'Blog de SolarVento',
    url: `${ORIGIN}/blog/`,
    inLanguage: 'es',
    blogPost: articles.map((a) => ({
      '@type': 'BlogPosting',
      headline: a.title,
      datePublished: a.date,
      url: `${ORIGIN}/blog/${a.slug}.html`,
    })),
  }
  const crumbs = breadcrumbLd([
    ['SolarVento', `${ORIGIN}/`],
    ['Blog', `${ORIGIN}/blog/`],
  ])
  const cards = articles
    .map(
      (a) => `        <article class="card">
          <h2><a href="/blog/${a.slug}.html">${a.title}</a></h2>
          <p class="meta"><time datetime="${a.date}">${humanDate(a.date)}</time></p>
          <p class="excerpt">${a.excerpt}</p>
        </article>`,
    )
    .join('\n')
  const title = 'Blog de SolarVento: guías de autoconsumo solar'
  const description =
    'Guías prácticas sobre autoconsumo solar en España: facturas de la luz, placas, baterías, ayudas y amortización, del equipo de la calculadora SolarVento.'
  return `<!doctype html>
<!-- GENERADO por frontend/scripts/generate-static-pages.mjs a partir de frontend/content/blog/ — NO EDITAR A MANO -->
<html lang="es">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${title}</title>
    <meta name="description" content="${description}" />
    <meta name="robots" content="index, follow, max-image-preview:large" />
    <link rel="canonical" href="${ORIGIN}/blog/" />
${socialBlock('blog/', title, description)}
    <link rel="icon" href="/favicon.ico" sizes="any" />
    <style>
${indentCss(css)}
    </style>
    <script type="application/ld+json">
${JSON.stringify(ld, null, 2)}
    </script>
    <script type="application/ld+json">
${JSON.stringify(crumbs, null, 2)}
    </script>
  </head>
  <body>
    <main class="wrap">
${SITE_HEADER}
      <h1>Blog</h1>
      <p class="lead">
        Guías prácticas para entender tu factura, dimensionar una instalación de autoconsumo y
        no dejarte llevar por promesas comerciales. Sin humo: números y normativa española.
      </p>
      <div class="cards">
${cards}
      </div>
${SITE_FOOTER}
    </main>
  </body>
</html>
`
}

export function blogSitemapEntries(articles) {
  const compact = (loc, lastmod, changefreq, priority) =>
    `  <url><loc>${loc}</loc><lastmod>${lastmod}</lastmod><changefreq>${changefreq}</changefreq><priority>${priority}</priority></url>`
  const newest = articles.length ? articles[0].updated : null
  const lines = []
  if (newest) lines.push(compact(`${ORIGIN}/blog/`, newest, 'weekly', '0.8'))
  for (const a of articles) {
    lines.push(compact(`${ORIGIN}/blog/${a.slug}.html`, a.updated, 'monthly', '0.6'))
  }
  return lines
}
