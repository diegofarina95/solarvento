import assert from 'node:assert/strict'
import test from 'node:test'

import { translations } from '../src/i18n/translations.js'

function flattenKeys(value, prefix = '') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      return flattenKeys(child, path)
    }
    return [path]
  })
}

test('all languages provide the same translation keys as Spanish', () => {
  const baseKeys = flattenKeys(translations.es).sort()
  for (const [language, dictionary] of Object.entries(translations)) {
    assert.deepEqual(
      flattenKeys(dictionary).sort(),
      baseKeys,
      `translation keys differ for ${language}`,
    )
  }
})
