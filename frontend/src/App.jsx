import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import AdSlot from './components/AdSlot'
import SunArc from './components/SunArc'
import LocationSearch from './components/LocationSearch'
import MapPicker from './components/MapPicker'
import SolarForm from './components/SolarForm'
import { ApiError, apiErrorMessage, solarEstimate } from './api'
import { parseLocaleNumber } from './numberParsing'

// Results arrastra Recharts (~40% del bundle) y solo se ve tras calcular:
// cargarlo en diferido recorta el JS inicial de la página.
const Results = lazy(() => import('./components/Results'))
import { createI18n, LANGUAGE_OPTIONS } from './i18n/translations'
import {
  COUNTRY_MAP_CENTERS,
  COUNTRY_OPTIONS,
  isSupportedEuropeanLocation,
  normalizeCountryCode,
} from './pricing/countries'

const INITIAL_POSITION = { lat: 40.4168, lon: -3.7038 }

const SUPPORTED_LANGUAGES = new Set(LANGUAGE_OPTIONS.map((option) => option.code))

function detectInitialLanguage() {
  if (typeof navigator === 'undefined') return 'es'
  const candidates = [...(navigator.languages ?? []), navigator.language].filter(Boolean)
  for (const candidate of candidates) {
    const base = candidate.toLowerCase().split('-')[0]
    if (SUPPORTED_LANGUAGES.has(base)) return base
  }
  return 'es'
}

function requireLocaleNumber(value, label, t, options) {
  const parsed = parseLocaleNumber(value, options)
  if (parsed == null) throw new Error(t('errors.invalidNumber', { label }))
  return parsed
}

