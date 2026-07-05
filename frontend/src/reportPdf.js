// Informes PDF de descarga directa (jsPDF). DOS informes deliberadamente
// distintos: usuario (visual, sin jerga) y técnico (todos los números y tablas).
// Este módulo y jsPDF se cargan de forma diferida (import() al pulsar descargar),
// así no engordan el bundle inicial.
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'

const AMBER = [217, 119, 6]
const INK = [28, 25, 23]
const MUTED = [120, 113, 108]
const GOOD = [4, 120, 87]
const OK = [180, 83, 9]
const POOR = [185, 28, 28]
const MARGIN = 40

const LOW_SUITABILITY_KWH = 3000
const LOW_SUITABILITY_PAYBACK_YEARS = 8

function verdict(payback, annualKwh, bonoSocial) {
  const lowConsumption = annualKwh != null && annualKwh < LOW_SUITABILITY_KWH
  const slowPayback = payback == null || payback <= 0 || payback > LOW_SUITABILITY_PAYBACK_YEARS
  if (lowConsumption || slowPayback || bonoSocial) return 'poor'
  if (payback <= 10) return 'good'
  if (payback <= 15) return 'ok'
  return 'poor'
}
const VERDICT_COLOR = { good: GOOD, ok: OK, poor: POOR }

function brandHeader(doc, subtitle, i18n, fmt) {
  const { t } = i18n
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(22)
  doc.setTextColor(...INK)
  doc.text('SolarVento', MARGIN, 52)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  doc.setTextColor(...MUTED)
  doc.text(subtitle, MARGIN, 70)
  const dateStr = t('report.generatedOn', { date: fmt.date.format(new Date()) })
  doc.text(dateStr, doc.internal.pageSize.getWidth() - MARGIN, 52, { align: 'right' })
  doc.setDrawColor(230, 226, 214)
  doc.line(MARGIN, 82, doc.internal.pageSize.getWidth() - MARGIN, 82)
  return 104
}

function footer(doc, i18n) {
  const { t } = i18n
  const w = doc.internal.pageSize.getWidth()
  const h = doc.internal.pageSize.getHeight()
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(...MUTED)
  const lines = doc.splitTextToSize(t('report.dataSource'), w - MARGIN * 2)
  doc.text(lines, MARGIN, h - 40)
}

function sectionTitle(doc, text, y) {
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(...INK)
  doc.text(text, MARGIN, y)
  return y + 8
}

