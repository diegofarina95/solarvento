"""Country coverage and light-weight location inference for pricing."""

from dataclasses import dataclass


DEFAULT_COUNTRY_CODE = "ES"
EUROPE_FALLBACK_COUNTRY_CODE = "EU"


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    currency: str
    currency_symbol: str
    # Bounding boxes are deliberately broad: they are a fallback only when the
    # geocoder did not provide a country code.
    bounds: tuple[float, float, float, float] | None = None  # min_lat, max_lat, min_lon, max_lon


COUNTRIES: dict[str, Country] = {
    "AL": Country("AL", "Albania", "ALL", "ALL", (39.5, 42.7, 19.0, 21.1)),
    "AD": Country("AD", "Andorra", "EUR", "€", (42.4, 42.7, 1.4, 1.8)),
    "AT": Country("AT", "Austria", "EUR", "€", (46.3, 49.1, 9.5, 17.2)),
    "BY": Country("BY", "Belarus", "BYN", "BYN", (51.2, 56.3, 23.1, 32.8)),
    "BE": Country("BE", "Belgium", "EUR", "€", (49.4, 51.6, 2.5, 6.5)),
    "BA": Country("BA", "Bosnia and Herzegovina", "BAM", "BAM", (42.5, 45.3, 15.7, 19.7)),
    "BG": Country("BG", "Bulgaria", "BGN", "BGN", (41.1, 44.3, 22.3, 28.7)),
    "HR": Country("HR", "Croatia", "EUR", "€", (42.1, 46.6, 13.4, 19.4)),
    "CY": Country("CY", "Cyprus", "EUR", "€", (34.5, 35.8, 32.0, 34.9)),
    "CZ": Country("CZ", "Czechia", "CZK", "CZK", (48.5, 51.1, 12.1, 18.9)),
    "DK": Country("DK", "Denmark", "DKK", "DKK", (54.5, 57.9, 8.0, 15.3)),
    "EE": Country("EE", "Estonia", "EUR", "€", (57.4, 59.8, 21.5, 28.3)),
    "FI": Country("FI", "Finland", "EUR", "€", (59.6, 70.2, 19.0, 31.6)),
    "FR": Country("FR", "France", "EUR", "€", (41.0, 51.5, -5.5, 10.0)),
    "DE": Country("DE", "Germany", "EUR", "€", (47.0, 55.5, 5.5, 15.5)),
    "GR": Country("GR", "Greece", "EUR", "€", (34.7, 41.8, 19.3, 29.7)),
    "HU": Country("HU", "Hungary", "HUF", "HUF", (45.7, 48.6, 16.0, 22.9)),
    "IS": Country("IS", "Iceland", "ISK", "ISK", (63.1, 66.7, -25.0, -13.0)),
    "IE": Country("IE", "Ireland", "EUR", "€", (51.3, 55.5, -10.8, -5.4)),
    "IT": Country("IT", "Italy", "EUR", "€", (35.0, 47.5, 6.0, 19.0)),
    "XK": Country("XK", "Kosovo", "EUR", "€", (41.8, 43.3, 20.0, 21.9)),
    "LV": Country("LV", "Latvia", "EUR", "€", (55.6, 58.1, 20.9, 28.3)),
    "LI": Country("LI", "Liechtenstein", "CHF", "CHF", (47.0, 47.3, 9.45, 9.65)),
    "LT": Country("LT", "Lithuania", "EUR", "€", (53.8, 56.5, 20.9, 26.9)),
    "LU": Country("LU", "Luxembourg", "EUR", "€", (49.4, 50.2, 5.7, 6.6)),
    "MT": Country("MT", "Malta", "EUR", "€", (35.7, 36.1, 14.1, 14.7)),
    "MD": Country("MD", "Moldova", "MDL", "MDL", (45.3, 48.7, 26.6, 30.2)),
    "MC": Country("MC", "Monaco", "EUR", "€", (43.70, 43.76, 7.38, 7.45)),
    "ME": Country("ME", "Montenegro", "EUR", "€", (41.8, 43.6, 18.4, 20.4)),
    "NL": Country("NL", "Netherlands", "EUR", "€", (50.7, 53.7, 3.3, 7.3)),
    "MK": Country("MK", "North Macedonia", "MKD", "MKD", (40.8, 42.4, 20.4, 23.1)),
    "NO": Country("NO", "Norway", "NOK", "NOK", (57.8, 71.3, 4.5, 31.5)),
    "PL": Country("PL", "Poland", "PLN", "PLN", (49.0, 54.9, 14.1, 24.2)),
    "PT": Country("PT", "Portugal", "EUR", "€", (30.0, 42.5, -31.5, -6.0)),
    "RO": Country("RO", "Romania", "RON", "RON", (43.6, 48.4, 20.2, 29.8)),
    "RU": Country("RU", "Russia", "RUB", "RUB", (41.2, 72.0, 19.6, 66.0)),
    "SM": Country("SM", "San Marino", "EUR", "€", (43.8, 44.0, 12.3, 12.6)),
    "RS": Country("RS", "Serbia", "RSD", "RSD", (42.2, 46.3, 18.8, 23.1)),
    "SK": Country("SK", "Slovakia", "EUR", "€", (47.7, 49.7, 16.8, 22.6)),
    "SI": Country("SI", "Slovenia", "EUR", "€", (45.4, 46.9, 13.3, 16.7)),
    "ES": Country("ES", "Spain", "EUR", "€", (27.0, 44.5, -19.0, 5.0)),
    "SE": Country("SE", "Sweden", "SEK", "SEK", (55.0, 69.1, 10.5, 24.5)),
    "CH": Country("CH", "Switzerland", "CHF", "CHF", (45.8, 47.9, 5.9, 10.5)),
    "TR": Country("TR", "Turkey", "TRY", "TRY", (35.8, 42.2, 25.6, 45.0)),
    "UA": Country("UA", "Ukraine", "UAH", "UAH", (44.0, 52.4, 22.1, 40.3)),
    "GB": Country("GB", "United Kingdom", "GBP", "£", (49.5, 61.5, -8.5, 2.5)),
    "VA": Country("VA", "Vatican City", "EUR", "€", (41.89, 41.91, 12.44, 12.47)),
    "EU": Country("EU", "Europe", "EUR", "€", None),
}


