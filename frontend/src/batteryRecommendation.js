export function batteryRecommendation(analysis, i18n, fmt) {
  const { t } = i18n
  const lifetime = analysis.battery_lifetime_years ?? 10
  const base = analysis.scenarios.find((s) => s.battery_kwh === 0) ?? analysis.scenarios[0]
  const recommended = analysis.scenarios.find(
    (s) => s.battery_kwh > 0 && s.battery_kwh === analysis.recommended_battery_kwh,
  )
  if (recommended) {
    return t('battery.recommendation', {
      battery: fmt.nf1.format(recommended.battery_kwh),
      payback: fmt.nf1.format(recommended.battery_marginal_payback_years),
      selfBefore: fmt.nf1.format(base.self_sufficiency_pct),
      selfAfter: fmt.nf1.format(recommended.self_sufficiency_pct),
      lifetime,
    })
  }
  const candidates = analysis.scenarios.filter(
    (s) => s.battery_kwh > 0 && s.battery_marginal_payback_years != null,
  )
  const best = candidates.reduce(
    (current, item) =>
      !current || item.battery_marginal_payback_years < current.battery_marginal_payback_years
        ? item
        : current,
    null,
  )
  const detail = best
    ? t('battery.bestDetail', {
        battery: fmt.nf1.format(best.battery_kwh),
        payback: fmt.nf1.format(best.battery_marginal_payback_years),
        extraSavings: fmt.money0.format(Math.max(0, best.annual_savings_eur - base.annual_savings_eur)),
        extraInvestment: fmt.money0.format(Math.max(0, best.investment_eur - base.investment_eur)),
      })
    : ''
  return t('battery.noRecommendation', { lifetime, detail })
}
