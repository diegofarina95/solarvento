// Informe BÁSICO: veredicto (semáforo) + cifras clave + gráfico mensual + avisos
// en color, para el usuario no técnico. Todos los datos vienen de la respuesta
// del cálculo; no hay lógica de negocio nueva aquí (solo presentación).

// Lógica del veredicto y del score: módulo puro (testable, sin JSX).
import {
  batteryLabel,
  computeSolarScore,
  computeVerdict,
  lowSuitabilityReason,
  scoreQualifier,
} from '../solarScore'

// Re-export para compatibilidad con importadores existentes.
export { computeSolarScore, computeVerdict, lowSuitabilityReason }

const TONE = {
  good: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  ok: 'border-amber-300 bg-amber-50 text-amber-900',
  poor: 'border-red-300 bg-red-50 text-red-900',
}
const DOT = { good: 'bg-emerald-500', ok: 'bg-amber-500', poor: 'bg-red-500' }

function ScoreCard({ data, t }) {
  const { score, factors } = computeSolarScore(data)
  if (!factors.length) return null
  const qual = scoreQualifier(score)
  const ring = { excellent: 'text-emerald-600', good: 'text-emerald-600', fair: 'text-amber-600', poor: 'text-red-600' }
  return (
    <div className="card-solar px-4 py-4">
      <div className="flex items-center gap-4">
        <div className="flex flex-col items-center">
          <span className={`text-3xl font-bold ${ring[qual]}`}>{score}</span>
          <span className="text-[10px] font-medium uppercase tracking-wide text-stone-400">/ 100</span>
        </div>
        <div>
          <p className="text-sm font-semibold text-stone-700">{t('basic.score.title')}</p>
          <p className="text-sm text-stone-500">{t(`basic.score.${qual}`)}</p>
        </div>
      </div>
      <ul className="mt-3 grid grid-cols-1 gap-1 sm:grid-cols-2">
        {factors.map((f) => (
          <li key={f.key} className="flex items-center gap-2 text-sm text-stone-700">
            <span className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${DOT[f.tone]}`} />
            {t(`basic.score.factor.${f.key}`)}
          </li>
        ))}
      </ul>
    </div>
  )
}

function VerdictBanner({ verdict, subtitle, t }) {
  return (
    <div className={`rounded-xl border p-4 ${TONE[verdict]}`}>
      <p className="flex items-center gap-2 text-lg font-semibold">
        <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${DOT[verdict]}`} />
        {t(`basic.verdict.${verdict}`)}
      </p>
      {subtitle && <p className="mt-0.5 pl-[18px] text-sm opacity-90">{subtitle}</p>}
    </div>
  )
}

function StatCard({ label, value }) {
  return (
    <div className="card-solar flex flex-col items-center justify-center px-3 py-4 text-center">
      <span className="text-2xl font-bold text-stone-800">{value}</span>
      <span className="mt-1 text-xs font-medium text-stone-500">{label}</span>
    </div>
  )
}

function SelfSufficiencyBar({ pct, t }) {
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div className="card-solar px-4 py-3">
      <div className="mb-1.5 flex items-center justify-between text-sm">
        <span className="font-medium text-stone-700">{t('basic.selfSufficiencyLabel')}</span>
        <span className="font-bold text-emerald-700">{Math.round(clamped)}%</span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-stone-200">
        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${clamped}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-stone-500">{t('basic.selfSufficiencyHint')}</p>
    </div>
  )
}

function MonthlyChart({ production, consumption, locale, t }) {
  if (!Array.isArray(production) || production.length === 0) return null
  const prod = production.map((m) => m.production_kwh ?? 0)
  const cons = Array.isArray(consumption) && consumption.length === 12 ? consumption : null
  const max = Math.max(1, ...prod, ...(cons ?? [0]))
  const labels = Array.from({ length: 12 }, (_, i) =>
    new Intl.DateTimeFormat(locale, { month: 'narrow' }).format(new Date(2025, i, 1)),
  )
  return (
    <div className="card-solar px-4 py-3">
      <p className="mb-2 text-sm font-medium text-stone-700">{t('basic.chartTitle')}</p>
      <div className="flex items-end gap-1">
        {prod.map((p, i) => {
          const c = cons ? cons[i] : 0
          const auto = cons ? Math.min(p, c) : 0 // autoconsumo = lo que cubre el sol
          const exc = cons ? Math.max(0, p - auto) : 0 // excedente vertido
          return (
            <div key={i} className="flex flex-1 flex-col items-center">
              {/* Pista de altura FIJA (h-28): los % de las barras resuelven siempre. */}
              <div className="flex h-28 w-full items-end justify-center gap-[2px]">
                {cons ? (
                  <div
                    className="flex w-1/2 flex-col justify-end"
                    style={{ height: `${Math.max(2, (p / max) * 100)}%` }}
                    title={`${Math.round(p)} kWh`}
                  >
                    {exc > 0 && (
                      <div className="rounded-t bg-orange-400" style={{ height: `${(exc / p) * 100}%` }} />
                    )}
                    <div className={exc > 0 ? 'bg-emerald-500' : 'rounded-t bg-emerald-500'}
                         style={{ height: `${(auto / p) * 100}%` }} />
                  </div>
                ) : (
                  <div
                    className="w-1/2 rounded-t bg-amber-400"
                    style={{ height: `${Math.max(2, (p / max) * 100)}%` }}
                    title={`${Math.round(p)} kWh`}
                  />
                )}
                {cons && (
                  <div
                    className="w-1/2 rounded-t bg-teal-500"
                    style={{ height: `${Math.max(2, (c / max) * 100)}%` }}
                    title={`${Math.round(c)} kWh`}
                  />
                )}
              </div>
              <span className="mt-1 text-[10px] text-stone-400">{labels[i]}</span>
            </div>
          )
        })}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-stone-500">
        {cons ? (
          <>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-3 rounded-sm bg-emerald-500" /> {t('basic.legendSelfUse')}
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-3 rounded-sm bg-orange-400" /> {t('basic.legendSurplus')}
            </span>
          </>
        ) : (
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm bg-amber-400" /> {t('basic.legendProduction')}
          </span>
        )}
        {cons && (
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm bg-teal-500" /> {t('basic.legendConsumption')}
          </span>
        )}
      </div>
    </div>
  )
}

function Notes({ notes }) {
  if (notes.length === 0) return null
  return (
    <ul className="space-y-1.5">
      {notes.map((n, i) => (
        <li key={i} className="flex items-start gap-2 text-sm text-stone-700">
          <span className={`mt-[6px] inline-block h-1.5 w-1.5 shrink-0 rounded-full ${DOT[n.tone]}`} />
          <span>{n.text}</span>
        </li>
      ))}
    </ul>
  )
}

function buildNotes(data, fmt, t) {
  const notes = []
  if (data.subsidies) {
    notes.push(
      data.subsidies.applicable
        ? { tone: 'good', text: t('basic.notes.subsidyAvailable') }
        : { tone: 'ok', text: t('basic.notes.subsidyConsult') },
    )
  }
  if (data.grid_limits) {
    notes.push({ tone: 'ok', text: t('basic.notes.gridLimit', {
      contracted: fmt.nf2.format(data.grid_limits.contracted_power_kw),
    }) })
  }
  if ((data.confidence?.estimated_inputs ?? []).includes('consumption')) {
    notes.push({ tone: 'ok', text: t('basic.notes.consumptionEstimated') })
  }
  return notes
}

function BatteryCard({ battery, fmt, t }) {
  const recKwh = battery.recommended_battery_kwh
  const scenarios = battery.scenarios ?? []
  if (!recKwh || recKwh <= 0) {
    if (!scenarios.some((s) => s.battery_kwh > 0)) return null
    return (
      <div className="card-solar px-4 py-3">
        <p className="text-sm font-semibold text-stone-700">{t('basic.battery.title')}</p>
        <p className="mt-1 flex items-center gap-2 text-sm text-stone-600">
          <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-amber-500" />
          {t('basic.battery.none')}
        </p>
      </div>
    )
  }
  const base = scenarios.find((s) => s.battery_kwh === 0)
  const rec = scenarios.find((s) => s.battery_kwh === recKwh)
  const payback = rec?.battery_incremental_payback_years
  const label = batteryLabel(payback, battery.battery_useful_life_years) ?? 'good'
  const beforeAfter =
    rec && base && rec.self_sufficiency_pct != null && base.self_sufficiency_pct != null
      ? { before: base.self_sufficiency_pct, after: rec.self_sufficiency_pct }
      : null
  return (
    <div className="card-solar px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-stone-700">
          {t('basic.battery.title')} · {t('basic.battery.recommend', { kwh: fmt.nf1.format(recKwh) })}
        </p>
        <span
          className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${TONE[label]}`}
        >
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${DOT[label]}`} />
          {t(`basic.battery.label.${label}`)}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-3">
        {beforeAfter && (
          <div>
            <p className="text-lg font-bold text-stone-800">
              {fmt.nf1.format(beforeAfter.before)}% → {fmt.nf1.format(beforeAfter.after)}%
            </p>
            <p className="text-xs text-stone-500">{t('basic.battery.selfSuff')}</p>
          </div>
        )}
        {payback != null && (
          <div>
            <p className="text-lg font-bold text-stone-800">{t('basic.years', { value: fmt.nf1.format(payback) })}</p>
            <p className="text-xs text-stone-500">{t('basic.battery.paybackLabel')}</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default function BasicReport({ data, i18n, fmt }) {
  const { t } = i18n
  const eco = data.economics ?? {}
  const ae = data.annual_energy ?? {}
  const cons = data.consumption ?? {}
  const panels = data.panels
  const annualSavings = eco.annual_savings_eur ?? 0
  const payback = eco.payback_years
  const annualKwh = cons.annual_kwh
  const bonoSocial = !!cons.bono_social
  const verdict = computeVerdict(payback, annualKwh, bonoSocial)
  const lowReason = lowSuitabilityReason(payback, annualKwh, bonoSocial)
  const singleMonth = !!cons.single_month || cons.consumption_reliability === 'low'

  const paybackText =
    payback != null && payback > 0
      ? t('basic.years', { value: fmt.nf1.format(payback) })
      : t('basic.paybackNever')
  const subtitle = lowReason
    ? t(`basic.lowSuitability.${lowReason}`, {
        kwh: fmt.nf.format(annualKwh ?? 0),
        years: payback != null && payback > 0 ? fmt.nf1.format(payback) : '—',
      })
    : t('basic.verdictSub', { year: fmt.money0.format(annualSavings) })
  const system = data.user_system ?? data.optimal
  const selfSuff = ae.self_sufficiency_pct
  const production = system?.annual_production_kwh

  return (
    <div className="space-y-4">
      <VerdictBanner verdict={verdict} subtitle={subtitle} t={t} />

      {singleMonth && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {t('basic.singleMonthCaveat')}
        </div>
      )}

      {cons.distinct_cups > 1 && (
        <div className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {t('basic.mixedSupply', { n: cons.distinct_cups })}
        </div>
      )}

      <ScoreCard data={data} t={t} />

      <div className="grid grid-cols-3 gap-3">
        <StatCard label={t('basic.savingMonth')} value={fmt.money0.format(annualSavings / 12)} />
        <StatCard label={t('basic.savingYear')} value={fmt.money0.format(annualSavings)} />
        <StatCard label={t('basic.paybackLabel')} value={paybackText} />
      </div>

      {/* Una frase que resume toda la página */}
      {selfSuff != null && (
        <p className="text-sm leading-relaxed text-stone-700">
          {t('basic.summary', {
            selfSuff: fmt.nf.format(selfSuff),
            savings: fmt.money0.format(annualSavings),
          })}
        </p>
      )}

      {selfSuff != null && <SelfSufficiencyBar pct={selfSuff} t={t} />}

      {panels && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 text-sm text-emerald-900">
          <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
            {t('basic.recommendationTitle')}
          </p>
          <p className="mt-1 font-medium">
            {t('basic.recommendationBody', {
              count: fmt.nf.format(panels.count),
              kwp: fmt.nf2.format(panels.total_kwp),
              area: fmt.nf.format(panels.roof_area_m2),
            })}
          </p>
          {production != null && (
            <p className="mt-1 text-emerald-800">
              {t('basic.estimatedProduction')}:{' '}
              <span className="font-semibold">
                {t('basic.production', { value: fmt.nf.format(production) })}
              </span>
            </p>
          )}
        </div>
      )}

      <MonthlyChart
        production={system?.monthly}
        consumption={data.consumption?.monthly_kwh}
        locale={i18n.locale}
        t={t}
      />

      {data.battery_analysis && <BatteryCard battery={data.battery_analysis} fmt={fmt} t={t} />}

      <Notes notes={buildNotes(data, fmt, t)} />
    </div>
  )
}
