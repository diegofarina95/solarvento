export const COUNTRY_OPTIONS = [
  'AL',
  'AD',
  'AT',
  'BY',
  'BE',
  'BA',
  'BG',
  'HR',
  'CY',
  'CZ',
  'DK',
  'EE',
  'FI',
  'FR',
  'DE',
  'GR',
  'HU',
  'IS',
  'IE',
  'IT',
  'XK',
  'LV',
  'LI',
  'LT',
  'LU',
  'MT',
  'MD',
  'MC',
  'ME',
  'NL',
  'MK',
  'NO',
  'PL',
  'PT',
  'RO',
  'RU',
  'SM',
  'RS',
  'SK',
  'SI',
  'ES',
  'SE',
  'CH',
  'TR',
  'UA',
  'GB',
  'VA',
  'EU',
]

export const COUNTRY_MAP_CENTERS = {
  AL: { lat: 41.1533, lon: 20.1683 },
  AD: { lat: 42.5063, lon: 1.5218 },
  AT: { lat: 47.5162, lon: 14.5501 },
  BY: { lat: 53.7098, lon: 27.9534 },
  BE: { lat: 50.5039, lon: 4.4699 },
  BA: { lat: 43.9159, lon: 17.6791 },
  BG: { lat: 42.7339, lon: 25.4858 },
  HR: { lat: 45.1, lon: 15.2 },
  CY: { lat: 35.1264, lon: 33.4299 },
  CZ: { lat: 49.8175, lon: 15.473 },
  DK: { lat: 56.2639, lon: 9.5018 },
  EE: { lat: 58.5953, lon: 25.0136 },
  FI: { lat: 61.9241, lon: 25.7482 },
  FR: { lat: 46.6034, lon: 1.8883 },
  DE: { lat: 51.1657, lon: 10.4515 },
  GR: { lat: 39.0742, lon: 21.8243 },
  HU: { lat: 47.1625, lon: 19.5033 },
  IS: { lat: 64.9631, lon: -19.0208 },
  IE: { lat: 53.1424, lon: -7.6921 },
  IT: { lat: 42.5042, lon: 12.6464 },
  XK: { lat: 42.6026, lon: 20.903 },
  LV: { lat: 56.8796, lon: 24.6032 },
  LI: { lat: 47.166, lon: 9.5554 },
  LT: { lat: 55.1694, lon: 23.8813 },
  LU: { lat: 49.8153, lon: 6.1296 },
  MT: { lat: 35.9375, lon: 14.3754 },
  MD: { lat: 47.4116, lon: 28.3699 },
  MC: { lat: 43.7384, lon: 7.4246 },
  ME: { lat: 42.7087, lon: 19.3744 },
  NL: { lat: 52.1326, lon: 5.2913 },
  MK: { lat: 41.6086, lon: 21.7453 },
  NO: { lat: 60.472, lon: 8.4689 },
  PL: { lat: 51.9194, lon: 19.1451 },
  PT: { lat: 39.3999, lon: -8.2245 },
  RO: { lat: 45.9432, lon: 24.9668 },
  RU: { lat: 55.7558, lon: 37.6173 },
  SM: { lat: 43.9424, lon: 12.4578 },
  RS: { lat: 44.0165, lon: 21.0059 },
  SK: { lat: 48.669, lon: 19.699 },
  SI: { lat: 46.1512, lon: 14.9955 },
  ES: { lat: 40.4168, lon: -3.7038 },
  SE: { lat: 60.1282, lon: 18.6435 },
  CH: { lat: 46.8182, lon: 8.2275 },
  TR: { lat: 39.0, lon: 35.0 },
  UA: { lat: 48.3794, lon: 31.1656 },
  GB: { lat: 54.7024, lon: -3.2766 },
  VA: { lat: 41.9029, lon: 12.4534 },
  EU: { lat: 48.8566, lon: 2.3522 },
}

const COUNTRY_ALIASES = {
  EL: 'GR',
  UK: 'GB',
  XKX: 'XK',
}

const EUROPE_BOUNDS = {
  minLat: 27.0,
  maxLat: 72.5,
  minLon: -31.5,
  maxLon: 66.0,
}

export function normalizeCountryCode(countryCode) {
  if (!countryCode) return 'EU'
  const code = String(countryCode).toUpperCase()
  return COUNTRY_OPTIONS.includes(COUNTRY_ALIASES[code] ?? code)
    ? (COUNTRY_ALIASES[code] ?? code)
    : 'EU'
}

export function isSupportedEuropeanLocation(lat, lon) {
  return (
    Number.isFinite(lat)
    && Number.isFinite(lon)
    && lat >= EUROPE_BOUNDS.minLat
    && lat <= EUROPE_BOUNDS.maxLat
    && lon >= EUROPE_BOUNDS.minLon
    && lon <= EUROPE_BOUNDS.maxLon
  )
}
