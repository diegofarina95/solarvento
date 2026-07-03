// Narrativa de la batería con las cifras de ESTA casa. Cada dato sale de:
//  - base: escenario sin batería (autoconsumo %, excedente kWh).
//  - best/recommended: payback INCREMENTAL (coste extra / ahorro extra), no el
//    del sistema completo.
//  - analysis: garantía y vida útil (parámetros distintos) y el techo estructural.
export function batteryRecommendation(analysis, i18n, fmt) {
  const { t } = i18n
  const warranty = analysis.battery_warranty_years ?? 10
  const usefulLife = analysis.battery_useful_life_years ?? 12
  const base = analysis.scenarios.find((s) => s.battery_kwh === 0) ?? analysis.scenarios[0]
  const recommended = analysis.scenarios.find(
    (s) => s.battery_kwh > 0 && s.battery_kwh === analysis.recommended_battery_kwh,
  )
  if (recommended) {
    return t('battery.recommendation', {
      battery: fmt.nf1.format(recommended.battery_kwh),
      payback: fmt.nf1.format(recommended.battery_incremental_payback_years),
      usefulLife,
      selfBefore: fmt.nf1.format(base.self_sufficiency_pct),
      selfAfter: fmt.nf1.format(recommended.self_sufficiency_pct),
    })
  }
  const candidates = analysis.scenarios.filter(
    (s) => s.battery_kwh > 0 && s.battery_incremental_payback_years != null,
  )
  const best = candidates.reduce(
    (current, item) =>
      !current ||
      item.battery_incremental_payback_years < current.battery_incremental_payback_years
        ? item
        : current,
    null,
  )
  if (!best) return t('battery.noRecommendationGeneric', { warranty, usefulLife })
  const extraCost = best.battery_extra_cost_eur ?? Math.max(0, best.investment_eur - base.investment_eur)
  const extraSavings = best.battery_extra_savings_eur ?? Math.max(0, best.annual_savings_eur - base.annual_savings_eur)
  return t('battery.noRecommendation', {
    extraCost: fmt.money0.format(extraCost),
    extraSavings: fmt.money0.format(extraSavings),
    payback: fmt.nf1.format(best.battery_incremental_payback_years),
    selfConsumption: fmt.nf1.format(base.self_consumption_pct),
    surplus: fmt.nf.format(base.exported_kwh),
    warranty,
    usefulLife,
    cap: fmt.money0.format(analysis.max_battery_value_eur ?? 0),
  })
}
