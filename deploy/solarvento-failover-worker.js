/**
 * Cloudflare Worker — failover de solarvento.es
 *
 * Proxy inverso (NO redirect: la barra sigue mostrando solarvento.es) con
 * failover automático:
 *   1) intenta el ORIGEN PRIMARIO (el server de prod, cuando exista);
 *   2) si falla o da 5xx, sirve desde el FUNNEL de la máquina de dev.
 *
 * El funnel publica la app bajo el prefijo /solvento y Tailscale quita UN
 * /solvento antes de reenviar; por eso mapeamos solarvento.es/<path> ->
 * funnel/solvento/<path>. La app está compilada con base /solvento/, así que
 * los assets llegan como /solvento/assets/… y el doble prefijo lo absorbe el
 * middleware _strip_public_prefix del backend (verificado: 200).
 *
 * Despliegue (Cloudflare dashboard):
 *   Workers & Pages → Create → Worker → pega esto → Deploy.
 *   En el Worker: Settings → Triggers → Routes → añade:
 *       solarvento.es/*        (zona solarvento.es)
 *       www.solarvento.es/*    (si usas www)
 *   El registro DNS de solarvento.es puede seguir siendo el del túnel (muerto):
 *   la Route del Worker intercepta ANTES del origen, así que el túnel caído
 *   deja de importar.
 *
 * Cuando vuelva el server de prod: pon PRIMARY con un hostname propio que
 * apunte al túnel de prod (p. ej. prod.solarvento.es, proxied, SIN Worker) y
 * el Worker preferirá prod y solo caerá al funnel si prod falla.
 */

const FUNNEL = 'https://mockwebsite-diego.tailfc8d71.ts.net'
const FUNNEL_PREFIX = '/solvento'
// Vacío = servir siempre desde el funnel. Cuando prod vuelva, algo como
// 'https://prod.solarvento.es' para failover automático.
const PRIMARY = ''

export default {
  async fetch(request) {
    const url = new URL(request.url)
    // El cuerpo (subida de facturas) se lee una sola vez: lo bufferizamos para
    // poder reintentar en el fallback sin perderlo.
    const body = ['GET', 'HEAD'].includes(request.method)
      ? undefined
      : await request.arrayBuffer()

    const build = (base, prefix = '') => {
      const headers = new Headers(request.headers)
      headers.delete('host') // que fetch ponga el Host del destino (ts.net)
      return new Request(base + prefix + url.pathname + url.search, {
        method: request.method,
        headers,
        body,
        redirect: 'manual', // los redirects de la app llegan al navegador
      })
    }

    if (PRIMARY) {
      try {
        const primary = await fetch(build(PRIMARY))
        if (primary.status < 500) return primary // prod respondió: úsalo
      } catch (_) {
        /* prod inalcanzable → cae al funnel */
      }
    }
    return fetch(build(FUNNEL, FUNNEL_PREFIX))
  },
}
