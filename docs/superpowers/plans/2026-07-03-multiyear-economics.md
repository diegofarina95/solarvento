# Economía plurianual (payback real, VAN/TIR, factor fiscal, subvención) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir el payback simple (coste / ahorro del año 1) por un flujo de caja plurianual con degradación, escalada de precios, mantenimiento y reemplazo de inversor; corregir el precio evitado con impuestos cuando viene de facturas; y permitir indicar una subvención.

**Architecture:** Nuevo módulo backend `cashflow.py` que re-simula cada año con `simulation.simulate_self_consumption` (paneles y batería envejecidos, precios escalados) y calcula payback interpolado, ahorro a 25 años, VAN y TIR. `main.py` lo conecta a la economía base y a cada escenario de batería. El frontend añade campo de subvención, tarjetas nuevas, bloque de supuestos y gráfica de flujo acumulado.

**Tech Stack:** FastAPI + Pydantic (backend), pytest, React + recharts + i18n propio (frontend, 4 idiomas: es/en/fr/it).

**Spec:** `docs/superpowers/specs/2026-07-03-multiyear-economics-design.md`

## Global Constraints

- Los tests backend se ejecutan desde `backend/` con `.venv/bin/python -m pytest` (los de integración PVGIS requieren `-m integration`; no tocarlos).
- No renombrar campos existentes de la API; solo añadir (`payback_years` cambia de semántica, no de nombre).
- Todas las cadenas visibles nuevas van a `frontend/src/i18n/translations.js` en es, en, fr e it.
- Los supuestos económicos son constantes documentadas en `cashflow.py` y viajan en la respuesta (`economics.assumptions`).
- El factor fiscal solo se aplica cuando `electricity_price_source == "bills"`; para países sin dato verificado el factor es 1.0 (comportamiento actual).
- Commits frecuentes, mensajes en español como el historial, con `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Motor de flujo de caja (parte analítica)

**Files:**
- Create: `backend/app/cashflow.py`
- Test: `backend/tests/test_cashflow.py`

**Interfaces:**
- Consumes: nada (módulo hoja en esta task).
- Produces:
  - `simple_yearly_savings(first_year_savings: float, *, years=30, panel_degradation=0.005, price_escalation=0.02) -> list[float]`
  - `cashflow_analysis(yearly_savings: list[float], *, investment_eur: float, subsidy_eur=0.0, om_eur_per_year=0.0, replacements: dict[int, float] | None = None, discount_rate=0.03, headline_years=25) -> dict` con claves `payback_years`, `net_investment_eur`, `savings_headline_eur`, `npv_eur`, `irr_pct`, `cumulative` (lista `{year, net_eur, cumulative_eur}`), `assumptions` (dict).
  - Constantes: `HORIZON_YEARS=30`, `HEADLINE_YEARS=25`, `PANEL_DEGRADATION_PER_YEAR=0.005`, `PRICE_ESCALATION_PER_YEAR=0.02`, `BATTERY_DEGRADATION_PER_YEAR=0.02`, `OM_PCT_PER_YEAR=0.01`, `INVERTER_REPLACEMENT_YEAR=13`, `DISCOUNT_RATE=0.03`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `backend/tests/test_cashflow.py`:

```python
"""Tests del flujo de caja plurianual."""

import pytest

from app import cashflow


def _flat(savings: float, years: int = 30) -> list[float]:
    return [savings] * years


def test_payback_flat_savings_is_simple_division():
    result = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    assert result["payback_years"] == 10.0


def test_payback_interpolates_within_year():
    # 1000 de inversión, 400/año: se recupera a mitad del año 3
    result = cashflow.cashflow_analysis(_flat(400.0), investment_eur=1000.0)
    assert result["payback_years"] == 2.5


def test_price_escalation_shortens_payback():
    escalated = cashflow.simple_yearly_savings(
        100.0, panel_degradation=0.0, price_escalation=0.05
    )
    result = cashflow.cashflow_analysis(escalated, investment_eur=1000.0)
    assert result["payback_years"] < 10.0


def test_degradation_lengthens_payback():
    degraded = cashflow.simple_yearly_savings(
        100.0, panel_degradation=0.02, price_escalation=0.0
    )
    result = cashflow.cashflow_analysis(degraded, investment_eur=1000.0)
    assert result["payback_years"] > 10.0


def test_om_and_replacement_reduce_net_flows():
    base = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    with_costs = cashflow.cashflow_analysis(
        _flat(100.0),
        investment_eur=1000.0,
        om_eur_per_year=20.0,
        replacements={3: 100.0},
    )
    assert with_costs["payback_years"] > base["payback_years"]
    year3 = with_costs["cumulative"][2]
    assert year3["net_eur"] == pytest.approx(100.0 - 20.0 - 100.0)


def test_subsidy_reduces_net_investment_and_payback():
    result = cashflow.cashflow_analysis(
        _flat(100.0), investment_eur=1000.0, subsidy_eur=500.0
    )
    assert result["net_investment_eur"] == 500.0
    assert result["payback_years"] == 5.0


def test_payback_none_when_never_recovered():
    result = cashflow.cashflow_analysis(_flat(1.0), investment_eur=1000.0)
    assert result["payback_years"] is None


def test_npv_at_zero_discount_equals_cumulative_savings_minus_investment():
    result = cashflow.cashflow_analysis(
        _flat(100.0), investment_eur=1000.0, discount_rate=0.0
    )
    assert result["npv_eur"] == pytest.approx(100.0 * 25 - 1000.0)


def test_irr_of_25y_annuity_is_close_to_annuity_rate():
    # 1000 invertidos, 100/año durante 25 años: TIR ~9.3%
    result = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    assert result["irr_pct"] == pytest.approx(9.3, abs=0.3)


def test_irr_none_when_unprofitable():
    result = cashflow.cashflow_analysis(_flat(1.0), investment_eur=1000.0)
    assert result["irr_pct"] is None


def test_cumulative_rows_cover_horizon():
    result = cashflow.cashflow_analysis(_flat(100.0), investment_eur=1000.0)
    assert len(result["cumulative"]) == 30
    assert result["cumulative"][0] == {
        "year": 1,
        "net_eur": 100.0,
        "cumulative_eur": -900.0,
    }


def test_assumptions_reflect_inputs():
    result = cashflow.cashflow_analysis(
        _flat(100.0),
        investment_eur=1000.0,
        om_eur_per_year=15.0,
        replacements={13: 800.0},
        discount_rate=0.04,
    )
    a = result["assumptions"]
    assert a["om_eur_per_year"] == 15.0
    assert a["inverter_replacement_year"] == 13
    assert a["inverter_replacement_cost_eur"] == 800.0
    assert a["discount_rate_pct"] == 4.0
    assert a["horizon_years"] == 30
```

- [ ] **Step 2: Comprobar que fallan**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cashflow.py -v`
Expected: FAIL / ERROR con `ModuleNotFoundError: app.cashflow` o `ImportError`.

- [ ] **Step 3: Implementar `backend/app/cashflow.py`**

