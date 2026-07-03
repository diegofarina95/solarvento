// Cliente de la API del backend SolVento.

// La app puede servirse bajo un prefijo (/solvento en producción). Las llamadas
// se hacen relativas a esa base; el funnel elimina el prefijo antes de llegar al
// backend, que expone las rutas en /api. En dev, BASE_URL es '/'.
const API_BASE = import.meta.env.BASE_URL.replace(/\/$/, '')

export class ApiError extends Error {
  constructor(code, { detail = null, status = null } = {}) {
    super(detail ?? code)
    this.name = 'ApiError'
    this.code = code
    this.detail = detail
    this.status = status
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
    try {
      const body = await resp.json()
      if (typeof body.detail === 'string') {
        detail = body.detail
        if (body.detail.includes('Europa') || body.detail.includes('europeas')) code = 'europeOnly'
      } else if (Array.isArray(body.detail)) {
        code = 'invalidParameters'
      }
    } catch {
      /* cuerpo no JSON: se mantiene el mensaje genérico */
    }
    throw new ApiError(code, { detail, status: resp.status })
  }
  return resp.json()
}

export function apiErrorMessage(err, t) {
  if (err instanceof ApiError) {
    if (err.code === 'network') return t('errors.network')
    if (err.code === 'invalidParameters') return t('errors.invalidParameters')
    if (err.code === 'europeOnly') return t('errors.europeOnly')
    if (err.detail) return err.detail
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
  return request(`${API_BASE}/api/parse-bill`, { method: 'POST', body: form })
}
