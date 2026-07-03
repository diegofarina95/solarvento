"""Provider catalogue and normalized provider price records."""

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Provider:
    name: str
    country_code: str
    homepage_url: str
    feed_url: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ProviderPriceRecord:
    provider_name: str
    country_code: str
    updated_at: date
    panel_price_per_w: float | None = None
    inverter_price_per_kwp: float | None = None
    battery_price_per_kwh: float | None = None
    mounting_price_per_kwp: float | None = None
    labour_price_per_kwp: float | None = None
    turnkey_cost_per_kwp: float | None = None
    vat_rate: float | None = None


PROVIDERS_BY_COUNTRY: dict[str, list[Provider]] = {
    "AL": [
        Provider("Vega Solar", "AL", "https://vegasolar.al/"),
        Provider("ENF Solar Albania directory", "AL", "https://www.enfsolar.com/directory/installer"),
    ],
    "AD": [
        Provider("AutoSolar", "AD", "https://autosolar.es/"),
        Provider("ENF Solar Andorra directory", "AD", "https://www.enfsolar.com/directory/installer"),
    ],
    "AT": [
        Provider("Krannich Solar Austria", "AT", "https://www.krannich-solar.com/"),
        Provider("BayWa r.e. Solar Distribution Austria", "AT", "https://solar-distribution.baywa-re.at/"),
        Provider("Memodo Austria", "AT", "https://www.memodo.at/"),
    ],
    "BY": [
        Provider("Unisolar", "BY", "https://unisolar.by/"),
        Provider("ENF Solar Belarus directory", "BY", "https://www.enfsolar.com/directory/installer"),
    ],
    "BE": [
        Provider("Solarclarity Belgium", "BE", "https://www.solarclarity.be/"),
        Provider("ESTG", "BE", "https://www.estg.eu/"),
        Provider("Rexel Belgium", "BE", "https://www.rexel.be/"),
    ],
    "BA": [
        Provider("EMT Solar", "BA", "https://emtsolar.ba/"),
        Provider("ENF Solar Bosnia and Herzegovina directory", "BA", "https://www.enfsolar.com/directory/installer"),
    ],
    "BG": [
        Provider("Solarity Bulgaria", "BG", "https://solarity.eu/"),
        Provider("Elmark", "BG", "https://www.elmarkholding.eu/"),
        Provider("ENF Solar Bulgaria directory", "BG", "https://www.enfsolar.com/directory/installer"),
    ],
    "HR": [
        Provider("Solvis", "HR", "https://solvis.hr/"),
        Provider("Solarity Croatia", "HR", "https://solarity.eu/"),
        Provider("ENF Solar Croatia directory", "HR", "https://www.enfsolar.com/directory/installer"),
    ],
    "CY": [
        Provider("Green Air", "CY", "https://greenair-cy.com/"),
        Provider("ENF Solar Cyprus directory", "CY", "https://www.enfsolar.com/directory/installer"),
    ],
    "CZ": [
        Provider("Solarity", "CZ", "https://solarity.eu/"),
        Provider("Memodo Czechia", "CZ", "https://www.memodo.cz/"),
        Provider("PVshop.eu", "CZ", "https://www.pvshop.eu/"),
    ],
    "DK": [
        Provider("Solar Danmark", "DK", "https://www.solar.eu/"),
        Provider("Krannich Solar Denmark", "DK", "https://www.krannich-solar.com/"),
        Provider("ENF Solar Denmark directory", "DK", "https://www.enfsolar.com/directory/installer"),
    ],
    "EE": [
        Provider("Solarstone", "EE", "https://solarstone.com/"),
        Provider("Enefit", "EE", "https://www.enefit.ee/"),
        Provider("ENF Solar Estonia directory", "EE", "https://www.enfsolar.com/directory/installer"),
    ],
    "FI": [
        Provider("Onninen Finland", "FI", "https://www.onninen.fi/"),
        Provider("Scanoffice", "FI", "https://www.scanoffice.fi/"),
        Provider("ENF Solar Finland directory", "FI", "https://www.enfsolar.com/directory/installer"),
    ],
    "ES": [
        Provider("Leroy Merlin España", "ES", "https://www.leroymerlin.es/"),
        Provider("SolarPlak", "ES", "https://solarplak.es/"),
        Provider("AutoSolar", "ES", "https://autosolar.es/"),
        Provider("Cambio Energético", "ES", "https://www.cambioenergetico.com/"),
        Provider("SotySolar", "ES", "https://sotysolar.es/"),
    ],
    "FR": [
        Provider("Oscaro Power", "FR", "https://www.oscaro-power.com/"),
        Provider("Mon Kit Solaire", "FR", "https://www.monkitsolaire.fr/"),
        Provider("Leroy Merlin France", "FR", "https://www.leroymerlin.fr/"),
    ],
    "IT": [
        Provider("Leroy Merlin Italia", "IT", "https://www.leroymerlin.it/"),
        Provider("VP Solar", "IT", "https://www.vpsolar.com/"),
        Provider("Solar Energy Point", "IT", "https://www.solarenergypoint.it/"),
    ],
    "GR": [
        Provider("BIG SOLAR", "GR", "https://www.bigsolar.gr/"),
        Provider("Kafkas", "GR", "https://www.kafkas.gr/"),
        Provider("Krannich Solar Greece", "GR", "https://www.krannich-solar.com/"),
    ],
    "HU": [
        Provider("Wagner Solar Hungária", "HU", "https://www.wagnersolar.hu/"),
        Provider("Solarity Hungary", "HU", "https://solarity.eu/"),
        Provider("ENF Solar Hungary directory", "HU", "https://www.enfsolar.com/directory/installer"),
    ],
    "IS": [
        Provider("ENF Solar Iceland directory", "IS", "https://www.enfsolar.com/directory/installer"),
        Provider("IEA PVPS country reports", "IS", "https://iea-pvps.org/national-survey-reports/"),
    ],
    "IE": [
        Provider("Midsummer Ireland", "IE", "https://midsummer.ie/"),
        Provider("Solartricity", "IE", "https://www.solartricity.ie/"),
        Provider("ENF Solar Ireland directory", "IE", "https://www.enfsolar.com/directory/installer"),
    ],
    "XK": [
        Provider("Jaha Solar", "XK", "https://jaha-solar.com/"),
        Provider("ENF Solar Kosovo directory", "XK", "https://www.enfsolar.com/directory/installer"),
    ],
    "LV": [
        Provider("AJ Power", "LV", "https://ajpower.lv/"),
        Provider("ENF Solar Latvia directory", "LV", "https://www.enfsolar.com/directory/installer"),
    ],
    "LI": [
        Provider("Solarmarkt", "LI", "https://www.solarmarkt.ch/"),
        Provider("Krannich Solar Switzerland", "LI", "https://www.krannich-solar.com/"),
    ],
    "LT": [
        Provider("SoliTek", "LT", "https://www.solitek.eu/"),
        Provider("ENF Solar Lithuania directory", "LT", "https://www.enfsolar.com/directory/installer"),
    ],
    "LU": [
        Provider("Energipark Réiden", "LU", "https://www.energipark.lu/"),
        Provider("Soluxtec", "LU", "https://soluxtec.com/"),
        Provider("ENF Solar Luxembourg directory", "LU", "https://www.enfsolar.com/directory/installer"),
    ],
    "MT": [
        Provider("Solar Solutions", "MT", "https://solarsolutions.com.mt/"),
        Provider("Bajada New Energy", "MT", "https://bajada.com.mt/"),
        Provider("ENF Solar Malta directory", "MT", "https://www.enfsolar.com/directory/installer"),
    ],
    "MD": [
        Provider("Volta", "MD", "https://volta.md/"),
        Provider("EcoEnergy Moldova", "MD", "https://ecoenergy.md/"),
        Provider("ENF Solar Moldova directory", "MD", "https://www.enfsolar.com/directory/installer"),
    ],
    "MC": [
        Provider("EDF ENR", "MC", "https://www.edfenr.com/"),
        Provider("DualSun", "MC", "https://dualsun.com/"),
    ],
    "ME": [
        Provider("EPCG Solar Gradnja", "ME", "https://www.epcg.com/"),
        Provider("ENF Solar Montenegro directory", "ME", "https://www.enfsolar.com/directory/installer"),
    ],
    "NL": [
        Provider("ESTG", "NL", "https://www.estg.eu/"),
        Provider("Solarclarity", "NL", "https://www.solarclarity.nl/"),
        Provider("Libra Energy", "NL", "https://www.libra.energy/"),
    ],
    "MK": [
        Provider("PiKCELL Group", "MK", "https://pikcellgroup.com/"),
        Provider("ENF Solar North Macedonia directory", "MK", "https://www.enfsolar.com/directory/installer"),
    ],
    "NO": [
        Provider("Otovo Norway", "NO", "https://www.otovo.no/"),
        Provider("Solcellespesialisten", "NO", "https://solcellespesialisten.no/"),
        Provider("ENF Solar Norway directory", "NO", "https://www.enfsolar.com/directory/installer"),
    ],
    "PL": [
        Provider("Menlo Electric", "PL", "https://menloelectric.com/"),
        Provider("KENO", "PL", "https://www.keno-energy.com/"),
        Provider("Corab", "PL", "https://corab.pl/"),
    ],
    "DE": [
        Provider("Memodo", "DE", "https://www.memodo.de/"),
        Provider("IBC Solar", "DE", "https://www.ibc-solar.de/"),
        Provider("zolar", "DE", "https://www.zolar.de/"),
    ],
    "PT": [
        Provider("Leroy Merlin Portugal", "PT", "https://www.leroymerlin.pt/"),
        Provider("FF Solar", "PT", "https://ffsolar.com/"),
        Provider("SolarShop Portugal", "PT", "https://www.solarshop.pt/"),
    ],
    "RO": [
        Provider("Wattkraft Romania", "RO", "https://www.wattkraft.ro/"),
        Provider("Solarity Romania", "RO", "https://solarity.eu/"),
        Provider("ENF Solar Romania directory", "RO", "https://www.enfsolar.com/directory/installer"),
    ],
    "RU": [
        Provider("Hevel Solar", "RU", "https://www.hevelsolar.com/"),
        Provider("ENF Solar Russia directory", "RU", "https://www.enfsolar.com/directory/installer"),
    ],
    "SM": [
        Provider("VP Solar", "SM", "https://www.vpsolar.com/"),
        Provider("Leroy Merlin Italia", "SM", "https://www.leroymerlin.it/"),
    ],
    "RS": [
        Provider("MT-KOMEX", "RS", "https://mt-komex.co.rs/"),
        Provider("Solarity Serbia", "RS", "https://solarity.eu/"),
        Provider("ENF Solar Serbia directory", "RS", "https://www.enfsolar.com/directory/installer"),
    ],
    "SK": [
        Provider("Solarity Slovakia", "SK", "https://solarity.eu/"),
        Provider("Photomate", "SK", "https://photomate.eu/"),
        Provider("ENF Solar Slovakia directory", "SK", "https://www.enfsolar.com/directory/installer"),
    ],
    "SI": [
        Provider("BISOL", "SI", "https://www.bisol.com/"),
        Provider("GEN-I Sonce", "SI", "https://gen-i.si/"),
        Provider("ENF Solar Slovenia directory", "SI", "https://www.enfsolar.com/directory/installer"),
    ],
    "SE": [
        Provider("Midsummer", "SE", "https://midsummer.se/"),
        Provider("Svea Solar", "SE", "https://sveasolar.com/"),
        Provider("ENF Solar Sweden directory", "SE", "https://www.enfsolar.com/directory/installer"),
    ],
    "CH": [
        Provider("Solarmarkt", "CH", "https://www.solarmarkt.ch/"),
        Provider("Krannich Solar Switzerland", "CH", "https://www.krannich-solar.com/"),
        Provider("BayWa r.e. Solar Distribution Switzerland", "CH", "https://solar-distribution.baywa-re.ch/"),
    ],
    "TR": [
        Provider("CW Enerji", "TR", "https://cw-enerji.com/"),
        Provider("Smart Güneş Teknolojileri", "TR", "https://smartgunes.com/"),
        Provider("ENF Solar Turkey directory", "TR", "https://www.enfsolar.com/directory/installer"),
    ],
    "UA": [
        Provider("KNESS", "UA", "https://kness.energy/"),
        Provider("Atmosfera", "UA", "https://www.atmosfera.ua/"),
        Provider("ENF Solar Ukraine directory", "UA", "https://www.enfsolar.com/directory/installer"),
    ],
    "GB": [
        Provider("ITS Technologies", "GB", "https://www.itstechnologies.shop/"),
        Provider("Midsummer Wholesale", "GB", "https://midsummerwholesale.co.uk/"),
        Provider("Solartricity", "GB", "https://www.solartricity.ie/"),
    ],
    "VA": [
        Provider("VP Solar", "VA", "https://www.vpsolar.com/"),
        Provider("Leroy Merlin Italia", "VA", "https://www.leroymerlin.it/"),
    ],
    "EU": [
        Provider("IEA PVPS country reports", "EU", "https://iea-pvps.org/"),
        Provider("SolarPower Europe", "EU", "https://www.solarpowereurope.org/"),
        Provider("ENF Solar installer directory", "EU", "https://www.enfsolar.com/directory/installer"),
    ],
}


