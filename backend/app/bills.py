"""Extracción de datos de facturas de la luz.

Extrae del texto del PDF: kWh consumidos, importe total y periodo de
facturación. Es heurístico (cada comercializadora maqueta distinto): se
devuelve también una lista de avisos con lo que no se pudo detectar para que
el usuario lo corrija a mano en el formulario.
"""

import io
import logging
import re
from datetime import date, timedelta

from pypdf import PdfReader

from . import bill_messages
from .profiles import DAYS_PER_MONTH, MONTHLY_WEIGHTS
from .spain_postal import province_from_postal_code

logger = logging.getLogger(__name__)

MONTH_NAMES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
}

# Abreviaturas de 3 letras del histórico mensual español (Ene, Feb, ... Dic).
MONTH_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}
# Token de mes para el histórico: nombre completo español o abreviatura de 3 letras.
_HISTORY_MONTH_TOKEN = (
    r"ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|abr(?:il)?|may(?:o)?|jun(?:io)?"
    r"|jul(?:io)?|ago(?:sto)?|sep(?:tiembre)?|set(?:iembre)?|oct(?:ubre)?"
    r"|nov(?:iembre)?|dic(?:iembre)?"
)

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

# Fila del histórico mensual: 'Ene 2.902 kWh'. Requiere _NUM, ya definido.
_HISTORY_LINE_RE = re.compile(
    rf"\b({_HISTORY_MONTH_TOKEN})\.?\s*[:\-]?\s*{_NUM}\s*kWh", re.IGNORECASE
)

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
# Tope de kWh de una factura. Cubre facturas anuales de viviendas grandes; el
# filtro real contra lecturas acumuladas del contador es el de precio por kWh
# (_looks_like_accumulated_reading), no este tope absoluto.
MAX_BILL_KWH = 60_000
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

# Precio efectivo = importe TOTAL de la factura / consumo. Distinto de
# PRICE_PLAUSIBILITY_BY_CURRENCY (que acota el término de energía): incluye
# potencia, impuestos e IVA, así que la banda es más estrecha por arriba. Una
# doméstica española 2.0TD ronda 0,15–0,35 €/kWh todo incluido; fuera de la banda
# es señal de consumo mal detectado (p. ej. una sola columna de periodo tomada
# por el total: 3.029 € / 2.150 kWh = 1,41 €/kWh), no de un precio real.
EFFECTIVE_PRICE_BOUNDS_BY_CURRENCY = {
    "EUR": (0.10, 0.40),
    "GBP": (0.10, 0.60),
    "CHF": (0.10, 0.60),
}
# Con bono social (descuento sobre el PVPC) el precio efectivo baja mucho y es
# legítimo: p. ej. 0,057 €/kWh. Se rebaja el suelo para no marcar esos casos como
# error, manteniendo un mínimo que aún atrapa una lectura acumulada o una columna
# suelta tomadas por el total.
BONO_SOCIAL_MIN_PRICE_EUR_KWH = 0.03

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


# Un periodo horario canónico por familia (2.0TD = P1/P2/P3; 3.0TD añade más,
# pero el split para batería/tiempo sólo distingue punta/llano/valle).
_PERIOD_CANONICAL = {
    "p1": "punta", "punta": "punta", "peak": "punta",
    "p2": "llano", "llano": "llano", "shoulder": "llano",
    "p3": "valle", "valle": "valle", "offpeak": "valle", "off-peak": "valle",
}
_PERIOD_LABEL_RE = re.compile(
    r"^(?:periodo\s+)?(p[1-6]|punta|llano|valle|peak|off[-\s]?peak|shoulder)\b",
    re.IGNORECASE,
)


def _parse_period_table(text: str) -> dict | None:
    """Consumo por periodo horario leído por ETIQUETA, no por posición.

    El consumo total de una factura multi-periodo (2.0TD/3.0TD) es la SUMA de las
    columnas de periodo (P1+P2+P3…), nunca una sola. Reconoce filas 'P1 Punta …',
    tomando como kWh el número seguido de 'kWh' o, si no lo hay, el primer número
    de la fila (el precio €/kWh y el importe € quedan descartados por el rango).

    Devuelve {'periods': {punta,llano,valle}, 'total_kwh': suma, 'prices':
    {punta,llano,valle} €/kWh} o None si no hay al menos dos filas de periodo
    (una sola fila no es una tabla fiable). 'prices' permite valorar la batería
    al precio del periodo que desplaza (valle), sin inventar cifras.
    """
    periods: dict[str, float] = {}
    prices: dict[str, float] = {}
    raw_total = 0.0
    seen = 0
    for line in _clean_lines(text):
        match = _PERIOD_LABEL_RE.match(line)
        if not match:
            continue
        rest = line[match.end():]
        unit = re.search(rf"{_NUM}\s*kWh", rest, re.IGNORECASE)
        if unit:
            value = _to_float(unit.group(1))
        else:
            numbers = re.findall(_NUM, rest)
            value = _to_float(numbers[0]) if numbers else None
        if value is None or not (1 <= value <= MAX_BILL_KWH):
            continue
        # Precio €/kWh del periodo: el número pegado a '/kWh', o el primer número
        # de la fila con pinta de precio unitario (0 < x < 2, distinto del kWh).
        price = None
        pmatch = re.search(rf"{_NUM}\s*(?:€|EUR)?\s*/\s*kWh", rest, re.IGNORECASE)
        if pmatch:
            price = _to_float(pmatch.group(1))
        else:
            for token in re.findall(_NUM, rest):
                candidate = _to_float(token)
                if candidate != value and 0 < candidate < 2:
                    price = candidate
                    break
        raw_total += value
        seen += 1
        canonical = _PERIOD_CANONICAL.get(match.group(1).lower().replace(" ", ""))
        if canonical and canonical not in periods:
            periods[canonical] = value
            if price is not None:
                prices[canonical] = price
    if seen < 2:
        return None
    return {"periods": periods, "total_kwh": round(raw_total, 1), "prices": prices or None}


