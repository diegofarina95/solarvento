"""Perfil de consumo eléctrico residencial tipo (España).

Forma horaria aproximada al perfil doméstico peninsular (valle nocturno,
subida matinal, meseta de mediodía y punta de tarde-noche) y estacionalidad
mensual con máximos en invierno y verano (calefacción/aire acondicionado).
Cuando el usuario aporta facturas, la estacionalidad real de sus consumos
sustituye a estos pesos por defecto.
"""

# Forma del día (24 valores, se normaliza a suma 1)
_HOURLY_SHAPE = [
    0.55, 0.45, 0.40, 0.38, 0.38, 0.42,  # 0-5 h: valle nocturno
    0.55, 0.80, 0.95, 0.95, 0.90, 0.95,  # 6-11 h: subida matinal
    1.05, 1.15, 1.10, 0.95, 0.90, 0.95,  # 12-17 h: mediodía
    1.10, 1.35, 1.55, 1.60, 1.30, 0.85,  # 18-23 h: punta de tarde-noche
]
_SHAPE_SUM = sum(_HOURLY_SHAPE)

# Peso relativo de cada mes en el consumo anual (se normaliza).
# Se exporta porque las facturas parciales usan el mismo perfil para completar
# los meses no observados.
MONTHLY_WEIGHTS = [1.12, 1.06, 0.98, 0.90, 0.86, 0.94, 1.08, 1.10, 0.94, 0.90, 1.00, 1.12]
_WEIGHTS_SUM = sum(MONTHLY_WEIGHTS)

DAYS_PER_MONTH = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def consumption_profile(
    annual_kwh: float, monthly_kwh: list[float] | None = None
) -> list[list[float]]:
    """Matriz 12x24: kWh consumidos en la hora h de un día medio del mes m.

    Si se pasan los kWh reales de cada mes (derivados de facturas), se usan;
    si no, el anual se reparte con la estacionalidad por defecto.
    """
    if monthly_kwh is not None:
        if len(monthly_kwh) != 12:
            raise ValueError("monthly_kwh debe tener 12 valores")
        months = monthly_kwh
    else:
        months = [annual_kwh * w / _WEIGHTS_SUM for w in MONTHLY_WEIGHTS]

    profile = []
    for m in range(12):
        daily_kwh = months[m] / DAYS_PER_MONTH[m]
        profile.append([round(daily_kwh * s / _SHAPE_SUM, 4) for s in _HOURLY_SHAPE])
    return profile