PRICE_FIELDS = (
    "panel_price_per_w",
    "inverter_price_per_kwp",
    "battery_price_per_kwh",
    "mounting_price_per_kwp",
    "labour_price_per_kwp",
    "turnkey_cost_per_kwp",
    "vat_rate",
)


def provider_names(country_code: str) -> list[str]:
    return [provider.name for provider in PROVIDERS_BY_COUNTRY.get(country_code, [])]


def parse_provider_records(payload: Any, country_code: str) -> list[ProviderPriceRecord]:
    """Parse a maintained JSON feed into normalized provider records.

    Supported shapes:
    - {"records": [{...}, {...}]}
    - {"countries": {"ES": {"turnkey_cost_per_kwp": 1250, ...}}}
    - [{...}, {...}]
    """

    raw_records: list[dict[str, Any]]
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        raw_records = payload["records"]
    elif isinstance(payload, dict) and isinstance(payload.get("countries"), dict):
        country_payload = payload["countries"].get(country_code)
        raw_records = [country_payload] if isinstance(country_payload, dict) else []
    elif isinstance(payload, list):
        raw_records = payload
    else:
        raw_records = []

    records = []
    for item in raw_records:
        if not isinstance(item, dict):
            continue
        code = str(item.get("country_code") or country_code).upper()
        if code != country_code:
            continue
        updated_raw = item.get("updated_at")
        try:
            updated_at = date.fromisoformat(updated_raw) if updated_raw else date.today()
        except (TypeError, ValueError):
            updated_at = date.today()
        values = {
            field: _optional_float(item.get(field))
            for field in PRICE_FIELDS
        }
        records.append(
            ProviderPriceRecord(
                provider_name=str(item.get("provider_name") or item.get("source") or "Provider feed"),
                country_code=code,
                updated_at=updated_at,
                **values,
            )
        )
    return records


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
