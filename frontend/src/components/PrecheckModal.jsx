// Pop-up de confirmación (cortafuegos). Muestra números concretos y, según el
// nivel de confianza del backend (precheck), pide confirmar (MEDIA) o avisa de
// datos poco fiables (BAJA). Los botones dicen la ACCIÓN, no "Aceptar/Cancelar".

function KeyNumbers({ nums, i18n, fmt }) {
  const { t } = i18n
  const rows = [
    nums.annual_kwh != null && [t('precheck.annualLabel'), `${fmt.nf.format(nums.annual_kwh)} kWh`],
    nums.price_eur_kwh != null && [t('precheck.priceLabel'), `${fmt.nf3.format(nums.price_eur_kwh)} €/kWh`],
    nums.kwp != null && [t('precheck.powerLabel'), `${fmt.nf1.format(nums.kwp)} kWp`],
  ].filter(Boolean)
  if (!rows.length) return null
  return (
    <dl className="mt-3 divide-y divide-stone-200 rounded-lg border border-stone-200 bg-stone-50">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between px-3 py-2 text-sm">
          <dt className="text-stone-500">{label}</dt>
          <dd className="font-semibold text-stone-800">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function PrecheckModal({ precheck, i18n, fmt, onConfirm, onEdit }) {
  const { t } = i18n
  if (!precheck) return null
  const low = precheck.level === 'low'
  const failed = (precheck.checks || []).filter((c) => !c.passed)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="precheck-title"
    >
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl">
        <div className="flex items-start gap-3">
          <span
            className={`mt-0.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${low ? 'bg-red-500' : 'bg-amber-500'}`}
          />
          <div className="min-w-0">
            <h2 id="precheck-title" className="text-base font-semibold text-stone-900">
              {t(low ? 'precheck.lowTitle' : 'precheck.mediumTitle')}
            </h2>
            <p className="mt-1 text-sm text-stone-600">
              {t(low ? 'precheck.lowIntro' : 'precheck.mediumIntro')}
            </p>
          </div>
        </div>

        {low ? (
          <ul className="mt-3 space-y-1.5 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {failed.map((c) => (
              <li key={c.code} className="flex gap-2">
                <span aria-hidden className="text-red-400">•</span>
                <span>{t(`precheck.checks.${c.code}`, c.params || {})}</span>
              </li>
            ))}
          </ul>
        ) : (
          <KeyNumbers nums={precheck.key_numbers || {}} i18n={i18n} fmt={fmt} />
        )}

        {/* Botones: la acción PRINCIPAL cambia según el nivel. En BAJA, calcular
            igualmente existe pero es secundaria frente a revisar la tabla. */}
        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          {low ? (
            <>
              <button
                type="button"
                onClick={onConfirm}
                className="rounded-lg px-3 py-2 text-sm font-medium text-stone-500 hover:text-stone-800"
              >
                {t('precheck.calcAnyway')}
              </button>
              <button
                type="button"
                onClick={onEdit}
                className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-semibold text-white hover:bg-stone-700"
              >
                {t('precheck.reviewTable')}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={onEdit}
                className="rounded-lg px-3 py-2 text-sm font-medium text-stone-500 hover:text-stone-800"
              >
                {t('precheck.editBefore')}
              </button>
              <button
                type="button"
                onClick={onConfirm}
                className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-500"
              >
                {t('precheck.calcWithThese')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
