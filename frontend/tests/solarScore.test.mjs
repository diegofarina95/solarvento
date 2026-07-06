import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  computeSolarScore,
  scoreQualifier,
} from '../src/solarScore.js'

// Caso base: todo constante salvo lo que barremos en cada test.
function base(overrides = {}) {
  return {
    economics: { payback_years: 6, irr_pct: 10, ...(overrides.economics || {}) },
    annual_energy: { self_sufficiency_pct: 55, ...(overrides.annual_energy || {}) },
    optimal: { hsp_daily_avg: 4.6, ...(overrides.optimal || {}) },
    consumption: { annual_kwh: 5000, ...(overrides.consumption || {}) },
    battery_analysis: overrides.battery_analysis ?? null,
  }
}

test('monotónico en payback: mejor payback ⇒ score ≥ (todo lo demás fijo)', () => {
  let prev = Infinity
  for (let pb = 0.5; pb <= 25; pb += 0.1) {
    const s = computeSolarScore(base({ economics: { payback_years: pb, irr_pct: 10 } })).score
    assert.ok(s <= prev + 1e-9, `payback ${pb.toFixed(1)}: score ${s} > previo ${prev}`)
    prev = s
  }
})

test('monotónico en payback también con batería presente', () => {
  const battery = {
    recommended_battery_kwh: 5,
    battery_useful_life_years: 15,
    scenarios: [{ battery_kwh: 5, battery_incremental_payback_years: 10 }],
  }
  let prev = Infinity
  for (let pb = 1; pb <= 20; pb += 0.25) {
    const s = computeSolarScore(base({ economics: { payback_years: pb, irr_pct: 8 }, battery_analysis: battery })).score
    assert.ok(s <= prev + 1e-9, `payback ${pb}: ${s} > ${prev}`)
    prev = s
  }
})

test('no decreciente en TIR: más TIR ⇒ score ≥ (payback fijo)', () => {
  let prev = -Infinity
  for (let irr = 0; irr <= 25; irr += 0.5) {
    const s = computeSolarScore(base({ economics: { payback_years: 6, irr_pct: irr } })).score
    assert.ok(s >= prev - 1e-9, `irr ${irr}: ${s} < ${prev}`)
    prev = s
  }
})

test('el caso Return (3,5 a) NO puntúa menos que Balanced (3,8 a)', () => {
  // Mismo perfil, distinto slider: Return amortiza mejor pero con menos autosuf.
  const ret = computeSolarScore(base({ economics: { payback_years: 3.5, irr_pct: 12 }, annual_energy: { self_sufficiency_pct: 55 } })).score
  const bal = computeSolarScore(base({ economics: { payback_years: 3.8, irr_pct: 11 }, annual_energy: { self_sufficiency_pct: 62 } })).score
  assert.ok(ret >= bal, `Return ${ret} debería ser ≥ Balanced ${bal}`)
})

test('un solo mes (baja fiabilidad) se penaliza: no llega a bueno/excelente', () => {
  const reliable = computeSolarScore(base({ economics: { payback_years: 4, irr_pct: 12 } }))
  const single = computeSolarScore(base({
    economics: { payback_years: 4, irr_pct: 12 },
    consumption: { annual_kwh: 5000, single_month: true, consumption_reliability: 'low' },
  }))
  assert.ok(single.score < reliable.score, 'el single-month debe puntuar menos')
  assert.ok(single.score < 60, `single-month score ${single.score} no debe estar en bueno/excelente`)
  assert.notEqual(scoreQualifier(single.score), 'excellent')
  assert.ok(single.factors.some((f) => f.key === 'reliability'), 'debe reflejar el factor de fiabilidad')
})

test('anual impreso fiable NO se penaliza aunque single_month esté marcado', () => {
  const printed = computeSolarScore(base({
    economics: { payback_years: 4, irr_pct: 12 },
    consumption: { annual_kwh: 5000, single_month: true, consumption_reliability: 'low', annual_from_printed: true },
  }))
  assert.ok(!printed.factors.some((f) => f.key === 'reliability'), 'no debe penalizar el anual impreso')
})

test('consumo bajo (<3000) queda topado a poor', () => {
  const low = computeSolarScore(base({ economics: { payback_years: 4, irr_pct: 12 }, consumption: { annual_kwh: 2000 } }))
  assert.ok(low.score <= 39, `consumo bajo score ${low.score} debe estar topado`)
})
