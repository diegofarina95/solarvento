# Economía plurianual: ahorro y amortización precisos

**Fecha:** 2026-07-03
**Estado:** diseño adoptado con el usuario ausente; opciones recomendadas elegidas.
Pendiente de revisión por Diego.

## Problema

El payback mostrado hoy es `coste / ahorro del año 1` (`calculations.payback_years`).
Para una inversión de 15–25 años eso ignora efectos que mueven el resultado en
años enteros:

1. Degradación de los paneles (~0,5 %/año).
2. Evolución del precio de la electricidad (histórico europeo: +2–5 %/año).
3. Reemplazo del inversor (~año 13, coste por kWp ya presente en la tabla de precios).
4. Mantenimiento/seguro (~1 % del capex/año).
5. Impuestos sobre el kWh evitado: el precio derivado de facturas usa el término
   de energía **sin impuestos**; cada kWh autoconsumido evita también impuesto
   eléctrico + IVA (España ≈ ×1,27). Hoy se infraestima el ahorro en ese caso.
6. Subvenciones/deducciones: sin forma de reflejarlas.
7. Sin métricas de decisión estándar: ahorro a 25 años, VAN, TIR.

La simulación energética (PVGIS horario × perfil de consumo × batería ×
esquema de excedentes por país) ya es sólida y **no se toca**; se corrige la
capa económica que la consume.

## Decisión

**Motor de flujo de caja plurianual** que reutiliza la simulación horaria año a
año, más corrección fiscal del precio evitado y campo manual de subvención.

Alternativas descartadas:
- Aproximación analítica con series geométricas: menos código, pero ignora que
  la degradación cambia el % de autoconsumo, y el ahorro de complejidad es menor.
- Solo afinar entradas manteniendo payback simple: no ataca la imprecisión principal.
- Tabla automática de subvenciones por país: varían por región y año; dar cifras
  legales erróneas a usuarios reales es peor que pedir el dato.

## Diseño

### 1. Módulo nuevo `backend/app/cashflow.py`

`multi_year_cashflow(...)` simula el horizonte año a año (30 años simulados,
cifras titulares a 25):

- **Año y:** producción del año 1 × (1 − degradación)^(y−1); capacidad útil de
  batería × (1 − degradación_batería)^(y−1); se re-ejecuta
  `simulation.simulate_self_consumption` y se valora con
  `annual_savings_with_surplus` usando precios del año y.
- **Precios:** precio de compra × (1 + escalada)^(y−1). Precio de excedente:
  constante si `export_scheme == "feed_in"` (tarifas reguladas fijas ~20 años);
  escala con el de compra en el resto (compensación/net-metering/mercado siguen
  al precio minorista).
- **Costes recurrentes:** mantenimiento = `om_pct` × coste bruto del sistema/año.
  Reemplazo del inversor en `inverter_replacement_year` por
  `inverter_price_per_kwp.medium × kWp` (país). No se modela reemplazo de
  batería: su capacidad sigue degradándose (documentado en supuestos).
- **Salidas:** payback real interpolado (primer año con acumulado ≥ 0; `None`
  si no llega en el horizonte), ahorro total a 25 años, VAN a la tasa de
  descuento, TIR (bisección), curva anual `[{year, net_eur, cumulative_eur}]`,
  y `assumptions` con todos los parámetros usados.
- **Modo sin simulación horaria** (sin dato de consumo): misma mecánica sobre el
  ahorro anual simple (degradación + escalada, sin re-simulación).

Constantes por defecto (en `cashflow.py`, configurables vía `config.py` si ya
existe patrón; siempre expuestas en `assumptions`):

| Parámetro | Valor | Justificación |
|---|---|---|
| `horizon_years` | 30 (titulares a 25) | garantía típica de producción 25 años |
| `panel_degradation_pct` | 0,5 %/año | garantías Tier-1 (~84–88 % a 25 años) |
| `price_escalation_pct` | 2 %/año | conservador frente al histórico europeo |
| `om_pct_per_year` | 1 % del capex | referencia habitual residencial |
| `inverter_replacement_year` | 13 | vida típica 10–15 años |
| `battery_degradation_pct` | 2 %/año | LFP ~80 % a 10 años |
| `discount_rate_pct` | 3 % | VAN nominal |