```python
"""Flujo de caja plurianual de la instalación.

El payback simple (coste / ahorro del año 1) ignora efectos que mueven el
resultado en años enteros: degradación de los paneles, subida del precio de
la electricidad, mantenimiento y reemplazo del inversor. Este módulo simula
el horizonte año a año y devuelve payback real, ahorro acumulado, VAN y TIR.
Los supuestos son constantes documentadas y viajan en la respuesta de la API.
"""

from .simulation import annual_savings_with_surplus, simulate_self_consumption

HORIZON_YEARS = 30
HEADLINE_YEARS = 25  # cifras titulares (ahorro total, VAN, TIR) a 25 años
PANEL_DEGRADATION_PER_YEAR = 0.005  # garantías Tier-1: ~85-88% a los 25 años
PRICE_ESCALATION_PER_YEAR = 0.02  # conservador frente al histórico europeo
BATTERY_DEGRADATION_PER_YEAR = 0.02  # LFP: ~80% de capacidad a los 10 años
OM_PCT_PER_YEAR = 0.01  # mantenimiento/seguro anual sobre el coste del sistema
INVERTER_REPLACEMENT_YEAR = 13  # vida típica de un inversor: 10-15 años
DISCOUNT_RATE = 0.03  # tasa nominal para el VAN


def simple_yearly_savings(
    first_year_savings: float,
    *,
    years: int = HORIZON_YEARS,
    panel_degradation: float = PANEL_DEGRADATION_PER_YEAR,
    price_escalation: float = PRICE_ESCALATION_PER_YEAR,
) -> list[float]:
    """Ahorro de cada año sin re-simular: degradación y escalada sobre el año 1."""
    return [
        first_year_savings
        * (1 - panel_degradation) ** y
        * (1 + price_escalation) ** y
        for y in range(years)
    ]


def simulated_yearly_savings(
    production: list[list[float]],
    consumption: list[list[float]],
    battery_kwh: float,
    price_eur_kwh: float,
    surplus_price_eur_kwh: float,
    export_scheme: str,
    *,
    years: int = HORIZON_YEARS,
    panel_degradation: float = PANEL_DEGRADATION_PER_YEAR,
    battery_degradation: float = BATTERY_DEGRADATION_PER_YEAR,
    price_escalation: float = PRICE_ESCALATION_PER_YEAR,
) -> list[float]:
    """Ahorro anual re-simulando cada año con paneles y batería envejecidos.

    El precio del excedente solo escala en esquemas ligados al precio
    minorista; las tarifas de inyección reguladas (feed_in) quedan fijas.
    """
    surplus_escalates = export_scheme != "feed_in"
    savings = []
    for y in range(years):
        production_factor = (1 - panel_degradation) ** y
        production_y = [
            [value * production_factor for value in month] for month in production
        ]
        capacity_y = battery_kwh * (1 - battery_degradation) ** y
        balance = simulate_self_consumption(production_y, consumption, capacity_y)
        escalation = (1 + price_escalation) ** y
        price_y = price_eur_kwh * escalation
        surplus_y = surplus_price_eur_kwh * (escalation if surplus_escalates else 1.0)
        savings.append(
            annual_savings_with_surplus(balance, price_y, surplus_y, export_scheme)
        )
    return savings


def marginal_battery_payback(
    yearly_savings: list[float],
    base_yearly_savings: list[float],
    extra_cost_eur: float,
) -> float | None:
    """Años hasta que el ahorro extra acumulado de la batería cubre su sobrecoste."""
    if extra_cost_eur <= 0:
        return None
    cumulative = 0.0
    for year, (with_battery, without) in enumerate(
        zip(yearly_savings, base_yearly_savings, strict=True), start=1
    ):
        extra = with_battery - without
        previous = cumulative
        cumulative += extra
        if cumulative >= extra_cost_eur and extra > 0:
            return round(year - 1 + (extra_cost_eur - previous) / extra, 1)
    return None


def cashflow_analysis(
    yearly_savings: list[float],
    *,
    investment_eur: float,
    subsidy_eur: float = 0.0,
    om_eur_per_year: float = 0.0,
    replacements: dict[int, float] | None = None,
    discount_rate: float = DISCOUNT_RATE,
    headline_years: int = HEADLINE_YEARS,
) -> dict:
    """Payback real, ahorro acumulado, VAN y TIR a partir del ahorro anual.

    replacements: coste extra en un año dado (p. ej. {13: coste del inversor}).
    El payback se busca en todo el horizonte; el resto de cifras se calculan a
    headline_years.
    """
    replacements = replacements or {}
    net_investment = max(investment_eur - subsidy_eur, 0.0)
    flows = [
        savings - om_eur_per_year - replacements.get(year, 0.0)
        for year, savings in enumerate(yearly_savings, start=1)
    ]

    cumulative_rows = []
    cumulative = -net_investment
    payback = None
    for year, net in enumerate(flows, start=1):
        previous = cumulative
        cumulative += net
        cumulative_rows.append(
            {
                "year": year,
                "net_eur": round(net, 2),
                "cumulative_eur": round(cumulative, 2),
            }
        )
        if payback is None and cumulative >= 0 and net > 0:
            payback = round(year - 1 + -previous / net, 1)

    headline_flows = flows[:headline_years]
    irr = _irr(net_investment, headline_flows)
    return {
        "payback_years": payback,
        "net_investment_eur": round(net_investment, 2),
        "savings_headline_eur": round(sum(headline_flows), 2),
        "npv_eur": round(_npv(discount_rate, net_investment, headline_flows), 2),
        "irr_pct": round(irr * 100, 1) if irr is not None else None,
        "cumulative": cumulative_rows,
        "assumptions": {
            "horizon_years": len(yearly_savings),
            "headline_years": headline_years,
            "panel_degradation_pct_per_year": round(PANEL_DEGRADATION_PER_YEAR * 100, 2),
            "price_escalation_pct_per_year": round(PRICE_ESCALATION_PER_YEAR * 100, 2),
            "battery_degradation_pct_per_year": round(BATTERY_DEGRADATION_PER_YEAR * 100, 2),
            "om_pct_per_year": round(OM_PCT_PER_YEAR * 100, 2),
            "om_eur_per_year": round(om_eur_per_year, 2),
            "inverter_replacement_year": INVERTER_REPLACEMENT_YEAR,
            "inverter_replacement_cost_eur": round(
                replacements.get(INVERTER_REPLACEMENT_YEAR, 0.0), 2
            ),
            "discount_rate_pct": round(discount_rate * 100, 2),
        },
    }


def _npv(rate: float, net_investment: float, flows: list[float]) -> float:
    return -net_investment + sum(
        flow / (1 + rate) ** year for year, flow in enumerate(flows, start=1)
    )


def _irr(net_investment: float, flows: list[float]) -> float | None:
    """TIR por bisección; None si la inversión no es rentable en el horizonte."""
    if net_investment <= 0:
        return None
    low, high = -0.9, 1.0
    if _npv(low, net_investment, flows) < 0:
        return None
    if _npv(high, net_investment, flows) > 0:
        return high
    for _ in range(80):
        mid = (low + high) / 2
        if _npv(mid, net_investment, flows) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2
```

