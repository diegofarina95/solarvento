import BillsInput from './BillsInput'

const ORIENTATIONS = [
  { labelKey: 'orientations.south', suffix: 'S', value: 0 },
  { labelKey: 'orientations.southwest', suffix: 'SW', value: 45 },
  { labelKey: 'orientations.west', suffix: 'W', value: 90 },
  { labelKey: 'orientations.northwest', suffix: 'NW', value: 135 },
  { labelKey: 'orientations.north', suffix: 'N', value: 180 },
  { labelKey: 'orientations.northeast', suffix: 'NE', value: -135 },
  { labelKey: 'orientations.east', suffix: 'E', value: -90 },
  { labelKey: 'orientations.southeast', suffix: 'SE', value: -45 },
]

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-stone-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-stone-500">{hint}</span>}
    </label>
  )
}

const inputClass =
  'w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-200'

export default function SolarForm({
  form,
  setForm,
  bills,
  setBills,
  advanced,
  onSubmit,
  loading,
  i18n,
  onBillLocationDetected,
}) {
  const { t } = i18n
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })
  const setBool = (key) => (e) => setForm({ ...form, [key]: e.target.checked })
  const hasBills = bills.length > 0

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit()
      }}
      className="space-y-4"
    >
      <Field label={t('form.peakPower')}>
        <input
          type="number"
          min="0.1"
          max="10000"
          step="0.1"
          required
          value={form.peakPower}
          onChange={set('peakPower')}
          className={inputClass}
        />
      </Field>

      <BillsInput
        bills={bills}
        setBills={setBills}
        i18n={i18n}
        onLocationDetected={onBillLocationDetected}
      />

      {advanced && (
        <>
          <Field label={t('form.tilt', { value: form.tilt })}>
            <input
              type="range"
              min="0"
              max="90"
              step="1"
              value={form.tilt}
              onChange={set('tilt')}
              className="w-full accent-amber-500"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label={t('form.orientation')}>
              <select value={form.azimuth} onChange={set('azimuth')} className={inputClass}>
                {/* Con un azimut fino intermedio (p.ej. 30°) el select quedaría
                    en blanco; se muestra el valor actual como opción propia */}
                {!ORIENTATIONS.some((o) => String(o.value) === String(form.azimuth)) && (
                  <option value={form.azimuth}>{form.azimuth}°</option>
                )}
                {ORIENTATIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {t(o.labelKey)} ({o.suffix})
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('form.fineAzimuth')} hint={t('form.fineAzimuthHint')}>
              <input
                type="number"
                min="-180"
                max="180"
                step="1"
                value={form.azimuth}
                onChange={set('azimuth')}
                className={inputClass}
              />
            </Field>
          </div>

          <Field label={t('form.losses')} hint={t('form.lossesHint')}>
            <input
              type="number"
              min="0"
              max="50"
              step="0.5"
              value={form.losses}
              onChange={set('losses')}
              className={inputClass}
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field
              label={t('form.annualConsumption')}
              hint={hasBills ? t('form.annualConsumptionHintBills') : t('form.annualConsumptionHintManual')}
            >
              <input
                type="text"
                inputMode="decimal"
                value={form.consumption}
                onChange={set('consumption')}
                placeholder="3500"
                disabled={hasBills}
                className={`${inputClass} disabled:bg-stone-100 disabled:text-stone-400`}
              />
            </Field>
            <Field label={t('form.installationCost')} hint={t('form.installationCostHint')}>
              <input
                type="text"
                inputMode="decimal"
                value={form.cost}
                onChange={set('cost')}
                placeholder={t('form.installationCostPlaceholder')}
                className={inputClass}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field
              label={t('form.electricityPrice')}
              hint={hasBills ? t('form.electricityPriceHint') : undefined}
            >
              <input
                type="text"
                inputMode="decimal"
                value={form.price}
                onChange={set('price')}
                placeholder={hasBills ? t('form.electricityPricePlaceholderBills') : '0.15'}
                className={inputClass}
              />
            </Field>
            <Field label={t('form.panelPower')}>
              <input
                type="number"
                min="50"
                max="1000"
                step="5"
                value={form.panelPower}
                onChange={set('panelPower')}
                className={inputClass}
              />
            </Field>
          </div>

          <details className="rounded-lg border border-stone-200 p-3">
            <summary className="cursor-pointer text-sm font-medium text-stone-700">
              {t('form.consumptionProfile')}
            </summary>
            <div className="mt-3 space-y-3">
              <Field label={t('form.occupancyProfile')} hint={t('form.occupancyProfileHint')}>
                <select
                  value={form.occupancyProfile}
                  onChange={set('occupancyProfile')}
                  className={inputClass}
                >
                  <option value="standard">{t('form.occupancy.standard')}</option>
                  <option value="home_day">{t('form.occupancy.home_day')}</option>
                  <option value="evening">{t('form.occupancy.evening')}</option>
                  <option value="night">{t('form.occupancy.night')}</option>
                </select>
              </Field>
              <div className="grid gap-2 sm:grid-cols-3">
                <label className="flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700">
                  <input
                    type="checkbox"
                    checked={Boolean(form.hasHeatPump)}
                    onChange={setBool('hasHeatPump')}
                    className="h-4 w-4 accent-amber-500"
                  />
                  {t('form.hasHeatPump')}
                </label>
                <label className="flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700">
                  <input
                    type="checkbox"
                    checked={Boolean(form.hasEv)}
                    onChange={setBool('hasEv')}
                    className="h-4 w-4 accent-amber-500"
                  />
                  {t('form.hasEv')}
                </label>
                <label className="flex items-center gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-700">
                  <input
                    type="checkbox"
                    checked={Boolean(form.hasPool)}
                    onChange={setBool('hasPool')}
                    className="h-4 w-4 accent-amber-500"
                  />
                  {t('form.hasPool')}
                </label>
              </div>
            </div>
          </details>

          <details className="rounded-lg border border-stone-200 p-3">
            <summary className="cursor-pointer text-sm font-medium text-stone-700">
              {t('form.economicAssumptions')}
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Field label={t('form.surplusPrice')} hint={t('form.surplusPriceHint')}>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.surplusPrice}
                  onChange={set('surplusPrice')}
                  placeholder="0.06"
                  className={inputClass}
                />
              </Field>
              <Field label={t('form.costPerKwp')} hint={t('form.costPerKwpHint')}>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.costPerKwp}
                  onChange={set('costPerKwp')}
                  placeholder="1250"
                  className={inputClass}
                />
              </Field>
              <Field label={t('form.batteryCost')} hint={t('form.batteryCostHint')}>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.batteryCost}
                  onChange={set('batteryCost')}
                  placeholder="650"
                  className={inputClass}
                />
              </Field>
            </div>
          </details>
        </>
      )}

      <button
        type="submit"
        disabled={loading}
        className="btn-solar w-full px-4 py-2.5 text-sm"
      >
        {loading ? t('form.calculating') : t('form.calculate')}
      </button>
    </form>
  )
}
