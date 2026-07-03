"""Extracción de datos de facturas de la luz.

Extrae del texto del PDF: kWh consumidos, importe total y periodo de
facturación. Es heurístico (cada comercializadora maqueta distinto): se
devuelve también una lista de avisos con lo que no se pudo detectar para que
el usuario lo corrija a mano en el formulario.
"""

import io
import re
from datetime import date, timedelta

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
DEFAULT_CURRENCY = "EUR"

CURRENCY_SYMBOLS = {
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "zł": "PLN",
    "PLN": "PLN",
    "Kč": "CZK",
    "CZK": "CZK",
    "CHF": "CHF",
    "Ft": "HUF",
    "HUF": "HUF",
    "lei": "RON",
    "RON": "RON",
    "лв": "BGN",
    "BGN": "BGN",
    "kn": "EUR",
    "DKK": "DKK",
    "NOK": "NOK",
    "SEK": "SEK",
    "ISK": "ISK",
}

PRICE_PLAUSIBILITY_BY_CURRENCY = {
    "EUR": (0.05, 1.00),
    "GBP": (0.05, 1.50),
    "CHF": (0.05, 1.50),
    "PLN": (0.20, 5.00),
    "CZK": (1.00, 25.00),
    "HUF": (10.00, 250.00),
    "RON": (0.20, 5.00),
    "BGN": (0.10, 2.50),
    "DKK": (0.30, 12.00),
    "NOK": (0.30, 12.00),
    "SEK": (0.30, 12.00),
    "ISK": (5.00, 150.00),
    "TRY": (0.50, 20.00),
    "ALL": (2.00, 80.00),
    "BAM": (0.10, 2.50),
    "BYN": (0.10, 3.50),
    "MDL": (1.00, 15.00),
    "MKD": (2.00, 40.00),
    "RUB": (2.00, 40.00),
    "RSD": (2.00, 80.00),
    "UAH": (1.00, 25.00),
}

_ENERGY_CHARGE_LABELS = [
    r"energ[ií]a\s+(?:consumida|facturada|activa)",
    r"t[ée]rmino\s+de\s+energ[ií]a",
    r"consumo\s+(?:facturado|electricidad|el[ée]ctrico)",
    r"electricity\s+(?:used|charge|charges|consumption)",
    r"energy\s+(?:used|charge|charges|consumption)",
    r"consommation\s+(?:[ée]lectricit[ée]|factur[ée]e|totale)",
    r"[ée]nergie\s+(?:consomm[ée]e|factur[ée]e|active)",
    r"energia\s+(?:consumata|fatturata|attiva)",
    r"consumo\s+fatturato",
    r"energia\s+(?:consumida|faturada|ativa)",
    r"verbrauch(?:spreis)?",
    r"arbeitspreis",
]

_FIXED_CHARGE_LABELS = [
    r"potencia\s+contratada",
    r"t[ée]rmino\s+de\s+potencia",
    r"alquiler\s+(?:de\s+)?(?:equipos|contador)",
    r"standing\s+charge",
    r"meter\s+(?:rental|charge)",
    r"abonnement",
    r"puissance\s+(?:souscrite|abonn[ée]e)",
    r"potenza\s+(?:impegnata|disponibile)",
    r"quota\s+fissa",
    r"termo\s+fixo",
    r"grundpreis",
    r"z[aä]hler(?:miete|geb[üu]hr)",
]

_TAX_CHARGE_LABELS = [
    r"\biva\b",
    r"\bvat\b",
    r"\btva\b",
    r"impuesto",
    r"tax(?:es)?",
    r"imposta",
    r"accise",
    r"contribui[cç][aã]o",
    r"steuer",
]

# Líneas necesarias para derivar el coste marginal evitado por factura:
# IEE_rate ≈ impuesto eléctrico / (término energía + término potencia)
# IVA_rate ≈ IVA / base imponible (o el % impreso en la etiqueta)
_POWER_CHARGE_LABELS = [
    r"t[ée]rmino\s+de\s+potencia",
    r"potencia\s+contratada",
]

_IEE_LABELS = [
    r"impuesto\s+(?:especial\s+)?(?:sobre\s+la\s+)?electricidad",
    r"impuesto\s+el[ée]ctrico",
]