Nota: `simulated_yearly_savings` y `marginal_battery_payback` se testean en la Task 2; se incluyen ya para no editar el módulo dos veces.

- [ ] **Step 4: Comprobar que pasan**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cashflow.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/cashflow.py backend/tests/test_cashflow.py
git commit -m "Motor de flujo de caja plurianual: payback real, VAN, TIR y curva acumulada"
```

---

### Task 2: Ahorro anual re-simulado y payback marginal de batería

**Files:**
- Modify: `backend/app/cashflow.py` (ya escrito en Task 1; esta task solo lo verifica con tests)
- Test: `backend/tests/test_cashflow.py`

**Interfaces:**
- Consumes: `simulation.simulate_self_consumption`, `simulation.annual_savings_with_surplus` (existentes).
- Produces:
  - `simulated_yearly_savings(production: list[list[float]], consumption: list[list[float]], battery_kwh: float, price_eur_kwh: float, surplus_price_eur_kwh: float, export_scheme: str, *, years=30, ...) -> list[float]`
  - `marginal_battery_payback(yearly_savings: list[float], base_yearly_savings: list[float], extra_cost_eur: float) -> float | None`

- [ ] **Step 1: Añadir los tests**

Añadir al final de `backend/tests/test_cashflow.py`:

```python
def _uniform_profile(daily_kwh_per_hour: float) -> list[list[float]]:
    return [[daily_kwh_per_hour] * 24 for _ in range(12)]


def _solar_profile(peak_kwh: float) -> list[list[float]]:
    """Producción solo entre las 8 y las 18 h, para que haya excedente a mediodía."""
    day = [peak_kwh if 8 <= h < 18 else 0.0 for h in range(24)]
    return [day[:] for _ in range(12)]


def test_simulated_savings_decline_without_escalation():
    savings = cashflow.simulated_yearly_savings(
        _solar_profile(1.0),
        _uniform_profile(0.5),
        0.0,
        0.20,
        0.06,
        "capped_compensation",
        price_escalation=0.0,
    )
    assert len(savings) == 30
    assert savings[10] < savings[0]
    assert savings[29] < savings[10]


def test_simulated_savings_grow_with_escalation_above_degradation():
    savings = cashflow.simulated_yearly_savings(
        _solar_profile(1.0),
        _uniform_profile(0.5),
        0.0,
        0.20,
        0.06,
        "capped_compensation",
        price_escalation=0.03,
    )
    assert savings[10] > savings[0]


def test_feed_in_surplus_price_does_not_escalate():
    # Sistema muy excedentario: casi todo el valor viene del vertido
    kwargs = dict(
        production=_solar_profile(2.0),
        consumption=_uniform_profile(0.05),
        battery_kwh=0.0,
        price_eur_kwh=0.30,
        surplus_price_eur_kwh=0.08,
        panel_degradation=0.0,
        price_escalation=0.05,
    )
    feed_in = cashflow.simulated_yearly_savings(
        kwargs["production"], kwargs["consumption"], kwargs["battery_kwh"],
        kwargs["price_eur_kwh"], kwargs["surplus_price_eur_kwh"], "feed_in",
        panel_degradation=0.0, price_escalation=0.05,
    )
    market = cashflow.simulated_yearly_savings(
        kwargs["production"], kwargs["consumption"], kwargs["battery_kwh"],
        kwargs["price_eur_kwh"], kwargs["surplus_price_eur_kwh"], "market_price",
        panel_degradation=0.0, price_escalation=0.05,
    )
    # Con feed_in el excedente no escala: el ahorro del año 10 crece menos
    assert feed_in[9] / feed_in[0] < market[9] / market[0]


def test_battery_capacity_degrades_over_years():
    with_battery = cashflow.simulated_yearly_savings(
        _solar_profile(1.5),
        _uniform_profile(0.6),
        10.0,
        0.25,
        0.05,
        "capped_compensation",
        price_escalation=0.0,
        panel_degradation=0.0,
        battery_degradation=0.03,
    )
    # Sin degradación de paneles ni escalada, la única pérdida es la batería
    assert with_battery[20] < with_battery[0]


def test_marginal_battery_payback_interpolates():
    with_battery = [300.0] * 30
    without = [200.0] * 30
    # 100 extra/año, sobrecoste 250: payback marginal 2.5 años
    assert cashflow.marginal_battery_payback(with_battery, without, 250.0) == 2.5


def test_marginal_battery_payback_none_cases():
    assert cashflow.marginal_battery_payback([100.0] * 30, [100.0] * 30, 500.0) is None
    assert cashflow.marginal_battery_payback([200.0] * 30, [100.0] * 30, 0.0) is None
```

- [ ] **Step 2: Ejecutar los tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_cashflow.py -v`
Expected: PASS (la implementación existe desde Task 1; si algo falla, corregir `cashflow.py`).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_cashflow.py
git commit -m "Tests del ahorro re-simulado por año y del payback marginal de batería"
```

---

### Task 3: Factor fiscal del kWh evitado por país

**Files:**
- Modify: `backend/app/pricing/default_prices.py`
- Modify: `backend/app/pricing/fetch_prices.py` (función `_build_quote`, línea ~74)
- Modify: `backend/app/schemas.py` (clase `PricingSummary`, línea ~223)
- Test: `backend/tests/test_pricing.py`

**Interfaces:**
- Consumes: `DEFAULT_PRICING_BY_COUNTRY` (existente).
- Produces: `ELECTRICITY_TAX_FACTOR_BY_COUNTRY: dict[str, float]` en `default_prices.py`; campo `electricity_tax_factor: float` en el quote de `_build_quote` y en `PricingSummary` (default 1.0).

- [ ] **Step 1: Escribir el test que falla**

Añadir a `backend/tests/test_pricing.py` (seguir el estilo de los tests existentes del quote; si construyen el quote vía `PricingService` o `_build_quote`, replicarlo):

```python
def test_electricity_tax_factor_present_for_verified_countries():
    from app.pricing.default_prices import ELECTRICITY_TAX_FACTOR_BY_COUNTRY

    assert ELECTRICITY_TAX_FACTOR_BY_COUNTRY["ES"] == pytest.approx(1.27, abs=0.01)
    # Solo países con dato verificado; el resto no corrige (factor 1.0)
    assert "MD" not in ELECTRICITY_TAX_FACTOR_BY_COUNTRY


def test_quote_includes_electricity_tax_factor():
    from app.pricing.countries import country_for_coordinates
    from app.pricing.fetch_prices import _build_quote

    spain = country_for_coordinates(40.4, -3.7, None)
    quote = _build_quote(spain, [])
    assert quote["electricity_tax_factor"] == pytest.approx(1.27, abs=0.01)

    poland = country_for_coordinates(52.2, 21.0, None)
    quote_pl = _build_quote(poland, [])
    assert quote_pl["electricity_tax_factor"] == 1.0
