// Lógica pura del veredicto y del Solar score (sin JSX): separada de BasicReport
// para poder testearla con `node --test`. El score está ANCLADO AL RETORNO
// (payback/TIR), es MONÓTONO en el payback (mejor payback ⇒ score ≥) y penaliza
// la baja fiabilidad del dato (un solo mes extrapolado).

// Umbrales del veredicto por años de amortización.
export const VERDICT_GOOD_MAX_YEARS = 10
export const VERDICT_OK_MAX_YEARS = 15
// Baja idoneidad: consumo pequeño o amortización larga → probablemente no compensa.
export const LOW_SUITABILITY_KWH = 3000
export const LOW_SUITABILITY_PAYBACK_YEARS = 8
export const LOW_SUITABILITY_SCORE_CAP = 39
// Anclaje al retorno: payback continuo decreciente + TIR complementaria. El
// rango es estrecho (2–14 a) para que diferencias finas de payback SÍ muevan el
// score y dominen sobre los factores menores (que casi no varían con el slider).
export const PB_FULL_YEARS = 2 // ≤2 años → puntos máximos de payback
export const PB_ZERO_YEARS = 14 // ≥14 años → 0 puntos de payback
export const IRR_TARGET_PCT = 12 // TIR que da los puntos máximos de TIR
// Penalización por baja fiabilidad del dato (un solo mes extrapolado).
export const RELIABILITY_SCORE_CAP = 59
export const RELIABILITY_PENALTY = 0.7

const clamp01 = (x) => Math.max(0, Math.min(1, x))

export function lowSuitabilityReason(paybackYears, annualKwh, bonoSocial = false) {
  const lowConsumption = annualKwh != null && annualKwh < LOW_SUITABILITY_KWH
  const slowPayback =
    paybackYears == null || paybackYears <= 0 || paybackYears > LOW_SUITABILITY_PAYBACK_YEARS
  if (lowConsumption && slowPayback) return 'both'
  if (lowConsumption) return 'lowConsumption'
  if (slowPayback) return 'slowPayback'
  // Bono social ⇒ consumidor vulnerable con consumo bajo subvencionado.
  if (bonoSocial) return 'bonoSocial'
  return null
}

export function computeVerdict(paybackYears, annualKwh, bonoSocial = false) {
  if (lowSuitabilityReason(paybackYears, annualKwh, bonoSocial)) return 'poor'
  if (paybackYears == null || paybackYears <= 0) return 'poor'
  if (paybackYears <= VERDICT_GOOD_MAX_YEARS) return 'good'
  if (paybackYears <= VERDICT_OK_MAX_YEARS) return 'ok'
  return 'poor'
}

// Etiqueta de la batería por payback incremental frente a su vida útil.
export function batteryLabel(incrementalPayback, usefulLifeYears) {
  if (incrementalPayback == null || usefulLifeYears == null) return null
  if (incrementalPayback <= usefulLifeYears * 0.8) return 'good'
  if (incrementalPayback <= usefulLifeYears) return 'ok'
  return 'poor'
}

export function scoreQualifier(score) {
  if (score >= 80) return 'excellent'
  if (score >= 60) return 'good'
  if (score >= 40) return 'fair'
  return 'poor'
}

// Solar score /100 anclado al RETORNO; autosuficiencia/potencial/consumo/batería
// menores; penaliza baja fiabilidad. Solo presentación (números ya calculados).
export function computeSolarScore(data) {
  const eco = data.economics ?? {}
  const ae = data.annual_energy ?? {}
  const system = data.user_system ?? data.optimal ?? {}
  const cons = data.consumption ?? {}
  const battery = data.battery_analysis
  const factors = []
  let score = 0

  // --- ANCLA: RETORNO (55 pts) ---
  const pb = eco.payback_years
  const irr = eco.irr_pct
  const hasIrr = irr != null
  const paybackWeight = hasIrr ? 45 : 55 // sin TIR, su peso se pliega en el payback
  if (pb != null && pb > 0) {
    const pbFrac = clamp01((PB_ZERO_YEARS - pb) / (PB_ZERO_YEARS - PB_FULL_YEARS))
    score += paybackWeight * pbFrac
    const tone = pb <= 6 ? 'good' : pb <= 10 ? 'ok' : 'poor'
    factors.push({ key: 'payback', tone })
  } else {
    factors.push({ key: 'payback', tone: 'poor' })
  }
  if (hasIrr) score += 10 * clamp01(irr / IRR_TARGET_PCT)

  // --- MENORES (45 pts) ---
  const hsp = system.hsp_daily_avg
  if (hsp != null) {
    const tone = hsp >= 4.5 ? 'good' : hsp >= 3.5 ? 'ok' : 'poor'
    score += tone === 'good' ? 15 : tone === 'ok' ? 10 : 5
    factors.push({ key: 'potential', tone })
  }
  const ss = ae.self_sufficiency_pct
  if (ss != null) {
    // Autosuficiencia: componente MENOR y CONTINUO (máx 6). Continuo a propósito:
    // sin saltos de tramo que puedan superar una mejora de payback al mover el slider.
    score += 6 * clamp01(ss / 70)
    const tone = ss >= 60 ? 'good' : ss >= 35 ? 'ok' : 'poor'
    factors.push({ key: 'selfSuff', tone })
  }
  const annual = cons.annual_kwh
  if (annual != null) {
    const tone = annual >= 4000 ? 'good' : annual >= LOW_SUITABILITY_KWH ? 'ok' : 'poor'
    score += tone === 'good' ? 10 : tone === 'ok' ? 6 : 3
    factors.push({ key: 'consumption', tone })
  }
  if (battery) {
    const rec = (battery.scenarios ?? []).find((s) => s.battery_kwh === battery.recommended_battery_kwh)
    const tone = batteryLabel(rec?.battery_incremental_payback_years, battery.battery_useful_life_years)
    if (battery.recommended_battery_kwh > 0 && tone) {
      score += tone === 'good' ? 10 : tone === 'ok' ? 6 : 3
      factors.push({ key: 'battery', tone })
    } else {
      score += 6
      factors.push({ key: 'battery', tone: 'ok' })
    }
  }
  score = Math.round(score)

  // Penalización por baja fiabilidad (un solo mes), salvo anual impreso fiable.
  const lowRel =
    (!!cons.single_month || cons.consumption_reliability === 'low') && !cons.annual_from_printed
  if (lowRel) {
    score = Math.min(Math.round(score * RELIABILITY_PENALTY), RELIABILITY_SCORE_CAP)
    factors.push({ key: 'reliability', tone: 'poor' })
  }

  // Tope de idoneidad: min() preserva la monotonía en el payback.
  const reason = lowSuitabilityReason(eco.payback_years, annual, cons.bono_social)
  if (reason) score = Math.min(score, LOW_SUITABILITY_SCORE_CAP)
  return { score, factors, lowSuitability: reason }
}
