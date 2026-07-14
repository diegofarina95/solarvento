import { useRef, useState } from 'react'
import { ApiError, parseBill } from '../api'

const inputClass =
  'w-full min-w-0 rounded-md border border-stone-300 bg-white px-2 py-1.5 text-sm outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-200'

const EMPTY_ROW = {
  month: '',
  kwh: '',
  energyAmount: '',
  totalAmount: '',
  amount: '',
  currency: '',
  start: '',
  end: '',
}

// Ids estables para las filas: con key={index}, borrar una fila intermedia
// hace saltar el foco y reutiliza estado de inputs de la fila siguiente.
let nextRowId = 1
function newRow(fields) {
  return { id: nextRowId++, ...EMPTY_ROW, ...fields }
}

function parseDateInput(value) {
  if (!value) return null
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return null
  return new Date(year, month - 1, day)
}

function inferBillMonth(start, end) {
  const startDate = parseDateInput(start)
  const endDate = parseDateInput(end)
  if (startDate && endDate) {
    // Periodo ~anual (01/01–31/12): no tiene un mes representativo → dejar en
    // "Auto" (vacío), no el punto medio (que daría julio, sin sentido).
    const spanDays = (endDate.getTime() - startDate.getTime()) / 86400000
    if (spanDays >= 330) return ''
    return String(new Date((startDate.getTime() + endDate.getTime()) / 2).getMonth() + 1)
  }
  const date = startDate ?? endDate
  return date ? String(date.getMonth() + 1) : ''
}

function spanDays(start, end) {
  const s = parseDateInput(start)
  const e = parseDateInput(end)
  if (!s || !e) return 0
  return (e.getTime() - s.getTime()) / 86400000
}

function monthFromDates(start, end) {
  const m = inferBillMonth(start, end)
  return m ? Number(m) : null
}

// Consolida el resumen "Datos detectados" por CUPS: varias facturas del mismo
// suministro se combinan como meses (nº real de meses, consumo combinado), en vez
// de mostrar solo la última y avisar de "un solo mes" habiendo varias.
function mergeDetected(prev, rawEntries) {
  const groups = new Map(
    prev.map((g) => [
      g.cupsKey,
      { ...g, months: new Set(g.months), periods: new Set(g.periodKeys || []) },
    ]),
  )
  for (const e of rawEntries) {
    let g = groups.get(e.cupsKey)
    if (!g) {
      g = {
        cupsKey: e.cupsKey,
        cups: e.cups,
        months: new Set(),
        periods: new Set(),
        monthlyKwh: 0,
        printedAnnual: null,
        isAnnual: false,
        tariff: null,
        bonoSocial: false,
        energyPrice: null,
        avgPrice: null,
        currency: e.currency,
        lastFallbackAnnual: null,
      }
      groups.set(e.cupsKey, g)
    }
    // La MISMA factura reimportada no cuenta dos veces (mismo periodo+kWh).
    if (g.periods.has(e.periodKey)) continue
    g.periods.add(e.periodKey)
    if (e.month) g.months.add(e.month)
    if (e.monthlyKwh != null) g.monthlyKwh += e.monthlyKwh
    if (e.printedAnnual != null) g.printedAnnual = e.printedAnnual
    if (e.isAnnual) g.isAnnual = true
    if (e.tariff) g.tariff = e.tariff
    if (e.bonoSocial) g.bonoSocial = true
    if (e.energyPrice != null) g.energyPrice = e.energyPrice
    if (e.avgPrice != null) g.avgPrice = e.avgPrice
    if (e.currency) g.currency = e.currency
    g.lastFallbackAnnual = e.fallbackAnnual
  }
  return Array.from(groups.values()).map((g) => ({
    cupsKey: g.cupsKey,
    cups: g.cups,
    months: Array.from(g.months).sort((a, b) => a - b),
    periodKeys: Array.from(g.periods),
    count: g.periods.size,
    monthlyKwh: g.monthlyKwh,
    printedAnnual: g.printedAnnual,
    isAnnual: g.isAnnual,
    tariff: g.tariff,
    bonoSocial: g.bonoSocial,
    energyPrice: g.energyPrice,
    avgPrice: g.avgPrice,
    currency: g.currency,
    lastFallbackAnnual: g.lastFallbackAnnual,
  }))
}

