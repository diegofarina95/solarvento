"""Perfiles de consumo eléctrico residencial.

Forma horaria aproximada al perfil doméstico europeo y estacionalidad mensual
con ajustes por clima/país y por algunos hábitos/equipos relevantes.
Cuando el usuario aporta facturas, la estacionalidad real de sus consumos
sustituye a estos pesos por defecto; los ajustes horarios siguen aplicando.
"""

# Forma del día (24 valores, se normaliza a suma 1)
_HOURLY_SHAPE = [
    0.55, 0.45, 0.40, 0.38, 0.38, 0.42,  # 0-5 h: valle nocturno
    0.55, 0.80, 0.95, 0.95, 0.90, 0.95,  # 6-11 h: subida matinal
    1.05, 1.15, 1.10, 0.95, 0.90, 0.95,  # 12-17 h: mediodía
    1.10, 1.35, 1.55, 1.60, 1.30, 0.85,  # 18-23 h: punta de tarde-noche
]

_OCCUPANCY_SHAPES = {
    "standard": _HOURLY_SHAPE,
    "home_day": [
        0.50, 0.42, 0.38, 0.36, 0.36, 0.40,
        0.55, 0.82, 1.00, 1.08, 1.12, 1.18,
        1.25, 1.30, 1.22, 1.10, 1.02, 1.05,
        1.15, 1.35, 1.48, 1.48, 1.18, 0.78,
    ],
    "evening": [
        0.48, 0.40, 0.36, 0.34, 0.34, 0.38,
        0.50, 0.70, 0.78, 0.75, 0.72, 0.75,
        0.78, 0.82, 0.80, 0.78, 0.86, 1.05,
        1.30, 1.62, 1.85, 1.88, 1.45, 0.92,
    ],
    "night": [
        0.78, 0.72, 0.68, 0.66, 0.64, 0.68,
        0.82, 0.95, 0.88, 0.78, 0.72, 0.74,
        0.78, 0.84, 0.82, 0.78, 0.82, 0.92,
        1.08, 1.28, 1.48, 1.62, 1.48, 1.05,
    ],
}

# Peso relativo de cada mes en el consumo anual (se normaliza).
# Se exporta porque las facturas parciales usan el mismo perfil para completar
# los meses no observados.
MONTHLY_WEIGHTS = [1.12, 1.06, 0.98, 0.90, 0.86, 0.94, 1.08, 1.10, 0.94, 0.90, 1.00, 1.12]

_NORTHERN_COUNTRIES = {"BY", "DK", "EE", "FI", "GB", "IE", "IS", "LT", "LV", "NO", "SE"}
_CENTRAL_COUNTRIES = {"AT", "BE", "CH", "CZ", "DE", "FR", "HU", "LU", "NL", "PL", "SK"}
_SOUTHERN_COUNTRIES = {
    "AL", "AD", "BA", "BG", "CY", "ES", "GR", "HR", "IT", "MC", "ME", "MK",
    "MT", "PT", "RO", "RS", "SI", "SM", "TR", "VA", "XK",
}

_COUNTRY_MONTHLY_ADJUSTMENTS = {
    "north": [1.18, 1.14, 1.06, 0.96, 0.86, 0.78, 0.74, 0.78, 0.88, 1.00, 1.14, 1.24],
    "central": [1.12, 1.08, 1.02, 0.94, 0.88, 0.88, 0.92, 0.94, 0.94, 0.98, 1.06, 1.16],
    "south": [1.04, 0.98, 0.92, 0.86, 0.88, 1.02, 1.22, 1.24, 1.02, 0.90, 0.92, 1.00],
}

DAYS_PER_MONTH = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _profile_region(country_code: str | None) -> str:
    code = (country_code or "").upper()
    if code in _NORTHERN_COUNTRIES:
        return "north"
    if code in _SOUTHERN_COUNTRIES:
        return "south"
    if code in _CENTRAL_COUNTRIES:
        return "central"
    return "central"


def _normalize(values: list[float]) -> list[float]:
    total = sum(values)
    if total <= 0:
        return values
    return [value / total for value in values]


def _monthly_weights(
    country_code: str | None,
    *,
    has_heat_pump: bool = False,
    has_ev: bool = False,
    has_pool: bool = False,
) -> list[float]:
    region = _profile_region(country_code)
    values = MONTHLY_WEIGHTS[:]
    adjustment = _COUNTRY_MONTHLY_ADJUSTMENTS[region]
    values = [value * adjustment[i] for i, value in enumerate(values)]
    if has_heat_pump:
        winter = [1.28, 1.24, 1.14, 1.02, 0.90, 0.76, 0.70, 0.72, 0.86, 1.02, 1.16, 1.30]
        values = [value * winter[i] for i, value in enumerate(values)]
    if has_ev:
        values = [value * factor for value, factor in zip(values, [1.05, 1.04, 1.02, 1.0, 0.98, 0.96, 0.96, 0.98, 1.0, 1.02, 1.04, 1.05], strict=True)]
    if has_pool:
        pool = [0.88, 0.88, 0.92, 1.00, 1.08, 1.20, 1.30, 1.30, 1.12, 0.98, 0.88, 0.86]
        values = [value * pool[i] for i, value in enumerate(values)]
    return values


def _hourly_shape(
    occupancy_profile: str,
    *,
    has_heat_pump: bool = False,
    has_ev: bool = False,
    has_pool: bool = False,
) -> list[float]:
    shape = _OCCUPANCY_SHAPES.get(occupancy_profile, _HOURLY_SHAPE)[:]
    if has_heat_pump:
        for hour in (5, 6, 7, 18, 19, 20, 21):
            shape[hour] *= 1.12
    if has_ev:
        for hour in (0, 1, 2, 3, 4, 23):
            shape[hour] *= 1.35
    if has_pool:
        for hour in (10, 11, 12, 13, 14, 15, 16):
            shape[hour] *= 1.12
    return shape


def consumption_profile(
    annual_kwh: float,
    monthly_kwh: list[float] | None = None,
    *,
    country_code: str | None = None,
    occupancy_profile: str = "standard",
    has_heat_pump: bool = False,
    has_ev: bool = False,
    has_pool: bool = False,
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
        weights = _monthly_weights(
            country_code,
            has_heat_pump=has_heat_pump,
            has_ev=has_ev,
            has_pool=has_pool,
        )
        weight_sum = sum(weights)
        months = [annual_kwh * w / weight_sum for w in weights]

    shape = _hourly_shape(
        occupancy_profile,
        has_heat_pump=has_heat_pump,
        has_ev=has_ev,
        has_pool=has_pool,
    )
    hourly_fractions = _normalize(shape)
    profile = []
    for m in range(12):
        daily_kwh = months[m] / DAYS_PER_MONTH[m]
        profile.append([round(daily_kwh * fraction, 4) for fraction in hourly_fractions])
    return profile