```

(Si `test_pricing.py` no importa `pytest`, añadir el import al principio.)

- [ ] **Step 2: Comprobar que falla**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pricing.py -v -k tax_factor`
Expected: FAIL con ImportError/KeyError.

- [ ] **Step 3: Implementar**

En `backend/app/pricing/default_prices.py`, añadir tras `DEFAULT_PRICING_BY_COUNTRY`:

```python
# Factor fiscal del kWh evitado: (1 + impuesto eléctrico) x (1 + IVA de la
# electricidad). Se aplica SOLO cuando el precio €/kWh se deriva del término de
# energía de las facturas (que va sin impuestos): cada kWh autoconsumido evita
# también sus impuestos. Los impuestos por kWh (accisas) se aproximan como % del
# precio doméstico medio del país. Solo países con dato verificado; el resto no
# corrige (factor 1.0, comportamiento conservador).
ELECTRICITY_TAX_FACTOR_BY_COUNTRY: dict[str, float] = {
    "ES": 1.27,  # impuesto eléctrico 5,11% x IVA 21%
    "PT": 1.23,  # IVA 23% (tramo general de energía)
    "FR": 1.28,  # accise ~0,021 €/kWh (~8% del precio) x TVA 20%
    "DE": 1.25,  # Stromsteuer 0,0205 €/kWh (~5%) x USt 19%
    "IT": 1.18,  # accisa 0,0227 €/kWh (~7%) x IVA 10%
    "GB": 1.05,  # VAT 5% en electricidad doméstica
}
DEFAULT_ELECTRICITY_TAX_FACTOR = 1.0
```

En `backend/app/pricing/fetch_prices.py`:
- Ampliar el import: `from .default_prices import (DEFAULT_ELECTRICITY_TAX_FACTOR, DEFAULT_PRICE_REVIEW_DATE, DEFAULT_PRICING_BY_COUNTRY, ELECTRICITY_TAX_FACTOR_BY_COUNTRY)`.
- En el dict que devuelve `_build_quote`, junto a `"export_scheme": ...`, añadir:

```python
        "electricity_tax_factor": ELECTRICITY_TAX_FACTOR_BY_COUNTRY.get(
            country.code, DEFAULT_ELECTRICITY_TAX_FACTOR
        ),
```

En `backend/app/schemas.py`, en `PricingSummary` (junto a `export_scheme`):

```python
    electricity_tax_factor: float = 1.0
```

- [ ] **Step 4: Comprobar que pasa y que nada se rompe**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pricing.py tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pricing/default_prices.py backend/app/pricing/fetch_prices.py backend/app/schemas.py backend/tests/test_pricing.py
git commit -m "Factor fiscal del kWh evitado por país (impuesto eléctrico + IVA)"
```

---

### Task 4: Schemas de petición y respuesta

**Files:**
- Modify: `backend/app/schemas.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces (usado por Task 5 y el frontend):
  - `SolarEstimateRequest.subsidy_eur: float | None`
  - `class YearCashflow(BaseModel)`: `year: int`, `net_eur: float`, `cumulative_eur: float`
  - `class CashflowAssumptions(BaseModel)` con los campos del dict `assumptions` de `cashflow_analysis`
  - `Economics` ampliado: `simple_payback_years`, `savings_25yr_eur`, `npv_eur`, `irr_pct`, `subsidy_eur`, `net_investment_eur`, `effective_price_eur_kwh`, `marginal_price_factor`, `cumulative_cashflow`, `assumptions`
  - `BatteryScenario.npv_eur: float | None`

- [ ] **Step 1: Editar `schemas.py`**

En `SolarEstimateRequest`, tras `battery_cost_per_kwh_eur`:

```python
    subsidy_eur: float | None = Field(
        None,
        ge=0,
        le=100_000_000,
        description="Subvención o deducción estimada; se resta de la inversión neta",
    )
```

Antes de `class Economics`, añadir:

```python
class YearCashflow(BaseModel):
    year: int
    net_eur: float
    cumulative_eur: float


class CashflowAssumptions(BaseModel):
    horizon_years: int
    headline_years: int
    panel_degradation_pct_per_year: float
    price_escalation_pct_per_year: float
    battery_degradation_pct_per_year: float
    om_pct_per_year: float
    om_eur_per_year: float
    inverter_replacement_year: int
    inverter_replacement_cost_eur: float
    discount_rate_pct: float
```

En `Economics`, tras `roi_pct`:

```python
    # Flujo de caja plurianual: payback_years pasa a ser el payback real
    simple_payback_years: float | None = None
    savings_25yr_eur: float | None = None
    npv_eur: float | None = None
    irr_pct: float | None = None
    subsidy_eur: float | None = None
    net_investment_eur: float | None = None
    effective_price_eur_kwh: float | None = None
    marginal_price_factor: float = 1.0
    cumulative_cashflow: list[YearCashflow] = Field(default_factory=list)
    assumptions: CashflowAssumptions | None = None
```

En `BatteryScenario`, tras `battery_marginal_payback_years`:

```python
    npv_eur: float | None = None
```

- [ ] **Step 2: Comprobar que los tests existentes siguen pasando**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS (todos los campos nuevos son opcionales).

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas.py
git commit -m "Schemas: subvención en la petición y economía plurianual en la respuesta"
```

---

### Task 5: Cablear el flujo de caja en `main.py`

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `cashflow.simple_yearly_savings`, `cashflow.simulated_yearly_savings`, `cashflow.cashflow_analysis`, `cashflow.marginal_battery_payback`, constantes `OM_PCT_PER_YEAR` e `INVERTER_REPLACEMENT_YEAR`; `price_quote["electricity_tax_factor"]`; `req.subsidy_eur`.
- Produces: respuesta con `economics` plurianual y escenarios de batería con payback plurianual.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `backend/tests/test_api.py`:

```python
@respx.mock
def test_solar_estimate_multiyear_economics(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "tilt_deg": 20,
            "azimuth_deg": 45,
            "annual_consumption_kwh": 4000,
            "installation_cost_eur": 7000,
            "electricity_price_eur_kwh": 0.20,
        },
    )
    assert resp.status_code == 200
    eco = resp.json()["economics"]
    assert eco["payback_years"] is not None
    assert eco["simple_payback_years"] is not None
    assert eco["savings_25yr_eur"] is not None
    assert len(eco["cumulative_cashflow"]) == 30
    a = eco["assumptions"]
    assert a["price_escalation_pct_per_year"] == 2.0
    assert a["inverter_replacement_year"] == 13
    assert a["inverter_replacement_cost_eur"] > 0
    assert a["om_eur_per_year"] == pytest.approx(70.0)  # 1% de 7000
    # Precio manual: sin corrección fiscal
    assert eco["marginal_price_factor"] == 1.0
    assert eco["effective_price_eur_kwh"] == 0.20
    # El año 13 refleja el reemplazo del inversor
    year13 = eco["cumulative_cashflow"][12]
    year12 = eco["cumulative_cashflow"][11]
    assert year13["net_eur"] < year12["net_eur"]
    # Escenarios de batería con métricas plurianuales
    scenarios = resp.json()["battery_analysis"]["scenarios"]
    assert all("npv_eur" in s for s in scenarios)


