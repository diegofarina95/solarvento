"""Extracción de datos de facturas de la luz.

Extrae del texto del PDF: kWh consumidos, importe total y periodo de
facturación. Es heurístico (cada comercializadora maqueta distinto): se
devuelve también una lista de avisos con lo que no se pudo detectar para que
el usuario lo corrija a mano en el formulario.
"""

import io
import re
from datetime import date

from pypdf import PdfReader

from .profiles import DAYS_PER_MONTH, MONTHLY_WEIGHTS

MONTH_NAMES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
}

COUNTRY_HINTS = [
    ("GB", r"\b(?:united kingdom|great britain|reino unido|uk vat|gb)\b|£"),
    ("ES", r"\b(?:españa|spain|cnmc|endesa|iberdrola|naturgy)\b"),
    ("FR", r"\b(?:france|edf|enedis|république française|facture d['’]électricité)\b"),
    ("IT", r"\b(?:italia|italy|enel|servizio elettrico)\b"),
    ("DE", r"\b(?:deutschland|germany|stromrechnung|bundesnetzagentur)\b"),
    ("PT", r"\b(?:portugal|edp|erse|fatura de eletricidade)\b"),
]

LANGUAGE_HINTS = [
    ("es", r"\b(?:factura|periodo de facturación|consumo|importe)\b"),
    ("fr", r"\b(?:facture|période|consommation|montant)\b"),
    ("it", r"\b(?:bolletta|fattura|periodo|consumo|importo)\b"),
    ("pt", r"\b(?:fatura|período|consumo|montante)\b"),
    ("de", r"\b(?:rechnung|verbrauch|betrag|strom)\b"),
    ("en", r"\b(?:bill|invoice|billing period|consumption|amount)\b"),
]

_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"

# Monedas europeas tal como aparecen junto al total (símbolo o código ISO)
_CURRENCY = r"(?:€|EUR|£|GBP|zł|PLN|Kč|CZK|CHF|Ft|HUF|lei|RON|лв|BGN|kn|kr\.?|DKK|NOK|SEK|ISK)"

# Etiquetas de "total de la factura" por idioma. Son específicas, así que tras
# ellas se acepta el importe aunque la moneda no esté pegada al número.
_TOTAL_LABELS = [
    # español
    r"total\s+(?:importe\s+)?factura",
    r"importe\s+total",
    r"total\s+a\s+pagar",
    # francés
    r"montant\s+(?:total\s+)?(?:ttc|[aà]\s+payer|factur[ée]?)",
    r"total\s+ttc",
    r"net\s+[aà]\s+payer",
    # italiano
    r"totale\s+(?:da\s+pagare|bolletta|fattura|documento)",
    r"importo\s+(?:totale|da\s+pagare)",
    # alemán
    r"rechnungsbetrag",
    r"gesamtbetrag",
    r"zu\s+zahlen(?:der\s+betrag)?",
    r"endbetrag",
    # portugués
    r"total\s+da\s+fatura",
    r"valor\s+a\s+pagar",
    # inglés
    r"total\s+(?:amount\s+)?(?:due|to\s+pay|payable)",
    r"amount\s+due",
    r"total\s+charges",
    r"total\s+bill",
]
MAX_BILL_KWH = 20_000
SUSPICIOUS_MONTHLY_KWH = 5_000
SUSPICIOUS_MIN_PRICE_EUR_KWH = 0.05
SUSPICIOUS_MAX_PRICE_EUR_KWH = 1.00


class BillParseError(Exception):
    pass


