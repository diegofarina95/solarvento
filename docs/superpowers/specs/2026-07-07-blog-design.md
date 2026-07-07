# Blog de SolarVento en /blog — diseño

Fecha: 2026-07-07 · Estado: implementado en esta sesión

## Objetivo

Sección de blog en `/blog` (subdirectorio, no subdominio) con artículos servidos
como HTML estático real: Google recibe el contenido completo en la respuesta
del servidor, sin depender del bundle de React.

## Decisión clave: cero cambios de backend

FastAPI ya monta `StaticFiles(directory=frontend/dist, html=True)` en `/`
(main.py). Vite copia `frontend/public/` a `dist/` en el build. Por tanto:

- `frontend/public/blog/index.html` → se sirve en `/blog/` (y `/blog` redirige
  a `/blog/` automáticamente por `html=True`).
- `frontend/public/blog/<slug>.html` → se sirve en `/blog/<slug>.html`.

Es exactamente el mismo mecanismo que ya usan faq/privacidad/ayudas, que están
verificadas como indexables en producción.

## Fuente de contenido

- Carpeta versionable: `frontend/content/blog/`, un archivo por artículo.
- Formato: fragmento HTML con frontmatter delimitado por `---`:

  ```
  ---
  title: Título SEO (para <title> y og:title)
  description: meta-description
  keywords: coma, separadas
  date: 2026-07-07          # ISO; ordena el índice y alimenta lastmod/JSON-LD
  excerpt: Extracto para la tarjeta del índice.
  lang: es                  # preparado para PT futuro; hoy solo es
  ---
  <p>Cuerpo en HTML…</p>
  ```

- El slug es el nombre del archivo sin extensión; canonical
  `https://solarvento.es/blog/<slug>.html`.
- Para publicar un artículo nuevo: añadir el archivo y ejecutar
  `npm run generate` (o simplemente `npm run build`, que lo hace en prebuild).
  El índice y el sitemap se regeneran leyendo la carpeta.
- El frontmatter es el mismo que usaría un `.md`; si algún día se quiere
  Markdown, basta añadir un conversor en `blog.mjs` sin tocar plantillas.

## Generador

- `frontend/scripts/blog.mjs`: módulo con `loadArticles()`, `articlePage()`,
  `blogIndexPage()` y `blogSitemapEntries()`. Unidad testeable por separado.
- `generate-static-pages.mjs` lo importa y añade sus salidas al mismo mapa de
  outputs: el modo `--check` (guarda anti-deriva en CI/tests) cubre el blog
  sin trabajo extra.

## Plantilla de artículo

- Meta completos: title, description, keywords, robots `index, follow`,
  canonical, Open Graph (`og:type=article` + `article:published_time`),
  Twitter Card, favicon.
- JSON-LD `Article` (headline, description, datePublished, dateModified,
  inLanguage, author/publisher Organization SolarVento, mainEntityOfPage,
  image og-image) + `BreadcrumbList` (SolarVento → Blog → artículo).
- Identidad visual: fondo cálido stone `#fafaf9`, acentos ámbar
  (`#f59e0b`/enlaces `#b45309`), logo "Solar**Vento**" con Vento en ámbar,
  cuerpo serif + titulares sans, modo oscuro con `prefers-color-scheme`
  (como el resto de estáticas), foco de teclado visible (`:focus-visible`),
  responsive.
- Componentes reutilizables en `frontend/content/styles/blog.css` (inlinado
  por el generador, mismo patrón que faq.css/privacy.css): `.callout` (aviso
  ámbar), `.anatomy` (tarjeta de desglose), `.cta-block` (bloque hacia la
  calculadora), header con "Calcular mi ahorro", footer con
  calculadora/FAQ/ayudas/privacidad.

## Índice /blog/

- Lista los artículos de la carpeta ordenados por fecha descendente: título
  enlazado, fecha legible, extracto.
- JSON-LD `Blog` con los `BlogPosting` + breadcrumb. Canonical
  `https://solarvento.es/blog/`.

## Enlaces internos (embudo)

- Artículo → calculadora: header + `.cta-block` + footer.
- Web principal → blog: enlace "Blog" en el footer de la app React
  (clave i18n `app.blog` en los 7 idiomas) y en el footer de `ayudas.html`.

## Sitemap y robots

- `sitemap.xml` (ya generado por el mismo script) añade `/blog/` (weekly, 0.8)
  y cada artículo (monthly, 0.6) con `lastmod` de su frontmatter.
- `robots.txt` ya permite todo salvo `/api/`: nada que cambiar.

## Primer artículo

`como-leer-tu-factura-de-la-luz.html` — el artículo de referencia que citaba
la petición no está en esta máquina, así que se escribe de nuevo respetando
los elementos descritos: tarjeta de anatomía de factura, callouts, CTA y
footer estándar. Si aparece el original, basta sustituir el archivo fuente y
regenerar.

## Tests

`frontend/tests/blog.test.mjs`:
- Generador `--check` sin deriva (cubierto también por el test existente).
- Artículo: canonical correcto, JSON-LD Article parseable, OG completo,
  contenido íntegro en el HTML plano, CTA a `/`, robots index.
- Índice: lista el artículo, orden por fecha (unidad, con fixtures).
- Sitemap: incluye índice y artículos.

## Fuera de alcance (preparado, no implementado)

- i18n del blog (PT): el frontmatter ya lleva `lang`; faltaría decidir rutas
  (`/blog/pt/...`) y hreflang cuando llegue.
- Automatización de publicación: la carpeta + regeneración ya lo permiten.