@respx.mock
def test_solar_estimate_subsidy_reduces_payback(respx_mock, client):
    mock_pvgis(respx_mock)
    base_body = {
        "lat": 42.88,
        "lon": -8.54,
        "peak_power_kwp": 5.0,
        "annual_consumption_kwh": 4000,
        "installation_cost_eur": 7000,
        "electricity_price_eur_kwh": 0.20,
    }
    base = client.post("/api/solar-estimate", json=base_body).json()["economics"]
    subsidized = client.post(
        "/api/solar-estimate", json={**base_body, "subsidy_eur": 2000}
    ).json()["economics"]
    assert subsidized["net_investment_eur"] == 5000.0
    assert subsidized["subsidy_eur"] == 2000.0
    assert subsidized["payback_years"] < base["payback_years"]


@respx.mock
def test_bills_price_gets_tax_factor(respx_mock, client):
    mock_pvgis(respx_mock)
    resp = client.post(
        "/api/solar-estimate",
        json={
            "lat": 42.88,
            "lon": -8.54,
            "peak_power_kwp": 5.0,
            "bills": [
                {"kwh": 300, "energy_eur": 45.0, "month": 1},
                {"kwh": 250, "energy_eur": 38.0, "month": 6},
            ],
        },
    )
    assert resp.status_code == 200
    eco = resp.json()["economics"]
    assert eco["electricity_price_source"] == "bills"
    # España: el término de energía va sin impuestos; el kWh evitado los incluye
    assert eco["marginal_price_factor"] == pytest.approx(1.27, abs=0.01)
    assert eco["effective_price_eur_kwh"] == pytest.approx(
        eco["electricity_price_eur_kwh"] * 1.27, rel=0.01
    )
```

(Si `test_api.py` no importa `pytest`, ya lo importa — verificar en cabecera.)

- [ ] **Step 2: Comprobar que fallan**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -v -k "multiyear or subsidy or tax_factor"`
Expected: FAIL (faltan campos en la respuesta).

- [ ] **Step 3: Implementar en `main.py`**

3a. Import: en `from . import bills as bills_mod` (línea ~14) añadir `cashflow`:

```python
from . import bills as bills_mod
from . import calculations, cashflow, simulation
```

3b. Tras `_resolve_electricity_price(...)` (línea ~884) y ANTES de `_attach_consumption_costs`, calcular el precio efectivo y usar ese para el gasto estimado:

```python
    # El término de energía de las facturas va sin impuestos: cada kWh
    # autoconsumido evita también impuesto eléctrico + IVA. Los precios por
    # defecto ya los incluyen y el manual se asume final.
    marginal_price_factor = (
        price_quote.get("electricity_tax_factor", 1.0) if price_source == "bills" else 1.0
    )
    effective_price = round(price * marginal_price_factor, 4)
    _attach_consumption_costs(consumption_summary, effective_price)
```

(Eliminar la llamada anterior `_attach_consumption_costs(consumption_summary, price)`.)

3c. Tras el bloque de `surplus_price` (línea ~904), añadir:

```python
    export_scheme = price_quote.get("export_scheme", "capped_compensation")
    # En esquemas que descuentan de la factura, la compensación reduce también
    # la base imponible; en feed-in/mercado el vertido es un ingreso sin IVA evitado.
    effective_surplus = (
        round(surplus_price * marginal_price_factor, 4)
        if export_scheme in ("capped_compensation", "net_metering")
        else surplus_price
    )
    subsidy = req.subsidy_eur or 0.0
    om_eur = round(cost * cashflow.OM_PCT_PER_YEAR, 2)
    inverter_replacement_cost = round(
        cost_details["inverter_price_per_kwp"]["medium"] * analysis_power_kwp, 2
    )
    replacements = {cashflow.INVERTER_REPLACEMENT_YEAR: inverter_replacement_cost}
```

3d. En la llamada a `simulation.battery_scenarios(...)` (línea ~942), sustituir `price` por `effective_price`, `surplus_price` por `effective_surplus` y `export_scheme=price_quote.get(...)` por `export_scheme=export_scheme`.

3e. Tras `_attach_battery_cost_ranges(...)` y ANTES de `_battery_recommendation(scenarios)`, recalcular métricas plurianuales por escenario:

```python
        scenario_yearly = {
            s["battery_kwh"]: cashflow.simulated_yearly_savings(
                hourly_production,
                cons_profile,
                s["battery_kwh"],
                effective_price,
                effective_surplus,
                export_scheme,
            )
            for s in scenarios
        }
        base_yearly = scenario_yearly[0.0]
        base_analysis = None
        for s in scenarios:
            analysis = cashflow.cashflow_analysis(
                scenario_yearly[s["battery_kwh"]],
                investment_eur=s["investment_eur"],
                subsidy_eur=subsidy,
                om_eur_per_year=om_eur,
                replacements=replacements,
            )
            s["payback_years"] = analysis["payback_years"]
            s["npv_eur"] = analysis["npv_eur"]
            if s["battery_kwh"] == 0:
                base_analysis = analysis
            else:
                s["battery_marginal_payback_years"] = cashflow.marginal_battery_payback(
                    scenario_yearly[s["battery_kwh"]],
                    base_yearly,
                    s["investment_eur"] - cost,
                )
```

3f. En la rama `else` (sin simulación horaria, línea ~986), tras calcular y capar `savings`, construir el análisis analítico. La estructura final del tramo queda:

```python
        savings = scenarios[0]["annual_savings_eur"]
    else:
        savings = calculations.annual_savings_eur(
            selected["annual_production_kwh"], effective_price, annual_consumption
        )
        savings = _cap_savings_to_annual_spend(
            savings, annual_consumption, effective_price, export_scheme
        )
        base_analysis = cashflow.cashflow_analysis(
            cashflow.simple_yearly_savings(savings),
            investment_eur=cost,
            subsidy_eur=subsidy,
            om_eur_per_year=om_eur,
            replacements=replacements,
        )
    savings = _cap_savings_to_annual_spend(
        savings, annual_consumption, effective_price, export_scheme
    )
```

(Nota: la llamada exterior a `_cap_savings_to_annual_spend` existente pasa a usar `effective_price` y `export_scheme`; la interior de la rama else puede omitirse si se deja solo la exterior — dejar SOLO la exterior para no capar dos veces.)

3g. Sustituir el bloque `payback/roi/economics` (líneas ~994-1006) por:

