import { useState } from 'react'
import {
  ProductionChart,
  IrradiationChart,
  TypicalDayChart,
  MonthlyConsumptionChart,
  CashflowChart,
} from './Charts'
import AdSlot from './AdSlot'
import PrintReport from './PrintReport'
import { batteryRecommendation } from '../batteryRecommendation'

function ReportDownload({ data, i18n, fmt }) {
  const { t } = i18n
  const [variant, setVariant] = useState('informative')

  function download() {
    // El componente ya está montado con la variante elegida; el diálogo de
    // impresión del navegador permite "Guardar como PDF".
    window.print()
  }

  return (
    <div className="card-solar flex flex-wrap items-center gap-2 px-4 py-3 print:hidden">
      <span className="text-sm font-medium text-stone-700">{t('report.download')}:</span>
      <select
        value={variant}
        onChange={(e) => setVariant(e.target.value)}
        className="rounded-lg border border-stone-300 bg-white px-2.5 py-1.5 text-sm"
        aria-label={t('report.download')}
      >
        <option value="informative">{t('report.forInformative')}</option>
        <option value="installer">{t('report.forInstaller')}</option>
      </select>
      <button
        type="button"
        onClick={download}
        className="rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-stone-700"
      >
        {t('report.download')}
      </button>
      <PrintReport data={data} i18n={i18n} fmt={fmt} variant={variant} />
    </div>
  )
}

// Los Intl.NumberFormat son caros de construir y este componente se
// re-renderiza en cada hover de tooltip: caché por locale+moneda.
const formatterCache = new Map()

function makeFormatters(locale, currency) {
  const cacheKey = `${locale}|${currency}`
  const cached = formatterCache.get(cacheKey)
  if (cached) return cached
  const formatters = buildFormatters(locale, currency)
  formatterCache.set(cacheKey, formatters)
  return formatters
}

function buildFormatters(locale, currency) {
  return {
    nf: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
    nf1: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
    nf2: new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }),
    money0: new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }),
    money2: new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    }),
    date: new Intl.DateTimeFormat(locale, { day: '2-digit', month: '2-digit', year: 'numeric' }),
  }
}

function Card({ title, value, unit, detail, children, hero = false }) {
  return (
    <div className={`card-solar p-4 ${hero ? 'card-hero' : ''}`}>
      <p className="text-xs font-medium tracking-wide text-stone-500 uppercase">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-stone-900">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-stone-500">{unit}</span>}
      </p>
      {detail && <p className="mt-1 text-xs text-stone-500">{detail}</p>}
      {children}
    </div>
  )
}

function formatRange(range, formatter) {
  if (!range) return null
  if (Math.abs(range.high - range.low) < 0.01) return formatter.format(range.medium)
  return `${formatter.format(range.low)} - ${formatter.format(range.high)}`
}

function formatPerUnit(range, formatter, unit) {
  const formatted = formatRange(range, formatter)
  return formatted ? `${formatted}/${unit}` : null
}

function azimuthLabel(deg, i18n, nf) {
  const { t } = i18n
  const names = [
    [0, 'orientations.south'],
    [45, 'orientations.southwest'],
    [90, 'orientations.west'],
    [135, 'orientations.northwest'],
    [180, 'orientations.north'],
    [-180, 'orientations.north'],
    [-135, 'orientations.northeast'],
    [-90, 'orientations.east'],
    [-45, 'orientations.southeast'],
  ]
  const closest = names.reduce((a, b) => (Math.abs(b[0] - deg) < Math.abs(a[0] - deg) ? b : a))
  return `${nf.format(deg)}° (${t(closest[1])})`
}

function pricingMessage(pricing, t) {
  if (pricing.system_cost_source === 'manual') return t('results.manualPrices')
  if (pricing.source_type === 'providers' && !pricing.fallback_used) return t('results.providerPrices')
  return t('results.marketFallback')
}