function MiniField({ label, children }) {
  return (
    <label className="block min-w-0">
      <span className="mb-0.5 block text-[10px] font-medium text-stone-500">{label}</span>
      {children}
    </label>
  )
}

export default function BillsInput({ bills, setBills, i18n, onLocationDetected }) {
  const { t, months } = i18n
  const fileRef = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [notice, setNotice] = useState(null)
  const [review, setReview] = useState(null)
  const [advisory, setAdvisory] = useState(null)
  const [detected, setDetected] = useState([])

  // Traduce un aviso {code, params} del backend; cae a `text` si el código no
  // existe en el catálogo (avisos "raw" del modelo).
  function noteText(note) {
    if (!note?.code) return note?.text ?? ''
    const key = `billNotices.${note.code}`
    const out = t(key, note.params ?? {})
    return out === key ? (note.params?.text ?? '') : out
  }
  const nfmt = new Intl.NumberFormat(i18n.locale, { maximumFractionDigits: 0 })
  const pfmt = new Intl.NumberFormat(i18n.locale, { maximumFractionDigits: 3 })

  function update(index, key, value) {
    setBills((prev) => prev.map((b, i) => (i === index ? { ...b, [key]: value } : b)))
  }

  function removeRow(index) {
    setBills(bills.filter((_, i) => i !== index))
  }

  async function handleFiles(fileList) {
    setUploading(true)
    setNotice(null)
    setReview(null)
    setAdvisory(null)
    // NO se resetea `detected`: se consolidan las nuevas facturas con las ya
    // detectadas (mismo CUPS = meses del mismo suministro).
    const added = []
    const problems = []
    const reviews = []
    const advisories = []
    const detectedRaw = []
    let detectedLocation = null
    // Los PDFs se parsean en paralelo: con varios archivos y un parser lento
    // la espera secuencial se multiplicaba por el número de facturas.
    const results = await Promise.allSettled(fileList.map((file) => parseBill(file)))
    results.forEach((result, index) => {
      const file = fileList[index]
      if (result.status === 'rejected') {
        const err = result.reason
        // Límite de subidas: NO es un error de lectura. Aviso propio y traducido,
        // sin interpolar el texto (antes mezclaba idiomas: "the bill could not be
        // read (Has alcanzado el límite...)").
        if (err instanceof ApiError && (err.code === 'upload_limit' || err.code === 'upload_quota')) {
          problems.push({ kind: err.code, file: file.name, params: err.params })
          return
        }
        // Se guardan datos, NO texto ya traducido: así el aviso se traduce al
        // idioma actual en cada render (antes quedaba fijado al idioma de la
        // importación y podía verse en inglés dentro de la app en español).
        problems.push({
          kind: 'billParseFailed',
          file: file.name,
          detail: err instanceof ApiError && typeof err.detail === 'string' ? err.detail : null,
        })
        return
      }
      const parsed = result.value
      // Factura de otro país (lanzamiento solo-España): se bloquea con aviso, sin
      // crear fila ni intentar calcular nada.
      if (parsed.state === 'unsupported_country') {
        if (parsed.warning_notes?.length) {
          advisories.push({ file: file.name, notes: parsed.warning_notes })
        } else {
          problems.push({ kind: 'billCountryBlocked', file: file.name })
        }
        return
      }
      if (parsed.kwh == null) {
        problems.push({ kind: 'billNoConsumption', file: file.name })
      }
      added.push(newRow({
        month: parsed.month ? String(parsed.month) : inferBillMonth(parsed.start_date, parsed.end_date),
        // Redondeo también en el campo editable (no solo en el resumen): nada de "3855.3".
        kwh: parsed.kwh != null ? String(Math.round(parsed.kwh)) : '',
        energyAmount: parsed.energy_eur ?? '',
        totalAmount: parsed.total_eur ?? parsed.amount_eur ?? '',
        amount: parsed.total_eur ?? parsed.amount_eur ?? '',
        currency: parsed.currency ?? '',
        start: parsed.start_date ?? '',
        end: parsed.end_date ?? '',
        // Líneas de impuestos del parser: viajan con la fila (no editables) para
        // que el backend derive el coste marginal evitado por factura.
        power_eur: parsed.power_eur ?? null,
        iee_eur: parsed.iee_eur ?? null,
        iva_eur: parsed.iva_eur ?? null,
        iva_rate: parsed.iva_rate ?? null,
        vat_base_eur: parsed.vat_base_eur ?? null,
        consumptionHistory: parsed.consumption_history ?? null,
        consumptionPeriods: parsed.consumption_periods ?? null,
        consumptionPeriodPrices: parsed.consumption_period_prices ?? null,
        // CUPS y bono social: consolidación por suministro y banda de precio.
        cups: parsed.cups ?? null,
        bonoSocial: parsed.bono_social ?? false,
        // Consumo anual declarado ("último año"): manda sobre la extrapolación
        // de meses parciales. Sin esto, el cálculo lo perdía y extrapolaba.
        rollingAnnualKwh: parsed.rolling_annual_kwh ?? null,
      }))
      if (parsed.needs_review && (parsed.review_notes?.length || parsed.review_reasons?.length)) {
        // Guarda de reconciliación/precio efectivo: el consumo detectado es
        // sospechoso. Se marca en rojo con el motivo concreto (traducido desde
        // el código i18n; se cae al texto del backend si falta el código).
        reviews.push({
          file: file.name,
          notes: parsed.review_notes ?? [],
          reasons: parsed.review_reasons ?? [],
        })
      } else if (parsed.warnings?.length) {
        problems.push({ kind: 'billNeedsReview', file: file.name })
      }
      // Avisos informativos (bono social, un solo mes, ubicación aproximada…):
      // se muestran traducidos, no bloquean el cálculo.
      if (parsed.warning_notes?.length) {
        advisories.push({ file: file.name, notes: parsed.warning_notes })
      }
      if (parsed.lat != null && parsed.lon != null) {
        detectedLocation = parsed
      } else if (!detectedLocation && parsed.country_code) {
        detectedLocation = parsed
      }

      // Resumen "Datos detectados": entrada CRUDA por factura; se consolidan por
      // CUPS aguas abajo (dos facturas del mismo suministro = meses del mismo).
      const res = parsed.consumption_resolution ?? {}
      const total = parsed.total_eur ?? parsed.amount_eur ?? null
      const printedAnnual =
        res.method === 'printed_annual' || parsed.rolling_annual_kwh ? res.annual_kwh : null
      const isAnnual =
        ['printed_annual', 'history', 'declared_annual'].includes(res.method) ||
        spanDays(parsed.start_date, parsed.end_date) >= 330
      const monthNum = parsed.month
        ? Number(parsed.month)
        : monthFromDates(parsed.start_date, parsed.end_date)
      if (parsed.kwh != null || printedAnnual != null) {
        detectedRaw.push({
          cupsKey: parsed.cups ? parsed.cups.trim().toUpperCase() : `file:${file.name}`,
          cups: parsed.cups || null,
          month: monthNum,
          // Firma del periodo para no contar dos veces la misma factura reimportada.
          periodKey:
            parsed.start_date && parsed.end_date
              ? `${parsed.start_date}|${parsed.end_date}|${Math.round(parsed.kwh ?? 0)}`
              : monthNum != null
                ? `m${monthNum}|${Math.round(parsed.kwh ?? 0)}`
                : `f:${file.name}`,
          monthlyKwh: parsed.kwh ?? null,
          printedAnnual,
          fallbackAnnual: res.annual_kwh ?? parsed.kwh ?? null,
          isAnnual,
          tariff: parsed.tariff ?? null,
          bonoSocial: !!parsed.bono_social,
          // Precio de ENERGÍA (término de energía), el mismo que usa el motor.
          energyPrice: parsed.energy_price_eur_kwh ?? null,
          // Precio MEDIO de la factura (importe÷kWh): informativo, aparte.
          avgPrice: total && parsed.kwh ? total / parsed.kwh : null,
          currency: parsed.currency || '€',
        })
      }
    })
    // Updater funcional: si el usuario editó o añadió filas mientras se
    // parseaban los PDFs, sus cambios no se sobrescriben.
    if (added.length) setBills((prev) => [...prev, ...added])
    if (detectedLocation) onLocationDetected?.(detectedLocation)
    if (problems.length) setNotice(problems)
    if (reviews.length) setReview(reviews)
    if (advisories.length) setAdvisory(advisories)
    if (detectedRaw.length) setDetected((prev) => mergeDetected(prev, detectedRaw))
    setUploading(false)
  }

  return (
    <div className="rounded-lg border border-stone-200 bg-stone-50 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-stone-700">{t('bills.title')}</p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="rounded-md border border-stone-300 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 hover:border-amber-500 disabled:opacity-50"
          >
            {uploading ? t('bills.importing') : t('bills.importPdf')}
          </button>
          <button
            type="button"
            onClick={() => setBills((prev) => [...prev, newRow()])}
            className="rounded-md border border-stone-300 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 hover:border-amber-500"
          >
            {t('bills.addRow')}
          </button>
        </div>
      </div>
      {/* HEIC/HEIF fuera del accept a propósito: sin anunciarlos, iOS
          transcodifica la foto a JPEG y la anonimización por OCR del backend
          aplica también a los iPhone (el HEIC crudo saltaba esa capa). */}
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf,image/jpeg,image/png,image/webp"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) handleFiles([...e.target.files])
          e.target.value = ''
        }}
      />

      {bills.length === 0 && <p className="text-xs text-stone-500">{t('bills.empty')}</p>}

      {bills.length > 0 && (
        <div className="space-y-2">
          {bills.map((bill, i) => (
            <div key={bill.id ?? i} className="rounded-md border border-stone-200 bg-white p-2">
              <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)_auto] gap-1.5">
                <MiniField label={t('bills.month')}>
                  <select
                    value={bill.month ?? ''}
                    onChange={(e) => update(i, 'month', e.target.value)}
                    className={inputClass}
                    aria-label={t('bills.monthAria', { index: i + 1 })}
                  >
                    <option value="">{t('bills.auto')}</option>
                    {months.long.map((month, monthIndex) => (
                      <option key={month} value={monthIndex + 1}>
                        {month}
                      </option>
                    ))}
                  </select>
                </MiniField>
                <MiniField label="kWh">
                  <input
                    type="text"
                    inputMode="decimal"
                    required
                    value={bill.kwh}
                    onChange={(e) => update(i, 'kwh', e.target.value)}
                    placeholder="kWh"
                    className={inputClass}
                    aria-label={t('bills.kwhAria', { index: i + 1 })}
                  />
                </MiniField>
                <button
                  type="button"
                  onClick={() => removeRow(i)}
                  className="mt-[18px] h-8 px-1.5 text-sm text-stone-400 hover:text-red-600"
                  aria-label={t('bills.remove', { index: i + 1 })}
                >
                  x
                </button>
              </div>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                <MiniField label={t('bills.energyAmount')}>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={bill.energyAmount ?? ''}
                    onChange={(e) => update(i, 'energyAmount', e.target.value)}
                    placeholder="€"
                    className={inputClass}
                    aria-label={t('bills.energyAmountAria', { index: i + 1 })}
                  />
                </MiniField>
                <MiniField label={t('bills.totalAmount')}>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={bill.totalAmount ?? bill.amount ?? ''}
                    onChange={(e) => {
                      update(i, 'totalAmount', e.target.value)
                      update(i, 'amount', e.target.value)
                    }}
                    placeholder="€"
                    className={inputClass}
                    aria-label={t('bills.totalAmountAria', { index: i + 1 })}
                  />
                </MiniField>
              </div>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                <MiniField label={t('bills.start')}>
                  <input
                    type="date"
                    value={bill.start}
                    onChange={(e) => update(i, 'start', e.target.value)}
                    className={inputClass}
                    aria-label={t('bills.startAria', { index: i + 1 })}
                  />
                </MiniField>
                <MiniField label={t('bills.end')}>
                  <input
                    type="date"
                    value={bill.end}
                    onChange={(e) => update(i, 'end', e.target.value)}
                    className={inputClass}
                    aria-label={t('bills.endAria', { index: i + 1 })}
                  />
                </MiniField>
              </div>
            </div>
          ))}
          <p className="text-[11px] text-stone-500">{t('bills.datesNote')}</p>
        </div>
      )}

      {review && (
        <div className="mt-2 rounded-md border border-red-300 bg-red-50 p-2.5 text-xs text-red-800">
          <p className="font-semibold">{t('errors.billReviewTitle')}</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {review.map((item, i) => (
              <li key={i}>
                <span className="font-medium">{item.file}:</span>{' '}
                {(item.notes?.length
                  ? item.notes.map(noteText)
                  : item.reasons
                ).join(' ')}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-red-700">{t('errors.billReviewHint')}</p>
        </div>
      )}
      {advisory && (
        <div className="mt-2 rounded-md border border-amber-300 bg-amber-50 p-2.5 text-xs text-amber-800">
          <ul className="list-disc space-y-0.5 pl-4">
            {advisory.map((item, i) =>
              item.notes.map((n, j) => <li key={`${i}-${j}`}>{noteText(n)}</li>),
            )}
          </ul>
        </div>
      )}
      {detected.length > 0 && (
        <div className="mt-2 space-y-2">
          {detected.map((d, i) => {
            const monthsCount = d.months.length || d.count
            const reliableAnnual = d.printedAnnual ?? (d.isAnnual ? d.lastFallbackAnnual : null)
            const singleMonth = !d.isAnnual && reliableAnnual == null && monthsCount < 2
            return (
              <div key={d.cupsKey ?? i} className="rounded-md border border-emerald-200 bg-emerald-50 p-2.5 text-xs text-emerald-900">
                <p className="font-semibold">{t('bills.detectedTitle')}</p>
                <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
                  {reliableAnnual != null ? (
                    <>
                      <dt className="text-emerald-700">{t('bills.detectedAnnual')}</dt>
                      <dd className="text-right font-medium">{nfmt.format(reliableAnnual)} kWh</dd>
                    </>
                  ) : singleMonth ? (
                    <>
                      <dt className="text-emerald-700">{t('bills.detectedMonthly')}</dt>
                      <dd className="text-right font-medium">{nfmt.format(d.monthlyKwh)} kWh</dd>
                    </>
                  ) : (
                    <>
                      <dt className="text-emerald-700">{t('bills.detectedCombined')}</dt>
                      <dd className="text-right font-medium">{nfmt.format(d.monthlyKwh)} kWh</dd>
                    </>
                  )}
                  {reliableAnnual == null && monthsCount >= 1 && (
                    <>
                      <dt className="text-emerald-700">{t('bills.detectedPeriod')}</dt>
                      <dd className="text-right font-medium">{t('bills.detectedMonths', { n: nfmt.format(monthsCount) })}</dd>
                    </>
                  )}
                  {d.tariff && (
                    <>
                      <dt className="text-emerald-700">{t('bills.detectedTariff')}</dt>
                      <dd className="text-right font-medium">{d.tariff}</dd>
                    </>
                  )}
                  {d.energyPrice != null && (
                    <>
                      <dt className="text-emerald-700">{t('bills.detectedEnergyPrice')}</dt>
                      <dd className="text-right font-medium">
                        {pfmt.format(d.energyPrice)} {d.currency}/kWh
                        {d.bonoSocial ? ` · ${t('bills.detectedBonoSocial')}` : ''}
                      </dd>
                    </>
                  )}
                  {d.avgPrice != null && (
                    <>
                      <dt className="text-emerald-700">{t('bills.detectedAvgPrice')}</dt>
                      <dd className="text-right font-medium">
                        {pfmt.format(d.avgPrice)} {d.currency}/kWh
                      </dd>
                    </>
                  )}
                </dl>
                {singleMonth && (
                  <p className="mt-1.5 text-amber-700">{t('bills.singleMonthWarning')}</p>
                )}
              </div>
            )
          })}
        </div>
      )}
      {notice && notice.length > 0 && (
        <p className="mt-2 text-xs text-amber-700">
          {[
            ...new Set(
              notice.map((p) =>
                t(`errors.${p.kind}`, { file: p.file, detail: p.detail, ...(p.params || {}) }),
              ),
            ),
          ].join(' ')}
        </p>
      )}
    </div>
  )
}