def _effective_price_bounds(
    currency: str | None, bono_social: bool = False
) -> tuple[float, float]:
    """Banda del precio efectivo (importe total / consumo) por moneda.

    Con bono social el suelo se rebaja (BONO_SOCIAL_MIN_PRICE_EUR_KWH): un precio
    efectivo bajo es legítimo, no un consumo mal detectado."""
    cur = (currency or DEFAULT_CURRENCY).upper()
    if cur in EFFECTIVE_PRICE_BOUNDS_BY_CURRENCY:
        low, high = EFFECTIVE_PRICE_BOUNDS_BY_CURRENCY[cur]
    else:
        # Sin banda específica: se reutiliza la del término de energía como red de
        # seguridad (más laxa, pero mejor que no comprobar nada).
        low, high = _price_bounds(cur)
    if bono_social:
        low = min(low, BONO_SOCIAL_MIN_PRICE_EUR_KWH)
    return low, high


def safe_to_float(raw: object) -> float | None:
    """_to_float que no lanza: normaliza formato español o devuelve None.

    Punto único de normalización numérica del contrato de extracción (Layer 3):
    "6.551"->6551, "1.689,65"->1689,65, "0,24"->0,24. Ignora unidades/símbolos
    pegados al número ('6.551 kWh', '0,241 €/kWh')."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw)
    match = re.search(r"-?\d[\d.,\s ]*\d|-?\d", text)
    if not match:
        return None
    try:
        return _to_float(match.group(0))
    except ValueError:
        return None


def _values_close(a: float | None, b: float | None) -> bool:
    """Dos lecturas del consumo se consideran la misma cifra (2 % o 5 kWh)."""
    if not a or not b:
        return False
    return abs(a - b) <= max(0.02 * max(a, b), 5)


def _annual_consumption_sources(bill: dict) -> dict[str, float]:
    """Las varias lecturas del consumo anual, para cruzarlas entre sí:
    la cifra destacada, la suma de columnas de periodo y la suma del histórico
    mensual (11-12 meses = anual, sin depender de fechas)."""
    sources: dict[str, float] = {}
    headline = bill.get("kwh")
    if headline and headline > 0:
        sources["headline"] = round(float(headline), 1)

    # Total de la tabla de periodos TAL COMO LO IMPRIME la factura (candidato
    # distinto de la suma de columnas que calcula la app).
    printed_total = bill.get("period_total_kwh")
    if isinstance(printed_total, (int, float)) and printed_total > 0:
        sources["period_total_printed"] = round(float(printed_total), 1)

    periods = bill.get("consumption_periods") or {}
    period_sum = sum(v for v in periods.values() if isinstance(v, (int, float)) and v > 0)
    if period_sum > 0:
        sources["period_total"] = round(period_sum, 1)

    history = bill.get("consumption_history") or []
    if len(history) >= 11:
        history_sum = sum(
            h.get("kwh", 0) for h in history if isinstance(h, dict) and h.get("kwh")
        )
        if history_sum > 0:
            sources["history_sum"] = round(history_sum, 1)
    return sources


def reconcile_annual_consumption(bill: dict) -> tuple[float | None, str | None, list[str]]:
    """Cruza el consumo anual de sus VARIAS fuentes y devuelve el valor autoritativo.

    La misma cifra aparece en varios sitios (cifra destacada 'consumo facturado',
    total de la tabla de periodos, suma del histórico mensual). Se tratan como
    corroboraciones, no como lecturas independientes:
      - si dos fuentes coinciden, esa cifra manda y se CORRIGE la que discrepe
        (p. ej. una tarjeta mal parseada) — la factura calcula, no va a revisión;
      - una sola columna de periodo tomada por el total se corrige a la suma;
      - solo si NINGUNA fuente se corrobora con otra se deja para revisión.

    Devuelve (kwh_autoritativo, nota_de_correccion|None, motivos_de_revision).
    """
    headline = bill.get("kwh")
    sources = _annual_consumption_sources(bill)
    head = sources.get("headline")

    periods = bill.get("consumption_periods") or {}
    matches_single_period = any(
        _values_close(head, v) for v in periods.values() if isinstance(v, (int, float))
    )

    # Valor corroborado por ≥2 fuentes que coinciden entre sí (mayor consenso gana).
    values = list(sources.values())
    authoritative: float | None = None
    best_support = 1
    for candidate in values:
        agree = [w for w in values if _values_close(candidate, w)]
        if len(agree) >= 2 and len(agree) > best_support:
            authoritative = round(sum(agree) / len(agree), 1)
            best_support = len(agree)

    if authoritative is None:
        # Sin corroboración: reparación de columna única (cabecera = una columna,
        # existe un total mayor) usando el total impreso o la suma de columnas.
        period_total = sources.get("period_total_printed") or sources.get("period_total")
        if period_total and matches_single_period and period_total > (head or 0) * 1.2:
            authoritative = period_total

    if authoritative is None:
        # Nada se corrobora. Si hay varias fuentes y NO coinciden → revisión.
        if len(sources) >= 2:
            detail = ", ".join(f"{k}={v:.0f}" for k, v in sources.items())
            return headline, None, [
                f"Las fuentes de consumo no coinciden ({detail} kWh); revisa el consumo."
            ]
        return headline, None, []

    if headline is None or not _values_close(headline, authoritative):
        note = (
            f"Consumo anual corregido a {authoritative:.0f} kWh por coincidencia de fuentes "
            f"(suma de periodos/histórico); la cifra detectada ({headline}) no cuadraba."
        )
        return authoritative, note, []
    return authoritative, None, []


def validate_bill_consumption(bill: dict) -> list[dict]:
    """Guarda de plausibilidad del consumo YA reconciliado: el precio efectivo.

    Agnóstica al parser (IA o local). La reconciliación de fuentes la hace
    reconcile_annual_consumption; aquí queda el backstop independiente: si
    incluso el consumo reconciliado da un precio efectivo imposible (p. ej. una
    factura con una única columna de periodo y sin más fuentes que la corroboren),
    se deja para revisión. Con bono social el precio bajo es legítimo (banda más
    baja) y NO se marca. Devuelve avisos {code, params} (lista vacía = sin objeciones).
    """
    notes: list[dict] = []
    kwh = bill.get("kwh")
    if not kwh or kwh <= 0:
        return notes
    currency = bill.get("currency")

    total = bill.get("total_eur") or bill.get("amount_eur")
    if total:
        effective = total / kwh
        low, high = _effective_price_bounds(currency, bool(bill.get("bono_social")))
        if effective < low or effective > high:
            notes.append(
                bill_messages.note(
                    "effective_price_out_of_range",
                    price=effective,
                    low=low,
                    high=high,
                    currency=currency or "EUR",
                )
            )
    return notes


def _month_from_token(token: str) -> int | None:
    normalized = token.lower()
    return MONTH_NAMES.get(normalized) or MONTH_ABBR.get(normalized[:3])


def _month_line_to_number(line: str) -> int | None:
    """Nº de mes si la línea es SOLO un nombre/abreviatura de mes (con año opcional).

    Reconoce 'Enero', 'Ene', 'Marzo 2026', 'Ago', etc. — no texto en prosa que
    contenga un mes.
    """
    match = re.fullmatch(
        rf"({_HISTORY_MONTH_TOKEN})\.?(?:\s+(?:de\s+)?\d{{4}})?", line.strip(), re.IGNORECASE
    )
    return _month_from_token(match.group(1)) if match else None


def _parse_vertical_month_table(text: str) -> dict[int, tuple[float, float | None]]:
    """Tabla mensual en formato vertical: mes → (kWh, importe|None).

    Cubre 'Detalle mensual consolidado' (Mes / kWh / importe) e históricos
    verticales ('Marzo 2026' / '2.115', o 'Ago' / '1210' de un gráfico de barras),
    donde el mes y su valor van en líneas separadas. Filas no-mes (MES, CONSUMO,
    IMPORTE, TOTAL 2026…) se saltan.
    """
    lines = _clean_lines(text)
    result: dict[int, tuple[float, float | None]] = {}
    i = 0
    while i < len(lines):
        month = _month_line_to_number(lines[i])
        if month is None or i + 1 >= len(lines) or not _line_is_plain_number(lines[i + 1]):
            i += 1
            continue
        kwh = _to_float(lines[i + 1])
        eur = None
        step = 2
        if i + 2 < len(lines) and re.search(_CURRENCY, lines[i + 2]):
            amounts = _line_amount_candidates(lines[i + 2])
            if amounts:
                eur = amounts[-1]
                step = 3
        if 1 <= kwh <= MAX_BILL_KWH and month not in result:
            result[month] = (kwh, eur)
        i += step
    return result


def parse_consumption_history(text: str) -> list[dict]:
    """Histórico mensual de consumo de la factura: [{month, kwh, eur?}, ...].

    Combina el histórico en línea ('Ene 2.902 kWh' bajo la cabecera 'Histórico de
    consumo') con las tablas verticales ('Detalle mensual consolidado' de las
    facturas anuales, y los históricos verticales). Un mes por entrada.
    """
    by_month: dict[int, float] = {}
    spend: dict[int, float] = {}

    header = re.search(
        r"hist[oó]rico(?:\s+reciente)?\s+de\s+consumo", text, re.IGNORECASE
    )
    if header:
        segment = text[header.end():header.end() + 800]
        for match in _HISTORY_LINE_RE.finditer(segment):
            month = _month_from_token(match.group(1))
            kwh = _to_float(match.group(2))
            if month is not None and 1 <= kwh <= MAX_BILL_KWH:
                by_month[month] = kwh

    # Tablas verticales (rellenan meses no vistos y aportan el importe mensual).
    # Solo se aceptan si hay ≥2 meses, para no confundir un mes suelto en prosa.
    vertical = _parse_vertical_month_table(text)
    if len(vertical) >= 2:
        for month, (kwh, eur) in vertical.items():
            by_month.setdefault(month, kwh)
            if eur is not None:
                spend.setdefault(month, eur)

    entries = []
    for month in sorted(by_month):
        entry = {"month": month, "kwh": by_month[month]}
        if month in spend:
            entry["eur"] = spend[month]
        entries.append(entry)
    return entries


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
        # Las filas del histórico mensual ('Ene 2.902 kWh') no son el consumo
        # del periodo: se excluyen del último recurso de detección de kWh.
        if _HISTORY_LINE_RE.search(line):
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


_SUPPLY_ADDRESS_LABELS = (
    r"(?:punto|direcci[oó]n|lugar|domicilio)\s+de\s+suministro"
    r"|punto\s+de\s+suministro"
)
_FISCAL_ADDRESS_LABELS = (
    r"direcci[oó]n\s+fiscal|domicilio\s+fiscal|direcci[oó]n\s+de\s+facturaci[oó]n"
)
_SPANISH_CP_RE = re.compile(r"\b(\d{5})\b")


def _find_supply_location(text: str) -> dict | None:
    """Domicilio del PUNTO DE SUMINISTRO, con preferencia sobre el fiscal.

    Devuelve {postal_code, city, supply_address, source}. El CP (5 dígitos) es
    el ancla; se busca primero junto a una etiqueta de suministro, luego junto a
    una fiscal, y por último el primero del documento.
    """
    for label, source in (
        (_SUPPLY_ADDRESS_LABELS, "supply"),
        (_FISCAL_ADDRESS_LABELS, "fiscal"),
        (None, "any"),
    ):
        if label is not None:
            match = re.search(label, text, re.IGNORECASE)
            if not match:
                continue
            window = text[match.start(): match.end() + 160]
        else:
            window = text
        cp_match = _SPANISH_CP_RE.search(window)
        if not cp_match:
            continue
        cp = cp_match.group(1)
        after = window[cp_match.end():cp_match.end() + 60]
        city_match = re.match(r"[\s,]*([A-Za-zÁÉÍÓÚÑáéíóúñ'.\- ]{2,40})", after)
        city = city_match.group(1).strip(" ,.-\n") if city_match else None
        return {
            "postal_code": cp,
            "city": city or None,
            "supply_address": " ".join(window.split())[:120],
            "source": source,
        }
    return None


def _find_contracted_power_kw(text: str) -> float | None:
    """Potencia contratada en kW (la mayor entre punta/valle si difieren)."""
    values = []
    for match in re.finditer(
        r"(?:potencia\s+(?:contratada|punta|valle|m[aá]xima)"
        r"|puissance\s+souscrite|potenza\s+impegnata)"
        r"[^\n\d]{0,40}?(\d{1,3}(?:[.,]\d+)?)\s*kW\b",
        text,
        re.IGNORECASE,
    ):
        value = _to_float(match.group(1))
        if 0 < value <= 1000:
            values.append(value)
    return max(values) if values else None


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


_BONO_SOCIAL_RE = re.compile(
    r"bono\s+social|descuento\s+por\s+bono|pvpc\s+con\s+bono|consumidor\s+vulnerable",
    re.IGNORECASE,
)
# "Consumo acumulado del último año: 3.450 kWh" y variantes.
_ROLLING_ANNUAL_RE = re.compile(
    r"(?:consumo\s+(?:acumulado|total)?\s*(?:del|de\s+los|en\s+los)?\s*"
    r"(?:[úu]ltimo|últimos)\s+(?:12\s*meses|a[ñn]o)"
    r"|consumo\s+anual"
    r"|consumo\s+en\s+los\s+[úu]ltimos\s+12\s*meses)"
    r"[^\d]{0,40}?([\d][\d.\s]*\d|\d)\s*k?wh",
    re.IGNORECASE,
)


def detect_bono_social(text: str | None) -> bool:
    """True si el texto de la factura menciona el bono social."""
    return bool(text and _BONO_SOCIAL_RE.search(text))


def detect_rolling_annual_kwh(text: str | None) -> float | None:
    """Consumo anual impreso ('Consumo acumulado del último año: X kWh'), si existe."""
    if not text:
        return None
    for match in _ROLLING_ANNUAL_RE.finditer(text):
        value = safe_to_float(match.group(1))
        if value is not None and 0 < value <= MAX_BILL_KWH:
            return value
    return None


def augment_contract_from_text(contract: dict, text: str | None) -> dict:
    """Rellena bono_social y rolling_annual_kwh desde el texto si el modelo los
    omitió (refuerzo determinista; no pisa lo que el modelo sí detectó)."""
    if not isinstance(contract, dict) or not text:
        return contract
    if not contract.get("bono_social") and detect_bono_social(text):
        contract["bono_social"] = True
    if contract.get("rolling_annual_kwh") in (None, ""):
        rolling = detect_rolling_annual_kwh(text)
        if rolling is not None:
            # El contrato guarda números como STRING verbatim; se normaliza igual.
            contract["rolling_annual_kwh"] = str(rolling)
    return contract


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
        "contracted_power_kw": None,
        "consumption_history": [],
        "consumption_periods": None,
        "consumption_period_prices": None,
        "needs_review": False,
        "review_reasons": [],
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
        "location_confidence": None,
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
    result["contracted_power_kw"] = _find_contracted_power_kw(text)
    result["consumption_history"] = parse_consumption_history(text)
    # Bono social y consumo anual impreso (misma detección que el refuerzo del
    # contrato LLM), para la vía de degradación local.
    result["bono_social"] = detect_bono_social(text)
    result["rolling_annual_kwh"] = detect_rolling_annual_kwh(text)

    # Domicilio del punto de suministro (preferido sobre el fiscal) para geocodar
    supply = _find_supply_location(text)
    if supply:
        result["postal_code"] = supply["postal_code"]
        result["city"] = result["city"] or supply["city"]
        result["supply_address"] = supply["supply_address"]
        province = province_from_postal_code(supply["postal_code"])
        # El CP fija país=ES solo en contexto español (evita colisión con CP de
        # otros países que comparten los dos primeros dígitos, p. ej. FR 33xxx).
        if province and result["country_code"] in (None, "ES") and (
            result["country_code"] == "ES" or result["language"] == "es"
        ):
            result["country_code"] = "ES"
            result["region"] = result["region"] or province[0]

    # --- Tabla de periodos horarios (P1/P2/P3): el total es la SUMA, no una columna ---
    period_table = _parse_period_table(text)
    if period_table:
        result["consumption_periods"] = period_table["periods"] or None
        result["consumption_period_prices"] = period_table["prices"]

    # --- kWh: consumo del periodo > diferencia de lecturas > kWh no acumulados ---
    period_candidates = _period_consumption_candidates(text)
    if period_table:
        # La suma de todas las columnas de periodo es el candidato autoritativo
        # (mayor que cualquier columna suelta, así que max() lo elige).
        period_candidates.append(period_table["total_kwh"])
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

    # --- Reconciliación de fuentes (corrige) + guarda de precio efectivo (revisa) ---
    corrected_kwh, correction_note, review_reasons = reconcile_annual_consumption(result)
    result["kwh"] = corrected_kwh
    if correction_note:
        warnings.append(correction_note)
    review_reasons = review_reasons + validate_bill_consumption(result)
    if review_reasons:
        result["needs_review"] = True
        result["review_reasons"] = review_reasons
        warnings.extend(review_reasons)

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


def extract_pdf_text_safe(pdf_bytes: bytes) -> str | None:
    """Capa de texto del PDF como señal AUXILIAR para el extractor LLM.

    No lanza: un escaneo sin capa de texto o un PDF corrupto devuelve None (las
    páginas renderizadas son la fuente autoritativa para el modelo)."""
    try:
        text = extract_text(pdf_bytes)
    except BillParseError:
        return None
    return text.strip() or None


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
# (El IVA al 10% exigía potencia contratada ≤ 10 kW; el IEE al 0,5% se aplicó a
# todos. Una posible reaparición del 10% en ago-sep 2026 era condicional: se
# prefiere siempre el valor derivado de la propia factura.)
_ES_REDUCED_TAX_WINDOW = (date(2026, 3, 22), date(2026, 5, 31))
_IVA_REDUCED_MAX_POWER_KW = 10.0

# Bandas de plausibilidad de los tipos derivados de una factura. El IEE legal
# nunca baja de 0,5% (rebaja temporal) ni supera ~5,11%; se da un pequeño
# margen. Fuera de banda, el valor de la factura es ruido (redondeos, líneas
# agrupadas) y se descarta a favor del tipo normativo del periodo.
IEE_MIN_RATE = 0.005
IEE_MAX_RATE = 0.052
_IVA_KNOWN_RATES = (IVA_REDUCED_RATE, IVA_STANDARD_RATE)
_IVA_SNAP_TOLERANCE = 0.015


def _in_reduced_window(day: date) -> bool:
    return _ES_REDUCED_TAX_WINDOW[0] <= day <= _ES_REDUCED_TAX_WINDOW[1]


def _statutory_iee_for_day(day: date) -> float:
    return IEE_REDUCED_RATE if _in_reduced_window(day) else IEE_STANDARD_RATE


def _statutory_iva_for_day(day: date, contracted_power_kw: float | None) -> float:
    if (
        _in_reduced_window(day)
        and contracted_power_kw is not None
        and contracted_power_kw <= _IVA_REDUCED_MAX_POWER_KW
    ):
        return IVA_REDUCED_RATE
    return IVA_STANDARD_RATE


def _statutory_rates_es(bill: dict) -> tuple[float, float]:
    """(IEE, IVA) normativos ponderados por día del periodo facturado.

    Si el periodo cruza el cambio de tipos de 2026, cada tramo pesa por sus días.
    Sin fechas se usa el punto medio disponible o el tipo estándar.
    """
    start, end = bill.get("start_date"), bill.get("end_date")
    contracted = bill.get("contracted_power_kw")
    if not (start and end) or end < start:
        mid = _bill_period_mid(bill)
        if mid is None:
            return IEE_STANDARD_RATE, IVA_STANDARD_RATE
        return _statutory_iee_for_day(mid), _statutory_iva_for_day(mid, contracted)

    iee_sum = 0.0
    iva_sum = 0.0
    days = 0
    cursor = start
    while cursor <= end:
        iee_sum += _statutory_iee_for_day(cursor)
        iva_sum += _statutory_iva_for_day(cursor, contracted)
        cursor += timedelta(days=1)
        days += 1
    return iee_sum / days, iva_sum / days


def _bill_period_mid(bill: dict) -> date | None:
    start, end = bill.get("start_date"), bill.get("end_date")
    if start and end:
        return start + (end - start) / 2
    return None


def _derived_iva_rate(bill: dict) -> float | None:
    """IVA plausible de la factura: se ajusta a un tipo legal conocido o se descarta.

    Del % impreso en la etiqueta o de importe/base imponible; en ambos casos
    debe caer cerca de un tipo estatutario (21% o 10%). Si no, es ruido y se
    rechaza (→ fallback normativo).
    """
    candidates = []
    labelled = bill.get("iva_rate")
    if labelled:
        candidates.append(float(labelled))
    iva, base = bill.get("iva_eur"), bill.get("vat_base_eur")
    if iva and base and float(base) > 0:
        candidates.append(float(iva) / float(base))
    for value in candidates:
        nearest = min(_IVA_KNOWN_RATES, key=lambda rate: abs(rate - value))
        if abs(nearest - value) <= _IVA_SNAP_TOLERANCE:
            return nearest
    return None


def _derived_iee_rate(bill: dict) -> float | None:
    """IEE plausible de la factura: impuesto eléctrico / (energía + potencia).

    Debe caer en [0,5%, 5,2%]; fuera de banda se descarta (→ fallback normativo).
    """
    iee, energy = bill.get("iee_eur"), bill.get("energy_eur")
    if not iee or not energy:
        return None
    taxable = float(energy) + float(bill.get("power_eur") or 0.0)
    if taxable <= 0:
        return None
    ratio = float(iee) / taxable
    return ratio if IEE_MIN_RATE <= ratio <= IEE_MAX_RATE else None


def derive_bill_tax_rates(bill: dict, country_code: str | None = None) -> dict | None:
    """Tipos impositivos de una factura: derivados de sus líneas (si son plausibles)
    o normativos del periodo.

    Devuelve {"iee_rate","iva_rate","iee_source","iva_source","source"}, con cada
    *_source en {"from-bill","statutory-fallback"} y source agregado en
    {"bill","statutory","mixed"}. Para países sin tabla normativa propia solo se
    aceptan tipos derivados de las líneas.
    """
    iva = _derived_iva_rate(bill)
    iee = _derived_iee_rate(bill)
    if (country_code or "").upper() != "ES" and (iva is None or iee is None):
        return None

    statutory_iee, statutory_iva = _statutory_rates_es(bill)
    iee_source = "from-bill" if iee is not None else "statutory-fallback"
    iva_source = "from-bill" if iva is not None else "statutory-fallback"
    result_iee = iee if iee is not None else statutory_iee
    result_iva = iva if iva is not None else statutory_iva
    if iee_source == iva_source:
        source = "bill" if iee_source == "from-bill" else "statutory"
    else:
        source = "mixed"

    logger.info(
        "Tax rates: IEE %.4f (%s), IVA %.3f (%s) [period %s..%s]",
        result_iee,
        iee_source,
        result_iva,
        iva_source,
        bill.get("start_date"),
        bill.get("end_date"),
    )
    return {
        "iee_rate": result_iee,
        "iva_rate": result_iva,
        "iee_source": iee_source,
        "iva_source": iva_source,
        "source": source,
    }


ANNUAL_MIN_DAYS = 330  # una factura que cubre ~12 meses se trata como anual


def _is_annual_bill(bill: dict) -> bool:
    """True si la factura cubre un periodo anual (~12 meses)."""
    days = bill.get("days")
    if days is None:
        start, end = bill.get("start_date"), bill.get("end_date")
        if start and end:
            days = _period_days(start, end)
    return days is not None and float(days) >= ANNUAL_MIN_DAYS


def _bill_recency_key(bill: dict) -> date:
    """Fecha para resolver conflictos del histórico: la más reciente gana."""
    end, start = bill.get("end_date"), bill.get("start_date")
    if end:
        return end
    if start:
        return start
    month = bill.get("month")
    if month:
        return date(1900, int(month), 1)
    return date.min


def _merge_consumption_history(bills: list[dict]) -> dict[int, float]:
    """Une los históricos de todas las facturas en un mapa mes→kWh.

    Ante el mismo mes en varias facturas, gana el de la factura más reciente.
    El resultado es independiente del orden y del subconjunto de facturas subido.
    """
    merged: dict[int, float] = {}
    # Orden ascendente por fecha: las facturas más recientes se aplican al final
    # y sobrescriben a las antiguas para el mismo mes.
    for bill in sorted(bills, key=_bill_recency_key):
        for entry in bill.get("consumption_history") or []:
            merged[int(entry["month"])] = float(entry["kwh"])
    return merged


def _merge_history_spend(bills: list[dict]) -> dict[int, float]:
    """Importe mensual del histórico (mes→€), cuando la factura lo trae."""
    merged: dict[int, float] = {}
    for bill in sorted(bills, key=_bill_recency_key):
        for entry in bill.get("consumption_history") or []:
            eur = entry.get("eur")
            if eur is not None:
                merged[int(entry["month"])] = float(eur)
    return merged


def _twelve_months_from_history(
    known: dict[int, float],
) -> tuple[list[float], list[int]]:
    """Curva de 12 meses a partir de los meses conocidos del histórico.

    Los meses ausentes se interpolan linealmente entre los vecinos conocidos
    más cercanos en el eje circular de meses. Devuelve (monthly, estimated).
    """
    monthly = [0.0] * 12
    estimated: list[int] = []
    present = sorted(known)
    for month in range(1, 13):
        if month in known:
            monthly[month - 1] = known[month]
            continue
        estimated.append(month)
        # Vecino conocido más cercano hacia atrás y hacia delante en el círculo
        # de 12 meses (las distancias caen en 1..11 porque month no está presente).
        prev_month = min(present, key=lambda m, month=month: (month - m) % 12)
        next_month = min(present, key=lambda m, month=month: (m - month) % 12)
        prev_dist = (month - prev_month) % 12
        next_dist = (next_month - month) % 12
        span = prev_dist + next_dist
        monthly[month - 1] = round(
            (known[prev_month] * next_dist + known[next_month] * prev_dist) / span, 1
        )
    return monthly, estimated


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
        raw_kwh = bill.get("kwh")
        bill_history = bill.get("consumption_history") or []
        if raw_kwh in (None, "") and bill_history:
            # Factura con histórico pero sin consumo de periodo legible (p. ej.
            # una consolidada anual): el propio histórico da el kWh de la factura.
            raw_kwh = sum(float(entry["kwh"]) for entry in bill_history)
        if raw_kwh in (None, ""):
            raise BillParseError("Las facturas no contienen consumos válidos")
        kwh = float(raw_kwh)
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

    contracted_powers = [
        float(bill["contracted_power_kw"])
        for bill in bills
        if bill.get("contracted_power_kw")
    ]
    contracted_power_kw = max(contracted_powers) if contracted_powers else None

    # Consumo anual, por orden de fiabilidad:
    #  1) histórico mensual de la factura (determinista, no depende de qué meses
    #     se suban);
    #  2) facturas de periodo anual (~12 meses): su total ya ES el consumo anual,
    #     así que no se reparte plano por días; la forma estacional la aplica el
    #     perfil de consumo aguas abajo (igual que el consumo anual introducido a
    #     mano), por eso se deja monthly_kwh en None;
    #  3) facturas de periodos cortos: estimación por meses muestreados.
    history = _merge_consumption_history(bills)
    estimated_months: list[int] = []
    annual_only = not history and all(_is_annual_bill(bill) for bill in bills)
    # "Consumo acumulado del último año" impreso: el anual REAL de la casa. Manda
    # sobre la extrapolación de los meses subidos (que pueden ser solo valle y
    # sesgar a la baja). Se toma el mayor si varias facturas lo imprimen.
    rolling_candidates = [
        float(b["rolling_annual_kwh"])
        for b in bills
        if b.get("rolling_annual_kwh") and float(b["rolling_annual_kwh"]) > 0
    ]
    rolling_annual = max(rolling_candidates) if rolling_candidates else None
    # Forma estacional del histórico (si lo hay), calculada una vez.
    history_monthly = history_sum = None
    if history:
        history_monthly, estimated_months = _twelve_months_from_history(history)
        history_sum = sum(history_monthly)
    # El anual impreso solo MANDA si no hay histórico, o si supera claramente la
    # suma del histórico (caso "solo meses valle subidos" que sesga a la baja).
    # Si coincide con el histórico (factura consolidada anual), manda el histórico.
    use_rolling = bool(rolling_annual) and (
        not history or rolling_annual > (history_sum or 0) * 1.10
    )
    if use_rolling and history and history_sum:
        # El histórico da la FORMA estacional; se reescala al anual impreso.
        annual_kwh = rolling_annual
        observed_months = sorted(history)
        monthly = [round(v * rolling_annual / history_sum, 1) for v in history_monthly]
        seasonality_source = "printed_annual_history_shape"
    elif use_rolling:
        # Sin histórico: perfil residencial por defecto aguas abajo.
        annual_kwh = rolling_annual
        observed_months = []
        monthly = None
        seasonality_source = "printed_annual"
    elif history:
        monthly = history_monthly
        observed_months = sorted(history)
        annual_kwh = history_sum
        seasonality_source = "bill_history"
    elif annual_only:
        monthly = None
        observed_months = []
        annual_kwh = total_kwh
        seasonality_source = "annual_bill"
    else:
        annual_from_months, monthly, observed_months = _estimate_monthly_from_samples(
            monthly_kwh, monthly_days
        )
        annual_kwh = (
            annual_from_months
            if annual_from_months is not None
            else total_kwh / total_days * 365.25
        )
        if len(observed_months) == 12:
            seasonality_source = "full_year_bills"
        elif observed_months:
            seasonality_source = "estimated_from_sampled_months"
        else:
            seasonality_source = "annualized_by_days"
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
    # El importe mensual del histórico (si la factura lo trae) es la mejor fuente
    # del gasto por mes: real, no reconstruido.
    history_spend = _merge_history_spend(bills) if history else {}
    if history_spend:
        monthly_amount, _spend_estimated = _twelve_months_from_history(history_spend)
        annual_amount = round(sum(monthly_amount), 1)
    elif total_amount_bill_count > 0:
        if annual_only:
            # El importe de una factura anual ya es el gasto anual; no hay reparto
            # mensual fiable, coherente con monthly_kwh=None.
            annual_amount = round(total_bill_amount, 1)
        else:
            annual_amount_from_months, monthly_amount, _observed_amount_months = (
                _estimate_monthly_from_samples(monthly_total_amount, monthly_total_amount_days)
            )
            if annual_amount_from_months is not None:
                annual_amount = annual_amount_from_months
            elif total_amount_days > 0:
                annual_amount = round(total_bill_amount / total_amount_days * 365.25, 1)

    # Precio de energía del periodo valle (pre-impuestos), ponderado por kWh de
    # valle entre facturas: sirve para valorar la batería, que desplaza consumo
    # nocturno (valle), no punta. None si ninguna factura trae el precio por periodo.
    valle_num = valle_den = 0.0
    for bill in bills:
        prices = bill.get("consumption_period_prices") or {}
        periods = bill.get("consumption_periods") or {}
        valle_price = prices.get("valle") if isinstance(prices, dict) else None
        if valle_price and valle_price > 0:
            weight = (periods.get("valle") if isinstance(periods, dict) else None) or 1.0
            valle_num += valle_price * weight
            valle_den += weight
    valle_price_eur_kwh = round(valle_num / valle_den, 4) if valle_den > 0 else None

    # Fuente única de consumo: el mismo annual_kwh alimenta precio y dimensionado.
    # Si el importe/precio implica un consumo muy distinto, algo se detectó mal.
    currency_out = currencies[0] if currencies else (default_currency or DEFAULT_CURRENCY)
    agg_review: list[str] = []
    agg_review_notes: list[dict] = []
    any_bono_social = any(bill.get("bono_social") for bill in bills)

    # (Consolidación por CUPS) Varias facturas del MISMO CUPS son meses de un
    # único suministro (ya se combinan en la curva anual de arriba). Si aparecen
    # CUPS DISTINTOS, son puntos de suministro diferentes y no deberían sumarse
    # como si fueran una sola casa: se avisa.
    distinct_cups = sorted({
        c.strip().upper()
        for bill in bills
        if (c := bill.get("cups")) and str(c).strip()
    })
    if len(distinct_cups) > 1:
        note = bill_messages.note("mixed_cups", n=len(distinct_cups))
        agg_review_notes.append(note)
        agg_review.append(bill_messages.text_es(note["code"], **note["params"]))
    if annual_amount and annual_kwh > 0:
        effective = annual_amount / annual_kwh
        low, high = _effective_price_bounds(currency_out, any_bono_social)
        if effective < low or effective > high:
            note = bill_messages.note(
                "effective_price_annual_out_of_range",
                price=effective, low=low, high=high, currency=currency_out,
            )
            agg_review_notes.append(note)
            agg_review.append(bill_messages.text_es(note["code"], **note["params"]))

    # Fiabilidad del anual: si descansa sobre ~1 mes sin histórico ni factura
    # anual, la estacionalidad lo hace poco fiable para dimensionar (se avisa,
    # no se bloquea: el usuario puede seguir con la salvedad).
    months_covered = total_days / 30.4 if total_days else 0.0
    single_month = (
        not use_rolling and not history and not annual_only and months_covered < 2
    )
    consumption_reliability = "low" if single_month else "normal"

    return {
        "annual_kwh": round(annual_kwh, 1),
        "needs_review": bool(agg_review),
        "review_reasons": agg_review,
        "review_notes": agg_review_notes,
        "consumption_reliability": consumption_reliability,
        "single_month": single_month,
        "months_covered": round(months_covered, 1),
        "distinct_cups": len(distinct_cups),
        "bono_social": any_bono_social,
        "annual_from_printed": use_rolling,
        "valle_price_eur_kwh": valle_price_eur_kwh,
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
        "estimated_months": estimated_months,
        "contracted_power_kw": contracted_power_kw,
        "seasonality_source": seasonality_source,
        "currency": currencies[0] if currencies else (default_currency or DEFAULT_CURRENCY),
    }