# Si el IEE viene agrupado con otros conceptos ("y cargos regulados"), el
# importe no sirve para derivar el tipo: se cae al fallback normativo.
_IEE_LUMPED_LABELS = [r"cargos", r"regulad"]

_VAT_BASE_LABELS = [r"base\s+imponible"]

_IVA_AMOUNT_LABELS = [r"\biva\b"]

_CHARGE_EXCLUDE_LABELS = [
    r"total",
    r"importe\s+total",
    r"amount\s+due",
    r"net\s+[aà]\s+payer",
    r"zu\s+zahlen",
    r"totale\s+da\s+pagare",
    r"valor\s+a\s+pagar",
]


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
    candidates.extend(_consumption_table_candidates(text))
    return [v for v in candidates if 1 <= v <= MAX_BILL_KWH]


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _line_is_plain_number(line: str) -> bool:
    return re.fullmatch(_NUM, line.strip()) is not None


def _line_has_unit_price(line: str) -> bool:
    return re.search(r"/\s*kWh\b", line, re.IGNORECASE) is not None


def _consumption_table_candidates(text: str) -> list[float]:
    """Extrae kWh de tablas donde la unidad está en la cabecera, no junto al valor."""
    lines = _clean_lines(text)
    candidates: list[float] = []

    for index, line in enumerate(lines):
        normalized = line.lower()
        if not re.fullmatch(r"(?:total|total\s+energ[ií]a\s+consumida)", normalized):
            continue
        if index + 1 >= len(lines) or not _line_is_plain_number(lines[index + 1]):
            continue

        nearby_before = " ".join(lines[max(0, index - 6):index]).lower()
        nearby_after = " ".join(lines[index + 2:index + 5]).lower()
        if "kwh" not in nearby_before and not _line_has_unit_price(nearby_after):
            continue
        candidates.append(_to_float(lines[index + 1]))

    tariff_labels = r"punta|llano|valle|peak|off[-\s]?peak|shoulder"
    tariff_values: list[float] = []
    for index, line in enumerate(lines[:-2]):
        if not re.fullmatch(tariff_labels, line, re.IGNORECASE):
            continue
        if not _line_is_plain_number(lines[index + 1]):
            continue
        if not _line_has_unit_price(lines[index + 2]):
            continue
        tariff_values.append(_to_float(lines[index + 1]))
    if tariff_values:
        candidates.append(round(sum(tariff_values), 1))

    return candidates


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


def _price_bounds(currency: str | None) -> tuple[float, float]:
    return PRICE_PLAUSIBILITY_BY_CURRENCY.get(
        (currency or DEFAULT_CURRENCY).upper(),
        PRICE_PLAUSIBILITY_BY_CURRENCY[DEFAULT_CURRENCY],
    )


def _looks_like_accumulated_reading(
    kwh: float, amount: float | None, currency: str | None = None
) -> bool:
    if amount is None:
        return False
    min_price, _max_price = _price_bounds(currency)
    return (
        kwh >= SUSPICIOUS_MONTHLY_KWH
        and amount / kwh < min_price
    )


def _is_anomalous_effective_price(price: float, currency: str | None = None) -> bool:
    min_price, max_price = _price_bounds(currency)
    return price < min_price or price > max_price


def _select_consumption_kwh(
    period_candidates: list[float],
    reading_candidates: list[float],
    fallback_candidates: list[float],
    amount: float | None,
    currency: str | None,
    warnings: list[str],
) -> float | None:
    """Elige consumo real evitando confundir lecturas acumuladas con kWh del periodo."""
    period_plausible = [
        kwh for kwh in period_candidates
        if not _looks_like_accumulated_reading(kwh, amount, currency)
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
        if not _looks_like_accumulated_reading(kwh, amount, currency)
    ]
    if fallback_plausible:
        return max(fallback_plausible)

    if period_candidates or fallback_candidates:
        warnings.append(
            "El valor kWh detectado parece una lectura acumulada; introduce el consumo del periodo."
        )
    return None


def _detect_currency(text: str) -> str | None:
    for token, code in CURRENCY_SYMBOLS.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text, re.IGNORECASE):
            return code
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


