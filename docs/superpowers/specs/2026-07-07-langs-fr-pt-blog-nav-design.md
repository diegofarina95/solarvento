# Idiomas: retirar FR/PT, blog consciente del idioma y selector en el blog — diseño (2026-07-07)

## Decisiones (pedidas por Diego; «acaba» = aprobado el conjunto)

1. **Retirar FR y PT de toda la web.** Quedan es/en/gl/ca/eu — exactamente los
   idiomas del blog. FR/PT nunca tuvieron blog; sus páginas estáticas
   (faq-fr/pt, privacidad-fr/pt) se retiran de la fuente, del sitemap, del
   hreflang y del selector. Un navegador en fr/pt cae al español (regla ya
   existente de `detectInitialLanguage`).
2. **El enlace «Blog» de la calculadora respeta el idioma activo**: UI en EN →
   `/blog/en/`; es → `/blog/` (mismo patrón que ya usa el enlace de
   privacidad en el footer de App.jsx).
3. **Selector de idioma en el blog** (nuevo): en índices y artículos, una nav
   como la de FAQ/privacidad (`.langs`): idioma actual sin enlace, resto
   enlazados. En un artículo enlaza a SUS versiones existentes (las del grupo
   hreflang); en un índice, a los índices de idiomas con artículos.

## Cambios por archivo

- `frontend/src/i18n/translations.js`: fuera fr/pt de `LANGUAGE_OPTIONS`,
  bloques `fr:`/`pt:` de `translations` y `sharedMonths.fr`. El selector de la
  calculadora (App.jsx:381 mapea LANGUAGE_OPTIONS) pierde los botones solo.
- `frontend/src/App.jsx`: enlace del blog →
  `` href={language === 'es' ? '/blog/' : `/blog/${language}/`} ``.
- `frontend/scripts/generate-static-pages.mjs`: `LANGS` → 5 idiomas; limpiar
  fr/pt de `OG_LOCALES`, `LANG_NAMES`, `LANG_NAV_LABEL`.
- Borrar `frontend/content/src/fr.json` y `pt.json`; `git rm` de
  `public/faq-fr.html`, `public/faq-pt.html`, `public/privacidad-fr.html`,
  `public/privacidad-pt.html` (el generador no borra huérfanos).
- `frontend/scripts/blog.mjs`: nav de idiomas. `STRINGS[lang].langLabel`
  (Idioma/Language/Idioma/Idioma/Hizkuntza) y `LANG_NAMES` local
  (Español/English/Català/Galego/Euskara). En `articlePage`: nav con las
  versiones del grupo (necesita el grupo → `blogOutputs` pasa la lista de
  versiones a `articlePage`); en `blogIndexPage`: nav con los índices de
  idiomas con artículos (la lista `langs` ya existe en `blogOutputs`). Un solo
  idioma → sin nav (igual que el hreflang).
- `frontend/content/styles/blog.css`: regla `.langs` (tamaño meta, color
  muted, idioma actual en strong) coherente día/noche.
- `frontend/tests/staticPages.test.mjs`: su `LANGS` propio → 5.
- `frontend/tests/i18n.test.mjs`: se adapta solo (itera `translations`).
- Backend: sin cambios (el aviso «factura no española» no depende de la UI).

## Riesgos/SEO

- Las URLs faq-fr/pt y privacidad-fr/pt pasarán a 404 en prod tras el próximo
  deploy completo: correcto (contenido retirado a propósito), salen también
  del sitemap y del hreflang en el mismo cambio.
- Los cambios de App/traducciones requieren **deploy completo** (bundle);
  las páginas del blog podrían ir por sync del portal, pero irán juntas en el
  deploy.

## Tests

- Blog: el índice lleva `.langs` con los idiomas con artículos (actual sin
  enlace); un artículo enlaza solo a sus versiones; grupo sin traducciones →
  sin nav; nav ausente de fr/pt.
- Páginas estáticas: hreflang y langNav con 5 idiomas exactos.
- i18n: paridad de claves (automático tras el borrado).
- App: build de Vite en verde (no hay test unitario del footer; el enlace se
  verifica en el HTML del bundle o manualmente).
