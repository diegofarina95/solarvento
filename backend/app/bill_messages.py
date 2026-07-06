"""Catálogo único de avisos/revisiones del parser de facturas.

Cada aviso es un CÓDIGO estable + parámetros. El backend sigue emitiendo el
texto en español (para logs y compatibilidad), pero además emite el código para
que el frontend lo traduzca al idioma de la UI (ES/EN/IT/FR/PT). Un solo sitio
define el texto español y la lista de códigos válidos.
"""

from __future__ import annotations

from typing import Any

# code -> plantilla en español (función de params).
_TEMPLATES: dict[str, Any] = {
    # Paso a través de texto libre (avisos del modelo sin código propio).
    "raw": lambda p: str(p.get("text", "")),
    "effective_price_out_of_range": lambda p: (
        f"El precio efectivo detectado ({p['price']:.2f} {p['currency']}/kWh) queda fuera de "
        f"lo razonable ({p['low']:.2f}–{p['high']:.2f} {p['currency']}/kWh): el consumo puede "
        "ser una sola columna de periodo en vez del total. Revisa el consumo."
    ),
    "effective_price_annual_out_of_range": lambda p: (
        f"El precio efectivo anual ({p['price']:.2f} {p['currency']}/kWh) queda fuera de lo "
        f"razonable ({p['low']:.2f}–{p['high']:.2f}); revisa el consumo detectado."
    ),
    "sources_disagree": lambda p: (
        f"Las fuentes de consumo de la factura no coinciden ({p['detail']} kWh); revísalo."
    ),
    "annual_sources_disagree": lambda p: (
        f"Las fuentes de consumo no coinciden ({p['detail']} kWh); revisa el consumo."
    ),
    "consumption_corrected": lambda p: (
        f"Consumo de la factura corregido a {p['value']:.0f} kWh por coincidencia de fuentes; "
        f"la cifra detectada ({p['detected']}) no cuadraba."
    ),
    "no_annual_resolved": lambda p: (
        "No se pudo resolver el consumo anual; envía una factura con histórico o anual."
    ),
    "single_month": lambda p: (
        "Esto es el consumo de UN mes, no el anual. Una sola factura mensual no permite "
        "dimensionar con fiabilidad por la estacionalidad; sube el histórico anual (gráfico "
        "de 12 meses) o varias facturas repartidas por el año."
    ),
    "estimate_few_months": lambda p: (
        f"Estimación: solo ~{p['months']:g} meses de dato real. Envía más meses o una factura "
        "anual para mayor precisión."
    ),
    "existing_pv": lambda p: (
        "Este suministro ya tiene autoconsumo; el consumo de red no refleja la demanda real de "
        "la casa. Revisa antes de dimensionar (no se calcula sobre la red)."
    ),
    "low_confidence_consumption": lambda p: (
        f"Baja confianza en el consumo ({p['conf']:.0%}) y sin otra fuente que lo corrobore; "
        "confírmalo."
    ),
    "bono_social_savings": lambda p: (
        "Esta factura tiene bono social: el precio ya está muy subvencionado, así que el ahorro "
        "del solar puede ser bajo. Si pierdes el bono social, el solar compensa bastante más."
    ),
    "location_approx": lambda p: (
        "No se pudo ubicar el suministro con precisión (el CP no cuadró con el geocodificado); "
        "el mapa muestra una posición aproximada. Ajústala a mano si hace falta."
    ),
    "mixed_cups": lambda p: (
        f"Las facturas parecen de puntos de suministro distintos (CUPS diferentes: {p['n']}); "
        "sube solo las de un mismo suministro para dimensionar bien."
    ),
    "extractor_invalid": lambda p: "El extractor no devolvió un contrato válido.",
    "extraction_failed": lambda p: (
        "No se pudo leer la factura automáticamente; revisa e introduce los datos a mano."
    ),
    "images_unavailable": lambda p: (
        "Las fotos de factura no están disponibles ahora; sube la factura en PDF."
    ),
    "country_not_supported": lambda p: (
        "De momento solo procesamos facturas de España. Esta factura parece de otro país"
        + (f" ({p['country']})" if p.get("country") else "")
        + "; no se ha calculado nada."
    ),
    # --- Cortafuegos de sanidad (bloqueos duros antes de calcular) ---
    "consumption_negative": lambda p: (
        "Esta factura parece una regularización o ajuste (consumo negativo). Sube una factura "
        "de consumo normal."
    ),
    "annual_out_of_range": lambda p: (
        f"El consumo detectado ({p['annual']:.0f} kWh/año) está fuera del rango residencial "
        f"({p['low']:.0f}–{p['high']:.0f} kWh). Revísalo o comprueba que es una vivienda."
    ),
    "incoherent_period": lambda p: (
        "Las fechas del periodo no son válidas (fin anterior al inicio). Revísalas."
    ),
    # --- Límite de subidas (no es un error de lectura) ---
    "upload_limit": lambda p: (
        f"Has alcanzado el límite de {p.get('limit', 10)} facturas subidas. Introduce el resto "
        "de datos a mano o inténtalo más tarde."
    ),
    "upload_quota": lambda p: (
        "El servicio de lectura de facturas ha alcanzado su cupo diario. Introduce los datos a "
        "mano o inténtalo mañana."
    ),
}


def note(code: str, **params: Any) -> dict[str, Any]:
    """Devuelve el sobre {code, params} para el frontend. Valida el código."""
    if code not in _TEMPLATES:
        raise KeyError(f"código de aviso desconocido: {code}")
    return {"code": code, "params": params}


def text_es(code: str, **params: Any) -> str:
    """Texto español del aviso (logs / compatibilidad / tests)."""
    return _TEMPLATES[code](params)