// ---------- Informe de usuario (visual, claro) ----------
export function buildUserReport(data, i18n, fmt) {
  const { t } = i18n
  const eco = data.economics ?? {}
  const ae = data.annual_energy ?? {}
  const panels = data.panels
  const battery = data.battery_analysis
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  const w = doc.internal.pageSize.getWidth()
  let y = brandHeader(doc, t('report.informativeTitle'), i18n, fmt)

  // Veredicto
  const v = verdict(eco.payback_years, data.consumption?.annual_kwh, data.consumption?.bono_social)
  doc.setFillColor(...VERDICT_COLOR[v])
  doc.circle(MARGIN + 5, y - 4, 4, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.setTextColor(...INK)
  doc.text(t(`basic.verdict.${v}`), MARGIN + 16, y)
  y += 30

  // Tres cifras grandes
  const annual = eco.annual_savings_eur ?? 0
  const cards = [
    [t('basic.savingMonth'), fmt.money0.format(annual / 12)],
    [t('basic.savingYear'), fmt.money0.format(annual)],
    [
      t('basic.paybackLabel'),
      eco.payback_years > 0 ? t('basic.years', { value: fmt.nf1.format(eco.payback_years) }) : '—',
    ],
  ]
  const cardW = (w - MARGIN * 2 - 20) / 3
  cards.forEach(([label, value], i) => {
    const x = MARGIN + i * (cardW + 10)
    doc.setDrawColor(230, 226, 214)
    doc.setFillColor(252, 251, 248)
    doc.roundedRect(x, y, cardW, 56, 6, 6, 'FD')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(17)
    doc.setTextColor(...INK)
    doc.text(String(value), x + cardW / 2, y + 26, { align: 'center' })
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.setTextColor(...MUTED)
    doc.text(String(label), x + cardW / 2, y + 44, { align: 'center' })
  })
  y += 82

  // Frase resumen
  if (ae.self_sufficiency_pct != null) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(11)
    doc.setTextColor(...INK)
    const summary = t('basic.summary', {
      selfSuff: fmt.nf.format(ae.self_sufficiency_pct),
      savings: fmt.money0.format(annual),
    })
    doc.text(doc.splitTextToSize(summary, w - MARGIN * 2), MARGIN, y)
    y += 34
  }

  // Recomendación
  y = sectionTitle(doc, t('basic.recommendationTitle'), y + 4)
  y += 8
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(11)
  doc.setTextColor(...INK)
  const recLines = []
  if (panels) {
    recLines.push(
      t('basic.recommendationBody', {
        count: fmt.nf.format(panels.count),
        kwp: fmt.nf2.format(panels.total_kwp),
        area: fmt.nf.format(panels.roof_area_m2),
      }),
    )
    const system = data.user_system ?? data.optimal
    if (system?.annual_production_kwh != null) {
      recLines.push(
        `${t('basic.estimatedProduction')}: ${t('basic.production', {
          value: fmt.nf.format(system.annual_production_kwh),
        })}`,
      )
    }
  }
  if (battery?.recommended_battery_kwh > 0) {
    recLines.push(t('basic.battery.recommend', { kwh: fmt.nf1.format(battery.recommended_battery_kwh) }))
  }
  recLines.forEach((line) => {
    doc.text(`•  ${line}`, MARGIN, y)
    y += 18
  })

  footer(doc, i18n)
  return doc
}