```python
    payback = base_analysis["payback_years"]
    simple_payback = calculations.payback_years(base_analysis["net_investment_eur"], savings)
    roi_pct = round(savings / cost * 100, 1) if cost > 0 else None
    economics = {
        "electricity_price_eur_kwh": price,
        "electricity_price_source": price_source,
        "electricity_price_bill_count": price_bill_count,
        "annual_savings_eur": savings,
        "payback_years": payback,
        "simple_payback_years": simple_payback,
        "installation_cost_eur": cost,
        "installation_cost_range_eur": cost_details["system_cost_range"],
        "cost_is_estimated": cost_is_estimated,
        "roi_pct": roi_pct,
        "savings_25yr_eur": base_analysis["savings_headline_eur"],
        "npv_eur": base_analysis["npv_eur"],
        "irr_pct": base_analysis["irr_pct"],
        "subsidy_eur": subsidy if subsidy > 0 else None,
        "net_investment_eur": base_analysis["net_investment_eur"],
        "effective_price_eur_kwh": effective_price,
        "marginal_price_factor": marginal_price_factor,
        "cumulative_cashflow": base_analysis["cumulative"],
        "assumptions": base_analysis["assumptions"],
    }
```

3h. En `_validate_estimate_consistency` (línea ~742-746), el gasto anual debe compararse con el precio efectivo (con impuestos):

```python
    consumption = annual_energy.get("consumption_kwh")
    if consumption and consumption > 0:
        reference_price = (
            economics.get("effective_price_eur_kwh")
            or economics["electricity_price_eur_kwh"]
        )
        annual_spend = consumption * reference_price
        if economics["annual_savings_eur"] > annual_spend + 0.5:
            warnings.append("annual savings exceed annual electricity spend")
```

3i. En `battery_analysis` (línea ~970), el `export_scheme` ya está en variable: usar `"export_scheme": export_scheme`.

- [ ] **Step 4: Ejecutar todos los tests backend**

Run: `cd backend && .venv/bin/python -m pytest -v`
Expected: PASS. Ojo con tests existentes que comparen `payback_years` con valores concretos: la semántica cambió; si alguno falla por eso, actualizar su aserción (comprobar que el nuevo valor es coherente, p. ej. menor que el simple con escalada 2% > degradación 0.5%).

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_api.py
git commit -m "Economía plurianual en /api/solar-estimate: payback real, VAN/TIR, factor fiscal y subvención"
```

---

### Task 6: Frontend — campo de subvención

**Files:**
- Modify: `frontend/src/App.jsx` (estado del formulario línea ~49 y payload línea ~173)
- Modify: `frontend/src/components/SolarForm.jsx` (details «Supuestos económicos», línea ~228)
- Modify: `frontend/src/i18n/translations.js` (bloques `form` de es/en/fr/it)

**Interfaces:**
- Consumes: `params.subsidy_eur` (Task 4/5).
- Produces: `form.subsidy` (string) en el estado del formulario.

- [ ] **Step 1: Estado y payload en `App.jsx`**

En el estado inicial del formulario, tras `batteryCost: '',`:

```js
    subsidy: '',
```

En `calculate()`, dentro del bloque `if (advanced)`, tras el bloque de `form.batteryCost`:

```js
        if (form.subsidy) {
          params.subsidy_eur = requireLocaleNumber(form.subsidy, t('form.subsidy'), t, {
            thousands: true,
          })
        }
```

- [ ] **Step 2: Campo en `SolarForm.jsx`**

En el `<details>` de `form.economicAssumptions`, dentro del `<div className="mt-3 grid gap-3 sm:grid-cols-3">`, añadir tras el campo `batteryCost`:

```jsx
              <Field label={t('form.subsidy')} hint={t('form.subsidyHint')}>
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.subsidy}
                  onChange={set('subsidy')}
                  placeholder="0"
                  className={inputClass}
                />
              </Field>
```

Y tras cerrar ese `<div>` (aún dentro del `<details>`):

```jsx
            <p className="mt-2 text-xs text-stone-500">{t('form.subsidyNote')}</p>
```

- [ ] **Step 3: Traducciones (bloque `form` de cada idioma)**

```js
// es
      subsidy: 'Subvención o deducción (€)',
      subsidyHint: 'Se resta de la inversión para payback y rentabilidad',
      subsidyNote:
        'En muchos países existen ayudas o deducciones fiscales para autoconsumo (deducciones en la renta, IVA reducido, primas locales…). Infórmate de las de tu zona y añade aquí su valor estimado.',
// en
      subsidy: 'Grant or tax deduction (€)',
      subsidyHint: 'Deducted from the investment for payback and returns',
      subsidyNote:
        'Many countries offer grants or tax deductions for self-consumption (income tax deductions, reduced VAT, local schemes…). Check what applies in your area and enter its estimated value here.',
// fr
      subsidy: 'Aide ou déduction (€)',
      subsidyHint: 'Déduite de l’investissement pour le retour et la rentabilité',
      subsidyNote:
        'De nombreux pays proposent des aides ou déductions fiscales pour l’autoconsommation (prime à l’autoconsommation, TVA réduite, aides locales…). Renseignez-vous et indiquez ici leur valeur estimée.',
// it
      subsidy: 'Incentivo o detrazione (€)',
      subsidyHint: 'Si sottrae all’investimento per il rientro e la redditività',
      subsidyNote:
        'Molti paesi offrono incentivi o detrazioni fiscali per l’autoconsumo (detrazioni fiscali, IVA ridotta, bandi locali…). Informati sulla tua zona e inserisci qui il valore stimato.',
```

- [ ] **Step 4: Verificar build**

Run: `cd frontend && npm run build`
Expected: build sin errores.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/SolarForm.jsx frontend/src/i18n/translations.js
git commit -m "Campo de subvención/deducción en el formulario avanzado"
```

---

### Task 7: Frontend — resultados plurianuales, supuestos y gráfica de equilibrio

**Files:**
- Modify: `frontend/src/components/Charts.jsx` (nueva `CashflowChart`)
- Modify: `frontend/src/components/Results.jsx`
- Modify: `frontend/src/components/PrintReport.jsx`
- Modify: `frontend/src/i18n/translations.js` (bloques `results`, `charts` y nuevo bloque `financial` en es/en/fr/it)

**Interfaces:**
- Consumes: `economics.savings_25yr_eur`, `npv_eur`, `irr_pct`, `simple_payback_years`, `net_investment_eur`, `subsidy_eur`, `effective_price_eur_kwh`, `marginal_price_factor`, `cumulative_cashflow`, `assumptions` (Task 5).
- Produces: `CashflowChart({ rows, i18n, currency })` exportada de `Charts.jsx`.

- [ ] **Step 1: `CashflowChart` en `Charts.jsx`**

Añadir `ReferenceLine` al import de recharts y al final del archivo:

```jsx
export function CashflowChart({ rows, i18n, currency }) {
  const { t, locale } = i18n
  const { nf } = formatters(locale)
  const data = rows.map((r) => ({ year: r.year, cumulative: r.cumulative_eur }))
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-stone-700">{t('charts.cashflow')}</h3>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 4, right: 4, left: -4, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--gridline)" />
          <XAxis
            dataKey="year"
            tick={axisStyle}
            tickLine={false}
            stroke="var(--baseline)"
            tickFormatter={(y) => t('charts.yearShort', { value: y })}
          />
          <YAxis tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={nf.format} />
          <ReferenceLine y={0} stroke="var(--baseline)" strokeDasharray="4 4" />
          <Tooltip content={<ChartTooltip unit={currency} formatter={nf.format} />} />
          <Line
            type="monotone"
            dataKey="cumulative"
            stroke="var(--series-cost)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-stone-500">{t('charts.cashflowNote')}</p>
    </div>
  )
}
```