def _line_amount_candidates(line: str) -> list[float]:
    values = []
    for match in re.finditer(rf"(?:{_CURRENCY}\s*)?{_NUM}\s*(?:{_CURRENCY})?", line, re.IGNORECASE):
        start, end = match.span()
        context_after = line[end:end + 12].lower()
        context_before = line[max(0, start - 8):start].lower()
        if re.search(r"^(?:kwh|kw\b)|(?:/|\s+)kwh|(?:/|\s+)kw\b|%\s*$", context_after):
            continue
        if re.search(r"^\s*%", context_after):
            continue
        if re.search(r"\b\d+(?:[.,]\d+)?\s*%$", context_before):
            continue
        value = _to_float(match.group(1))
        if 0 < value <= 10000:
            values.append(value)
    return values


def _line_matches_any(line: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns)


def _find_charge_amount(
    text: str, labels: list[str], exclude: list[str] | None = None
) -> float | None:
    lines = _clean_lines(text)
    values: list[float] = []
    seen: set[float] = set()
    exclude_labels = _CHARGE_EXCLUDE_LABELS + (exclude or [])

    def add_amounts(amounts: list[float]) -> None:
        for amount in amounts:
            key = round(amount, 2)
            if key in seen:
                continue
            seen.add(key)
            values.append(amount)

    for index, line in enumerate(lines):
        normalized = line.strip()
        if _line_matches_any(normalized, exclude_labels):
            continue
        if not _line_matches_any(normalized, labels):
            continue

        amounts = _line_amount_candidates(normalized)
        if amounts:
            add_amounts([amounts[-1]])
            continue

        lookahead: list[float] = []
        for next_line in lines[index + 1:index + 4]:
            if _line_matches_any(next_line, exclude_labels):
                break
            if _line_matches_any(next_line, _ENERGY_CHARGE_LABELS + _FIXED_CHARGE_LABELS + _TAX_CHARGE_LABELS):
                break
            line_amounts = _line_amount_candidates(next_line)
            if line_amounts:
                lookahead.extend(line_amounts)
                break
        if lookahead:
            add_amounts([lookahead[-1]])

    return round(sum(values), 2) if values else None


def _find_iva_rate(text: str) -> float | None:
    """Tipo de IVA impreso en la etiqueta, p. ej. 'IVA (21%)' → 0.21."""
    match = re.search(r"\biva\b[^\n%]{0,15}?(\d{1,2}(?:[.,]\d+)?)\s*%", text, re.IGNORECASE)
    if not match:
        return None
    rate = _to_float(match.group(1)) / 100
    return round(rate, 4) if 0.0 < rate <= 0.30 else None


def _period_end_exclusive(start: date, end: date) -> bool:
    """Heurística: 01/01-01/02 suele expresar intervalo [inicio, fin)."""
    return end.day == 1 and start < end


def _period_end_boundary(start: date, end: date) -> date:
    return end if _period_end_exclusive(start, end) else end + timedelta(days=1)


def _period_days(start: date, end: date) -> int:
    return max(0, (_period_end_boundary(start, end) - start).days)


def _next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def split_bill_period_by_month(start: date, end: date) -> list[tuple[int, int]]:
    """Días de la factura que caen en cada mes.

    Soporta facturas con fecha final inclusiva (01/07-31/07) y periodos tipo
    [inicio, fin) cuando el final es día 1 del mes siguiente (01/01-01/02).
    """
    boundary = _period_end_boundary(start, end)
    if boundary <= start:
        return []

    cursor = start
    result: list[tuple[int, int]] = []
    while cursor < boundary:
        segment_end = min(_next_month_start(cursor), boundary)
        days = (segment_end - cursor).days
        if days > 0:
            result.append((cursor.month, days))
        cursor = segment_end
    return result


