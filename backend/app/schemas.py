"""Modelos Pydantic de entrada/salida de la API."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class BillHistoryEntry(BaseModel):
    """Un mes del histórico de consumo impreso en la factura."""

    month: int = Field(..., ge=1, le=12)
    kwh: float = Field(..., ge=0, le=20000)
    eur: float | None = Field(None, ge=0, le=100000, description="Importe del mes, si consta.")


class BillInput(BaseModel):
    """Una factura de la luz: consumo y, opcionalmente, importe y periodo."""

    # Tope alto para admitir facturas anuales de viviendas grandes; una lectura
    # acumulada del contador se filtra por precio implícito, no por este máximo.
    kwh: float = Field(..., gt=0, le=60000)
    energy_eur: float | None = Field(
        None,
        gt=0,
        le=10000,
        description="Cargo variable de energía de la factura, en la moneda local.",
    )
    fixed_eur: float | None = Field(
        None,
        ge=0,
        le=10000,
        description="Cargos fijos detectados, en la moneda local.",
    )
    taxes_eur: float | None = Field(
        None,
        ge=0,
        le=10000,
        description="Impuestos detectados, en la moneda local.",
    )
    total_eur: float | None = Field(
        None,
        gt=0,
        le=10000,
        description="Total final de la factura, en la moneda local.",
    )
    # Líneas detalladas para derivar el coste marginal evitado (IEE + IVA)
    power_eur: float | None = Field(
        None, ge=0, le=10000, description="Término de potencia del periodo."
    )
    iee_eur: float | None = Field(
        None, ge=0, le=10000, description="Impuesto especial sobre la electricidad."
    )
    iva_eur: float | None = Field(None, ge=0, le=10000, description="Importe de IVA.")
    iva_rate: float | None = Field(
        None, ge=0, le=0.3, description="Tipo de IVA impreso en la factura (0-0.3)."
    )
    vat_base_eur: float | None = Field(
        None, ge=0, le=100000, description="Base imponible del IVA."
    )
    contracted_power_kw: float | None = Field(
        None, ge=0, le=1000, description="Potencia contratada en kW."
    )
    consumption_history: list[BillHistoryEntry] | None = Field(
        None, max_length=24, description="Histórico mensual de consumo (mes → kWh)."
    )
    currency: str | None = Field(None, min_length=3, max_length=3)
    # Alias histórico. Se conserva para clientes antiguos, pero el precio
    # marginal solo usa energy_eur.
    amount_eur: float | None = Field(None, gt=0, le=10000)
    month: int | None = Field(None, ge=1, le=12, description="Mes representativo de la factura")
    start_date: date | None = None
    end_date: date | None = None
    days: float | None = Field(None, gt=0, le=370, description="Días del periodo si no hay fechas")

    @model_validator(mode="after")
    def _check_period(self) -> "BillInput":
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError(
                "El periodo de la factura es inválido: la fecha de inicio debe ser "
                "anterior a la de fin"
            )
        return self


class SolarEstimateRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitud")
    lon: float = Field(..., ge=-180, le=180, description="Longitud")
    peak_power_kwp: float = Field(..., gt=0, le=10000, description="Potencia pico instalada (kWp)")
    loss_pct: float = Field(14.0, ge=0, le=50, description="Pérdidas del sistema (%)")
    tilt_deg: float | None = Field(
        None, ge=0, le=90, description="Inclinación real del tejado (°); si se omite se usa la óptima"
    )
    azimuth_deg: float | None = Field(
        None,
        ge=-180,
        le=180,
        description="Azimut convención PVGIS: 0=Sur, 90=Oeste, -90=Este; si se omite se usa el óptimo",
    )
    annual_consumption_kwh: float | None = Field(None, gt=0, le=1_000_000)
    installation_cost_eur: float | None = Field(None, gt=0, le=100_000_000)
    electricity_price_eur_kwh: float | None = Field(None, gt=0, le=5)
    panel_power_w: int = Field(450, ge=50, le=1000)
    country_code: str | None = Field(
        None,
        min_length=2,
        max_length=2,
        description="Código ISO del país para precios; si falta se infiere por coordenadas",
    )
    refresh_prices: bool = Field(False, description="Forzar refresco de la caché de precios")
    # --- Análisis avanzado ---
    bills: list[BillInput] | None = Field(
        None, max_length=24, description="Facturas para derivar consumo y precio reales"
    )
    battery_options_kwh: list[Annotated[float, Field(ge=0, le=1000)]] = Field(
        default=[5.0, 10.0], max_length=6, description="Capacidades de batería a comparar"
    )
    surplus_price_eur_kwh: float | None = Field(
        None, ge=0, le=1, description="Override manual de compensación de excedentes"
    )
    cost_per_kwp_eur: float | None = Field(
        None, gt=0, le=10000, description="Override manual del coste de instalación por kWp"
    )
    battery_cost_per_kwh_eur: float | None = Field(
        None, gt=0, le=5000, description="Override manual del coste de batería por kWh"
    )
    subsidy_eur: float | None = Field(
        None,
        ge=0,
        le=100_000_000,
        description="Subvención o deducción estimada; se resta de la inversión neta",
    )
    occupancy_profile: Literal["standard", "home_day", "evening", "night"] = Field(
        "standard",
        description="Forma horaria del consumo residencial.",
    )
    has_heat_pump: bool = Field(False, description="Ajusta consumo a bomba de calor/aerotermia")
    has_ev: bool = Field(False, description="Añade carga nocturna típica de vehículo eléctrico")
    has_pool: bool = Field(False, description="Añade consumo diurno de piscina en meses cálidos")
    auto_size_power: bool = Field(
        False,
        description=(
            "Si hay consumo conocido, analiza la potencia recomendada (cobertura "
            "~100%) en vez de peak_power_kwp. peak_power_kwp sigue siendo la semilla."
        ),
    )


class MonthlyProduction(BaseModel):
    month: int
    production_kwh: float
    irradiation_kwh_m2: float
    hsp_daily: float


class SystemResult(BaseModel):
    slope_deg: float
    azimuth_deg: float
    monthly: list[MonthlyProduction]
    annual_production_kwh: float
    annual_irradiation_kwh_m2: float
    hsp_daily_avg: float


class MonthlyIrradiation(BaseModel):
    month: int
    irradiation_kwh_m2: float


class PanelsRecommendation(BaseModel):
    count: int
    total_kwp: float
    needed_kwp: float
    panel_power_w: int
    roof_area_m2: float | None = None
    coverage_pct: float | None = None
    production_to_consumption_pct: float | None = None
    explanation: str | None = None


class PriceRange(BaseModel):
    low: float
    medium: float
    high: float


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


class Economics(BaseModel):
    electricity_price_eur_kwh: float
    electricity_price_source: str = "default"  # 'manual' | 'bills' | 'default'
    electricity_price_bill_count: int = 0
    annual_savings_eur: float
    payback_years: float | None = None
    installation_cost_eur: float | None = None
    installation_cost_range_eur: PriceRange | None = None
    cost_is_estimated: bool = False
    roi_pct: float | None = None
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


class ConsumptionSummary(BaseModel):
    annual_kwh: float
    source: str  # 'bills' | 'input'
    avg_price_eur_kwh: float | None = None
    avg_price_kwh: float | None = None
    # Coste marginal evitado derivado de las facturas (término energía × IEE × IVA)
    marginal_price_eur_kwh: float | None = None
    marginal_price_factor: float | None = None
    tax_rates_source: str | None = None  # 'bill' | 'statutory' | 'mixed'
    bill_count: int = 0
    priced_bill_count: int = 0
    total_amount_bill_count: int = 0
    ignored_price_bill_count: int = 0
    days_covered: int | None = None
    monthly_kwh: list[float] | None = None
    monthly_eur: list[float] | None = None
    monthly_amount: list[float] | None = None
    annual_amount_eur: float | None = None
    annual_amount: float | None = None
    currency: str | None = None
    observed_months: list[int] = Field(default_factory=list)
    estimated_months: list[int] = Field(default_factory=list)
    seasonality_source: str | None = None
    profile: dict | None = None


class BatteryScenario(BaseModel):
    battery_kwh: float
    annual_savings_eur: float
    investment_eur: float
    investment_range_eur: PriceRange | None = None
    payback_years: float | None = None
    self_consumption_pct: float
    self_sufficiency_pct: float
    production_kwh: float
    consumption_kwh: float
    self_consumed_kwh: float
    direct_kwh: float
    battery_discharged_kwh: float
    exported_kwh: float
    imported_kwh: float
    battery_marginal_payback_years: float | None = None
    npv_eur: float | None = None


class AnnualEnergySummary(BaseModel):
    production_kwh: float
    consumption_kwh: float | None = None
    self_consumed_kwh: float | None = None
    exported_kwh: float | None = None
    imported_kwh: float | None = None
    coverage_pct: float | None = None
    production_to_consumption_pct: float | None = None
    self_consumption_pct: float | None = None
    self_sufficiency_pct: float | None = None


class BatteryAnalysis(BaseModel):
    scenarios: list[BatteryScenario]
    recommended_battery_kwh: float
    recommendation: str
    battery_lifetime_years: int = 10
    export_scheme: str = "capped_compensation"
    surplus_price_eur_kwh: float
    battery_cost_per_kwh_eur: float
    battery_cost_range_eur_per_kwh: PriceRange | None = None


class BatteryOptionCost(BaseModel):
    battery_kwh: float
    investment_range: PriceRange


class PricingSummary(BaseModel):
    country_code: str
    country_name: str
    currency: str
    currency_symbol: str
    vat_rate: float
    vat_note: str | None = None
    source_type: str
    fallback_used: bool
    provider_names: list[str]
    updated_at: date
    cache_ttl_days: int
    turnkey_cost_per_kwp: PriceRange
    system_cost_range: PriceRange
    battery_cost_per_kwh: PriceRange
    panel_price_per_w: PriceRange
    panel_price_per_panel: PriceRange
    inverter_price_per_kwp: PriceRange
    mounting_price_per_kwp: PriceRange
    labour_price_per_kwp: PriceRange
    installation_labour_factor: float
    surplus_price_eur_kwh: float
    electricity_price_kwh: float | None = None
    export_scheme: str = "capped_compensation"
    electricity_tax_factor: float = 1.0
    system_cost_source: str
    battery_cost_source: str
    battery_option_costs: list[BatteryOptionCost] = Field(default_factory=list)


class TypicalDay(BaseModel):
    """Día medio (24 valores en kWh por hora) para la gráfica de autoconsumo."""

    production: list[list[float]]  # 12x24
    consumption: list[list[float]]  # 12x24


class CalculationConfidence(BaseModel):
    level: str
    bill_count: int = 0
    priced_bill_count: int = 0
    pvgis_ok: bool = True
    prices_current: bool = False
    estimated_inputs: list[str] = Field(default_factory=list)
    # Qué puede hacer el usuario para subir el nivel (claves traducibles)
    improvement_hints: list[str] = Field(default_factory=list)


class SolarEstimateResponse(BaseModel):
    lat: float
    lon: float
    requested_peak_power_kwp: float
    analysis_power_kwp: float
    loss_pct: float
    elevation_m: float | None = None
    optimal: SystemResult
    user_system: SystemResult | None = None
    loss_vs_optimal_pct: float | None = None
    # Irradiación mensual sobre el plano del generador (H(i)_m de PVcalc)
    plane_irradiation_monthly: list[MonthlyIrradiation]
    economics: Economics
    pricing: PricingSummary
    panels: PanelsRecommendation | None = None
    consumption: ConsumptionSummary | None = None
    annual_energy: AnnualEnergySummary
    battery_analysis: BatteryAnalysis | None = None
    typical_day: TypicalDay | None = None
    confidence: CalculationConfidence


class ParsedBill(BaseModel):
    kwh: float | None = None
    amount_eur: float | None = None
    energy_eur: float | None = None
    fixed_eur: float | None = None
    taxes_eur: float | None = None
    total_eur: float | None = None
    power_eur: float | None = None
    iee_eur: float | None = None
    iva_eur: float | None = None
    iva_rate: float | None = None
    vat_base_eur: float | None = None
    contracted_power_kw: float | None = None
    consumption_history: list[BillHistoryEntry] = []
    currency: str | None = None
    month: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    country_code: str | None = None
    country_name: str | None = None
    supply_address: str | None = None
    postal_code: str | None = None
    city: str | None = None
    region: str | None = None
    location_label: str | None = None
    lat: float | None = None
    lon: float | None = None
    language: str | None = None
    parser: str = "local"
    warnings: list[str] = []


class OptimalAnglesResponse(BaseModel):
    lat: float
    lon: float
    slope_deg: float
    azimuth_deg: float
    annual_production_per_kwp: float
    hsp_daily_avg: float


class GeocodeResult(BaseModel):
    display_name: str
    lat: float
    lon: float
    country_code: str | None = None
