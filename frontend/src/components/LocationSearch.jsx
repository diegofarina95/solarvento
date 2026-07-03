import { useState } from 'react'
import { apiErrorMessage, geocode } from '../api'

export default function LocationSearch({ onSelect, i18n }) {
  const { t } = i18n
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState(null)

  async function search(e) {
    e.preventDefault()
    if (query.trim().length < 3) return
    setSearching(true)
    setError(null)
    try {
      const found = await geocode(query.trim())
      setResults(found)
      if (found.length === 1) pick(found[0])
    } catch (err) {
      setError(apiErrorMessage(err, t))
      setResults(null)
    } finally {
      setSearching(false)
    }
  }

  function pick(result) {
    setResults(null)
    setQuery(result.display_name)
    onSelect({
      lat: result.lat,
      lon: result.lon,
      label: result.display_name,
      countryCode: result.country_code,
    })
  }

  return (
    <div className="relative">
      <form onSubmit={search} className="flex gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('location.placeholder')}
          className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-200"
          aria-label={t('location.aria')}
        />
        <button
          type="submit"
          disabled={searching || query.trim().length < 3}
          className="shrink-0 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
        >
          {searching ? t('location.searching') : t('location.search')}
        </button>
      </form>

      {error && <p className="mt-1.5 text-sm text-red-700">{error}</p>}
      {results && results.length === 0 && (
        <p className="mt-1.5 text-sm text-stone-500">{t('location.noResults')}</p>
      )}
      {results && results.length > 1 && (
        <ul className="absolute z-[1000] mt-1 w-full overflow-hidden rounded-lg border border-stone-200 bg-white shadow-lg">
          {results.map((r) => (
            <li key={`${r.lat},${r.lon}`}>
              <button
                type="button"
                onClick={() => pick(r)}
                className="w-full px-3 py-2 text-left text-sm hover:bg-amber-50"
              >
                {r.display_name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
