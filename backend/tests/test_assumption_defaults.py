"""Supuestos por defecto del motor económico (ajuste jul-2026, validado por Diego).

- loss_pct 11%: instalaciones modernas rinden 8-12% de pérdidas; el 14% era el
  default heredado de PVGIS y sesgaba la producción a la baja.
- O&M 0,7% del capex/año: el 1% era el techo del rango residencial.
- Descuento 3,5% nominal: ni el 3% optimista ni el 5% conservador.
"""

from app import cashflow
from app.schemas import SolarEstimateRequest


def test_om_por_defecto_es_0_7_pct():
    assert cashflow.OM_PCT_PER_YEAR == 0.007


def test_descuento_por_defecto_es_3_5_pct():
    assert cashflow.DISCOUNT_RATE == 0.035


def test_perdidas_por_defecto_son_11_pct():
    assert SolarEstimateRequest.model_fields["loss_pct"].default == 11.0
