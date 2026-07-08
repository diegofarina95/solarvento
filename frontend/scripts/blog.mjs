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
//   lang: es            (es en content/blog/; en|ca|gl|eu en content/blog/<lang>/)
//   updated: 2026-07-08 (opcional; si no, date)
//   ---
//   <p>Cuerpo en HTML…</p>
//
// IDIOMAS: el original en español vive en content/blog/ y se sirve en
// /blog/<slug>/; las traducciones viven en content/blog/<lang>/<mismo-nombre>.html
// (las produce el portal con OpenAI) y se sirven en /blog/<lang>/<slug-traducido>/.
// El nombre de archivo agrupa las versiones de un mismo artículo; el hreflang
// enlaza el grupo y cada idioma con artículos tiene su índice /blog/<lang>/.
//
// El slug público (URL, índice, sitemap) es el campo «slug» del frontmatter
// si existe; si no, el nombre del archivo. Para publicar: añadir el archivo y
// regenerar (npm run generate); índices, hreflang y sitemap se rehacen solos.
// Este módulo lo consume generate-static-pages.mjs, que aporta el modo
// --check anti-deriva y escribe en public/blog/.

import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const ORIGIN = 'https://solarvento.es'

export const TRANSLATION_LANGS = ['en', 'ca', 'gl', 'eu']
export const BLOG_LANGS = ['es', ...TRANSLATION_LANGS]

// Categorías del blog: clave del frontmatter → etiqueta visible (idéntica en
// todos los idiomas). Valor no reconocido = sin categoría (render neutro).
export const CATEGORIES = { guia: 'GUÍA', analisis: 'ANÁLISIS', divulgacion: 'DIVULGACIÓN' }

