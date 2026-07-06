// Cliente de la API del backend SolarVento.

// La app puede servirse bajo un prefijo (/solvento en producción). Las llamadas
// se hacen relativas a esa base; el funnel elimina el prefijo antes de llegar al
// backend, que expone las rutas en /api. En dev, BASE_URL es '/'.
const API_BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

export class ApiError extends Error {
  constructor(code, { detail = null, status = null, params = null } = {}) {
    super((typeof detail === 'string' ? detail : null) ?? code)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
    this.status = status
    this.params = params
  }
}

async function request(path, options) {
  let resp
  try {
    resp = await fetch(path, options)
  } catch {
    throw new ApiError('network')
  }
  if (!resp.ok) {
    let detail = null
    let code = 'generic'
    let params = null
    try {
      const body = await resp.json()
      if (typeof body.detail === 'string') {
        detail = body.detail
        if (body.detail.includes('Europa') || body.detail.includes('europeas')) code = 'europeOnly'
      } else if (body.detail && typeof body.detail === 'object' && typeof body.detail.code === 'string') {
        // Detalle TIPADO {code, params}: cortafuegos de sanidad, límite de subidas…
        code = body.detail.code
        params = body.detail.params ?? null
      } else if (Array.isArray(body.detail)) {
        code = 'invalidParameters'
      }
    } catch {
      /* cuerpo no JSON: se mantiene el mensaje genérico */
    }
    throw new ApiError(code, { detail, status: resp.status, params })
  }
  return resp.json()
}

export function apiErrorMessage(err, t) {
  if (err instanceof ApiError) {
    if (err.code === 'network') return t('errors.network')
    if (err.code === 'invalidParameters') return t('errors.invalidParameters')
    if (err.code === 'europeOnly') return t('errors.europeOnly')
    // Códigos tipados del cortafuegos de sanidad (estimateErrors.*): se traducen
    // con sus params. t() devuelve la clave si no existe → probamos y validamos.
    if (err.code) {
      const key = `estimateErrors.${err.code}`
      const msg = t(key, err.params || {})
      if (msg !== key) return msg
    }
    if (typeof err.detail === 'string' && err.detail) return err.detail
    return t('errors.generic')
  }
  return t('errors.generic')
}

export function geocode(query) {
  return request(`${API_BASE}/api/geocode?q=${encodeURIComponent(query)}`)
}

export function solarEstimate(params) {
  return request(`${API_BASE}/api/solar-estimate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
}

export function parseBill(file) {
  const form = new FormData()
  form.append('file', file)
  form.append('website', '')
  return request(`${API_BASE}/api/parse-bill`, { method: 'POST', body: form })
}

// Privacidad: borra en el servidor las facturas cacheadas de esta sesión de
// navegador. sendBeacon llega de forma fiable aunque la página se esté cerrando.
export function purgeBillSession() {
  navigator.sendBeacon(`${API_BASE}/api/bill-session/purge`)
}
