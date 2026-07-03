export function parseLocaleNumber(value, { thousands = false } = {}) {
  if (value == null || value === '') return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null

  const raw = String(value).trim().replace(/\s/g, '')
  if (!raw) return null

  let normalized = raw
  if (raw.includes(',') && raw.includes('.')) {
    normalized = raw.lastIndexOf(',') > raw.lastIndexOf('.')
      ? raw.replace(/\./g, '').replace(',', '.')
      : raw.replace(/,/g, '')
  } else if (raw.includes(',')) {
    normalized = thousands && /^\d{1,3}(?:,\d{3})+$/.test(raw)
      ? raw.replace(/,/g, '')
      : raw.replace(',', '.')
  } else if (thousands && /^\d{1,3}(?:\.\d{3})+$/.test(raw)) {
    normalized = raw.replace(/\./g, '')
  }

  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}
