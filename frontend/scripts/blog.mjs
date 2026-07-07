// Blog estático de SolarVento (/blog). FUENTE ÚNICA: frontend/content/blog/,
// un archivo HTML por artículo con frontmatter delimitado por "---":
//
//   ---
//   title: Título SEO
//   description: meta-description
//   keywords: coma, separadas
//   date: 2026-07-07
//   excerpt: Extracto para la tarjeta del índice.
//   slug: url-para-seo  (opcional; si falta, el nombre del archivo)
//   lang: es            (opcional; preparado para PT futuro)
//   updated: 2026-07-08 (opcional; si no, date)
//   ---
//   <p>Cuerpo en HTML…</p>
//
// El slug público (URL, índice, sitemap) es el campo «slug» del frontmatter
// si existe; si no, el nombre del archivo. Para publicar: añadir el archivo y
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
  if (meta.slug && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(meta.slug))
    throw new Error(`${file}: slug inválido "${meta.slug}" (minúsculas, dígitos y guiones)`)
  return {
    slug: meta.slug || file.replace(/\.html$/, ''),
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
  const seen = new Map() // slug público → archivo (dos archivos, misma URL = error)
  const articles = files.map((f) => {
    const a = parseArticle(dir, f)
    if (seen.has(a.slug))
      throw new Error(`slug "${a.slug}" duplicado en ${seen.get(a.slug)} y ${f}`)
    seen.set(a.slug, f)
    return a
  })
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

// Cabecera y pie comunes: logo + wordmark como en la portada ("Vento" en
// ámbar), CTA a la calculadora y footer con el resto del sitio.
const SITE_HEADER = `      <header class="site">
        <a class="brand" href="/blog/">
          <b>Solar<span>Vento</span></b>
          <small>Blog</small>
        </a>
        <a class="cta" href="/">Calcular mi ahorro</a>
      </header>`

// La fuente de marca (titulares) se sirve autoalojada desde /fonts.
const FONT_PRELOAD =
  '    <link rel="preload" href="/fonts/bricolage-grotesque-latin-wght-normal.woff2" as="font" type="font/woff2" crossorigin />'

// Tema día/noche IGUAL que la portada: de noche cuando el sol se ha puesto en
// España (misma ecuación del amanecer que SunArc.jsx, Madrid, Europe/Madrid),
// NO según el modo claro/oscuro del sistema. Síncrono en el <head> para que no
// haya destello de tema equivocado; sin JS queda el tema claro (contenido y
// SEO intactos).
const THEME_SCRIPT = `    <script>
      (function () {
        var RAD = Math.PI / 180, TZ = 'Europe/Madrid', LAT = 40.4168, LON = -3.7038
        function hourInTZ(date) {
          var p = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(date)
          function v(t) { return Number(p.find(function (x) { return x.type === t }).value) }
          return v('hour') + v('minute') / 60
        }
        var now = new Date()
        var jd = now.getTime() / 86400000 + 2440587.5
        var n = Math.round(jd - 2451545.0 + 0.0008)
        var jStar = n + -LON / 360
        var M = (357.5291 + 0.98560028 * jStar) % 360
        var Mr = M * RAD
        var C = 1.9148 * Math.sin(Mr) + 0.02 * Math.sin(2 * Mr) + 0.0003 * Math.sin(3 * Mr)
        var lambda = ((M + C + 180 + 102.9372) % 360) * RAD
        var jTransit = 2451545.0 + jStar + 0.0053 * Math.sin(Mr) - 0.0069 * Math.sin(2 * lambda)
        var sinDec = Math.sin(lambda) * Math.sin(23.4397 * RAD)
        var cosDec = Math.cos(Math.asin(sinDec))
        var cosOmega = (Math.sin(-0.833 * RAD) - Math.sin(LAT * RAD) * sinDec) / (Math.cos(LAT * RAD) * cosDec)
        var omega = Math.acos(Math.min(1, Math.max(-1, cosOmega))) / RAD
        function jToDate(j) { return new Date((j - 2440587.5) * 86400000) }
        var sunrise = hourInTZ(jToDate(jTransit - omega / 360))
        var sunset = hourInTZ(jToDate(jTransit + omega / 360))
        var hour = hourInTZ(now)
        if (!(hour >= sunrise && hour < sunset)) document.documentElement.setAttribute('data-theme', 'night')
      })()
    </script>`

// Sin enlace a la calculadora: el cta-block del artículo y el CTA de la
// cabecera ya cubren ese camino; repetirlo en el footer era ruido.
const SITE_FOOTER = `      <footer>
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
    mainEntityOfPage: `${ORIGIN}/blog/${a.slug}/`,
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

// Embudo hacia la calculadora: todo artículo termina en un cta-block. Si el
// autor coloca el suyo (posición o texto propios), se respeta; si no, el
// template añade este estándar.
const DEFAULT_CTA = `<div class="cta-block">
  <p>¿Quieres saber cuánto ahorrarías con placas en tu tejado?</p>
  <a class="cta" href="/">Calcular mi ahorro</a>
</div>`

export function articlePage(a, css) {
  // URL limpia: /blog/<slug>/ (el fichero es blog/<slug>/index.html; el
  // backend sirve índices de directorio con StaticFiles html=True).
  const path = `blog/${a.slug}/`
  const bodyHtml = a.bodyHtml.includes('cta-block')
    ? a.bodyHtml
    : `${a.bodyHtml}\n${DEFAULT_CTA}`
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
${FONT_PRELOAD}
${THEME_SCRIPT}
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
${bodyHtml.replace(/^/gm, '        ')}
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
      url: `${ORIGIN}/blog/${a.slug}/`,
    })),
  }
  const crumbs = breadcrumbLd([
    ['SolarVento', `${ORIGIN}/`],
    ['Blog', `${ORIGIN}/blog/`],
  ])
  const cards = articles
    .map(
      (a) => `        <article class="card">
          <h2><a href="/blog/${a.slug}/">${a.title}</a></h2>
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
${FONT_PRELOAD}
${THEME_SCRIPT}
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
    lines.push(compact(`${ORIGIN}/blog/${a.slug}/`, a.updated, 'monthly', '0.6'))
  }
  return lines
}