def _to_float(s: str) -> float:
    """Convierte números en formato europeo ('1.234,56'), inglés ('1,234.56') o simple.

    Con ambos separadores, el que aparece más a la derecha es el decimal.
    Con solo coma se asume decimal europeo ('71,39'); con solo puntos de miles
    ('1.234') se asume miles.
    """
    s = re.sub(r"\s+", "", s.strip())
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            return float(s.replace(".", "").replace(",", "."))  # 1.234,56
        return float(s.replace(",", ""))  # 1,234.56
    if "," in s:
        if re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}", s):
            # dos o más grupos de miles con coma solo pueden ser formato inglés
            return float(s.replace(",", ""))
        return float(s.replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        # punto como separador de miles sin decimales: '1.234' → 1234
        return float(s.replace(".", ""))
    return float(s)


def _parse_date(day: str, month: str, year: str) -> date | None:
    try:
        m = MONTH_NAMES.get(month.lower()) or int(month)
        y = int(year)
        if y < 100:
            y += 2000
        return date(y, m, int(day))
    except ValueError:
        return None


def _find_dates(text: str) -> list[date]:
    dates = []
    # dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
    for d, m, y in re.findall(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b", text):
        parsed = _parse_date(d, m, y)
        if parsed and 2000 <= parsed.year <= 2100:
            dates.append(parsed)
    # 'dd de enero de yyyy'
    for d, m, y in re.findall(
        r"\b(\d{1,2})\s+de\s+([a-zA-Záéíóú]+)\s+(?:de\s+)?(\d{4})\b", text, re.IGNORECASE
    ):
        parsed = _parse_date(d, m, y)
        if parsed:
            dates.append(parsed)
    return dates


def _period_consumption_candidates(text: str) -> list[float]:
    """Valores kWh etiquetados como consumo del periodo, no lecturas acumuladas."""
    patterns = [
        rf"(?:consumo\s+(?:en\s+el\s+periodo|del\s+periodo|facturado|total)"
        rf"|energ[ií]a\s+(?:consumida|facturada)"
        rf"|consommation\s+(?:sur\s+la\s+p[ée]riode|de\s+la\s+p[ée]riode|factur[ée]e|totale)"
        rf"|[ée]nergie\s+(?:consomm[ée]e|factur[ée]e))[^\n€]{{0,80}}?{_NUM}\s*kWh",
        rf"{_NUM}\s*kWh[^\n€]{{0,80}}?"
        rf"(?:consumo\s+(?:en\s+el\s+periodo|del\s+periodo|facturado|total)"
        rf"|energ[ií]a\s+(?:consumida|facturada)"
        rf"|consommation\s+(?:sur\s+la\s+p[ée]riode|de\s+la\s+p[ée]riode|factur[ée]e|totale)"
        rf"|[ée]nergie\s+(?:consomm[ée]e|factur[ée]e))",
    ]
    candidates: list[float] = []
    for pattern in patterns:
        candidates.extend(_to_float(m) for m in re.findall(pattern, text, re.IGNORECASE))
    return [v for v in candidates if 1 <= v <= MAX_BILL_KWH]


def _reading_kind(label: str) -> str:
    normalized = label.lower()
    if re.search(r"anterior|ancien|pr[ée]c[ée]dent|previous|precedente", normalized):
        return "previous"
    return "current"


def _reading_difference_candidates(text: str) -> list[float]:
    """Consumos derivados de parejas 'lectura anterior' / 'lectura actual'."""
    reading_re = re.compile(
        rf"("
        rf"lectura\s+(?:anterior|actual)"
        rf"|(?:ancien|nouveau)\s+relev[ée]"
        rf"|relev[ée]\s+(?:pr[ée]c[ée]dent|actuel)"
        rf"|index\s+(?:ancien|nouveau)"
        rf"|(?:previous|current)\s+reading"
        rf"|lettura\s+(?:precedente|attuale)"
        rf")[^\d]{{0,50}}{_NUM}\s*kWh",
        re.IGNORECASE,
    )
    readings = [
        (_reading_kind(match.group(1)), _to_float(match.group(2)), match.start(), match.end())
        for match in reading_re.finditer(text)
    ]

    candidates: list[float] = []
    i = 0
    while i < len(readings) - 1:
        label_a, value_a, _start_a, end_a = readings[i]
        label_b, value_b, start_b, _end_b = readings[i + 1]
        if label_a != label_b and start_b - end_a <= 250:
            diff = abs(value_b - value_a)
            if 1 <= diff <= MAX_BILL_KWH:
                candidates.append(diff)
                i += 2
                continue
        i += 1
    return candidates


def _fallback_kwh_candidates(text: str) -> list[float]:
    """Último recurso: kWh en líneas que no parecen lecturas de contador."""
    candidates: list[float] = []
    for line in text.splitlines():
        if re.search(
            r"\b(?:lectura|contador|compteur|relev[ée]|index|meter|reading|lettura|z[aä]hler)\b",
            line,
            re.IGNORECASE,
        ):
            continue
        candidates.extend(_to_float(m) for m in re.findall(rf"{_NUM}\s*kWh", line, re.IGNORECASE))
    return [v for v in candidates if 1 <= v <= MAX_BILL_KWH]


def _looks_like_accumulated_reading(kwh: float, amount_eur: float | None) -> bool:
    if amount_eur is None:
        return False
    return (
        kwh >= SUSPICIOUS_MONTHLY_KWH
        and amount_eur / kwh < SUSPICIOUS_MIN_PRICE_EUR_KWH
    )


def _is_anomalous_effective_price(price: float) -> bool:
    return price < SUSPICIOUS_MIN_PRICE_EUR_KWH or price > SUSPICIOUS_MAX_PRICE_EUR_KWH


def _select_consumption_kwh(
    period_candidates: list[float],
    reading_candidates: list[float],
    fallback_candidates: list[float],
    amount_eur: float | None,
    warnings: list[str],
) -> float | None:
    """Elige consumo real evitando confundir lecturas acumuladas con kWh del periodo."""
    period_plausible = [
        kwh for kwh in period_candidates
        if not _looks_like_accumulated_reading(kwh, amount_eur)
    ]
    if period_plausible:
        return max(period_plausible)

    if reading_candidates:
        if period_candidates:
            warnings.append(
                "Consumo calculado por diferencia de lecturas; se ignoró una lectura acumulada."
            )
        return round(sum(reading_candidates), 1)

    fallback_plausible = [
        kwh for kwh in fallback_candidates
        if not _looks_like_accumulated_reading(kwh, amount_eur)
    ]
    if fallback_plausible:
        return max(fallback_plausible)

    if period_candidates or fallback_candidates:
        warnings.append(
            "El valor kWh detectado parece una lectura acumulada; introduce el consumo del periodo."
        )
    return None


def _find_total_amount(text: str, warnings: list[str]) -> float | None:
    """Importe total de la factura en la moneda del documento.

    Prioridad: etiqueta específica de total (con la moneda antes, después o
    ausente) > etiqueta genérica 'total' con moneda pegada > el mayor importe
    plausible junto a un símbolo de moneda.
    """
    # La moneda puede ir antes (£81.20) o después (81,20 €) del número; tras una
    # etiqueta específica también se acepta sin moneda, pero nunca un kWh/kW.
    for label in _TOTAL_LABELS:
        pattern = (
            rf"(?:{label})[^\d\n]{{0,40}}?{_CURRENCY}?\s*{_NUM}(?!\s*k[WV])\s*{_CURRENCY}?"
        )
        found = re.findall(pattern, text, re.IGNORECASE)
        if found:
            return _to_float(found[-1])

    # 'total' a secas es demasiado genérico: solo cuenta con moneda adyacente
    generic = re.findall(
        rf"total[^\d\n]{{0,20}}(?:{_CURRENCY}\s*{_NUM}|{_NUM}\s*{_CURRENCY})",
        text,
        re.IGNORECASE,
    )
    if generic:
        value = next(v for v in generic[-1] if v)
        return _to_float(value)

    amounts = [
        _to_float(next(v for v in m if v))
        for m in re.findall(
            rf"(?:{_CURRENCY}\s*{_NUM}|{_NUM}\s*{_CURRENCY})", text, re.IGNORECASE
        )
    ]
    plausible = [v for v in amounts if 5 <= v <= 5000]
    if plausible:
        warnings.append("Importe total estimado (no se encontró la etiqueta 'Total factura')")
        return max(plausible)
    warnings.append("No se detectó el importe de la factura")
    return None


def _detect_from_hints(text: str, hints: list[tuple[str, str]]) -> str | None:
    for code, pattern in hints:
        if re.search(pattern, text, re.IGNORECASE):
            return code
    return None


def extract_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # pypdf lanza tipos variados con PDFs corruptos
        raise BillParseError(f"No se pudo leer el PDF: {exc}") from exc


def parse_bill_text(text: str) -> dict:
    """Extrae kwh, importe y periodo del texto de una factura.

    Devuelve {kwh, amount_eur, start_date, end_date, warnings[]} con None en
    lo que no se haya detectado.
    """
    if not text.strip():
        raise BillParseError(
            "El PDF no contiene texto extraíble (puede ser un escaneo). Introduce los datos a mano."
        )

    warnings: list[str] = []
    result: dict = {
        "kwh": None,
        "amount_eur": None,
        "month": None,
        "start_date": None,
        "end_date": None,
        "country_code": _detect_from_hints(text, COUNTRY_HINTS),
        "country_name": None,
        "supply_address": None,
        "postal_code": None,
        "city": None,
        "region": None,
        "location_label": None,
        "lat": None,
        "lon": None,
        "language": _detect_from_hints(text, LANGUAGE_HINTS),
        "parser": "local",
        "warnings": warnings,
    }

    # --- Importe total (multi-idioma y multi-moneda) ---
    result["amount_eur"] = _find_total_amount(text, warnings)

    # --- kWh: consumo del periodo > diferencia de lecturas > kWh no acumulados ---
    period_candidates = _period_consumption_candidates(text)
    reading_candidates = _reading_difference_candidates(text)
    fallback_candidates = _fallback_kwh_candidates(text)
    result["kwh"] = _select_consumption_kwh(
        period_candidates,
        reading_candidates,
        fallback_candidates,
        result["amount_eur"],
        warnings,
    )
    if result["kwh"] is None:
        warnings.append("No se detectó el consumo en kWh")

    # --- Periodo de facturación ---
    period = re.search(
        r"(?:periodo|per[ií]odo|p[ée]riode)[^\n]{0,80}?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})"
        r"[^\n]{0,30}?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if period:
        parts = [re.split(r"[/.\-]", g) for g in period.groups()]
        start = _parse_date(*parts[0])
        end = _parse_date(*parts[1])
        if start and end and start < end:
            result["start_date"], result["end_date"] = start, end
    if result["start_date"] is None:
        dates = sorted(set(_find_dates(text)))
        # Buscar un par de fechas separadas ~1 mes (25-35 días) como periodo
        for i in range(len(dates) - 1):
            for j in range(i + 1, len(dates)):
                delta = (dates[j] - dates[i]).days
                if 25 <= delta <= 35:
                    result["start_date"], result["end_date"] = dates[i], dates[j]
                    break
            if result["start_date"]:
                break
    if result["start_date"] is None:
        warnings.append("No se detectó el periodo de facturación")
    else:
        start, end = result["start_date"], result["end_date"]
        result["month"] = (start + (end - start) / 2).month

    return result


def parse_bill_pdf(pdf_bytes: bytes) -> dict:
    return parse_bill_text(extract_text(pdf_bytes))


def _bill_month(bill: dict, start: date | None, end: date | None) -> int | None:
    """Mes representativo de la factura: explícito o punto medio del periodo."""
    if start and end:
        return (start + (end - start) / 2).month
    if bill.get("month") is not None:
        return int(bill["month"])
    return None


def _estimate_monthly_from_samples(
    monthly_kwh: list[float], monthly_days: list[float]
) -> tuple[float | None, list[float] | None, list[int]]:
    """Completa una curva anual a partir de meses observados.

    Cada mes observado se normaliza a mes completo. Los meses no observados se
    rellenan con el perfil residencial por defecto, escalado al nivel de consumo
    que implican los meses reales.
    """
    observed = [m for m, days in enumerate(monthly_days) if days > 0]
    if not observed:
        return None, None, []

    full_months = [0.0] * 12
    for m in observed:
        full_months[m] = monthly_kwh[m] / monthly_days[m] * DAYS_PER_MONTH[m]

    weight_sum = sum(MONTHLY_WEIGHTS)
    fractions = [w / weight_sum for w in MONTHLY_WEIGHTS]
    if len(observed) == 12:
        monthly = full_months
    else:
        annual_estimates = [full_months[m] / fractions[m] for m in observed]
        confidence_weights = [monthly_days[m] for m in observed]
        annual = sum(
            estimate * weight
            for estimate, weight in zip(annual_estimates, confidence_weights, strict=True)
        ) / sum(confidence_weights)

        observed_sum = sum(full_months[m] for m in observed)
        remaining_annual = annual - observed_sum
        remaining_fraction = 1 - sum(fractions[m] for m in observed)
        monthly = full_months[:]
        if remaining_annual > 0 and remaining_fraction > 0:
            for m in range(12):
                if m not in observed:
                    monthly[m] = remaining_annual * fractions[m] / remaining_fraction
        else:
            annual = observed_sum

    monthly = [round(v, 1) for v in monthly]
    return round(sum(monthly), 1), monthly, [m + 1 for m in observed]


def aggregate_bills(bills: list[dict]) -> dict:
    """Agrega facturas (kwh, amount_eur, days) a consumo anual y precio medio.

    Cada factura: {kwh, amount_eur (opcional), month (opcional),
    start_date/end_date o days}. Si hay meses identificables, estima una curva
    anual completa usando esos meses como muestras reales y el perfil
    residencial por defecto para completar los huecos.
    """
    total_kwh = 0.0
    total_days = 0.0
    total_eur = 0.0
    kwh_with_eur = 0.0
    priced_bill_count = 0
    ignored_price_bill_count = 0
    monthly_kwh = [0.0] * 12
    monthly_days = [0.0] * 12

    for bill in bills:
        kwh = float(bill["kwh"])
        amount = float(bill["amount_eur"]) if bill.get("amount_eur") else None
        if amount is not None and kwh >= SUSPICIOUS_MONTHLY_KWH:
            implicit_price = amount / kwh
            if implicit_price < SUSPICIOUS_MIN_PRICE_EUR_KWH:
                raise BillParseError(
                    "Una factura parece usar una lectura acumulada del contador como consumo. "
                    "Introduce el consumo del periodo (kWh) o importa una factura con lectura "
                    "actual y anterior para calcular la diferencia."
                )
        days = bill.get("days")
        start, end = bill.get("start_date"), bill.get("end_date")
        month = _bill_month(bill, start, end)
        if days is None and start and end:
            days = (end - start).days
        if days is None and month is not None:
            days = DAYS_PER_MONTH[month - 1]
        days = float(days) if days else 30.4
        total_kwh += kwh
        total_days += days
        if amount is not None:
            effective_price = amount / kwh
            if _is_anomalous_effective_price(effective_price):
                ignored_price_bill_count += 1
            else:
                total_eur += amount
                kwh_with_eur += kwh
                priced_bill_count += 1
        if month is not None:
            monthly_kwh[month - 1] += kwh
            monthly_days[month - 1] += days

    if total_kwh <= 0 or total_days <= 0:
        raise BillParseError("Las facturas no contienen consumos válidos")

    annual_from_months, monthly, observed_months = _estimate_monthly_from_samples(
        monthly_kwh, monthly_days
    )
    annual_kwh = annual_from_months if annual_from_months is not None else total_kwh / total_days * 365.25
    price = round(total_eur / kwh_with_eur, 4) if kwh_with_eur > 0 else None

    if len(observed_months) == 12:
        seasonality_source = "full_year_bills"
    elif observed_months:
        seasonality_source = "estimated_from_sampled_months"
    else:
        seasonality_source = "annualized_by_days"

    return {
        "annual_kwh": round(annual_kwh, 1),
        "avg_price_eur_kwh": price,
        "bill_count": len(bills),
        "priced_bill_count": priced_bill_count,
        "ignored_price_bill_count": ignored_price_bill_count,
        "days_covered": round(total_days),
        "monthly_kwh": monthly,
        "observed_months": observed_months,
        "seasonality_source": seasonality_source,
    }
