import { expect, test } from '@playwright/test'

const monthly = Array.from({ length: 12 }, (_, index) => ({
  month: index + 1,
  production_kwh: 500,
  irradiation_kwh_m2: 120,
  hsp_daily: 4,
}))

function estimateResponse() {
  return {
    lat: 40.42,
    lon: -3.7,
    requested_peak_power_kwp: 5,
    analysis_power_kwp: 5,
    loss_pct: 14,
    elevation_m: 650,
    optimal: {
      slope_deg: 35,
      azimuth_deg: 0,
      monthly,
      annual_production_kwh: 6000,
      annual_irradiation_kwh_m2: 1700,
      hsp_daily_avg: 4.7,
    },
    user_system: null,
    loss_vs_optimal_pct: null,
    plane_irradiation_monthly: monthly.map(({ month, irradiation_kwh_m2 }) => ({
      month,
      irradiation_kwh_m2,
    })),
    economics: {
      electricity_price_eur_kwh: 0.18,
      electricity_price_source: 'bills',
      electricity_price_bill_count: 1,
      annual_savings_eur: 620,
      payback_years: 8.9,
      installation_cost_eur: 5500,
      installation_cost_range_eur: { low: 5000, medium: 5500, high: 6200 },
      cost_is_estimated: true,
      roi_pct: 11.3,
    },
    pricing: {
      country_code: 'ES',
      country_name: 'Spain',
      currency: 'EUR',
      currency_symbol: '€',
      vat_rate: 0.21,
      vat_note: null,
      source_type: 'market_average',
      fallback_used: true,
      provider_names: ['SolVento defaults'],
      updated_at: '2026-01-01',
      cache_ttl_days: 7,
      turnkey_cost_per_kwp: { low: 1000, medium: 1100, high: 1240 },
      system_cost_range: { low: 5000, medium: 5500, high: 6200 },
      battery_cost_per_kwh: { low: 500, medium: 650, high: 850 },
      panel_price_per_w: { low: 0.12, medium: 0.18, high: 0.28 },
      panel_price_per_panel: { low: 54, medium: 81, high: 126 },
      inverter_price_per_kwp: { low: 120, medium: 180, high: 260 },
      mounting_price_per_kwp: { low: 120, medium: 180, high: 250 },
      labour_price_per_kwp: { low: 220, medium: 300, high: 420 },
      installation_labour_factor: 1,
      surplus_price_eur_kwh: 0.06,
      electricity_price_kwh: 0.18,
      export_scheme: 'capped_compensation',
      system_cost_source: 'market_average',
      battery_cost_source: 'market_average',
      battery_option_costs: [],
    },
    panels: {
      count: 8,
      total_kwp: 3.6,
      needed_kwp: 3.4,
      panel_power_w: 450,
      roof_area_m2: 20.2,
      coverage_pct: 101,
      production_to_consumption_pct: 101,
      explanation: null,
    },
    consumption: {
      annual_kwh: 3600,
      source: 'bills',
      avg_price_eur_kwh: 0.18,
      avg_price_kwh: 0.18,
      bill_count: 1,
      priced_bill_count: 1,
      total_amount_bill_count: 1,
      ignored_price_bill_count: 0,
      days_covered: 31,
      monthly_kwh: Array(12).fill(300),
      monthly_eur: Array(12).fill(85),
      monthly_amount: Array(12).fill(85),
      annual_amount_eur: 1020,
      annual_amount: 1020,
      currency: 'EUR',
      observed_months: [1],
      seasonality_source: 'estimated_from_sampled_months',
      profile: {
        country_code: 'ES',
        occupancy_profile: 'standard',
        has_heat_pump: false,
        has_ev: false,
        has_pool: false,
      },
    },
    annual_energy: {
      production_kwh: 6000,
      consumption_kwh: 3600,
      self_consumed_kwh: 2200,
      exported_kwh: 3800,
      imported_kwh: 1400,
      coverage_pct: 166.7,
      production_to_consumption_pct: 166.7,
      self_consumption_pct: 36.7,
      self_sufficiency_pct: 61.1,
    },
    battery_analysis: null,
    typical_day: null,
    confidence: {
      level: 'medium',
      bill_count: 1,
      priced_bill_count: 1,
      pvgis_ok: true,
      prices_current: false,
      estimated_inputs: ['market_prices'],
      improvement_hints: ['add_seasonal_bills'],
    },
  }
}

test('main estimate flow renders analysed and recommended power separately', async ({ page }) => {
  await page.route('**/api/solar-estimate', async (route) => {
    await route.fulfill({ json: estimateResponse() })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /Advanced|Avanzado/ }).click()
  await page.getByLabel(/Peak power|Potencia pico/).fill('5')
  await page.getByRole('button', { name: /Calculate solar production|Calcular producción solar/ }).click()

  const app = page.locator('#app-shell')
  await expect(app.getByText(/Analysed power|Potencia analizada/)).toBeVisible()
  await expect(app.getByText(/Recommended panels|Paneles recomendados/)).toBeVisible()
  await expect(app.getByText('5 kWp').first()).toBeVisible()
})

test('bill upload fills energy and total amounts from parser response', async ({ page }) => {
  await page.route('**/api/parse-bill', async (route) => {
    await route.fulfill({
      json: {
        kwh: 312,
        energy_eur: 43.06,
        total_eur: 71.39,
        amount_eur: 71.39,
        currency: 'EUR',
        month: 3,
        start_date: '2026-03-01',
        end_date: '2026-03-31',
        parser: 'local',
        warnings: [],
      },
    })
  })

  await page.goto('/')
  await page.locator('input[type="file"]').setInputFiles({
    name: 'bill.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%%EOF'),
  })

  await expect(page.getByLabel(/Bill 1 variable energy charge|Cargo variable de energía factura 1/)).toHaveValue('43.06')
  await expect(page.getByLabel(/Bill 1 total|Total factura 1/)).toHaveValue('71.39')
})

test('rate-limit errors are shown to the user', async ({ page }) => {
  await page.route('**/api/solar-estimate', async (route) => {
    await route.fulfill({
      status: 429,
      json: { detail: 'Has hecho demasiados cálculos seguidos; espera un rato.' },
    })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /Calculate solar production|Calcular producción solar/ }).click()

  await expect(page.getByRole('alert')).toContainText('demasiados cálculos')
})
