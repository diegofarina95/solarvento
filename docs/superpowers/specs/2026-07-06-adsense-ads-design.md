# Anuncios AdSense discretos — diseño

**Fecha:** 2026-07-06
**Estado:** aprobado para planificar
**Ámbito:** frontend (React/Vite) + assets estáticos + configuración de build/deploy. Sin cambios de backend.

## Objetivo

Monetizar SolarVento con anuncios **poco intrusivos** ("en un ladito"), reutilizando el andamiaje AdSense que ya existe (`frontend/src/components/AdSlot.jsx`), cumpliendo el RGPD (consentimiento de cookies) y los requisitos de aprobación de Google AdSense.

## Decisiones (tomadas con el usuario)

1. **Red:** Google AdSense.
2. **Colocación:** hueco **lateral** nuevo + reactivar los huecos ya cableados **top** y **footer**.
   - En móvil el lateral no aparece; quedan top/footer (que sí caben) → el móvil también monetiza.
3. **Estilo del lateral:** "rascacielos" en el **margen derecho vacío**, visible solo en pantallas anchas (≈≥1400px). **No** modifica el layout actual (no estrecha `resultados`); si no hay hueco, no se muestra.
4. **Consentimiento:** **CMP integrado de Google** (mensaje RGPD configurado en el panel de AdSense) + *default* de **Consent Mode v2** en código.

## Estado de partida (ya existe)

- `AdSlot.jsx`: no renderiza nada salvo que en build exista `VITE_ADSENSE_CLIENT` y el slot correspondiente. Inyecta `adsbygoogle.js` de forma diferida; tolera adblockers.
- `App.jsx` usa `<AdSlot placement="top" />` (tras el header) y `<AdSlot placement="footer" />` (bajo resultados). El placement `results` está previsto pero sin usar.
- Layout: shell `mx-auto max-w-6xl px-4 py-8` → header → `grid gap-8 lg:grid-cols-[380px_1fr]` (form 380px + resultados 1fr).
- **No** hay: hueco lateral, banner de consentimiento, política de privacidad, footer con enlaces, `ads.txt`.

## Arquitectura / componentes

### 1. `AdSlot` — nuevo placement `side`
- Añadir `side` a `SLOTS` (`VITE_ADSENSE_SLOT_SIDE`).
- El contenedor del lateral: `position: fixed`, anclado al **borde derecho** con un offset vertical (queda a la vista al hacer scroll, comportamiento "rascacielos"), ancho ~160px, dentro del margen vacío a la derecha del shell `max-w-6xl`. Visible **solo** con media-query ≥1400px (si no, `display:none`). `print:hidden`, `aria-hidden`. No ocupa espacio en el flujo → no altera el grid actual.
- Mantener el contrato actual: si `!enabled` → `return null`.
- Etiqueta discreta **"Publicidad"** encima del `<ins>` (requisito de AdSense de distinguir anuncio de contenido). Traducida (i18n).

### 2. Reactivar `top` y `footer`
- Sin cambios de cableado; solo requieren las variables de build.
- Añadir la misma etiqueta "Publicidad" i18n.

### 3. Consentimiento (RGPD) — CMP de Google
- La mayor parte es **configuración en el panel de AdSense** (Privacy & messaging → mensaje RGPD, idiomas, textos).
- En código:
  - Garantizar que `adsbygoogle.js` cargue al inicio (el `AdSlot top` ya monta en el primer render → cubierto).
  - Añadir el **default de Consent Mode v2** antes de cargar anuncios: denegar `ad_storage`/`ad_user_data`/`ad_personalization`/`analytics_storage` por defecto; el CMP de Google actualiza el estado al aceptar. Snippet mínimo (`gtag('consent','default',{...})`) inyectado junto al script de ads.
- No se construye banner propio ni almacén de consentimientos (lo registra Google).