export default function App() {
  const [language, setLanguage] = useState(detectInitialLanguage)
  const i18n = useMemo(() => createI18n(language), [language])
  const { t } = i18n
  const [position, setPosition] = useState(INITIAL_POSITION)
  const [locationLabel, setLocationLabel] = useState(null)
  const [countryCode, setCountryCode] = useState('ES')
  const [advanced, setAdvanced] = useState(false)
  const [form, setForm] = useState({
    peakPower: '5',
    tilt: '30',
    azimuth: '0',
    losses: '14',
    consumption: '',
    cost: '',
    price: '',
    panelPower: '450',
    surplusPrice: '',
    costPerKwp: '',
    batteryCost: '',
    subsidy: '',
    occupancyProfile: 'standard',
    hasHeatPump: false,
    hasEv: false,
    hasPool: false,
  })
  const [bills, setBills] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [results, setResults] = useState(null)
  const resultsRef = useRef(null)

  // El idioma del documento debe seguir al selector: los lectores de pantalla
  // pronuncian el texto con la fonética del lang declarado.
  useEffect(() => {
    document.documentElement.lang = language
    document.title = `SolVento — ${t('app.subtitle')}`
  }, [language, t])

  // En el layout apilado (<lg) los resultados quedan bajo el formulario:
  // sin este scroll, en móvil pulsar «Calcular» no muestra nada visible.
  useEffect(() => {
    if ((results || error) && window.innerWidth < 1024) {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [results, error])

  function handleLocationSelect({ lat, lon, label, countryCode: detectedCountry }) {
    setPosition({ lat, lon })
    setLocationLabel(label ?? null)
    if (detectedCountry) setCountryCode(normalizeCountryCode(detectedCountry))
  }

  function handleBillLocationDetected(parsedBill) {
    const detectedCountry = parsedBill?.country_code
    const normalizedCountry = detectedCountry ? normalizeCountryCode(detectedCountry) : null
    if (normalizedCountry) setCountryCode(normalizedCountry)

    const lat = Number(parsedBill?.lat)
    const lon = Number(parsedBill?.lon)
    if (isSupportedEuropeanLocation(lat, lon)) {
      const billLocationLabel =
        [parsedBill.postal_code, parsedBill.city].filter(Boolean).join(' ') || null
      setPosition({ lat, lon })
      setLocationLabel(
        parsedBill.location_label
          ?? parsedBill.supply_address
          ?? billLocationLabel
          ?? null,
      )
      return
    }

    const center = normalizedCountry ? COUNTRY_MAP_CENTERS[normalizedCountry] : null
    if (center) {
      setPosition(center)
      setLocationLabel(
        t('location.fromBillCountry', { country: t(`countries.${normalizedCountry}`) }),
      )
    }
  }

  async function calculate() {
    setLoading(true)
    setError(null)
    try {
      const params = {
        lat: position.lat,
        lon: position.lon,
        peak_power_kwp: requireLocaleNumber(form.peakPower, t('form.peakPower'), t),
        country_code: countryCode,
      }
      const parsedBills = bills.map((b, index) => ({
        ...b,
        index,
        parsedKwh: parseLocaleNumber(b.kwh, { thousands: true }),
        parsedEnergyAmount: parseLocaleNumber(b.energyAmount, { thousands: true }),
        parsedTotalAmount: parseLocaleNumber(b.totalAmount ?? b.amount, { thousands: true }),
      }))
      // Una fila con kWh ilegible no se descarta en silencio: el usuario
      // creería que su factura cuenta en el cálculo.
      const invalidBill = parsedBills.find(
        (b) => String(b.kwh).trim() !== '' && (b.parsedKwh == null || b.parsedKwh <= 0),
      )
      if (invalidBill) {
        throw new Error(
          t('errors.invalidNumber', {
            label: `${t('bills.title')} #${invalidBill.index + 1} (kWh)`,
          }),
        )
      }
      const validBills = parsedBills.filter((b) => b.parsedKwh != null && b.parsedKwh > 0)
      if (validBills.length) {
        params.bills = validBills.map((b) => ({
          kwh: b.parsedKwh,
          energy_eur:
            b.parsedEnergyAmount != null && b.parsedEnergyAmount > 0
              ? b.parsedEnergyAmount
              : null,
          total_eur:
            b.parsedTotalAmount != null && b.parsedTotalAmount > 0
              ? b.parsedTotalAmount
              : null,
          amount_eur:
            b.parsedTotalAmount != null && b.parsedTotalAmount > 0
              ? b.parsedTotalAmount
              : null,
          currency: b.currency || null,
          month: b.month ? Number(b.month) : null,
          start_date: b.start || null,
          end_date: b.end || null,
          // Líneas de impuestos del parser (coste marginal evitado): se
          // reenvían tal cual; si faltan, el backend usa los tipos normativos.
          power_eur: b.power_eur ?? null,
          iee_eur: b.iee_eur ?? null,
          iva_eur: b.iva_eur ?? null,
          iva_rate: b.iva_rate ?? null,
          vat_base_eur: b.vat_base_eur ?? null,
          // Histórico mensual del parser: fuente determinista del consumo anual
          consumption_history: b.consumptionHistory ?? null,
        }))
      }
      if (advanced) {
        params.tilt_deg = requireLocaleNumber(form.tilt, t('form.tilt', { value: '' }), t)
        params.azimuth_deg = requireLocaleNumber(form.azimuth, t('form.fineAzimuth'), t)
        params.loss_pct = requireLocaleNumber(form.losses, t('form.losses'), t)
        params.panel_power_w = requireLocaleNumber(form.panelPower, t('form.panelPower'), t)
        if (form.surplusPrice) {
          params.surplus_price_eur_kwh = requireLocaleNumber(
            form.surplusPrice,
            t('form.surplusPrice'),
            t,
          )
        }
        if (form.costPerKwp) {
          params.cost_per_kwp_eur = requireLocaleNumber(
            form.costPerKwp,
            t('form.costPerKwp'),
            t,
            { thousands: true },
          )
        }
        if (form.batteryCost) {
          params.battery_cost_per_kwh_eur = requireLocaleNumber(
            form.batteryCost,
            t('form.batteryCost'),
            t,
            { thousands: true },
          )
        }
        if (form.subsidy) {
          params.subsidy_eur = requireLocaleNumber(form.subsidy, t('form.subsidy'), t, {
            thousands: true,
          })
        }
        if (form.price) {
          params.electricity_price_eur_kwh = requireLocaleNumber(
            form.price,
            t('form.electricityPrice'),
            t,
          )
        }
        if (form.cost) {
          params.installation_cost_eur = requireLocaleNumber(
            form.cost,
            t('form.installationCost'),
            t,
            { thousands: true },
          )
        }
        if (!validBills.length && form.consumption) {
          params.annual_consumption_kwh = requireLocaleNumber(
            form.consumption,
            t('form.annualConsumption'),
            t,
            { thousands: true },
          )
        }
        params.occupancy_profile = form.occupancyProfile
        params.has_heat_pump = Boolean(form.hasHeatPump)
        params.has_ev = Boolean(form.hasEv)
        params.has_pool = Boolean(form.hasPool)
      }
      setResults(await solarEstimate(params))
    } catch (err) {
      setError(err instanceof ApiError ? apiErrorMessage(err, t) : err.message || t('errors.generic'))
      setResults(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div id="app-shell" className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-8">
        <SunArc />
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl font-bold tracking-tight text-stone-900">
              Sol<span className="text-amber-600">Vento</span>
            </h1>
            <p className="mt-1.5 max-w-3xl text-stone-600">{t('app.subtitle')}</p>
          </div>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            aria-label={t('app.language')}
            className="rounded-lg border border-stone-300 bg-white/70 px-3 py-1.5 text-sm text-stone-700 backdrop-blur-sm"
          >
            {LANGUAGE_OPTIONS.map((option) => (
              <option key={option.code} value={option.code}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-stone-500">
          <span className="font-semibold text-stone-600">{t('app.europeNotice')}</span>{' '}
          {t('app.disclaimer')}
        </p>
        <AdSlot placement="top" />
      </header>

      <div className="grid gap-8 lg:grid-cols-[380px_1fr]">
        <section className="space-y-4">
          <div className="card-solar p-4">
            <h2 className="section-eyebrow mb-3">
              {t('app.locationSection')}
            </h2>
            <LocationSearch onSelect={handleLocationSelect} i18n={i18n} />
            <div className="mt-3">
              <MapPicker position={position} onChange={handleLocationSelect} />
            </div>
            <p className="mt-2 text-xs text-stone-500">
              {locationLabel ?? t('location.defaultHint')}{' '}
              <span className="tabular-nums">
                ({position.lat.toFixed(4)}, {position.lon.toFixed(4)})
              </span>
            </p>
            <label className="mt-3 block">
              <span className="mb-1 block text-sm font-medium text-stone-700">
                {t('countries.label')}
              </span>
              <select
                value={countryCode}
                onChange={(e) => setCountryCode(e.target.value)}
                className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
              >
                {COUNTRY_OPTIONS.map((code) => (
                  <option key={code} value={code}>
                    {t(`countries.${code}`)}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-stone-500">{t('countries.hint')}</span>
            </label>
          </div>

          <div className="card-solar p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="section-eyebrow">
                {t('app.installationSection')}
              </h2>
              <div className="flex rounded-lg border border-stone-200 p-0.5 text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setAdvanced(false)}
                  className={`rounded-md px-2.5 py-1 transition ${!advanced ? 'bg-stone-900 text-white' : 'text-stone-500 hover:text-stone-900'}`}
                >
                  {t('app.basic')}
                </button>
                <button
                  type="button"
                  onClick={() => setAdvanced(true)}
                  className={`rounded-md px-2.5 py-1 transition ${advanced ? 'bg-stone-900 text-white' : 'text-stone-500 hover:text-stone-900'}`}
                >
                  {t('app.advanced')}
                </button>
              </div>
            </div>
            <SolarForm
              form={form}
              setForm={setForm}
              bills={bills}
              setBills={setBills}
              advanced={advanced}
              onSubmit={calculate}
              loading={loading}
              i18n={i18n}
              onBillLocationDetected={handleBillLocationDetected}
            />
          </div>
        </section>

        <section ref={resultsRef} aria-live="polite">
          {error && (
            <div
              role="alert"
              className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
            >
              <p className="font-semibold">{t('app.errorTitle')}</p>
              <p className="mt-0.5">{error}</p>
            </div>
          )}

          {loading && (
            <div
              role="status"
              className="flex h-64 items-center justify-center rounded-xl border border-dashed border-stone-300 text-stone-500"
            >
              <div className="text-center">
                <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-stone-300 border-t-amber-500" />
                {t('app.loading')}
              </div>
            </div>
          )}

          {!loading && results && (
            <Suspense
              fallback={
                <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-stone-300 text-stone-500">
                  <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-stone-300 border-t-amber-500" />
                </div>
              }
            >
              <Results data={results} i18n={i18n} />
            </Suspense>
          )}

          {!loading && !results && !error && (
            <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-stone-300 text-center text-stone-500">
              <p className="max-w-sm px-4 text-sm">{t('app.empty')}</p>
            </div>
          )}

          <p className="mt-4 text-xs text-stone-500">{t('app.professionalDisclaimer')}</p>
          <AdSlot placement="footer" />
        </section>
      </div>
    </div>
  )
}