- [ ] **Step 2: `Results.jsx`**

2a. Importar `CashflowChart` donde se importan las otras gráficas.

2b. Tarjeta de payback (línea ~465): cambiar `detail` para reflejar la nueva semántica y mostrar el simple:

```jsx
        {eco.payback_years != null && (
          <Card
            hero
            title={t('results.payback')}
            value={fmt.nf1.format(eco.payback_years)}
            unit={t('units.years')}
            detail={[
              t('results.paybackDetail'),
              eco.simple_payback_years != null
                ? t('results.simplePayback', { value: fmt.nf1.format(eco.simple_payback_years) })
                : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          />
        )}
```

2c. Tarjeta de ahorro anual (línea ~459): si hay factor fiscal, mostrar el precio efectivo:

```jsx
        <Card
          hero
          title={t('results.estimatedSavings')}
          value={fmt.money2.format(eco.annual_savings_eur)}
          detail={
            eco.marginal_price_factor > 1 && eco.effective_price_eur_kwh != null
              ? `${fmt.money2.format(eco.effective_price_eur_kwh)}/kWh · ${t('results.taxInclusivePrice')}`
              : `${fmt.money2.format(eco.electricity_price_eur_kwh)}/kWh`
          }
        />
```

2d. Nueva tarjeta tras la de payback:

```jsx
        {eco.savings_25yr_eur != null && (
          <Card
            hero
            title={t('results.savings25', { years: eco.assumptions?.headline_years ?? 25 })}
            value={fmt.money0.format(eco.savings_25yr_eur)}
            detail={t('results.savings25Detail')}
          />
        )}
```

2e. Nuevo componente antes de `export default function Results` (usa el `formatRange` ya presente en el archivo si existe; si no, formatear directo):

```jsx
function FinancialDetails({ eco, i18n, fmt }) {
  const { t } = i18n
  const a = eco.assumptions
  if (!a) return null
  const rows = [
    eco.net_investment_eur != null && [t('financial.netInvestment'), fmt.money0.format(eco.net_investment_eur)],
    eco.subsidy_eur != null && [t('financial.subsidy'), fmt.money0.format(eco.subsidy_eur)],
    eco.npv_eur != null && [
      t('financial.npv', { rate: fmt.nf1.format(a.discount_rate_pct), years: a.headline_years }),
      fmt.money0.format(eco.npv_eur),
    ],
    eco.irr_pct != null && [t('financial.irr'), `${fmt.nf1.format(eco.irr_pct)} %`],
    [t('financial.degradation'), `${fmt.nf2.format(a.panel_degradation_pct_per_year)} %/${t('units.year')}`],
    [t('financial.escalation'), `+${fmt.nf1.format(a.price_escalation_pct_per_year)} %/${t('units.year')}`],
    [t('financial.om'), `${fmt.money0.format(a.om_eur_per_year)}/${t('units.year')}`],
    a.inverter_replacement_cost_eur > 0 && [
      t('financial.inverter', { year: a.inverter_replacement_year }),
      fmt.money0.format(a.inverter_replacement_cost_eur),
    ],
    eco.marginal_price_factor > 1 && [
      t('financial.taxFactor'),
      `×${fmt.nf2.format(eco.marginal_price_factor)}`,
    ],
  ].filter(Boolean)
  return (
    <details className="card-solar p-4">
      <summary className="cursor-pointer text-sm font-semibold text-stone-700">
        {t('financial.title')}
      </summary>
      <dl className="mt-3 grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3 border-b border-stone-100 pb-1">
            <dt className="text-stone-500">{label}</dt>
            <dd className="font-medium text-stone-800">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-stone-500">{t('financial.note')}</p>
    </details>
  )
}
```

2f. En el JSX de `Results`, tras `<CalculationBasis ... />`:

```jsx
      {(eco.cumulative_cashflow?.length > 0 || eco.assumptions) && (
        <div className="space-y-4">
          {eco.cumulative_cashflow?.length > 0 && (
            <div className="card-solar p-4">
              <CashflowChart
                rows={eco.cumulative_cashflow}
                i18n={i18n}
                currency={pricing.currency_symbol || pricing.currency}
              />
            </div>
          )}
          <FinancialDetails eco={eco} i18n={i18n} fmt={fmt} />
        </div>
      )}
```

- [ ] **Step 3: `PrintReport.jsx`**

Tras la `<Section title={t('report.monthlyProduction')}>` (o tras la sección de batería), añadir para ambas variantes:

```jsx
      {eco.assumptions && (
        <Section title={t('financial.title')}>
          <table className="pr-table pr-kv">
            <tbody>
              <Row
                label={t('results.savings25', { years: eco.assumptions.headline_years })}
                value={eco.savings_25yr_eur != null ? fmt.money0.format(eco.savings_25yr_eur) : null}
              />
              <Row
                label={t('financial.netInvestment')}
                value={eco.net_investment_eur != null ? fmt.money0.format(eco.net_investment_eur) : null}
              />
              <Row
                label={t('financial.npv', {
                  rate: fmt.nf1.format(eco.assumptions.discount_rate_pct),
                  years: eco.assumptions.headline_years,
                })}
                value={eco.npv_eur != null ? fmt.money0.format(eco.npv_eur) : null}
              />
              <Row
                label={t('financial.irr')}
                value={eco.irr_pct != null ? `${fmt.nf1.format(eco.irr_pct)} %` : null}
              />
              <Row
                label={t('financial.escalation')}
                value={`+${fmt.nf1.format(eco.assumptions.price_escalation_pct_per_year)} %/${t('units.year')}`}
              />
              <Row
                label={t('financial.degradation')}
                value={`${fmt.nf2.format(eco.assumptions.panel_degradation_pct_per_year)} %/${t('units.year')}`}
              />
              <Row
                label={t('financial.om')}
                value={`${fmt.money0.format(eco.assumptions.om_eur_per_year)}/${t('units.year')}`}
              />
              {eco.assumptions.inverter_replacement_cost_eur > 0 && (
                <Row
                  label={t('financial.inverter', { year: eco.assumptions.inverter_replacement_year })}
                  value={fmt.money0.format(eco.assumptions.inverter_replacement_cost_eur)}
                />
              )}
            </tbody>
          </table>
        </Section>
      )}
```

- [ ] **Step 4: Traducciones**

Bloque `results` (cada idioma):