### 4. Requisitos de aprobación de AdSense
- **Política de privacidad:** `frontend/public/privacidad.html` (ES; opcional EN) declarando uso de cookies y anuncios de terceros (Google) y cómo revocar consentimiento. Servida en `/solvento/privacidad.html`.
- **Footer nuevo** (mínimo) en `App.jsx`: enlace a la política de privacidad + aviso de cookies + copyright. `print:hidden`.
- **`ads.txt`:** `frontend/public/ads.txt` con `google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, f08c47fec0942fa0` (rellenar el pub id real). Servido en `/solvento/ads.txt`.
  - Nota: verificar que el backend/StaticFiles sirva `ads.txt` en la ruta que AdSense espera; si AdSense exige la **raíz del dominio** (`/ads.txt`) y la app vive en `/solvento/`, habrá que servirlo también en la raíz (config de proxy/servidor) — anotar como riesgo a validar.

### 5. Build / deploy
- Variables de build del frontend: `VITE_ADSENSE_CLIENT`, `VITE_ADSENSE_SLOT_TOP`, `VITE_ADSENSE_SLOT_SIDE`, `VITE_ADSENSE_SLOT_FOOTER`.
- Ubicación: `frontend/.env.production` (excluido de git; añadir a `.gitignore` y a las exclusiones de `rsync`/deploy). Documentar en `deploy-server-setup`.
- Sin variables → comportamiento idéntico a hoy (nada de anuncios). Activación = definir variables + rebuild.

## i18n
- Nuevas claves: etiqueta `ads.label` ("Publicidad"), textos del footer (`footer.privacy`, `footer.cookies`, `footer.copyright`) en los 7 idiomas (es/gl/ca/eu/en/fr/pt). El test de paridad de claves (`i18n.test.mjs`) debe seguir pasando.

## Flujo de datos
1. Carga la página → monta `AdSlot top` → inyecta `adsbygoogle.js` + default de Consent Mode (todo denegado).
2. El CMP de Google muestra el mensaje RGPD → usuario acepta/rechaza → Google actualiza el estado de consentimiento.
3. Según consentimiento, AdSense sirve anuncios personalizados / no personalizados en top, footer y (si la pantalla es ancha) side.

## Errores / casos límite
- **Adblocker:** el `push` va en try/catch (ya existe) → silencioso.
- **Sin hueco lateral (pantalla estrecha):** el lateral no se renderiza; nunca solapa contenido (política de AdSense).
- **Sin consentimiento:** anuncios no personalizados o ninguno, según config del panel; sin cookies de ads.
- **Sin variables de build:** `null` en todos los huecos.
- **Impresión/PDF:** todos los huecos `print:hidden` (el informe PDF ya existe y no debe llevar anuncios).

## Pruebas
- Lógica pura testeable con `node --test` (sin DOM): p.ej. un helper que decida `enabled`/slot a partir de env — extraer si hace falta.
- Componente React (`AdSlot`): verificación manual con un flag de debug que pinte un placeholder visible en cada hueco (top/side/footer) en dev, comprobando que el lateral solo aparece en pantalla ancha y no toca el contenido.
- `i18n.test.mjs` sigue verde (paridad de claves con las nuevas entradas).
- Gate de deploy (`scripts/deploy.sh`): build del frontend con las variables no debe romper.

## Fuera de ámbito (YAGNI)
- Router SPA, CMP de pago, base de datos de consentimientos, anuncios en el PDF, formatos de anuncio avanzados (in-feed/in-article).

## Riesgos / pendientes del usuario (no-código)
- Cuenta de **AdSense aprobada** (revisan el sitio; puede tardar y requiere contenido + política de privacidad + tráfico).
- Rellenar el **pub id** real en `ads.txt` y las variables de build.
- Validar la ruta de `ads.txt` (raíz del dominio vs `/solvento/`).
- Recordatorio pendiente del proyecto: rotar la contraseña SSH / pasar a clave (no relacionado, pero abierto).