// Cadenas de la carcasa del blog por idioma (el contenido llega ya traducido).
const STRINGS = {
  es: {
    locale: 'es_ES',
    blogLabel: 'Blog',
    blogName: 'Blog de SolarVento',
    cta: 'Calcular mi ahorro',
    ctaLead: '¿Quieres saber cuánto ahorrarías con placas en tu tejado?',
    indexTitle: 'Blog de SolarVento: guías de autoconsumo solar',
    indexDescription:
      'Guías prácticas sobre autoconsumo solar en España: facturas de la luz, placas, baterías, ayudas y amortización, del equipo de la calculadora SolarVento.',
    indexLead:
      'Guías prácticas para entender tu factura, dimensionar una instalación de autoconsumo y no dejarte llevar por promesas comerciales. Sin humo: números y normativa española.',
    faq: 'Preguntas frecuentes',
    ayudas: 'Ayudas por comunidad',
    privacidad: 'Privacidad',
    langLabel: 'Idioma',
    disclaimer:
      'SolarVento ofrece estimaciones orientativas basadas en datos oficiales; no sustituyen a un estudio técnico en tu tejado.',
  },
  en: {
    locale: 'en_US',
    blogLabel: 'Blog',
    blogName: 'SolarVento Blog',
    cta: 'Calculate my savings',
    ctaLead: 'Want to know how much you could save with solar panels on your roof?',
    indexTitle: 'SolarVento Blog: solar self-consumption guides',
    indexDescription:
      'Practical guides to solar self-consumption in Spain: electricity bills, panels, batteries, subsidies and payback, from the team behind the SolarVento calculator.',
    indexLead:
      'Practical guides to understand your electricity bill, size a self-consumption system and see through sales promises. No hot air: numbers and Spanish regulations.',
    faq: 'FAQ',
    ayudas: 'Subsidies by region',
    privacidad: 'Privacy',
    langLabel: 'Language',
    disclaimer:
      'SolarVento provides indicative estimates based on official data; they are no substitute for a technical survey of your roof.',
  },
  ca: {
    locale: 'ca_ES',
    blogLabel: 'Blog',
    blogName: 'Blog de SolarVento',
    cta: 'Calcular el meu estalvi',
    ctaLead: 'Vols saber quant estalviaries amb plaques al teu teulat?',
    indexTitle: "Blog de SolarVento: guies d'autoconsum solar",
    indexDescription:
      "Guies pràctiques sobre autoconsum solar a Espanya: factures de la llum, plaques, bateries, ajuts i amortització, de l'equip de la calculadora SolarVento.",
    indexLead:
      "Guies pràctiques per entendre la teva factura, dimensionar una instal·lació d'autoconsum i no deixar-te endur per promeses comercials. Sense fum: números i normativa espanyola.",
    faq: 'Preguntes freqüents',
    ayudas: 'Ajuts per comunitat',
    privacidad: 'Privacitat',
    langLabel: 'Idioma',
    disclaimer:
      'SolarVento ofereix estimacions orientatives basades en dades oficials; no substitueixen un estudi tècnic al teu teulat.',
  },
  gl: {
    locale: 'gl_ES',
    blogLabel: 'Blog',
    blogName: 'Blog de SolarVento',
    cta: 'Calcular o meu aforro',
    ctaLead: 'Queres saber canto aforrarías con placas no teu tellado?',
    indexTitle: 'Blog de SolarVento: guías de autoconsumo solar',
    indexDescription:
      'Guías prácticas sobre autoconsumo solar en España: facturas da luz, placas, baterías, axudas e amortización, do equipo da calculadora SolarVento.',
    indexLead:
      'Guías prácticas para entender a túa factura, dimensionar unha instalación de autoconsumo e non te deixar levar por promesas comerciais. Sen fume: números e normativa española.',
    faq: 'Preguntas frecuentes',
    ayudas: 'Axudas por comunidade',
    privacidad: 'Privacidade',
    langLabel: 'Idioma',
    disclaimer:
      'SolarVento ofrece estimacións orientativas baseadas en datos oficiais; non substitúen un estudo técnico no teu tellado.',
  },
  eu: {
    locale: 'eu_ES',
    blogLabel: 'Bloga',
    blogName: 'SolarVento bloga',
    cta: 'Nire aurrezpena kalkulatu',
    ctaLead: 'Jakin nahi duzu zenbat aurreztuko zenukeen zure teilatuan plakak jarrita?',
    indexTitle: 'SolarVento bloga: eguzki-autokontsumorako gidak',
    indexDescription:
      'Eguzki-autokontsumoari buruzko gida praktikoak Espainian: argindar-fakturak, plakak, bateriak, laguntzak eta amortizazioa, SolarVento kalkulagailuaren taldearen eskutik.',
    indexLead:
      'Gida praktikoak zure faktura ulertzeko, autokontsumo-instalazio bat dimentsionatzeko eta promesa komertzialek ez engainatzeko. Kerik gabe: zenbakiak eta Espainiako araudia.',
    faq: 'Ohiko galderak',
    ayudas: 'Laguntzak erkidegoka',
    privacidad: 'Pribatutasuna',
    langLabel: 'Hizkuntza',
    disclaimer:
      'SolarVentok datu ofizialetan oinarritutako gutxi gorabeherako estimazioak eskaintzen ditu; ez dute zure teilatuko azterketa tekniko bat ordezkatzen.',
  },
}

const MONTHS = {
  es: ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'],
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
  ca: ['gener', 'febrer', 'març', 'abril', 'maig', 'juny', 'juliol', 'agost', 'setembre', 'octubre', 'novembre', 'desembre'],
  gl: ['xaneiro', 'febreiro', 'marzo', 'abril', 'maio', 'xuño', 'xullo', 'agosto', 'setembro', 'outubro', 'novembro', 'decembro'],
  // Euskera: genitivo (uztailaren 7a = «el 7 de julio»)
  eu: ['urtarrilaren', 'otsailaren', 'martxoaren', 'apirilaren', 'maiatzaren', 'ekainaren', 'uztailaren', 'abuztuaren', 'irailaren', 'urriaren', 'azaroaren', 'abenduaren'],
}

function humanDate(iso, lang = 'es') {
  const [y, m, d] = iso.split('-').map(Number)
  const month = MONTHS[lang][m - 1]
  if (lang === 'en') return `${d} ${month} ${y}`
  if (lang === 'eu') return `${y}ko ${month} ${d}a`
  if (lang === 'ca') return `${d} ${/^[aeiou]/.test(month) ? "d'" : 'de '}${month} de ${y}`
  return `${d} de ${month} de ${y}`
}

