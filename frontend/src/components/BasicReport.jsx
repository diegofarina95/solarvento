// Informe BÁSICO: veredicto (semáforo) + cifras clave + gráfico mensual + avisos
// en color, para el usuario no técnico. Todos los datos vienen de la respuesta
// del cálculo; no hay lógica de negocio nueva aquí (solo presentación).

// Umbrales del veredicto por años de amortización (ajustables).
const VERDICT_GOOD_MAX_YEARS = 10
const VERDICT_OK_MAX_YEARS = 15

export function computeVerdict(paybackYears) {
  if (paybackYears == null || paybackYears <= 0) return 'poor'
  if (paybackYears <= VERDICT_GOOD_MAX_YEARS) return 'good'
  if (paybackYears <= VERDICT_OK_MAX_YEARS) return 'ok'
  return 'poor'
}

const TONE = {
  good: 'border-emerald-300 bg-emerald-50 text-emerald-900',
  ok: 'border-amber-300 bg-amber-50 text-amber-900',
  poor: 'border-red-300 bg-red-50 text-red-900',
}
const DOT = { good: 'bg-emerald-500', ok: 'bg-amber-500', poor: 'bg-red-500' }

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
        {prod.map((p, i) => (
          <div key={i} className="flex flex-1 flex-col items-center">
            {/* Pista de altura FIJA (h-28 = 112px): los % de las barras resuelven
                siempre, sin depender de alturas flex indefinidas. */}
            <div className="flex h-28 w-full items-end justify-center gap-[2px]">
              <div
                className="w-1/2 rounded-t bg-amber-400"
                style={{ height: `${Math.max(2, (p / max) * 100)}%` }}
                title={`${Math.round(p)} kWh`}
              />
              {cons && (
                <div
                  className="w-1/2 rounded-t bg-stone-300"
                  style={{ height: `${Math.max(2, (cons[i] / max) * 100)}%` }}
                  title={`${Math.round(cons[i])} kWh`}
                />
              )}
            </div>
            <span className="mt-1 text-[10px] text-stone-400">{labels[i]}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-4 text-xs text-stone-500">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-3 rounded-sm bg-amber-400" /> {t('basic.legendProduction')}
        </span>
        {cons && (
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm bg-stone-300" /> {t('basic.legendConsumption')}
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
  const battery = data.battery_analysis
  if (battery) {
    if (battery.recommended_battery_kwh > 0) {
      notes.push({ tone: 'good', text: t('basic.notes.batteryGood', {
        kwh: fmt.nf1.format(battery.recommended_battery_kwh),
      }) })
    } else if ((battery.scenarios ?? []).some((s) => s.battery_kwh > 0)) {
      notes.push({ tone: 'ok', text: t('basic.notes.batteryNone') })
    }
  }
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

export default function BasicReport({ data, i18n, fmt }) {
  const { t } = i18n
  const eco = data.economics ?? {}
  const ae = data.annual_energy ?? {}
  const panels = data.panels
  const annualSavings = eco.annual_savings_eur ?? 0
  const payback = eco.payback_years
  const verdict = computeVerdict(payback)

  const paybackText =
    payback != null && payback > 0
      ? t('basic.years', { value: fmt.nf1.format(payback) })
      : t('basic.paybackNever')
  const subtitle = t('basic.verdictSub', { year: fmt.money0.format(annualSavings) })
  const system = data.user_system ?? data.optimal

  return (
    <div className="space-y-4">
      <VerdictBanner verdict={verdict} subtitle={subtitle} t={t} />

      <div className="grid grid-cols-3 gap-3">
        <StatCard label={t('basic.savingMonth')} value={fmt.money0.format(annualSavings / 12)} />
        <StatCard label={t('basic.savingYear')} value={fmt.money0.format(annualSavings)} />
        <StatCard label={t('basic.paybackLabel')} value={paybackText} />
      </div>

      {ae.self_sufficiency_pct != null && (
        <SelfSufficiencyBar pct={ae.self_sufficiency_pct} t={t} />
      )}

      {panels && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-medium text-emerald-900">
          {t('basic.recommendation', {
            count: fmt.nf.format(panels.count),
            kwp: fmt.nf2.format(panels.total_kwp),
          })}
        </div>
      )}

      <MonthlyChart
        production={system?.monthly}
        consumption={data.consumption?.monthly_kwh}
        locale={i18n.locale}
        t={t}
      />

      <Notes notes={buildNotes(data, fmt, t)} />
    </div>
  )
}
