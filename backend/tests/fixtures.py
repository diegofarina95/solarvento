"""Respuestas de PVGIS reducidas para tests (estructura real de la API v5.2)."""


def pvcalc_response(slope: float = 35, azimuth: float = 0, optimal: bool = True) -> dict:
    base_monthly = [76.73, 100.37, 134.17, 152.61, 170.76, 171.54, 190.18, 187.04, 164.81, 121.52, 81.98, 75.52]
    monthly = [
        {
            "month": i + 1,
            "E_d": round(h * 4.2 / 30, 2),
            "E_m": round(h * 4.2, 2),
            "H(i)_d": round(h / 30, 2),
            "H(i)_m": h,
            "SD_m": 50.0,
        }
        for i, h in enumerate(base_monthly)
    ]
    total_e = round(sum(m["E_m"] for m in monthly), 2)
    total_h = round(sum(m["H(i)_m"] for m in monthly), 2)
    return {
        "inputs": {
            "location": {"latitude": 42.88, "longitude": -8.54, "elevation": 250.0},
            "meteo_data": {"radiation_db": "PVGIS-SARAH2"},
            "mounting_system": {
                "fixed": {
                    "slope": {"value": slope, "optimal": optimal},
                    "azimuth": {"value": azimuth, "optimal": optimal},
                }
            },
            "pv_module": {"technology": "c-Si", "peak_power": 5.0, "system_loss": 14.0},
        },
        "outputs": {
            "monthly": {"fixed": monthly},
            "totals": {
                "fixed": {
                    "E_d": 17.64,
                    "E_m": round(total_e / 12, 2),
                    "E_y": total_e,
                    "H(i)_d": 4.46,
                    "H(i)_m": round(total_h / 12, 2),
                    "H(i)_y": total_h,
                }
            },
        },
    }


def seriescalc_response() -> dict:
    """Serie horaria sintética de 2020: campana de producción de 8 a 17 h."""
    rows = []
    bell = {h: max(0, 1 - abs(h - 12.5) / 5) for h in range(24)}  # 0..1
    days_2020 = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for month in range(1, 13):
        season = 0.6 + 0.4 * (1 - abs(month - 6.5) / 5.5)
        for day in range(1, days_2020[month - 1] + 1):
            for hour in range(24):
                rows.append(
                    {
                        "time": f"2020{month:02d}{day:02d}:{hour:02d}10",
                        "P": round(3000 * bell[hour] * season, 1),  # W
                        "G(i)": 0.0,
                    }
                )
    return {"outputs": {"hourly": rows}}


