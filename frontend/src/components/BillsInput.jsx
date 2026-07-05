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
  const date = startDate && endDate
    ? new Date((startDate.getTime() + endDate.getTime()) / 2)
    : (startDate ?? endDate)
  return date ? String(date.getMonth() + 1) : ''
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
  const [detected, setDetected] = useState([])
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
    setDetected([])
    const added = []
    const problems = []
    const reviews = []
    const detectedList = []
    let detectedLocation = null
    // Los PDFs se parsean en paralelo: con varios archivos y un parser lento
    // la espera secuencial se multiplicaba por el número de facturas.
    const results = await Promise.allSettled(fileList.map((file) => parseBill(file)))
    results.forEach((result, index) => {
      const file = fileList[index]
      if (result.status === 'rejected') {
        const err = result.reason
        // Se guardan datos, NO texto ya traducido: así el aviso se traduce al
        // idioma actual en cada render (antes quedaba fijado al idioma de la
        // importación y podía verse en inglés dentro de la app en español).
        problems.push({
          kind: 'billParseFailed',
          file: file.name,
          detail: err instanceof ApiError ? err.detail : null,
        })
        return
      }
      const parsed = result.value
      if (parsed.kwh == null) {
        problems.push({ kind: 'billNoConsumption', file: file.name })
      }
      added.push(newRow({
        month: parsed.month ? String(parsed.month) : inferBillMonth(parsed.start_date, parsed.end_date),
        kwh: parsed.kwh ?? '',
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
      }))
      if (parsed.needs_review && parsed.review_reasons?.length) {
        // Guarda de reconciliación/precio efectivo: el consumo detectado es
        // sospechoso. Se marca en rojo y con el motivo concreto para que el
        // usuario confirme el kWh antes de calcular (mejor revisar que un
        // número seguro y equivocado).
        reviews.push({ file: file.name, reasons: parsed.review_reasons })
      } else if (parsed.warnings?.length) {
        problems.push({ kind: 'billNeedsReview', file: file.name })
      }
      if (parsed.lat != null && parsed.lon != null) {
        detectedLocation = parsed
      } else if (!detectedLocation && parsed.country_code) {
        detectedLocation = parsed
      }

      // Resumen "Datos detectados" (da confianza tras importar).
      const res = parsed.consumption_resolution ?? {}
      const annualKwh = res.annual_kwh ?? parsed.kwh
      const total = parsed.total_eur ?? parsed.amount_eur ?? null
      const months = res.months_real ?? null
      if (annualKwh != null) {
        detectedList.push({
          file: file.name,
          annualKwh,
          // Una sola factura mensual: se muestra el consumo MENSUAL, no el anual.
          singleMonth: !!res.single_month,
          monthlyKwh: res.monthly_kwh ?? parsed.kwh,
          // El gasto anual solo es fiable si la factura cubre ~un año.
          spendAnnual: months != null && months >= 11 && total ? total : null,
          tariff: parsed.tariff ?? null,
          months,
          bonoSocial: !!parsed.bono_social,
          // Precio efectivo like-with-like: importe ÷ consumo del MISMO periodo.
          price: total && parsed.kwh ? total / parsed.kwh : null,
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
    if (detectedList.length) setDetected(detectedList)
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
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif"
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
                <span className="font-medium">{item.file}:</span> {item.reasons.join(' ')}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-red-700">{t('errors.billReviewHint')}</p>
        </div>
      )}
      {detected.length > 0 && (
        <div className="mt-2 space-y-2">
          {detected.map((d, i) => (
            <div key={i} className="rounded-md border border-emerald-200 bg-emerald-50 p-2.5 text-xs text-emerald-900">
              <p className="font-semibold">{t('bills.detectedTitle')}</p>
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
                {d.singleMonth ? (
                  <>
                    <dt className="text-emerald-700">{t('bills.detectedMonthly')}</dt>
                    <dd className="text-right font-medium">{nfmt.format(d.monthlyKwh)} kWh</dd>
                  </>
                ) : (
                  <>
                    <dt className="text-emerald-700">{t('bills.detectedAnnual')}</dt>
                    <dd className="text-right font-medium">{nfmt.format(d.annualKwh)} kWh</dd>
                  </>
                )}
                {d.spendAnnual != null && (
                  <>
                    <dt className="text-emerald-700">{t('bills.detectedSpend')}</dt>
                    <dd className="text-right font-medium">{nfmt.format(d.spendAnnual)} {d.currency}</dd>
                  </>
                )}
                {d.tariff && (
                  <>
                    <dt className="text-emerald-700">{t('bills.detectedTariff')}</dt>
                    <dd className="text-right font-medium">{d.tariff}</dd>
                  </>
                )}
                {d.months != null && (
                  <>
                    <dt className="text-emerald-700">{t('bills.detectedPeriod')}</dt>
                    <dd className="text-right font-medium">{t('bills.detectedMonths', { n: nfmt.format(d.months) })}</dd>
                  </>
                )}
                {d.price != null && (
                  <>
                    <dt className="text-emerald-700">{t('bills.detectedPrice')}</dt>
                    <dd className="text-right font-medium">
                      {pfmt.format(d.price)} {d.currency}/kWh
                      {d.bonoSocial ? ` · ${t('bills.detectedBonoSocial')}` : ''}
                    </dd>
                  </>
                )}
              </dl>
              {d.singleMonth && (
                <p className="mt-1.5 text-amber-700">{t('bills.singleMonthWarning')}</p>
              )}
            </div>
          ))}
        </div>
      )}
      {notice && notice.length > 0 && (
        <p className="mt-2 text-xs text-amber-700">
          {notice
            .map((p) => t(`errors.${p.kind}`, { file: p.file, detail: p.detail }))
            .join(' ')}
        </p>
      )}
    </div>
  )
}