```js
// es
      paybackDetail: 'Con subida de la luz, degradación, mantenimiento e inversor incluidos',
      simplePayback: 'simple: {value} años',
      savings25: 'Ahorro neto a {years} años',
      savings25Detail: 'Descontados mantenimiento y reemplazo del inversor',
      taxInclusivePrice: 'con impuestos evitados',
// en
      paybackDetail: 'Includes electricity price rises, degradation, maintenance and inverter',
      simplePayback: 'simple: {value} yrs',
      savings25: 'Net savings over {years} years',
      savings25Detail: 'After maintenance and inverter replacement',
      taxInclusivePrice: 'including avoided taxes',
// fr
      paybackDetail: 'Hausse de l’électricité, dégradation, entretien et onduleur inclus',
      simplePayback: 'simple : {value} ans',
      savings25: 'Économies nettes sur {years} ans',
      savings25Detail: 'Après entretien et remplacement de l’onduleur',
      taxInclusivePrice: 'taxes évitées incluses',
// it
      paybackDetail: 'Con rincari della luce, degrado, manutenzione e inverter inclusi',
      simplePayback: 'semplice: {value} anni',
      savings25: 'Risparmio netto in {years} anni',
      savings25Detail: 'Al netto di manutenzione e sostituzione inverter',
      taxInclusivePrice: 'imposte evitate incluse',
```

(La clave `paybackDetail` existente se SUSTITUYE. La tarjeta ROI también la usaba: darle su propia clave y usarla en `Results.jsx` línea ~612 — `roiDetail`: es `'Ahorro del año 1 sobre la inversión'`, en `'Year-1 savings over the investment'`, fr `'Économies de l’année 1 sur l’investissement'`, it `'Risparmio del primo anno sull’investimento'`.)

Nuevo bloque `financial` (al nivel de `results`, en cada idioma):

```js
// es
    financial: {
      title: 'Supuestos y detalle financiero',
      netInvestment: 'Inversión neta',
      subsidy: 'Subvención aplicada',
      npv: 'VAN ({rate} %, {years} años)',
      irr: 'TIR',
      degradation: 'Degradación de paneles',
      escalation: 'Subida del precio de la luz',
      om: 'Mantenimiento',
      inverter: 'Inversor nuevo (año {year})',
      taxFactor: 'Impuestos evitados por kWh',
      note: 'Proyección orientativa con supuestos conservadores. El payback es el año en que el ahorro acumulado cubre la inversión neta; el VAN descuenta los flujos al tipo indicado.',
    },
// en
    financial: {
      title: 'Assumptions and financial detail',
      netInvestment: 'Net investment',
      subsidy: 'Applied grant',
      npv: 'NPV ({rate}%, {years} yrs)',
      irr: 'IRR',
      degradation: 'Panel degradation',
      escalation: 'Electricity price rise',
      om: 'Maintenance',
      inverter: 'New inverter (year {year})',
      taxFactor: 'Avoided taxes per kWh',
      note: 'Indicative projection with conservative assumptions. Payback is the year cumulative savings cover the net investment; NPV discounts flows at the stated rate.',
    },
// fr
    financial: {
      title: 'Hypothèses et détail financier',
      netInvestment: 'Investissement net',
      subsidy: 'Aide appliquée',
      npv: 'VAN ({rate} %, {years} ans)',
      irr: 'TRI',
      degradation: 'Dégradation des panneaux',
      escalation: 'Hausse du prix de l’électricité',
      om: 'Entretien',
      inverter: 'Nouvel onduleur (année {year})',
      taxFactor: 'Taxes évitées par kWh',
      note: 'Projection indicative avec des hypothèses prudentes. Le retour correspond à l’année où les économies cumulées couvrent l’investissement net ; la VAN actualise les flux au taux indiqué.',
    },
// it
    financial: {
      title: 'Ipotesi e dettaglio finanziario',
      netInvestment: 'Investimento netto',
      subsidy: 'Incentivo applicato',
      npv: 'VAN ({rate} %, {years} anni)',
      irr: 'TIR',
      degradation: 'Degrado dei pannelli',
      escalation: 'Rincaro della luce',
      om: 'Manutenzione',
      inverter: 'Nuovo inverter (anno {year})',
      taxFactor: 'Imposte evitate per kWh',
      note: 'Proiezione indicativa con ipotesi prudenti. Il rientro è l’anno in cui il risparmio cumulato copre l’investimento netto; il VAN attualizza i flussi al tasso indicato.',
    },
```

Bloque `charts` (cada idioma):

```js
// es
      cashflow: 'Ahorro acumulado frente a la inversión',
      cashflowNote: 'La curva cruza el cero en el año de amortización.',
      yearShort: 'a{value}',
// en
      cashflow: 'Cumulative savings vs investment',
      cashflowNote: 'The curve crosses zero in the payback year.',
      yearShort: 'y{value}',
// fr
      cashflow: 'Économies cumulées vs investissement',
      cashflowNote: 'La courbe franchit zéro l’année du retour sur investissement.',
      yearShort: 'a{value}',
// it
      cashflow: 'Risparmio cumulato vs investimento',
      cashflowNote: 'La curva supera lo zero nell’anno di rientro.',
      yearShort: 'a{value}',
```

- [ ] **Step 5: Build y e2e**

Run: `cd frontend && npm run build && npx playwright test`
Expected: build OK; e2e PASS (si el spec e2e asserta textos de payback antiguos, actualizarlos con el nuevo copy).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Charts.jsx frontend/src/components/Results.jsx frontend/src/components/PrintReport.jsx frontend/src/i18n/translations.js
git commit -m "Resultados plurianuales: ahorro a 25 años, supuestos, VAN/TIR y gráfica de equilibrio"
```

---

### Task 8: Verificación completa

**Files:** ninguno nuevo.

- [ ] **Step 1: Suite backend completa**

Run: `cd backend && .venv/bin/python -m pytest -v`
Expected: PASS.

- [ ] **Step 2: Build frontend + e2e**

Run: `cd frontend && npm run build && npx playwright test`
Expected: PASS.

- [ ] **Step 3: Prueba manual del endpoint**

Arrancar el backend y lanzar una petición representativa; comprobar a ojo que payback plurianual < payback simple (escalada 2% > degradación 0.5% + O&M), que `cumulative_cashflow` tiene 30 filas y que el año 13 tiene un neto menor:

```bash
cd backend && .venv/bin/python - <<'EOF'
from fastapi.testclient import TestClient
import respx, json
from tests.test_api import mock_pvgis
from app.main import app

with respx.mock as m:
    mock_pvgis(m)
    with TestClient(app) as c:
        r = c.post("/api/solar-estimate", json={
            "lat": 42.88, "lon": -8.54, "peak_power_kwp": 5.0,
            "annual_consumption_kwh": 4000, "installation_cost_eur": 7000,
            "electricity_price_eur_kwh": 0.20, "subsidy_eur": 1000,
        })
        eco = r.json()["economics"]
        print(json.dumps({k: eco[k] for k in (
            "payback_years", "simple_payback_years", "savings_25yr_eur",
            "npv_eur", "irr_pct", "net_investment_eur")}, indent=2))
EOF
```

Expected: valores coherentes y sin excepciones.

- [ ] **Step 4: Recordatorio al usuario**

Decir a Diego que reinicie el servidor desde el panel de Taller para ver los cambios.