### 2. Corrección fiscal del precio evitado

- Campos nuevos por país en `pricing/default_prices.py`:
  `electricity_vat_rate` y `electricity_excise_rate` (impuesto eléctrico o
  equivalente). Factor marginal = `(1 + excise) × (1 + vat)`.
- Se aplica **solo** cuando `price_source == "bills"` (término de energía sin
  impuestos). Precio por defecto: ya incluye impuestos → factor 1. Manual: se
  asume final → factor 1.
- El factor se aplica al precio de compra evitado y a la compensación de
  excedentes en esquemas que reducen la factura (`capped_compensation`,
  `net_metering`, donde la compensación reduce la base imponible). En `feed_in`
  y `market_price` el vertido es ingreso, no reduce impuestos → factor 1 para
  el excedente.
- El factor y el precio efectivo resultante se devuelven en la respuesta para
  que el frontend pueda explicarlo.

### 3. Subvención manual

- `SolarEstimateRequest.subsidy_eur: float | None` (0 ≤ x ≤ coste). Reduce la
  inversión neta en el año 0 para payback/VAN/TIR. Se muestra por separado
  (`net_investment_eur`). Aviso informativo en frontend de que existen ayudas
  por país (texto genérico, sin cifras).

### 4. Cambios de API (`schemas.py`)

`Economics` gana:
- `payback_years` — pasa a ser el payback real plurianual (mismo nombre; la
  semántica mejora).
- `simple_payback_years` — el métrico antiguo, por transparencia.
- `savings_25yr_eur`, `npv_eur`, `irr_pct`
- `subsidy_eur`, `net_investment_eur`
- `effective_price_eur_kwh`, `marginal_price_factor`
- `cumulative_cashflow: list[YearCashflow]` (año, neto, acumulado)
- `assumptions: CashflowAssumptions`

`BatteryScenario`:
- `payback_years` y `battery_marginal_payback_years` recalculados con el motor
  plurianual (marginal: año en que el ahorro marginal acumulado cubre el coste
  extra de la batería). `npv_eur` por escenario.
- La lógica de recomendación (`_battery_recommendation`) no cambia; consume los
  nuevos valores.

`_validate_estimate_consistency` se amplía: payback plurianual ≤ simple cuando
hay escalada > degradación; acumulado a 25 años coherente con el ahorro medio.

### 5. Frontend

- `SolarForm.jsx` (sección avanzada): campo subvención (€) + nota de ayudas.
- `Results.jsx`: tarjeta payback con nueva semántica; tarjeta "ahorro a 25
  años"; bloque plegable "Supuestos del cálculo" listando `assumptions` y el
  factor fiscal si aplica; VAN/TIR en ese bloque.
- `Charts.jsx`: gráfica de flujo acumulado (curva + línea de inversión,
  marcando el punto de equilibrio) alimentada por `cumulative_cashflow`.
- `PrintReport.jsx`: payback real, ahorro 25 años y supuestos.
- `i18n/translations.js`: claves nuevas en es/en/fr/it.
- `batteryRecommendation.js`: sin cambios de lógica (los valores ya vienen
  recalculados).

### 6. Tests

- `backend/tests/test_cashflow.py`: payback se acorta con escalada y se alarga
  con degradación/mantenimiento; salto del inversor en el año configurado;
  subvención reduce payback; VAN=0 ⇒ TIR=tasa; feed-in mantiene excedente
  constante; factor fiscal solo con `price_source="bills"`; modo sin consumo.
- `test_api.py`: campos nuevos presentes y coherentes; `simple_payback_years`
  ≥/≤ `payback_years` según el caso.
- E2E existente debe seguir pasando; se amplía si toca selectores nuevos.

### 7. Rendimiento y compatibilidad

- 30 años × ≤7 escenarios × simulación 12×24×3 ≈ 180k iteraciones ⇒ decenas de
  ms; sin cambios de infra.
- Nombres de campos existentes se conservan; solo se añaden campos. El cambio
  semántico de `payback_years` es intencional (es el número que debe ser preciso).

## Fuera de alcance

- Tabla automática de subvenciones por país.
- Tarifas horarias de compra (time-of-use) — posible mejora futura.
- Reemplazo de batería con precios futuros especulativos.
- Financiación/préstamos.
