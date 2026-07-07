# Categorías del blog — diseño (2026-07-07)

## Problema

Diego quiere que un campo `category` en el frontmatter aplique automáticamente
color y etiqueta de categoría en la página del artículo y en su card del
índice, sin tocar nada más, manteniendo la identidad ámbar como dominante.

## Decisiones (validadas con Diego)

- **Tres categorías exactas**: `guia` → «GUÍA», `analisis` → «ANÁLISIS»,
  `divulgacion` → «DIVULGACIÓN». Etiquetas idénticas en todos los idiomas.
- **Campo opcional, nunca rompe**: sin `category` o con valor no reconocido →
  estilo neutro (el render ámbar actual, sin etiqueta ni borde extra). El
  generador NO lanza error por categoría inválida.
- **Categoría = propiedad del grupo**: se lee del original español; `loadBlog`
  la propaga a las traducciones (su propio campo `category` se ignora). Editar
  un archivo actualiza las 5 versiones.
- **Sin flujo de edición en el portal** (decisión explícita): los artículos ya
  publicados se migran una vez, directamente en el repo, a `category: guia`.
  El borrador pendiente `horas-valle-luz-barata` NO se toca.
- **Colores fijados por Diego** (variables CSS):
  - Día: `--cat-guia: #f59e0b; --cat-analisis: #3f7f8f; --cat-divulgacion: #c2703d;`
  - Noche: `--cat-guia: #f0b95d; --cat-analisis: #6bb0be; --cat-divulgacion: #d99668;`
  - Aviso registrado: `#f59e0b` como texto sobre blanco ronda 2.2:1 de
    contraste; se implementa tal cual y se valida visualmente en ambos modos.

## Generador (`frontend/scripts/blog.mjs`)

- `export const CATEGORIES = { guia: 'GUÍA', analisis: 'ANÁLISIS', divulgacion: 'DIVULGACIÓN' }`.
- `parseArticle`: `category = (meta.category || '').trim().toLowerCase()`; si
  no está en `CATEGORIES`, queda `undefined`. Sin validación dura.
- `loadBlog`: tras agrupar, `g.tr[lang].category = g.es.category` para cada
  traducción presente.
- `articlePage(a, …)`: si `a.category`:
  - `<article class="cat-<key>">` (sin categoría: `<article>` como hoy).
  - Encima del `<h1>`: `<p class="eyebrow cat-label">GUÍA</p>`.
- `blogIndexPage`: card `<article class="card cat-<key>">` y la etiqueta junto
  a la fecha: `<p class="meta"><time …>…</time><span class="cat-label">GUÍA</span></p>`.
  Sin categoría: card idéntica a la actual.

## CSS (`frontend/content/styles/blog.css`)

Se engancha al mecanismo día/noche existente (script solar → `data-theme` en
`<html>`):

```css
:root {
  --cat-guia: #f59e0b;
  --cat-analisis: #3f7f8f;
  --cat-divulgacion: #c2703d;
}
:root[data-theme='night'] {
  --cat-guia: #f0b95d;
  --cat-analisis: #6bb0be;
  --cat-divulgacion: #d99668;
}
.cat-guia { --cat: var(--cat-guia); }
.cat-analisis { --cat: var(--cat-analisis); }
.cat-divulgacion { --cat: var(--cat-divulgacion); }
/* Punto del eyebrow y etiqueta en el color de la categoría (solo si hay --cat) */
article[class*='cat-'] .eyebrow::before {
  background: var(--cat);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cat) 18%, transparent);
}
.cat-label { color: var(--cat); }
/* Card del índice: borde izquierdo fino, fondo intacto */
.card[class*='cat-'] { border-left: 4px solid var(--cat); }
.card .cat-label { margin-left: .25rem; }
```

Notas:
- El punto de `.meta` (fecha) NO cambia: sigue el gradiente ámbar. Solo los
  `.eyebrow` dentro de un artículo categorizado y la etiqueta nueva toman el
  color.
- `color-mix` tiene soporte universal en navegadores actuales; si el test
  visual lo desaconseja, el halo puede fijarse por categoría sin variable.
- Neutro: al no existir la clase `cat-*`, ninguna regla nueva aplica.

## Migración única

Añadir `category: guia` al frontmatter de los 4 artículos ES publicados
(`como-leer-tu-factura-de-la-luz`, `que-electrodomesticos-gastan-mas`,
`coche-electrico-y-placas-solares`, `merecen-la-pena-placas-solares-espana`),
regenerar (mismo slug → misma URL, se reescriben en su sitio), commit y sync a
prod. Las traducciones publicadas heredan la categoría sin tocar sus archivos.

## Portal

Solo documentación: `FRONTMATTER_TEMPLATE` y la ayuda mencionan el campo
opcional `category: guia | analisis | divulgacion`.

## Tests

- `parseArticle`: categoría válida, ausente, inválida (→ neutro, sin error).
- `loadBlog`: la traducción hereda la categoría del es.
- Página de artículo: clase `cat-*`, etiqueta sobre el título; sin categoría,
  sin etiqueta ni clase.
- Índice: clase en la card y etiqueta junto a la fecha; neutra intacta.
- CSS: las 6 variables presentes (bloque día y bloque noche) en las páginas
  generadas.
- Verificación visual día y noche (captura o inspección de ambos temas).
- El check anti-deriva (`--check`) sigue en verde tras regenerar.
