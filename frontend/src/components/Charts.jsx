import {
  ResponsiveContainer,
  ComposedChart,
  BarChart,
  Bar,
  Cell,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'

const axisStyle = { fontSize: 12, fill: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }

// Caché por locale: los tooltips llaman a formatters() en cada movimiento del
// ratón y construir Intl.NumberFormat es caro.
const formatterCache = new Map()

function formatters(locale) {
  const cached = formatterCache.get(locale)
  if (cached) return cached
  const built = {
    nf: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
    nf1: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
    nf2: new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }),
  }
  formatterCache.set(locale, built)
  return built
}

function ChartTooltip({ active, payload, label, unit, formatter }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm shadow-md">
      <p className="font-medium">{label}</p>
      <p className="text-stone-600">
        {formatter(payload[0].value)} {unit}
      </p>
    </div>
  )
}

export function ProductionChart({ monthly, i18n }) {
  const { t, months, locale } = i18n
  const { nf } = formatters(locale)
  const data = monthly.map((m) => ({ name: months.short[m.month - 1], kwh: m.production_kwh }))
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-stone-700">
        {t('charts.productionMonthly')}
      </h3>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--gridline)" />
          <XAxis dataKey="name" tick={axisStyle} tickLine={false} stroke="var(--baseline)" />
          <YAxis tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={nf.format} />
          <Tooltip
            cursor={{ fill: 'rgba(11,11,11,0.05)' }}
            content={<ChartTooltip unit="kWh" formatter={nf.format} />}
          />
          <Bar
            dataKey="kwh"
            fill="var(--series-production)"
            radius={[4, 4, 0, 0]}
            maxBarSize={28}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function TwoSeriesTooltip({ active, payload, label, i18n }) {
  if (!active || !payload?.length) return null
  const { nf1 } = formatters(i18n.locale)
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm shadow-md">
      <p className="font-medium">{label}:00 h</p>
      {payload.map((entry) => (
        <p key={entry.dataKey} className="text-stone-600">
          <span
            className="mr-1.5 inline-block h-2 w-2 rounded-full"
            style={{ background: entry.color }}
          />
          {entry.name}: {nf1.format(entry.value)} kWh
        </p>
      ))}
    </div>
  )
}

export function TypicalDayChart({ production, consumption, i18n }) {
  const { t, locale } = i18n
  const { nf1 } = formatters(locale)
  const data = production.map((p, h) => ({ hour: h, prod: p, cons: consumption[h] }))
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--gridline)" />
        <XAxis
          dataKey="hour"
          tick={axisStyle}
          tickLine={false}
          stroke="var(--baseline)"
          ticks={[0, 4, 8, 12, 16, 20, 23]}
          tickFormatter={(h) => `${h}h`}
        />
        <YAxis tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={nf1.format} />
        <Tooltip content={<TwoSeriesTooltip i18n={i18n} />} />
        <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: 'var(--text-secondary)' }} />
        <Line
          name={t('charts.productionSolar')}
          type="monotone"
          dataKey="prod"
          stroke="var(--series-production)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 5 }}
        />
        <Line
          name={t('charts.consumption')}
          type="monotone"
          dataKey="cons"
          stroke="var(--series-consumption)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

function MonthlyConsumptionTooltip({ active, payload, label, i18n, currency }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const { t, locale } = i18n
  const { nf, nf2 } = formatters(locale)
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm shadow-md">
      <p className="font-medium">{label}</p>
      <p className="text-stone-600">
        {t('charts.consumption')}: {nf.format(row.kwh)} kWh
      </p>
      {row.eur != null && (
        <p className="text-stone-600">
          {t('charts.spending')}: {nf2.format(row.eur)}
          {currency ? ` ${currency}` : ''}
        </p>
      )}
      <p className="mt-1 text-xs text-stone-500">
        {row.observed ? t('charts.observedMonth') : t('charts.estimatedMonth')}
      </p>
    </div>
  )
}

export function MonthlyConsumptionChart({
  monthlyKwh,
  monthlyEur,
  observedMonths = [],
  i18n,
  currency,
}) {
  const { t, months, locale } = i18n
  const { nf } = formatters(locale)
  const observed = new Set(observedMonths)
  const hasCost = monthlyEur?.length === 12
  const data = monthlyKwh.map((kwh, i) => ({
    name: months.short[i],
    kwh,
    eur: hasCost ? monthlyEur[i] : null,
    observed: observed.has(i + 1),
  }))
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-stone-700">
        {t('charts.monthlyConsumption')}
      </h3>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 4, right: 24, left: -12, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--gridline)" />
          <XAxis dataKey="name" tick={axisStyle} tickLine={false} stroke="var(--baseline)" />
          <YAxis
            yAxisId="kwh"
            tick={axisStyle}
            tickLine={false}
            axisLine={false}
            tickFormatter={nf.format}
          />
          {hasCost && (
            <YAxis
              yAxisId="eur"
              orientation="right"
              tick={axisStyle}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => nf.format(v)}
            />
          )}
          <Tooltip
            cursor={{ fill: 'rgba(11,11,11,0.05)' }}
            content={<MonthlyConsumptionTooltip i18n={i18n} currency={currency} />}
          />
          <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: 'var(--text-secondary)' }} />
          <Bar
            name={t('charts.consumptionKwh')}
            yAxisId="kwh"
            dataKey="kwh"
            radius={[4, 4, 0, 0]}
            maxBarSize={28}
          >
            {data.map((row) => (
              <Cell
                key={row.name}
                fill={row.observed ? 'var(--series-consumption)' : 'var(--series-consumption-estimated)'}
              />
            ))}
          </Bar>
          {hasCost && (
            <Line
              name={t('charts.spendingEur')}
              yAxisId="eur"
              type="monotone"
              dataKey="eur"
              stroke="var(--series-cost)"
              strokeWidth={2}
              dot={{ r: 3, fill: 'var(--series-cost)', strokeWidth: 0 }}
              activeDot={{ r: 5 }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function IrradiationChart({ monthly, i18n }) {
  const { t, months, locale } = i18n
  const { nf, nf1 } = formatters(locale)
  const data = monthly.map((m) => ({ name: months.short[m.month - 1], h: m.irradiation_kwh_m2 }))
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-stone-700">
        {t('charts.irradiationMonthly')}
      </h3>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--gridline)" />
          <XAxis dataKey="name" tick={axisStyle} tickLine={false} stroke="var(--baseline)" />
          <YAxis tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={nf.format} />
          <Tooltip content={<ChartTooltip unit="kWh/m²" formatter={nf1.format} />} />
          <Line
            type="monotone"
            dataKey="h"
            stroke="var(--series-irradiation)"
            strokeWidth={2}
            dot={{ r: 3, fill: 'var(--series-irradiation)', strokeWidth: 0 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
