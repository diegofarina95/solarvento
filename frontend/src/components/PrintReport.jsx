import { createPortal } from 'react-dom'
import { batteryRecommendation } from '../batteryRecommendation'

// Informe imprimible (el usuario elige "Guardar como PDF" en el diálogo).
// Se renderiza fuera del #app-shell mediante un portal a <body>, y el CSS de
// impresión oculta la app y muestra solo este nodo. Dos variantes:
//   - informative: resumen para el usuario final
//   - installer: dosier técnico completo para pedir presupuesto a una empresa
const MONTHS_KEY = 'months'

function Row({ label, value }) {
  if (value == null || value === '') return null
  return (
    <tr>
      <td className="pr-label">{label}</td>
      <td className="pr-value">{value}</td>
    </tr>
  )
}

function Section({ title, children }) {
  return (
    <section className="pr-section">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

export default function PrintReport({ data, i18n, fmt, variant }) {
  const { t } = i18n
  const months = i18n[MONTHS_KEY].short
  const pricing = data.pricing
  const system = data.user_system ?? data.optimal
  const eco = data.economics
  const energy = data.annual_energy
  const isInstaller = variant === 'installer'
  const currency = pricing.currency

  const updated = fmt.date.format(new Date(`${pricing.updated_at}T00:00:00`))
  const generated = fmt.date.format(new Date())

  return createPortal(
    <div className="print-report" data-variant={variant}>
      <header className="pr-header">
        <div>
          <h1>
            Sol<span>Vento</span>
          </h1>
          <p className="pr-subtitle">
            {isInstaller ? t('report.installerTitle') : t('report.informativeTitle')}
          </p>
        </div>
        <div className="pr-meta">
          <p>{t('report.generatedOn', { date: generated })}</p>
          <p className="pr-coords">
            {fmt.nf2.format(data.lat)}, {fmt.nf2.format(data.lon)}
            {data.elevation_m != null ? ` · ${fmt.nf.format(data.elevation_m)} m` : ''}
          </p>
          <p>{t(`countries.${pricing.country_code}`)}</p>
        </div>
      </header>

      {/* KPIs principales */}
      <div className="pr-kpis">
        <div className="pr-kpi">
          <span className="pr-kpi-label">{t('results.annualProduction')}</span>
          <span className="pr-kpi-value">
            {fmt.nf.format(system.annual_production_kwh)} <small>{t('units.kwhYear')}</small>
          </span>
        </div>
        <div className="pr-kpi">
          <span className="pr-kpi-label">{t('results.estimatedSavings')}</span>
          <span className="pr-kpi-value">{fmt.money0.format(eco.annual_savings_eur)}/{t('units.year')}</span>
        </div>
        {eco.payback_years != null && (
          <div className="pr-kpi">
            <span className="pr-kpi-label">{t('results.payback')}</span>
            <span className="pr-kpi-value">
              {fmt.nf1.format(eco.payback_years)} <small>{t('units.years')}</small>
            </span>
          </div>
        )}
        {eco.installation_cost_eur != null && (
          <div className="pr-kpi">
            <span className="pr-kpi-label">
              {eco.cost_is_estimated ? t('results.turnkeyCost') : t('results.indicatedCost')}
            </span>
            <span className="pr-kpi-value">
              {formatRange(eco.installation_cost_range_eur, fmt.money0)}
            </span>
          </div>
        )}
      </div>

      <Section title={t('report.systemSection')}>
        <table className="pr-table pr-kv">
          <tbody>
            <Row
              label={t('report.analysedPower')}
              value={`${fmt.nf2.format(data.analysis_power_kwp)} kWp`}
            />
            {data.panels && (
              <Row
                label={t('results.recommendedPanels')}
                value={`${fmt.nf.format(data.panels.count)} × ${data.panels.panel_power_w} W · ~${fmt.nf.format(data.panels.roof_area_m2)} m²`}
              />
            )}
            <Row
              label={t('report.orientationTilt')}
              value={`${fmt.nf.format(system.slope_deg)}° · ${fmt.nf.format(system.azimuth_deg)}°`}
            />
            {isInstaller && (
              <Row
                label={t('results.optimalAngles')}
                value={`${fmt.nf.format(data.optimal.slope_deg)}° · ${fmt.nf.format(data.optimal.azimuth_deg)}°`}
              />
            )}
            {isInstaller && data.loss_vs_optimal_pct != null && (
              <Row
                label={t('results.lossVsOptimal')}
                value={`${fmt.nf1.format(data.loss_vs_optimal_pct)} %`}
              />
            )}
            {isInstaller && (
              <Row label={t('form.losses')} value={`${fmt.nf1.format(data.loss_pct)} %`} />
            )}
            <Row
              label={t('results.peakSunHours')}
              value={`${fmt.nf1.format(system.hsp_daily_avg)} ${t('units.hspDay')}`}
            />
            {energy?.self_sufficiency_pct != null && (
              <Row
                label={t('results.selfSufficiency')}
                value={`${fmt.nf1.format(energy.self_sufficiency_pct)} %`}
              />
            )}
            {energy?.self_consumption_pct != null && (
              <Row
                label={t('results.selfConsumption')}
                value={`${fmt.nf1.format(energy.self_consumption_pct)} %`}
              />
            )}
          </tbody>
        </table>
      </Section>

      {data.consumption && (
        <Section title={t('results.annualConsumption')}>
          <table className="pr-table pr-kv">
            <tbody>
              <Row
                label={t('results.annualConsumption')}
                value={`${fmt.nf.format(data.consumption.annual_kwh)} ${t('units.kwhYear')}`}
              />
              {data.consumption.avg_price_eur_kwh != null && (
                <Row
                  label={t('basis.energyTerm')}
                  value={`${fmt.money2.format(data.consumption.avg_price_eur_kwh)}/kWh`}
                />
              )}
              {data.consumption.annual_amount_eur != null && (
                <Row
                  label={t('results.annualBill')}
                  value={fmt.money0.format(data.consumption.annual_amount_eur)}
                />
              )}
            </tbody>
          </table>
        </Section>
      )}

      {/* Producción mensual: tabla, fiable en impresión */}
      <Section title={t('report.monthlyProduction')}>
        <table className="pr-table pr-months">
          <thead>
            <tr>
              <th />
              {system.monthly.map((m) => (
                <th key={m.month}>{months[m.month - 1]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="pr-label">kWh</td>
              {system.monthly.map((m) => (
                <td key={m.month}>{fmt.nf.format(m.production_kwh)}</td>
              ))}
            </tr>
            {isInstaller && (
              <tr>
                <td className="pr-label">kWh/m²</td>
                {system.monthly.map((m) => (
                  <td key={m.month}>{fmt.nf.format(m.irradiation_kwh_m2)}</td>
                ))}
              </tr>
            )}
          </tbody>
        </table>
      </Section>

      {eco.assumptions && (
        <Section title={t('financial.title')}>
          <table className="pr-table pr-kv">
            <tbody>
              <Row
                label={t('results.savings25', { years: eco.assumptions.headline_years })}
                value={eco.savings_25yr_eur != null ? fmt.money0.format(eco.savings_25yr_eur) : null}
              />
              <Row
                label={t('financial.netInvestment')}
                value={eco.net_investment_eur != null ? fmt.money0.format(eco.net_investment_eur) : null}
              />
              <Row
                label={t('financial.npv', {
                  rate: fmt.nf1.format(eco.assumptions.discount_rate_pct),
                  years: eco.assumptions.headline_years,
                })}
                value={eco.npv_eur != null ? fmt.money0.format(eco.npv_eur) : null}
              />
              <Row
                label={t('financial.irr')}
                value={eco.irr_pct != null ? `${fmt.nf1.format(eco.irr_pct)} %` : null}
              />
              <Row
                label={t('financial.escalation')}
                value={`+${fmt.nf1.format(eco.assumptions.price_escalation_pct_per_year)} %/${t('units.year')}`}
              />
              <Row
                label={t('financial.degradation')}
                value={`${fmt.nf2.format(eco.assumptions.panel_degradation_pct_per_year)} %/${t('units.year')}`}
              />
              <Row
                label={t('financial.om')}
                value={`${fmt.money0.format(eco.assumptions.om_eur_per_year)}/${t('units.year')}`}
              />
              {eco.assumptions.inverter_replacement_cost_eur > 0 && (
                <Row
                  label={t('financial.inverter', { year: eco.assumptions.inverter_replacement_year })}
                  value={fmt.money0.format(eco.assumptions.inverter_replacement_cost_eur)}
                />
              )}
            </tbody>
          </table>
        </Section>
      )}

      {data.battery_analysis && (
        <Section title={t('battery.title')}>
          <p className="pr-note">{batteryRecommendation(data.battery_analysis, i18n, fmt)}</p>
          {isInstaller && (
            <table className="pr-table pr-scenarios">
              <thead>
                <tr>
                  <th>{t('battery.scenario')}</th>
                  <th>{t('battery.investment')}</th>
                  <th>{t('battery.savingsYear')}</th>
                  <th>{t('battery.payback')}</th>
                  <th>{t('battery.selfSufficiency')}</th>
                  <th>{t('battery.selfConsumption')}</th>
                </tr>
              </thead>
              <tbody>
                {data.battery_analysis.scenarios.map((s) => (
                  <tr key={s.battery_kwh}>
                    <td>
                      {s.battery_kwh === 0
                        ? t('battery.noBattery')
                        : t('battery.battery', { value: fmt.nf.format(s.battery_kwh) })}
                    </td>
                    <td>{formatRange(s.investment_range_eur, fmt.money0) ?? fmt.money0.format(s.investment_eur)}</td>
                    <td>{fmt.money0.format(s.annual_savings_eur)}</td>
                    <td>{s.payback_years != null ? t('battery.years', { value: fmt.nf1.format(s.payback_years) }) : '—'}</td>
                    <td>{fmt.nf1.format(s.self_sufficiency_pct)} %</td>
                    <td>{fmt.nf1.format(s.self_consumption_pct)} %</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      )}

      {/* Base del cálculo: solo en el informe para instalador */}
      {isInstaller && (
        <Section title={t('basis.title')}>
          <table className="pr-table pr-kv">
            <tbody>
              <Row label={t('basis.production')} value={t('basis.pvgisPvcalc', { loss: fmt.nf1.format(data.loss_pct) })} />
              <Row
                label={t('basis.installationCost')}
                value={formatPerUnit(pricing.turnkey_cost_per_kwp, fmt.money0, 'kWp')}
              />
              <Row
                label={t('basis.battery')}
                value={formatPerUnit(pricing.battery_cost_per_kwh, fmt.money0, 'kWh')}
              />
              <Row
                label={t('basis.surplusPrice')}
                value={`${fmt.money2.format(pricing.surplus_price_eur_kwh)}/kWh`}
              />
              <Row label={t('basis.vat')} value={`${fmt.nf1.format(pricing.vat_rate * 100)} %`} />
              <Row label={t('basis.source')} value={pricing.provider_names?.slice(0, 4).join(', ') || t('basis.marketAverage')} />
              <Row label={t('basis.updated')} value={updated} />
              <Row label={t('report.currency')} value={currency} />
            </tbody>
          </table>
        </Section>
      )}

      {data.grid_limits && (
        <p className="pr-note">
          {t('grid.note', {
            power: fmt.nf2.format(data.grid_limits.recommended_power_kwp),
            contracted: fmt.nf2.format(data.grid_limits.contracted_power_kw),
            threshold: fmt.nf.format(data.grid_limits.tariff_threshold_kw),
          })}
        </p>
      )}

      <footer className="pr-footer">
        <p>{t('app.professionalDisclaimer')}</p>
        <p>{t('report.dataSource')}</p>
      </footer>
    </div>,
    document.body,
  )
}

function formatRange(range, formatter) {
  if (!range) return null
  if (Math.abs(range.high - range.low) < 0.01) return formatter.format(range.medium)
  return `${formatter.format(range.low)} – ${formatter.format(range.high)}`
}

function formatPerUnit(range, formatter, unit) {
  const formatted = formatRange(range, formatter)
  return formatted ? `${formatted}/${unit}` : null
}