EUROPE_COUNTRY_CODES = tuple(code for code in COUNTRIES if code != EUROPE_FALLBACK_COUNTRY_CODE)


COUNTRY_ALIASES = {
    "UK": "GB",
    "EL": "GR",
    "XKX": "XK",
}


# Geographical Europe plus Atlantic islands commonly covered in residential
# solar use cases. This is a product-support boundary, not a legal definition.
EUROPE_BOUNDS = (27.0, 72.5, -31.5, 66.0)


COORDINATE_INFERENCE_PRIORITY = (
    "VA",
    "MC",
    "SM",
    "LI",
    "AD",
    "LU",
    "MT",
    "XK",
    "ME",
    "SI",
    "SK",
    "CH",
    "AT",
    "BE",
    "NL",
    "CY",
    "MD",
    "MK",
    "AL",
    "BA",
    "BG",
    "HR",
    "CZ",
    "DK",
    "EE",
    "IE",
    "IS",
    "LV",
    "LT",
    "PT",
    "RO",
    "RS",
    "TR",
    "GR",
    "HU",
    "FI",
    "NO",
    "PL",
    "SE",
    "BY",
    "UA",
    "ES",
    "IT",
    "FR",
    "DE",
    "GB",
    "RU",
)


def _in_bounds(lat: float, lon: float, bounds: tuple[float, float, float, float]) -> bool:
    min_lat, max_lat, min_lon, max_lon = bounds
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


# El rectángulo general baja hasta 27° solo por las islas atlánticas; sin estas
# cajas específicas dejaba pasar el norte de África y Oriente Próximo (El Cairo,
# Marrakech, Tel Aviv…), contradiciendo el mensaje de "solo Europa".
_ATLANTIC_ISLAND_BOXES = (
    (27.0, 29.6, -18.5, -13.0),  # Canarias
    (32.3, 33.3, -17.6, -15.8),  # Madeira
    (36.8, 39.9, -31.5, -24.8),  # Azores
)
_EUROPE_MAINLAND_MIN_LAT = 34.4  # Chipre/Creta/Malta quedan dentro; Israel/Egipto fuera


def ensure_european_location(lat: float, lon: float) -> bool:
    """Return whether the coordinates are inside SolVento's current coverage."""

    if not _in_bounds(lat, lon, EUROPE_BOUNDS):
        return False
    if lat >= _EUROPE_MAINLAND_MIN_LAT:
        return True
    return any(_in_bounds(lat, lon, box) for box in _ATLANTIC_ISLAND_BOXES)


def normalize_country_code(country_code: str | None) -> str:
    """Return a supported country code or the generic Europe fallback."""

    if not country_code:
        return DEFAULT_COUNTRY_CODE
    code = COUNTRY_ALIASES.get(country_code.upper(), country_code.upper())
    if code in COUNTRIES:
        return code
    return EUROPE_FALLBACK_COUNTRY_CODE


def country_for_coordinates(lat: float, lon: float, country_code: str | None = None) -> Country:
    """Resolve the pricing country from explicit code first, then coordinates."""

    if country_code:
        return COUNTRIES[normalize_country_code(country_code)]

    seen = set()
    countries_by_specificity = []
    for code in COORDINATE_INFERENCE_PRIORITY:
        if code in COUNTRIES:
            countries_by_specificity.append(COUNTRIES[code])
            seen.add(code)
    countries_by_specificity.extend(
        country for code, country in COUNTRIES.items() if code not in seen and country.bounds
    )
    for country in countries_by_specificity:
        if country.bounds and _in_bounds(lat, lon, country.bounds):
            return country
    return COUNTRIES[EUROPE_FALLBACK_COUNTRY_CODE]