// URL pública de un artículo: el español vive en la raíz del blog.
export function articleUrl(a) {
  return a.lang === 'es' ? `blog/${a.slug}/` : `blog/${a.lang}/${a.slug}/`
}

function blogHome(lang) {
  return lang === 'es' ? 'blog/' : `blog/${lang}/`
}

// Nombres de idioma para el selector visible (mismos que las páginas estáticas).
const LANG_NAMES = { es: 'Español', en: 'English', ca: 'Català', gl: 'Galego', eu: 'Euskara' }

// Nav de idiomas: versión actual sin enlace, resto enlazadas (complementa el
// hreflang del <head> con enlaces visibles y rastreables). Con una sola
// versión no se emite, igual que el hreflang.
function langNav(current, versions) {
  if (versions.length < 2) return ''
  const items = versions.map(([lang, href]) =>
    lang === current
      ? `<strong>${LANG_NAMES[lang]}</strong>`
      : `<a href="${href}" hreflang="${lang}" lang="${lang}">${LANG_NAMES[lang]}</a>`,
  )
  return `      <nav class="langs" aria-label="${STRINGS[current].langLabel}">${items.join(' · ')}</nav>\n`
}

// Páginas estáticas del sitio por idioma (mismo esquema que generate-static-pages).
function sitePage(base, lang) {
  return lang === 'es' ? `/${base}.html` : `/${base}-${lang}.html`
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
    stem: file.replace(/\.html$/, ''),
    slug: meta.slug || file.replace(/\.html$/, ''),
    title: meta.title,
    description: meta.description,
    keywords: meta.keywords,
    date: meta.date,
    updated: meta.updated || meta.date,
    excerpt: meta.excerpt,
    lang: meta.lang || 'es',
    category: CATEGORIES[(meta.category || '').trim().toLowerCase()]
      ? (meta.category || '').trim().toLowerCase()
      : undefined,
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

// Carga el blog completo agrupado por artículo: el original es en la raíz y
// sus traducciones en content/blog/<lang>/<mismo-nombre>.html. Devuelve un
// Map stem → { es, tr: {en?, ca?, gl?, eu?} } y valida la coherencia.
export function loadBlog(dir) {
  const es = loadArticles(dir)
  for (const a of es) {
    if (a.lang !== 'es')
      throw new Error(
        `${a.stem}.html: lang "${a.lang}" en content/blog/ (las traducciones van en content/blog/${a.lang}/)`,
      )
    if (TRANSLATION_LANGS.includes(a.slug) || a.slug === 'index')
      throw new Error(`${a.stem}.html: slug "${a.slug}" reservado (colisiona con /blog/${a.slug}/)`)
  }
  const groups = new Map(es.map((a) => [a.stem, { es: a, tr: {} }]))
  for (const lang of TRANSLATION_LANGS) {
    const sub = join(dir, lang)
    if (!existsSync(sub)) continue
    for (const a of loadArticles(sub)) {
      if (a.lang !== lang)
        throw new Error(`${lang}/${a.stem}.html: lang "${a.lang}" no coincide con la carpeta "${lang}"`)
      if (a.slug === 'index')
        throw new Error(`${lang}/${a.stem}.html: slug "index" reservado`)
      const g = groups.get(a.stem)
      if (!g)
        throw new Error(
          `${lang}/${a.stem}.html: traducción huérfana, no existe content/blog/${a.stem}.html`,
        )
      g.tr[lang] = a
      a.category = g.es.category // la categoría es del grupo: manda el original
    }
  }
  return groups
}

function indentCss(css) {
  return css
    .trimEnd()
    .split('\n')
    .map((line) => (line ? '      ' + line : ''))
    .join('\n')
}

// Cabecera y pie comunes por idioma: wordmark como en la portada ("Vento" en
// ámbar), CTA a la calculadora y footer con el resto del sitio en su idioma.
function siteHeader(lang) {
  const s = STRINGS[lang]
  return `      <header class="site">
        <a class="brand" href="/${blogHome(lang)}">
          <b>Solar<span>Vento</span></b>
          <small>${s.blogLabel}</small>
        </a>
        <a class="cta" href="/">${s.cta}</a>
      </header>`
}

function siteFooter(lang) {
  const s = STRINGS[lang]
  return `      <footer>
        <a href="/${blogHome(lang)}">${s.blogLabel}</a>
        <span> · </span>
        <a href="${sitePage('faq', lang)}">${s.faq}</a>
        <span> · </span>
        <a href="/ayudas.html">${s.ayudas}</a>
        <span> · </span>
        <a href="${sitePage('privacidad', lang)}">${s.privacidad}</a>
        <p>${s.disclaimer}</p>
      </footer>`
}

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

function socialBlock(path, title, description, locale, extra = '') {
  return `    <meta property="og:type" content="${extra ? 'article' : 'website'}" />
    <meta property="og:site_name" content="SolarVento" />
    <meta property="og:locale" content="${locale}" />
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

// hreflang del grupo de un artículo: original + traducciones disponibles.
// Solo se emite cuando hay al menos una traducción; x-default = español.
function hreflangBlock(group) {
  const versions = [group.es, ...TRANSLATION_LANGS.map((l) => group.tr[l]).filter(Boolean)]
  if (versions.length < 2) return ''
  const lines = versions.map(
    (a) => `    <link rel="alternate" hreflang="${a.lang}" href="${ORIGIN}/${articleUrl(a)}" />`,
  )
  lines.push(`    <link rel="alternate" hreflang="x-default" href="${ORIGIN}/${articleUrl(group.es)}" />`)
  return lines.join('\n') + '\n'
}

// hreflang entre los índices /blog/, /blog/en/… (solo idiomas con artículos).
function indexHreflang(langs) {
  if (langs.length < 2) return ''
  const lines = langs.map(
    (l) => `    <link rel="alternate" hreflang="${l}" href="${ORIGIN}/${blogHome(l)}" />`,
  )
  lines.push(`    <link rel="alternate" hreflang="x-default" href="${ORIGIN}/${blogHome('es')}" />`)
  return lines.join('\n') + '\n'
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
    mainEntityOfPage: `${ORIGIN}/${articleUrl(a)}`,
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
// template añade el estándar en el idioma del artículo.
function defaultCta(lang) {
  const s = STRINGS[lang]
  return `<div class="cta-block">
  <p>${s.ctaLead}</p>
  <a class="cta" href="/">${s.cta}</a>
</div>`
}

export function articlePage(a, css, hreflang = '', versions = []) {
  // URL limpia: /blog/[lang/]<slug>/ (el fichero es …/<slug>/index.html; el
  // backend sirve índices de directorio con StaticFiles html=True).
  const path = articleUrl(a)
  const s = STRINGS[a.lang]
  const bodyHtml = a.bodyHtml.includes('cta-block')
    ? a.bodyHtml
    : `${a.bodyHtml}\n${defaultCta(a.lang)}`
  const published = `    <meta property="article:published_time" content="${a.date}" />
    <meta property="article:modified_time" content="${a.updated}" />
`
  const crumbs = breadcrumbLd([
    ['SolarVento', `${ORIGIN}/`],
    [s.blogLabel, `${ORIGIN}/${blogHome(a.lang)}`],
    [a.title, `${ORIGIN}/${path}`],
  ])
  const catClass = a.category ? ` class="cat-${a.category}"` : ''
  const catLabel = a.category
    ? `        <p class="eyebrow cat-label">${CATEGORIES[a.category]}</p>\n`
    : ''
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
${hreflang}${socialBlock(path, `${a.title} | SolarVento`, a.description, s.locale, published)}
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
${siteHeader(a.lang)}
${langNav(a.lang, versions)}      <article${catClass}>
${catLabel}        <h1>${a.title}</h1>
        <p class="meta"><time datetime="${a.date}">${humanDate(a.date, a.lang)}</time></p>
${bodyHtml.replace(/^/gm, '        ')}
      </article>
${siteFooter(a.lang)}
    </main>
  </body>
</html>
`
}

export function blogIndexPage(articles, css, lang = 'es', hreflang = '', indexLangs = []) {
  const s = STRINGS[lang]
  const home = blogHome(lang)
  const ld = {
    '@context': 'https://schema.org',
    '@type': 'Blog',
    name: s.blogName,
    url: `${ORIGIN}/${home}`,
    inLanguage: lang,
    blogPost: articles.map((a) => ({
      '@type': 'BlogPosting',
      headline: a.title,
      datePublished: a.date,
      url: `${ORIGIN}/${articleUrl(a)}`,
    })),
  }
  const crumbs = breadcrumbLd([
    ['SolarVento', `${ORIGIN}/`],
    [s.blogLabel, `${ORIGIN}/${home}`],
  ])
  const cards = articles
    .map(
      (a) => `        <article class="card${a.category ? ` cat-${a.category}` : ''}">
          <h2><a href="/${articleUrl(a)}">${a.title}</a></h2>
          <p class="meta"><time datetime="${a.date}">${humanDate(a.date, lang)}</time>${
            a.category ? `<span class="cat-label">${CATEGORIES[a.category]}</span>` : ''
          }</p>
          <p class="excerpt">${a.excerpt}</p>
        </article>`,
    )
    .join('\n')
  return `<!doctype html>
<!-- GENERADO por frontend/scripts/generate-static-pages.mjs a partir de frontend/content/blog/ — NO EDITAR A MANO -->
<html lang="${lang}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${s.indexTitle}</title>
    <meta name="description" content="${s.indexDescription}" />
    <meta name="robots" content="index, follow, max-image-preview:large" />
    <link rel="canonical" href="${ORIGIN}/${home}" />
${hreflang}${socialBlock(home, s.indexTitle, s.indexDescription, s.locale)}
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
${siteHeader(lang)}
${langNav(lang, indexLangs.map((l) => [l, `/${blogHome(l)}`]))}      <h1>${s.blogLabel}</h1>
      <p class="lead">
        ${s.indexLead}
      </p>
      <div class="cards">
${cards}
      </div>
${siteFooter(lang)}
    </main>
  </body>
</html>
`
}

// Todas las páginas del blog (artículos en todos los idiomas + índices por
// idioma), como rutas relativas a public/blog/. Fuente única para el generador.
export function blogOutputs(groups, css) {
  const out = new Map()
  const gs = [...groups.values()]
  const byLang = new Map(BLOG_LANGS.map((l) => [l, []]))
  for (const g of gs) {
    byLang.get('es').push(g.es)
    for (const l of TRANSLATION_LANGS) if (g.tr[l]) byLang.get(l).push(g.tr[l])
  }
  for (const g of gs) {
    const hb = hreflangBlock(g)
    const versions = [g.es, ...TRANSLATION_LANGS.map((l) => g.tr[l]).filter(Boolean)].map(
      (v) => [v.lang, `/${articleUrl(v)}`],
    )
    out.set(join(g.es.slug, 'index.html'), articlePage(g.es, css, hb, versions))
    for (const l of TRANSLATION_LANGS)
      if (g.tr[l])
        out.set(join(l, g.tr[l].slug, 'index.html'), articlePage(g.tr[l], css, hb, versions))
  }
  const langs = BLOG_LANGS.filter((l) => byLang.get(l).length > 0)
  const idxAlt = indexHreflang(langs)
  const byDate = (arr) =>
    [...arr].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.slug < b.slug ? -1 : 1))
  for (const l of langs) {
    const page = blogIndexPage(byDate(byLang.get(l)), css, l, idxAlt, langs)
    out.set(l === 'es' ? 'index.html' : join(l, 'index.html'), page)
  }
  return out
}

export function blogSitemapEntries(groups) {
  const compact = (loc, lastmod, changefreq, priority) =>
    `  <url><loc>${loc}</loc><lastmod>${lastmod}</lastmod><changefreq>${changefreq}</changefreq><priority>${priority}</priority></url>`
  const gs = [...groups.values()]
  const lines = []
  for (const l of BLOG_LANGS) {
    const arts = gs.map((g) => (l === 'es' ? g.es : g.tr[l])).filter(Boolean)
    if (!arts.length) continue
    const newest = arts.map((a) => a.updated).sort().at(-1)
    lines.push(compact(`${ORIGIN}/${blogHome(l)}`, newest, 'weekly', '0.8'))
  }
  for (const g of gs) {
    for (const a of [g.es, ...TRANSLATION_LANGS.map((l) => g.tr[l]).filter(Boolean)]) {
      lines.push(compact(`${ORIGIN}/${articleUrl(a)}`, a.updated, 'monthly', '0.6'))
    }
  }
  return lines
}