// ---------- Informe técnico (todos los números) ----------
export function buildTechnicalReport(data, i18n, fmt) {
  const { t } = i18n
  const eco = data.economics ?? {}
  const ae = data.annual_energy ?? {}
  const pricing = data.pricing ?? {}
  const cons = data.consumption ?? {}
  const doc = new jsPDF({ unit: 'pt', format: 'a4' })
  let y = brandHeader(doc, t('report.installerTitle'), i18n, fmt)

  const kv = (rows, startY) => {
    autoTable(doc, {
      startY,
      margin: { left: MARGIN, right: MARGIN },
      theme: 'plain',
      styles: { fontSize: 9, cellPadding: 2, textColor: INK },
      columnStyles: { 0: { textColor: MUTED, cellWidth: 200 }, 1: { fontStyle: 'bold' } },
      body: rows,
    })
    return doc.lastAutoTable.finalY + 16
  }

  // Sistema
  y = sectionTitle(doc, t('report.systemSection'), y)
  const system = data.user_system ?? data.optimal
  y = kv(
    [
      [t('results.analysedPower'), `${fmt.nf2.format(data.analysis_power_kwp)} kWp`],
      [t('results.annualProduction'), `${fmt.nf.format(system?.annual_production_kwh)} kWh`],
      [t('results.recommendedPanels'), data.panels ? `${fmt.nf.format(data.panels.count)} × ${data.panels.panel_power_w} W` : '—'],
      [t('results.peakSunHours'), `${fmt.nf1.format(system?.hsp_daily_avg)} h`],
      [t('results.optimalAngles'), `${fmt.nf.format(data.optimal?.slope_deg)}° / ${fmt.nf.format(data.optimal?.azimuth_deg)}°`],
      [t('results.selfSufficiency'), ae.self_sufficiency_pct != null ? `${fmt.nf1.format(ae.self_sufficiency_pct)} %` : '—'],
      [t('results.selfConsumption'), ae.self_consumption_pct != null ? `${fmt.nf1.format(ae.self_consumption_pct)} %` : '—'],
    ],
    y + 4,
  )

  // Económico
  y = sectionTitle(doc, t('report.secEconomics'), y)
  y = kv(
    [
      [t('results.estimatedSavings'), `${fmt.money2.format(eco.annual_savings_eur)}/a`],
      [t('results.payback'), eco.payback_years != null ? t('basic.years', { value: fmt.nf1.format(eco.payback_years) }) : '—'],
      [t('results.roi'), eco.roi_pct != null ? `${fmt.nf1.format(eco.roi_pct)} %` : '—'],
      [t('results.savings25', { years: eco.assumptions?.headline_years ?? 25 }), eco.savings_25yr_eur != null ? fmt.money0.format(eco.savings_25yr_eur) : '—'],
      [t('report.investment'), eco.installation_cost_eur != null ? fmt.money0.format(eco.installation_cost_eur) : '—'],
      [t('report.effectivePrice'), eco.effective_price_eur_kwh != null ? `${fmt.money2.format(eco.effective_price_eur_kwh)}/kWh` : `${fmt.money2.format(eco.electricity_price_eur_kwh)}/kWh`],
    ],
    y + 4,
  )

  // Escenarios de potencia
  if (data.sizing_analysis?.scenarios?.length) {
    y = sectionTitle(doc, t('report.secScenarios'), y)
    autoTable(doc, {
      startY: y + 4,
      margin: { left: MARGIN, right: MARGIN },
      headStyles: { fillColor: INK, fontSize: 8 },
      styles: { fontSize: 8, cellPadding: 3 },
      head: [[
        t('sizing.power'), t('sizing.investment'), t('sizing.savingsYear'),
        t('sizing.payback'), t('sizing.roi'), t('sizing.selfConsumption'),
      ]],
      body: data.sizing_analysis.scenarios.map((s) => [
        `${fmt.nf2.format(s.power_kwp)} kWp`,
        fmt.money0.format(s.investment_eur),
        fmt.money0.format(s.annual_savings_eur),
        s.payback_years != null ? fmt.nf1.format(s.payback_years) : '—',
        s.roi_pct != null ? `${fmt.nf1.format(s.roi_pct)} %` : '—',
        `${fmt.nf1.format(s.self_consumption_pct)} %`,
      ]),
    })
    y = doc.lastAutoTable.finalY + 16
  }

  // Batería
  if (data.battery_analysis?.scenarios?.length) {
    y = sectionTitle(doc, t('report.secBattery'), y)
    autoTable(doc, {
      startY: y + 4,
      margin: { left: MARGIN, right: MARGIN },
      headStyles: { fillColor: INK, fontSize: 8 },
      styles: { fontSize: 8, cellPadding: 3 },
      head: [[
        'kWh', t('sizing.savingsYear'),
        t('report.incrementalPayback'), t('results.selfSufficiency'),
      ]],
      body: data.battery_analysis.scenarios.map((s) => [
        `${fmt.nf1.format(s.battery_kwh)} kWh`,
        fmt.money0.format(s.annual_savings_eur),
        s.battery_incremental_payback_years != null ? t('basic.years', { value: fmt.nf1.format(s.battery_incremental_payback_years) }) : '—',
        s.self_sufficiency_pct != null ? `${fmt.nf1.format(s.self_sufficiency_pct)} %` : '—',
      ]),
    })
    y = doc.lastAutoTable.finalY + 16
  }

  // Base de cálculo
  y = sectionTitle(doc, t('report.secBasis'), y)
  kv(
    [
      [t('report.consumption'), cons.annual_kwh != null ? `${fmt.nf.format(cons.annual_kwh)} kWh` : '—'],
      [t('report.consumptionSource'), cons.source === 'bills' ? t('results.fromBills') : t('results.manualConsumption')],
      [t('report.electricityPrice'), pricing.currency ? `${fmt.money2.format(eco.electricity_price_eur_kwh)}/kWh` : '—'],
      [t('report.location'), `${fmt.nf2.format(data.lat)}, ${fmt.nf2.format(data.lon)}`],
    ],
    y + 4,
  )

  footer(doc, i18n)
  return doc
}

export async function downloadReport(kind, data, i18n, fmt) {
  const { t } = i18n
  const doc = kind === 'technical' ? buildTechnicalReport(data, i18n, fmt) : buildUserReport(data, i18n, fmt)
  const name = kind === 'technical' ? t('report.filenameTech') : t('report.filenameUser')
  doc.save(`${name}.pdf`)
}