function ConfidenceBadge({ confidence, t }) {
  const level = confidence?.level ?? 'low'
  const styles = {
    high: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    medium: 'border-amber-200 bg-amber-50 text-amber-800',
    low: 'border-red-200 bg-red-50 text-red-800',
  }
  const dots = {
    high: 'bg-emerald-500',
    medium: 'bg-amber-500',
    low: 'bg-red-500',
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${styles[level] ?? styles.low}`}
    >
      <span className={`h-2 w-2 rounded-full ${dots[level] ?? dots.low}`} />
      {t(`confidence.${level}`)}
    </span>
  )
}

function SizingSection({ analysis, i18n, fmt }) {
  const { t } = i18n
  const byKwp = new Map(analysis.scenarios.map((s) => [s.power_kwp, s]))
  const optimum = byKwp.get(analysis.economic_optimum_kwp)
  const maxSavings = byKwp.get(analysis.max_savings_kwp)
  if (!optimum || !maxSavings || optimum.power_kwp === maxSavings.power_kwp) return null
  const rows = [
    { key: 'optimum', label: t('sizing.optimum'), s: optimum, highlight: true },
    { key: 'maxSavings', label: t('sizing.maxSavings'), s: maxSavings, highlight: false },
  ]
  return (
    <div className="card-solar p-4">
      <h3 className="text-sm font-semibold text-stone-700">{t('sizing.title')}</h3>
      <p className="mt-1 text-xs text-stone-500">{t('sizing.intro')}</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-stone-200 text-left text-xs text-stone-500">
              <th className="py-2 pr-3 font-medium">{t('sizing.scenario')}</th>
              <th className="py-2 pr-3 font-medium">{t('sizing.power')}</th>
              <th className="py-2 pr-3 font-medium">{t('sizing.investment')}</th>
              <th className="py-2 pr-3 font-medium">{t('sizing.savingsYear')}</th>
              <th className="py-2 pr-3 font-medium">{t('sizing.payback')}</th>
              <th className="py-2 pr-3 font-medium">{t('sizing.roi')}</th>
              <th className="py-2 font-medium">{t('sizing.selfConsumption')}</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map(({ key, label, s, highlight }) => (
              <tr key={key} className={`border-b border-stone-100 ${highlight ? 'bg-amber-50' : ''}`}>
                <td className="py-2 pr-3 font-medium text-stone-800">
                  {label}
                  {highlight && (
                    <span className="ml-1.5 rounded bg-amber-200 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">
                      {t('sizing.recommended')}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-3">{fmt.nf2.format(s.power_kwp)} kWp</td>
                <td className="py-2 pr-3">{fmt.money0.format(s.investment_eur)}</td>
                <td className="py-2 pr-3">{fmt.money0.format(s.annual_savings_eur)}</td>
                <td className="py-2 pr-3">
                  {s.payback_years != null ? t('sizing.years', { value: fmt.nf1.format(s.payback_years) }) : '—'}
                </td>
                <td className="py-2 pr-3">{s.roi_pct != null ? `${fmt.nf1.format(s.roi_pct)}%` : '—'}</td>
                <td className="py-2">{fmt.nf1.format(s.self_consumption_pct)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-stone-500">{t('sizing.note')}</p>
    </div>
  )
}

function BatterySection({ analysis, i18n, pricing, fmt }) {
  const { t } = i18n
  const recommended = analysis.recommended_battery_kwh
  const recommendation = batteryRecommendation(analysis, i18n, fmt)
  return (
    <div className="card-solar p-4">
      <h3 className="text-sm font-semibold text-stone-700">{t('battery.title')}</h3>
      <p
        className={`mt-2 rounded-lg border p-3 text-sm ${
          recommended > 0
            ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
            : 'border-stone-200 bg-stone-50 text-stone-700'
        }`}
      >
        {recommendation}
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b border-stone-200 text-left text-xs text-stone-500">
              <th className="py-2 pr-3 font-medium">{t('battery.scenario')}</th>
              <th className="py-2 pr-3 font-medium">{t('battery.investment')}</th>
              <th className="py-2 pr-3 font-medium">{t('battery.savingsYear')}</th>
              <th className="py-2 pr-3 font-medium">{t('battery.payback')}</th>
              <th className="py-2 pr-3 font-medium">{t('battery.exported')}</th>
              <th className="py-2 pr-3 font-medium">{t('battery.selfSufficiency')}</th>
              <th className="py-2 font-medium">{t('battery.selfConsumption')}</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {analysis.scenarios.map((s) => (
              <tr
                key={s.battery_kwh}
                className={`border-b border-stone-100 ${
                  s.battery_kwh === recommended && recommended > 0 ? 'bg-amber-50' : ''
                }`}
              >
                <td className="py-2 pr-3 font-medium text-stone-800">
                  {s.battery_kwh === 0
                    ? t('battery.noBattery')
                    : t('battery.battery', { value: fmt.nf.format(s.battery_kwh) })}
                  {s.battery_kwh === recommended && recommended > 0 && (
                    <span className="ml-1.5 rounded bg-amber-200 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900">
                      {t('battery.recommended')}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-3">
                  {formatRange(s.investment_range_eur, fmt.money0) ?? fmt.money0.format(s.investment_eur)}
                </td>
                <td className="py-2 pr-3">{fmt.money0.format(s.annual_savings_eur)}</td>
                <td className="py-2 pr-3">
                  {s.payback_years != null
                    ? t('battery.years', { value: fmt.nf1.format(s.payback_years) })
                    : '—'}
                </td>
                <td className="py-2 pr-3">{fmt.nf.format(s.exported_kwh)} kWh</td>
                <td className="py-2 pr-3">{fmt.nf1.format(s.self_sufficiency_pct)}%</td>
                <td className="py-2">{fmt.nf1.format(s.self_consumption_pct)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-stone-500">
        {t('battery.note', {
          surplus: fmt.money2.format(analysis.surplus_price_eur_kwh),
          batteryCost:
            formatRange(pricing.battery_cost_per_kwh, fmt.money0) ??
            fmt.money0.format(analysis.battery_cost_per_kwh_eur),
        })}
      </p>
    </div>
  )
}

function TypicalDaySection({ typicalDay, i18n }) {
  const [month, setMonth] = useState(5)
  const { t, months } = i18n
  return (
    <div className="card-solar p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-stone-700">
          {t('charts.typicalDayTitle')}
        </h3>
        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="rounded-md border border-stone-300 bg-white px-2 py-1 text-xs"
          aria-label={t('charts.typicalDayMonthAria')}
        >
          {months.long.map((name, i) => (
            <option key={name} value={i}>
              {name}
            </option>
          ))}
        </select>
      </div>
      <TypicalDayChart
        production={typicalDay.production[month]}
        consumption={typicalDay.consumption[month]}
        i18n={i18n}
      />
      <p className="mt-1 text-xs text-stone-500">{t('charts.typicalDayNote')}</p>
    </div>
  )
}

function billMonthsText(months, i18n) {
  if (!months?.length) return null
  return months.map((m) => i18n.months.long[m - 1]).join(', ')
}

function ConsumptionSection({ consumption, i18n, currency }) {
  const { t } = i18n
  if (!consumption?.monthly_kwh) return null

  const observedMonths = billMonthsText(consumption.observed_months, i18n)
  const source = consumption.seasonality_source
  let note = t('results.consumptionEstimated')
  if (source === 'full_year_bills') {
    note = t('results.consumptionFromBills')
  } else if (source === 'estimated_from_sampled_months') {
    note = observedMonths
      ? t('results.consumptionSampled', { months: observedMonths })
      : t('results.consumptionNoMonths')
  }

  return (
    <div className="card-solar p-4">
      <MonthlyConsumptionChart
        monthlyKwh={consumption.monthly_kwh}
        monthlyEur={consumption.monthly_eur}
        observedMonths={consumption.observed_months}
        i18n={i18n}
        currency={currency}
      />
      <p className="mt-1 text-xs text-stone-500">{note}</p>
    </div>
  )
}

function BasisRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-stone-100 py-2 last:border-0">
      <dt className="text-stone-500">{label}</dt>
      <dd className="max-w-[65%] text-right font-medium text-stone-800">{value}</dd>
    </div>
  )
}

function pricingOrigin(pricing, source, t) {
  if (source === 'manual') return t('basis.manual')
  const country = t(`countries.${pricing.country_code}`)
  if (pricing.source_type === 'providers' && !pricing.fallback_used) {
    return t('basis.providerCountry', { country })
  }
  return t('basis.marketAverageCountry', { country })
}

function electricityPriceBasis(data, fmt, t) {
  const price = `${fmt.money2.format(data.economics.electricity_price_eur_kwh)}/kWh`
  const source = data.economics.electricity_price_source
  if (source === 'manual') return `${price} · ${t('basis.manual')}`
  if (source === 'bills') {
    const count =
      data.economics.electricity_price_bill_count || data.consumption?.priced_bill_count || 0
    const ignored = data.consumption?.ignored_price_bill_count || 0
    // El precio de facturas es el término de energía (sin impuestos); el ahorro
    // usa el coste marginal evitado, que se muestra en su propia tarjeta.
    return [
      `${price} · ${t('basis.energyTerm')}`,
      t('basis.fromBills', { count }),
      ignored ? t('basis.ignoredBills', { count: ignored }) : null,
    ]
      .filter(Boolean)
      .join(' · ')
  }
  return `${price} · ${t('basis.defaultElectricityPrice')}`
}

function CalculationBasis({ data, i18n, fmt }) {
  const { t } = i18n
  const pricing = data.pricing
  const updated = fmt.date.format(new Date(`${pricing.updated_at}T00:00:00`))
  const providerText = pricing.provider_names?.slice(0, 4).join(', ')
  // Sin guarda, un vat_note nulo o sin traducir renderizaría la clave cruda
  const vatNote = pricing.vat_note ? t(`basis.vatNotes.${pricing.vat_note}`) : null

  return (
    <div className="card-solar p-4">
      <h3 className="text-sm font-semibold text-stone-700">{t('basis.title')}</h3>
      <dl className="mt-2 text-sm">
        <BasisRow label={t('basis.country')} value={t(`countries.${pricing.country_code}`)} />
        <BasisRow
          label={t('basis.production')}
          value={t('basis.pvgisPvcalc', { loss: fmt.nf1.format(data.loss_pct) })}
        />
        <BasisRow
          label={t('basis.electricityPrice')}
          value={electricityPriceBasis(data, fmt, t)}
        />
        <BasisRow
          label={t('basis.installationCost')}
          value={`${pricingOrigin(pricing, pricing.system_cost_source, t)} · ${formatPerUnit(
            pricing.turnkey_cost_per_kwp,
            fmt.money0,
            'kWp',
          )}`}
        />
        <BasisRow
          label={t('basis.battery')}
          value={`${pricingOrigin(pricing, pricing.battery_cost_source, t)} · ${formatPerUnit(
            pricing.battery_cost_per_kwh,
            fmt.money0,
            'kWh',
          )}`}
        />
        <BasisRow
          label={t('basis.surplusPrice')}
          value={[
            `${fmt.money2.format(data.battery_analysis?.surplus_price_eur_kwh ?? pricing.surplus_price_eur_kwh)}/kWh`,
            pricing.export_scheme
              ? t(`basis.exportSchemes.${pricing.export_scheme}`)
              : null,
          ]
            .filter(Boolean)
            .join(' · ')}
        />
        <BasisRow
          label={t('basis.panel')}
          value={`${formatPerUnit(pricing.panel_price_per_w, fmt.money2, 'W')} · ${formatRange(
            pricing.panel_price_per_panel,
            fmt.money0,
          )}/${t('basis.panel').toLowerCase()}`}
        />
        <BasisRow
          label={t('basis.inverter')}
          value={formatPerUnit(pricing.inverter_price_per_kwp, fmt.money0, 'kWp')}
        />
        <BasisRow
          label={t('basis.mounting')}
          value={formatPerUnit(pricing.mounting_price_per_kwp, fmt.money0, 'kWp')}
        />
        <BasisRow
          label={t('basis.labour')}
          value={formatPerUnit(pricing.labour_price_per_kwp, fmt.money0, 'kWp')}
        />
        <BasisRow
          label={t('basis.vat')}
          value={
            vatNote
              ? `${fmt.nf1.format(pricing.vat_rate * 100)}% · ${vatNote}`
              : `${fmt.nf1.format(pricing.vat_rate * 100)}%`
          }
        />
        <BasisRow
          label={t('basis.source')}
          value={providerText || t('basis.marketAverage')}
        />
        <BasisRow label={t('basis.updated')} value={updated} />
      </dl>
    </div>
  )
}

function FinancialDetails({ eco, i18n, fmt }) {
  const { t } = i18n
  const a = eco.assumptions
  if (!a) return null
  const rows = [
    eco.net_investment_eur != null && [
      t('financial.netInvestment'),
      fmt.money0.format(eco.net_investment_eur),
    ],
    eco.subsidy_eur != null && [t('financial.subsidy'), fmt.money0.format(eco.subsidy_eur)],
    eco.npv_eur != null && [
      t('financial.npv', { rate: fmt.nf1.format(a.discount_rate_pct), years: a.headline_years }),
      fmt.money0.format(eco.npv_eur),
    ],
    eco.irr_pct != null && [t('financial.irr'), `${fmt.nf1.format(eco.irr_pct)} %`],
    [
      t('financial.degradation'),
      `${fmt.nf2.format(a.panel_degradation_pct_per_year)} %/${t('units.year')}`,
    ],
    [
      t('financial.escalation'),
      `+${fmt.nf1.format(a.price_escalation_pct_per_year)} %/${t('units.year')}`,
    ],
    [t('financial.om'), `${fmt.money0.format(a.om_eur_per_year)}/${t('units.year')}`],
    a.inverter_replacement_cost_eur > 0 && [
      t('financial.inverter', { year: a.inverter_replacement_year }),
      fmt.money0.format(a.inverter_replacement_cost_eur),
    ],
    eco.marginal_price_factor > 1 && [
      t('financial.taxFactor'),
      `×${fmt.nf2.format(eco.marginal_price_factor)}`,
    ],
  ].filter(Boolean)
  return (
    <details className="card-solar p-4">
      <summary className="cursor-pointer text-sm font-semibold text-stone-700">
        {t('financial.title')}
      </summary>
      <dl className="mt-3 grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between gap-3 border-b border-stone-100 pb-1"
          >
            <dt className="text-stone-500">{label}</dt>
            <dd className="font-medium text-stone-800">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-stone-500">{t('financial.note')}</p>
    </details>
  )
}

export default function Results({ data, i18n }) {
  const { t } = i18n
  if (!data?.pricing) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
        <p className="font-semibold">{t('app.errorTitle')}</p>
        <p className="mt-0.5">{t('errors.incompatibleResponse')}</p>
      </div>
    )
  }
  const pricing = data.pricing
  const fmt = makeFormatters(i18n.locale, pricing.currency)
  const system = data.user_system ?? data.optimal
  const isUserSystem = data.user_system != null
  const eco = data.economics
  const annualEnergy = data.annual_energy
  const updated = fmt.date.format(new Date(`${pricing.updated_at}T00:00:00`))

  return (
    <div className="space-y-6">
      <ReportDownload data={data} i18n={i18n} fmt={fmt} />

      <div className="card-solar px-4 py-3 text-sm text-stone-600">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>{pricingMessage(pricing, t)}</span>
          <ConfidenceBadge confidence={data.confidence} t={t} />
        </div>
        {data.confidence?.estimated_inputs?.length > 0 && (
          <p className="mt-1.5 text-xs text-stone-500">
            {t('confidence.estimatedLabel')}{' '}
            {data.confidence.estimated_inputs
              .map((input) => t(`confidence.inputs.${input}`))
              .join(', ')}
          </p>
        )}
        {data.confidence?.improvement_hints?.length > 0 && (
          <p className="mt-1 text-xs font-medium text-amber-700">
            {t('confidence.hintsLabel')}{' '}
            {data.confidence.improvement_hints
              .map((hint) => t(`confidence.hints.${hint}`))
              .join(' · ')}
          </p>
        )}
      </div>

      {/* Primero lo decisivo (ahorro, amortización, coste); el detalle técnico después */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Card
          hero
          title={t('results.estimatedSavings')}
          value={fmt.money2.format(eco.annual_savings_eur)}
          detail={
            eco.marginal_price_factor > 1 && eco.effective_price_eur_kwh != null
              ? t('results.marginalAvoidedCost', {
                  price: `${fmt.money2.format(eco.effective_price_eur_kwh)}/kWh`,
                })
              : `${fmt.money2.format(eco.electricity_price_eur_kwh)}/kWh`
          }
        />
        {eco.payback_years != null && (
          <Card
            hero
            title={t('results.payback')}
            value={fmt.nf1.format(eco.payback_years)}
            unit={t('units.years')}
            detail={[
              t('results.paybackDetail'),
              eco.simple_payback_years != null
                ? t('results.simplePayback', { value: fmt.nf1.format(eco.simple_payback_years) })
                : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          />
        )}
        {eco.savings_25yr_eur != null && (
          <Card
            hero
            title={t('results.savings25', { years: eco.assumptions?.headline_years ?? 25 })}
            value={fmt.money0.format(eco.savings_25yr_eur)}
            detail={t('results.savings25Detail')}
          />
        )}
        {eco.installation_cost_eur != null && (
          <Card
            hero
            title={eco.cost_is_estimated ? t('results.turnkeyCost') : t('results.indicatedCost')}
            value={formatRange(eco.installation_cost_range_eur, fmt.money0)}
            detail={[
              t('results.meanUsed', { value: fmt.money0.format(eco.installation_cost_eur) }),
              t('results.updatedOn', {
                country: t(`countries.${pricing.country_code}`),
                date: updated,
              }),
              eco.cost_is_estimated
                ? t('results.installedCostDetail', { kwp: fmt.nf2.format(data.analysis_power_kwp) })
                : t('results.indicatedCostDetail'),
              eco.cost_is_estimated ? t('results.typicalRangeNote') : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          />
        )}
        <Card
          title={t('results.analysedPower')}
          value={fmt.nf2.format(data.analysis_power_kwp)}
          unit="kWp"
          detail={
            data.requested_peak_power_kwp != null &&
            Math.abs(data.analysis_power_kwp - data.requested_peak_power_kwp) > 0.01
              ? t('results.analysedPowerAutoDetail')
              : t('results.analysedPowerDetail')
          }
        />
        <Card
          title={t('results.annualProduction')}
          value={fmt.nf.format(system.annual_production_kwh)}
          unit={t('units.kwhYear')}
          detail={`${fmt.nf2.format(data.analysis_power_kwp)} kWp · ${
            isUserSystem ? t('results.userAngles') : t('results.optimalAnglesMode')
          }`}
        />
        {data.consumption && (
          <Card
            title={t('results.annualConsumption')}
            value={fmt.nf.format(data.consumption.annual_kwh)}
            unit={t('units.kwhYear')}
            detail={
              data.consumption.source === 'bills'
                ? [
                    t('results.fromBills'),
                    data.consumption.bill_count
                      ? t('results.billsUsed', { value: data.consumption.bill_count })
                      : null,
                    data.consumption.observed_months?.length
                      ? t('results.months', { value: data.consumption.observed_months.length })
                      : data.consumption.days_covered != null
                        ? t('results.days', { value: fmt.nf.format(data.consumption.days_covered) })
                        : null,
                    data.consumption.avg_price_eur_kwh
                      ? t('results.effectivePrice', {
                          price: `${fmt.money2.format(data.consumption.avg_price_eur_kwh)}/kWh`,
                          count: data.consumption.priced_bill_count,
                        })
                      : null,
                    data.consumption.ignored_price_bill_count
                      ? t('results.ignoredBills', {
                          value: data.consumption.ignored_price_bill_count,
                        })
                      : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')
                : t('results.manualConsumption')
            }
          />
        )}
        {annualEnergy?.exported_kwh != null && (
          <Card
            title={t('results.exportedNoBattery')}
            value={fmt.nf.format(annualEnergy.exported_kwh)}
            unit={t('units.kwhYear')}
            detail={t('results.exportedDetail', {
              value: fmt.nf.format(annualEnergy.self_consumed_kwh),
            })}
          />
        )}
        {annualEnergy?.production_to_consumption_pct != null && (
          <Card
            title={t('results.productionEquivalent')}
            value={fmt.nf1.format(annualEnergy.production_to_consumption_pct)}
            unit="%"
            detail={t('results.productionEquivalentDetail')}
          />
        )}
        {annualEnergy?.self_sufficiency_pct != null && (
          <Card
            title={t('results.selfSufficiency')}
            value={fmt.nf1.format(annualEnergy.self_sufficiency_pct)}
            unit="%"
            detail={t('results.selfSufficiencyDetail', {
              value: fmt.nf.format(annualEnergy.self_consumed_kwh),
            })}
          />
        )}
        {annualEnergy?.self_consumption_pct != null && (
          <Card
            title={t('results.selfConsumption')}
            value={fmt.nf1.format(annualEnergy.self_consumption_pct)}
            unit="%"
            detail={t('results.selfConsumptionDetail')}
          />
        )}
        <Card
          title={t('results.peakSunHours')}
          value={fmt.nf1.format(system.hsp_daily_avg)}
          unit={t('units.hspDay')}
          detail={t('results.hspDetail', {
            value: fmt.nf.format(system.annual_irradiation_kwh_m2),
          })}
        />
        <Card
          title={t('results.optimalAngles')}
          value={`${fmt.nf.format(data.optimal.slope_deg)}°`}
          unit={t('units.tilt')}
          detail={t('results.optimalAnglesDetail', {
            orientation: azimuthLabel(data.optimal.azimuth_deg, i18n, fmt.nf),
          })}
        />
        {data.loss_vs_optimal_pct != null && (
          <Card
            title={t('results.lossVsOptimal')}
            value={fmt.nf1.format(data.loss_vs_optimal_pct)}
            unit="%"
            detail={`${fmt.nf.format(system.slope_deg)}° / ${azimuthLabel(
              system.azimuth_deg,
              i18n,
              fmt.nf,
            )} · ${fmt.nf.format(data.optimal.annual_production_kwh)} ${t('units.kwhYear')}`}
          />
        )}
        {eco.roi_pct != null && (
          <Card
            title={t('results.roi')}
            value={fmt.nf1.format(eco.roi_pct)}
            unit="%"
            detail={t('results.roiDetail')}
          />
        )}
        {data.consumption?.annual_amount_eur != null && (
          <Card
            title={t('results.annualBill')}
            value={fmt.money0.format(data.consumption.annual_amount_eur)}
            detail={
              data.consumption.total_amount_bill_count
                ? t('results.annualBillTotalDetail')
                : t('results.annualBillDetail')
            }
          />
        )}
        {data.panels && (
          <Card
            title={t('results.recommendedPanels')}
            value={fmt.nf.format(data.panels.count)}
            unit={`× ${data.panels.panel_power_w} W`}
            detail={t('results.roofDetail', {
              kwp: fmt.nf2.format(data.panels.total_kwp),
              area: fmt.nf.format(data.panels.roof_area_m2),
            })}
          >
            <p className="mt-2 text-xs leading-relaxed text-stone-500">
              {data.panels.coverage_pct != null && data.panels.production_to_consumption_pct != null
                ? t('results.recommendedPanelExplanation', {
                    ratio: fmt.nf1.format(data.panels.production_to_consumption_pct),
                  })
                : t('results.recommendedPanelFallback')}
            </p>
          </Card>
        )}
      </div>

      <AdSlot placement="results" />

      <CalculationBasis data={data} i18n={i18n} fmt={fmt} />

      {(eco.cumulative_cashflow?.length > 0 || eco.assumptions) && (
        <div className="space-y-4">
          {eco.cumulative_cashflow?.length > 0 && (
            <div className="card-solar p-4">
              <CashflowChart
                rows={eco.cumulative_cashflow}
                i18n={i18n}
                currency={pricing.currency_symbol || pricing.currency}
              />
            </div>
          )}
          <FinancialDetails eco={eco} i18n={i18n} fmt={fmt} />
        </div>
      )}

      <ConsumptionSection
        consumption={data.consumption}
        i18n={i18n}
        currency={pricing.currency_symbol || pricing.currency}
      />

      {data.sizing_analysis && (
        <SizingSection analysis={data.sizing_analysis} i18n={i18n} fmt={fmt} />
      )}

      {data.battery_analysis && (
        <BatterySection analysis={data.battery_analysis} i18n={i18n} pricing={pricing} fmt={fmt} />
      )}

      {data.typical_day && <TypicalDaySection typicalDay={data.typical_day} i18n={i18n} />}

      <div className="card-solar grid gap-6 p-4 lg:grid-cols-2">
        <ProductionChart monthly={system.monthly} i18n={i18n} />
        <IrradiationChart monthly={data.plane_irradiation_monthly} i18n={i18n} />
      </div>

      <p className="text-xs text-stone-500">
        {t('results.radiationFooter', {
          lat: fmt.nf2.format(data.lat),
          lon: fmt.nf2.format(data.lon),
          elevation:
            data.elevation_m != null ? fmt.nf.format(data.elevation_m) : null,
        })}
      </p>
    </div>
  )
}