def _bill_month_from_period(start: date, end: date) -> int:
    parts = split_bill_period_by_month(start, end)
    if parts:
        return max(parts, key=lambda item: item[1])[0]
    return (start + (end - start) / 2).month


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
    """Extrae kwh, importes y periodo del texto de una factura.

    Devuelve campos compatibles históricos (amount_eur) y campos nuevos
    separados: energy_eur/fixed_eur/taxes_eur/total_eur, todos en la moneda
    detectada del documento.
    """
    if not text.strip():
        raise BillParseError(
            "El PDF no contiene texto extraíble (puede ser un escaneo). Introduce los datos a mano."
        )

    warnings: list[str] = []
    result: dict = {
        "kwh": None,
        "amount_eur": None,
        "energy_eur": None,
        "fixed_eur": None,
        "taxes_eur": None,
        "total_eur": None,
        "power_eur": None,
        "iee_eur": None,
        "iva_eur": None,
        "iva_rate": None,
        "vat_base_eur": None,
        "currency": _detect_currency(text),
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
    result["total_eur"] = _find_total_amount(text, warnings)
    result["amount_eur"] = result["total_eur"]
    result["energy_eur"] = _find_charge_amount(text, _ENERGY_CHARGE_LABELS)
    result["fixed_eur"] = _find_charge_amount(text, _FIXED_CHARGE_LABELS)
    result["taxes_eur"] = _find_charge_amount(text, _TAX_CHARGE_LABELS)
    # Líneas para derivar el coste marginal evitado (IEE + IVA por factura)
    result["power_eur"] = _find_charge_amount(text, _POWER_CHARGE_LABELS)
    result["iee_eur"] = _find_charge_amount(text, _IEE_LABELS, exclude=_IEE_LUMPED_LABELS)
    result["iva_eur"] = _find_charge_amount(text, _IVA_AMOUNT_LABELS)
    result["iva_rate"] = _find_iva_rate(text)
    result["vat_base_eur"] = _find_charge_amount(text, _VAT_BASE_LABELS)

    # --- kWh: consumo del periodo > diferencia de lecturas > kWh no acumulados ---
    period_candidates = _period_consumption_candidates(text)
    reading_candidates = _reading_difference_candidates(text)
    fallback_candidates = _fallback_kwh_candidates(text)
    result["kwh"] = _select_consumption_kwh(
        period_candidates,
        reading_candidates,
        fallback_candidates,
        result["total_eur"],
        result["currency"],
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
        result["month"] = _bill_month_from_period(start, end)

    return result


def parse_bill_pdf(pdf_bytes: bytes) -> dict:
    return parse_bill_text(extract_text(pdf_bytes))


def _bill_month(bill: dict, start: date | None, end: date | None) -> int | None:
    """Mes representativo de la factura: explícito o mayor tramo del periodo."""
    if start and end:
        return _bill_month_from_period(start, end)
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


# --- Coste marginal evitado: IEE + IVA derivados por factura -----------------
#
# El término de energía de la factura va sin impuestos. Cada kWh autoconsumido
# evita también el impuesto eléctrico (IEE) y el IVA que se aplicarían sobre él,
# así que el ahorro debe valorarse al coste marginal:
#   marginal = precio_energía × (1 + IEE) × (1 + IVA)
# Los tipos NO se fijan como constantes: cambiaron a mitad de 2026 y pueden
# volver a cambiar. Se derivan de las líneas detalladas de cada factura y, solo
# si faltan, se cae a los tipos normativos vigentes en el periodo facturado.

IEE_STANDARD_RATE = 0.0511269632
IEE_REDUCED_RATE = 0.005
IVA_STANDARD_RATE = 0.21
IVA_REDUCED_RATE = 0.10
# Rebaja temporal española: devengos del 22-mar-2026 al 31-may-2026.
# (El IVA al 10% exigía potencia contratada ≤ 10 kW: se asume, esta calculadora
# es residencial. Una posible reaparición del 10% en ago-sep 2026 era
# condicional: se prefiere siempre el valor derivado de la propia factura.)
_ES_REDUCED_TAX_WINDOW = (date(2026, 3, 22), date(2026, 5, 31))

_IVA_KNOWN_RATES = (IVA_REDUCED_RATE, IVA_STANDARD_RATE)


def _statutory_rates_es(period_mid: date | None) -> tuple[float, float]:
    """(IEE, IVA) normativos para el periodo facturado; estándar si no hay fecha."""
    if period_mid and _ES_REDUCED_TAX_WINDOW[0] <= period_mid <= _ES_REDUCED_TAX_WINDOW[1]:
        return IEE_REDUCED_RATE, IVA_REDUCED_RATE
    return IEE_STANDARD_RATE, IVA_STANDARD_RATE


def _bill_period_mid(bill: dict) -> date | None:
    start, end = bill.get("start_date"), bill.get("end_date")
    if start and end:
        return start + (end - start) / 2
    return None


def _derived_iva_rate(bill: dict) -> float | None:
    """IVA de la factura: % impreso en la etiqueta o importe / base imponible."""
    labelled = bill.get("iva_rate")
    if labelled and 0.0 < float(labelled) <= 0.30:
        return float(labelled)
    iva, base = bill.get("iva_eur"), bill.get("vat_base_eur")
    if not iva or not base:
        return None
    ratio = float(iva) / float(base)
    # El cociente se ajusta al tipo legal más próximo (21% o 10%): el redondeo
    # de importes en factura desplaza el cociente unas décimas.
    nearest = min(_IVA_KNOWN_RATES, key=lambda rate: abs(rate - ratio))
    if abs(nearest - ratio) <= 0.01:
        return nearest
    return round(ratio, 4) if 0.03 <= ratio <= 0.30 else None


def _derived_iee_rate(bill: dict) -> float | None:
    """IEE de la factura: impuesto eléctrico / (término energía + potencia)."""
    iee, energy = bill.get("iee_eur"), bill.get("energy_eur")
    if not iee or not energy:
        return None
    taxable = float(energy) + float(bill.get("power_eur") or 0.0)
    if taxable <= 0:
        return None
    ratio = float(iee) / taxable
    return ratio if 0.001 <= ratio <= 0.08 else None


def derive_bill_tax_rates(bill: dict, country_code: str | None = None) -> dict | None:
    """Tipos impositivos de una factura: derivados de sus líneas o normativos.

    Devuelve {"iee_rate", "iva_rate", "source"} con source "bill" (ambos
    derivados), "statutory" (ambos de la tabla por fechas) o "mixed".
    Para países sin tabla normativa propia solo se derivan de las líneas.
    """
    iva = _derived_iva_rate(bill)
    iee = _derived_iee_rate(bill)
    if iva is not None and iee is not None:
        return {"iee_rate": iee, "iva_rate": iva, "source": "bill"}
    if (country_code or "").upper() != "ES" and (iva is None or iee is None):
        # Sin tabla normativa fuera de España: exige ambas líneas en la factura
        return None
    statutory_iee, statutory_iva = _statutory_rates_es(_bill_period_mid(bill))
    source = "statutory" if iva is None and iee is None else "mixed"
    return {
        "iee_rate": iee if iee is not None else statutory_iee,
        "iva_rate": iva if iva is not None else statutory_iva,
        "source": source,
    }


def aggregate_bills(
    bills: list[dict],
    default_currency: str | None = None,
    country_code: str | None = None,
) -> dict:
    """Agrega facturas a consumo anual, gasto total y precio variable medio.

    Cada factura: {kwh, energy_eur/total_eur/amount_eur (opcional), month (opcional),
    start_date/end_date o days}. Si hay meses identificables, estima una curva
    anual completa usando esos meses como muestras reales y el perfil
    residencial por defecto para completar los huecos.
    """
    total_kwh = 0.0
    total_days = 0.0
    total_variable_amount = 0.0
    kwh_with_variable_amount = 0.0
    total_bill_amount = 0.0
    total_amount_days = 0.0
    priced_bill_count = 0
    total_amount_bill_count = 0
    ignored_price_bill_count = 0
    monthly_kwh = [0.0] * 12
    monthly_days = [0.0] * 12
    monthly_total_amount = [0.0] * 12
    monthly_total_amount_days = [0.0] * 12
    currencies: list[str] = []
    tax_factor_weighted = 0.0
    tax_factor_kwh = 0.0
    tax_sources: set[str] = set()

    for bill in bills:
        kwh = float(bill["kwh"])
        currency = (bill.get("currency") or default_currency or DEFAULT_CURRENCY).upper()
        currencies.append(currency)
        variable_amount = float(bill["energy_eur"]) if bill.get("energy_eur") else None
        total_amount = None
        if bill.get("total_eur"):
            total_amount = float(bill["total_eur"])
        elif bill.get("amount_eur"):
            total_amount = float(bill["amount_eur"])

        reading_check_amount = variable_amount or total_amount
        if reading_check_amount is not None and kwh >= SUSPICIOUS_MONTHLY_KWH:
            implicit_price = reading_check_amount / kwh
            min_price, _max_price = _price_bounds(currency)
            if implicit_price < min_price:
                raise BillParseError(
                    "Una factura parece usar una lectura acumulada del contador como consumo. "
                    "Introduce el consumo del periodo (kWh) o importa una factura con lectura "
                    "actual y anterior para calcular la diferencia."
                )
        days = bill.get("days")
        start, end = bill.get("start_date"), bill.get("end_date")
        month = _bill_month(bill, start, end)
        if days is None and start and end:
            days = _period_days(start, end)
        if days is None and month is not None:
            days = DAYS_PER_MONTH[month - 1]
        days = float(days) if days else 30.4
        total_kwh += kwh
        total_days += days
        if variable_amount is not None:
            effective_price = variable_amount / kwh
            if _is_anomalous_effective_price(effective_price, currency):
                ignored_price_bill_count += 1
            else:
                total_variable_amount += variable_amount
                kwh_with_variable_amount += kwh
                priced_bill_count += 1
                # Coste marginal evitado: tipos de ESTA factura, ponderados por kWh
                rates = derive_bill_tax_rates(bill, country_code)
                if rates is not None:
                    factor = (1 + rates["iee_rate"]) * (1 + rates["iva_rate"])
                    tax_factor_weighted += kwh * factor
                    tax_factor_kwh += kwh
                    tax_sources.add(rates["source"])
        if total_amount is not None:
            total_bill_amount += total_amount
            total_amount_days += days
            total_amount_bill_count += 1

        if start and end:
            parts = split_bill_period_by_month(start, end)
            period_days = sum(part_days for _month, part_days in parts)
            if period_days > 0:
                for part_month, part_days in parts:
                    share = part_days / period_days
                    monthly_kwh[part_month - 1] += kwh * share
                    monthly_days[part_month - 1] += part_days
                    if total_amount is not None:
                        monthly_total_amount[part_month - 1] += total_amount * share
                        monthly_total_amount_days[part_month - 1] += part_days
                continue

        if month is not None:
            index = month - 1
            monthly_kwh[index] += kwh
            monthly_days[index] += days
            if total_amount is not None:
                monthly_total_amount[index] += total_amount
                monthly_total_amount_days[index] += days

    if total_kwh <= 0 or total_days <= 0:
        raise BillParseError("Las facturas no contienen consumos válidos")

    annual_from_months, monthly, observed_months = _estimate_monthly_from_samples(
        monthly_kwh, monthly_days
    )
    annual_kwh = annual_from_months if annual_from_months is not None else total_kwh / total_days * 365.25
    price = (
        round(total_variable_amount / kwh_with_variable_amount, 4)
        if kwh_with_variable_amount > 0
        else None
    )
    marginal_factor = (
        round(tax_factor_weighted / tax_factor_kwh, 4) if tax_factor_kwh > 0 else None
    )
    marginal_price = (
        round(price * marginal_factor, 4)
        if price is not None and marginal_factor is not None
        else None
    )
    if not tax_sources:
        tax_rates_source = None
    elif len(tax_sources) == 1:
        tax_rates_source = next(iter(tax_sources))
    else:
        tax_rates_source = "mixed"

    annual_amount = None
    monthly_amount = None
    if total_amount_bill_count > 0:
        annual_amount_from_months, monthly_amount, _observed_amount_months = (
            _estimate_monthly_from_samples(monthly_total_amount, monthly_total_amount_days)
        )
        if annual_amount_from_months is not None:
            annual_amount = annual_amount_from_months
        elif total_amount_days > 0:
            annual_amount = round(total_bill_amount / total_amount_days * 365.25, 1)

    if len(observed_months) == 12:
        seasonality_source = "full_year_bills"
    elif observed_months:
        seasonality_source = "estimated_from_sampled_months"
    else:
        seasonality_source = "annualized_by_days"

    return {
        "annual_kwh": round(annual_kwh, 1),
        "avg_price_eur_kwh": price,
        "avg_price_kwh": price,
        "marginal_price_eur_kwh": marginal_price,
        "marginal_price_factor": marginal_factor,
        "tax_rates_source": tax_rates_source,
        "annual_amount_eur": annual_amount,
        "annual_amount": annual_amount,
        "monthly_eur": monthly_amount,
        "monthly_amount": monthly_amount,
        "bill_count": len(bills),
        "priced_bill_count": priced_bill_count,
        "total_amount_bill_count": total_amount_bill_count,
        "ignored_price_bill_count": ignored_price_bill_count,
        "days_covered": round(total_days),
        "monthly_kwh": monthly,
        "observed_months": observed_months,
        "seasonality_source": seasonality_source,
        "currency": currencies[0] if currencies else (default_currency or DEFAULT_CURRENCY),
    }
