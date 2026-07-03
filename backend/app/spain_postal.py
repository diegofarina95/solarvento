"""Código postal español → provincia y centroide (ancla fiable de ubicación).

Los dos primeros dígitos del CP identifican la provincia (01–52) e implican
país = ES. Sirve para fijar país y, si el geocodificado del domicilio falla,
sesgar el mapa al centroide provincial (baja confianza). Centroides ≈ capital.
"""

# CP2 -> (nombre de provincia, lat, lon de la capital)
CP2_PROVINCE: dict[str, tuple[str, float, float]] = {
    "01": ("Álava", 42.8467, -2.6716),
    "02": ("Albacete", 38.9943, -1.8585),
    "03": ("Alicante", 38.3452, -0.4810),
    "04": ("Almería", 36.8340, -2.4637),
    "05": ("Ávila", 40.6565, -4.6818),
    "06": ("Badajoz", 38.8794, -6.9707),
    "07": ("Illes Balears", 39.5696, 2.6502),
    "08": ("Barcelona", 41.3851, 2.1734),
    "09": ("Burgos", 42.3439, -3.6969),
    "10": ("Cáceres", 39.4753, -6.3724),
    "11": ("Cádiz", 36.5271, -6.2886),
    "12": ("Castellón", 39.9864, -0.0513),
    "13": ("Ciudad Real", 38.9848, -3.9273),
    "14": ("Córdoba", 37.8882, -4.7794),
    "15": ("A Coruña", 43.3623, -8.4115),
    "16": ("Cuenca", 40.0704, -2.1374),
    "17": ("Girona", 41.9794, 2.8214),
    "18": ("Granada", 37.1773, -3.5986),
    "19": ("Guadalajara", 40.6320, -3.1669),
    "20": ("Gipuzkoa", 43.3183, -1.9812),
    "21": ("Huelva", 37.2614, -6.9447),
    "22": ("Huesca", 42.1362, -0.4087),
    "23": ("Jaén", 37.7796, -3.7849),
    "24": ("León", 42.5987, -5.5671),
    "25": ("Lleida", 41.6176, 0.6200),
    "26": ("La Rioja", 42.4627, -2.4449),
    "27": ("Lugo", 43.0121, -7.5559),
    "28": ("Madrid", 40.4168, -3.7038),
    "29": ("Málaga", 36.7213, -4.4214),
    "30": ("Murcia", 37.9922, -1.1307),
    "31": ("Navarra", 42.8125, -1.6458),
    "32": ("Ourense", 42.3358, -7.8639),
    "33": ("Asturias", 43.3619, -5.8494),
    "34": ("Palencia", 42.0096, -4.5288),
    "35": ("Las Palmas", 28.1235, -15.4363),
    "36": ("Pontevedra", 42.4310, -8.6444),
    "37": ("Salamanca", 40.9701, -5.6635),
    "38": ("Santa Cruz de Tenerife", 28.4636, -16.2518),
    "39": ("Cantabria", 43.4623, -3.8099),
    "40": ("Segovia", 40.9429, -4.1088),
    "41": ("Sevilla", 37.3891, -5.9845),
    "42": ("Soria", 41.7665, -2.4790),
    "43": ("Tarragona", 41.1189, 1.2445),
    "44": ("Teruel", 40.3456, -1.1065),
    "45": ("Toledo", 39.8628, -4.0273),
    "46": ("Valencia", 39.4699, -0.3763),
    "47": ("Valladolid", 41.6523, -4.7245),
    "48": ("Bizkaia", 43.2630, -2.9350),
    "49": ("Zamora", 41.5033, -5.7446),
    "50": ("Zaragoza", 41.6488, -0.8891),
    "51": ("Ceuta", 35.8894, -5.3213),
    "52": ("Melilla", 35.2923, -2.9381),
}


def province_from_postal_code(postal_code: str | None) -> tuple[str, float, float] | None:
    """(provincia, lat, lon) a partir de un CP español; None si no es válido."""
    if not postal_code:
        return None
    digits = "".join(ch for ch in str(postal_code) if ch.isdigit())
    if len(digits) < 4:
        return None
    return CP2_PROVINCE.get(digits[:2].zfill(2))
