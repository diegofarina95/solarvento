import assert from 'node:assert/strict'
import test from 'node:test'

import { parseLocaleNumber } from '../src/numberParsing.js'

test('parseLocaleNumber handles European and English thousands/decimal formats', () => {
  assert.equal(parseLocaleNumber('1.234,56', { thousands: true }), 1234.56)
  assert.equal(parseLocaleNumber('1,234.56', { thousands: true }), 1234.56)
  assert.equal(parseLocaleNumber('1,234', { thousands: true }), 1234)
  assert.equal(parseLocaleNumber('1,102.56', { thousands: true }), 1102.56)
  assert.equal(parseLocaleNumber('71,39'), 71.39)
  assert.equal(parseLocaleNumber('1.234', { thousands: true }), 1234)
})

test('parseLocaleNumber rejects empty and non numeric values', () => {
  assert.equal(parseLocaleNumber(''), null)
  assert.equal(parseLocaleNumber(null), null)
  assert.equal(parseLocaleNumber('abc'), null)
})
