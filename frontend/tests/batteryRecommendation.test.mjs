import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createI18n } from '../src/i18n/translations.js'
import { batteryRecommendation } from '../src/batteryRecommendation.js'

const nf = new Intl.NumberFormat('en', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('en', { maximumFractionDigits: 1 })
const money0 = new Intl.NumberFormat('en', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const fmt = { nf, nf1, money0 }

// Casa donde la batería NO se amortiza (autoconsumo alto, poco excedente)
const analysis = {
  recommended_battery_kwh: 0,
  battery_warranty_years: 10,
  battery_useful_life_years: 12,
  base_self_consumption_pct: 85.4,
  base_surplus_kwh: 1432,
  max_battery_value_eur: 286,
  scenarios: [
    { battery_kwh: 0, investment_eur: 9000, annual_savings_eur: 2285, self_consumption_pct: 85.4, exported_kwh: 1432, self_sufficiency_pct: 60 },
    { battery_kwh: 5, investment_eur: 12000, annual_savings_eur: 2436, self_consumption_pct: 93.2, exported_kwh: 666, self_sufficiency_pct: 66,
      battery_incremental_payback_years: 19.9, battery_extra_cost_eur: 3000, battery_extra_savings_eur: 151 },
    { battery_kwh: 10, investment_eur: 15000, annual_savings_eur: 2519, self_consumption_pct: 97.5, exported_kwh: 245, self_sufficiency_pct: 70,
      battery_incremental_payback_years: 24.0, battery_extra_cost_eur: 6000, battery_extra_savings_eur: 234 },
  ],
}

test('narrative uses computed incremental payback, not a within/near-warranty claim', () => {
  const { t } = createI18n('en')
  const text = batteryRecommendation(analysis, { t }, fmt)
  // Contiene el payback incremental calculado de esta casa (mejor = 5 kWh, 19.9)
  assert.ok(text.includes('19.9'), text)
  assert.ok(/incremental payback/i.test(text), text)
  assert.ok(text.includes('85.4'), text)   // autoconsumo base
  assert.ok(text.includes('1,432'), text)  // excedente base
  // NO afirma que se amortiza "cerca/dentro" de la garantía/vida útil
  assert.ok(!/within its (estimated )?(lifetime|useful life|warranty)/i.test(text), text)
  assert.ok(!/near .{0,20}warranty/i.test(text), text)
})

test('spanish narrative also avoids the favourable within-warranty phrasing', () => {
  const { t } = createI18n('es')
  const text = batteryRecommendation(analysis, { t }, fmt)
  assert.ok(text.includes('19.9') || text.includes('19,9'), text)
  assert.ok(!/dentro de (su )?(vida útil|garantía)/i.test(text), text)
})
