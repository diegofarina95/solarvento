// Proxy inverso de solarvento.es -> funnel de la máquina de dev (/solvento).
// Mantiene la URL solarvento.es. La app está en base /solvento/ y Tailscale
// quita un /solvento; anteponemos /solvento a TODA petición para que los
// enlaces raíz del blog (/blog, /fonts, /faq.html) también resuelvan.
const FUNNEL = 'https://mockwebsite-diego.tailfc8d71.ts.net'
const FUNNEL_PREFIX = '/solvento'

export default {
  async fetch(request) {
    const url = new URL(request.url)
    const body = ['GET', 'HEAD'].includes(request.method)
      ? undefined
      : await request.arrayBuffer()
    const headers = new Headers(request.headers)
    headers.delete('host') // que fetch ponga el Host del destino (ts.net)
    const target = FUNNEL + FUNNEL_PREFIX + url.pathname + url.search
    return fetch(new Request(target, { method: request.method, headers, body, redirect: 'manual' }))
  },
}
