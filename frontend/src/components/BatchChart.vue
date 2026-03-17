<script setup>
import { ref, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import Chart from 'chart.js/auto'
import { fetchBatchData } from '../services/api'

const props = defineProps({
    filename: { type: String, default: null },
    csvData: { type: Object, default: null },
})

const canvasRef = ref(null)
const chartInstance = shallowRef(null)
const loading = ref(false)
const error = ref('')
const data = ref(null)

// Channel definitions for batch data
const channels = [
    { id: 'temperature', key: 'temperature_K', label: 'Temperature', color: '#ef4444', yAxis: 'yTemp', unit: '\u00b0C', transform: v => v - 273.15, default: true },
    { id: 'jacket', key: 'jacket_temperature_K', label: 'Jacket Temp', color: '#f97316', yAxis: 'yTemp', unit: '\u00b0C', transform: v => v - 273.15, default: true },
    { id: 'conversion', key: null, label: 'Conversion', color: '#22c55e', yAxis: 'yConv', unit: '%', transform: v => v * 100, default: true },
    { id: 'viscosity', key: 'viscosity_Pas', label: 'Viscosity', color: '#06b6d4', yAxis: 'yVisc', unit: 'Pa\u00b7s', transform: v => Number.isFinite(v) ? v : 0, default: false },
    { id: 'mass_total', key: 'mass_total_kg', label: 'Total Mass', color: '#a855f7', yAxis: 'yMass', unit: 'kg', transform: v => v, default: false },
]

const activeChannels = ref(channels.filter(c => c.default).map(c => c.id))

// Phase colors
const PHASE_COLORS = {
    IDLE: 'rgba(100, 116, 139, 0.08)',
    CHARGING: 'rgba(59, 130, 246, 0.10)',
    HEATING: 'rgba(245, 158, 11, 0.10)',
    EXOTHERM: 'rgba(239, 68, 68, 0.12)',
    COOLING: 'rgba(6, 182, 212, 0.10)',
    DISCHARGING: 'rgba(34, 197, 94, 0.10)',
    RUNAWAY_ALARM: 'rgba(239, 68, 68, 0.20)',
}

const PHASE_BORDER_COLORS = {
    IDLE: 'rgba(100, 116, 139, 0.25)',
    CHARGING: 'rgba(59, 130, 246, 0.30)',
    HEATING: 'rgba(245, 158, 11, 0.30)',
    EXOTHERM: 'rgba(239, 68, 68, 0.35)',
    COOLING: 'rgba(6, 182, 212, 0.30)',
    DISCHARGING: 'rgba(34, 197, 94, 0.30)',
    RUNAWAY_ALARM: 'rgba(239, 68, 68, 0.50)',
}

// Phase bands plugin
const phaseBandsPlugin = {
    id: 'phaseBands',
    beforeDraw(chart) {
        const { ctx, chartArea, scales } = chart
        if (!chartArea || !scales.x) return
        const bands = chart.options.plugins.phaseBands?.bands
        if (!bands || bands.length === 0) return

        ctx.save()
        for (const band of bands) {
            const x1 = Math.max(scales.x.getPixelForValue(band.start), chartArea.left)
            const x2 = Math.min(scales.x.getPixelForValue(band.end), chartArea.right)
            if (x2 <= x1) continue

            // Fill
            ctx.fillStyle = band.color
            ctx.fillRect(x1, chartArea.top, x2 - x1, chartArea.bottom - chartArea.top)

            // Label at top
            if (x2 - x1 > 40) {
                ctx.fillStyle = band.borderColor || 'rgba(148, 163, 184, 0.5)'
                ctx.font = '9px Inter, sans-serif'
                ctx.textAlign = 'center'
                ctx.fillText(band.label, (x1 + x2) / 2, chartArea.top + 12)
            }
        }
        ctx.restore()
    }
}

function buildPhaseBands(elapsed, phases) {
    if (!elapsed || !phases || elapsed.length === 0) return []
    const bands = []
    let currentPhase = phases[0]
    let startTime = elapsed[0]

    for (let i = 1; i < phases.length; i++) {
        if (phases[i] !== currentPhase) {
            bands.push({
                start: startTime / 60,
                end: elapsed[i] / 60,
                label: currentPhase,
                color: PHASE_COLORS[currentPhase] || PHASE_COLORS.IDLE,
                borderColor: PHASE_BORDER_COLORS[currentPhase] || PHASE_BORDER_COLORS.IDLE,
            })
            currentPhase = phases[i]
            startTime = elapsed[i]
        }
    }
    // Final band
    bands.push({
        start: startTime / 60,
        end: elapsed[elapsed.length - 1] / 60,
        label: currentPhase,
        color: PHASE_COLORS[currentPhase] || PHASE_COLORS.IDLE,
        borderColor: PHASE_BORDER_COLORS[currentPhase] || PHASE_BORDER_COLORS.IDLE,
    })
    return bands
}

function findConversionKey(columns) {
    return columns.find(c => c.startsWith('conversion_')) || null
}

function buildChart() {
    if (!canvasRef.value || !data.value) return
    if (chartInstance.value) {
        chartInstance.value.destroy()
        chartInstance.value = null
    }

    const d = data.value
    const elapsed = d.data.elapsed.map(v => v / 60) // seconds to minutes
    const convKey = findConversionKey(d.columns)
    const bands = buildPhaseBands(d.data.elapsed, d.data.phase)

    const datasets = []
    const usedAxes = new Set()

    for (const ch of channels) {
        if (!activeChannels.value.includes(ch.id)) continue

        let values
        if (ch.id === 'conversion' && convKey) {
            values = d.data[convKey]
        } else if (ch.key && d.data[ch.key]) {
            values = d.data[ch.key]
        } else {
            continue
        }

        usedAxes.add(ch.yAxis)
        datasets.push({
            label: ch.label,
            data: elapsed.map((x, i) => ({ x, y: ch.transform(values[i]) })),
            borderColor: ch.color,
            backgroundColor: ch.color + '20',
            borderWidth: ch.id === 'temperature' ? 2 : 1.5,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.2,
            fill: false,
            yAxisID: ch.yAxis,
        })
    }

    const scales = {
        x: {
            type: 'linear',
            title: { display: true, text: 'Time (min)', color: '#64748b', font: { size: 10, family: 'Inter, sans-serif' } },
            ticks: { color: '#94a3b8', font: { family: '"JetBrains Mono", monospace', size: 10 } },
            grid: { color: '#334155' },
        },
    }

    if (usedAxes.has('yTemp')) {
        scales.yTemp = {
            type: 'linear',
            position: 'left',
            title: { display: true, text: 'Temperature (\u00b0C)', color: '#ef4444', font: { size: 10, family: 'Inter, sans-serif' } },
            ticks: { color: '#ef4444', font: { family: '"JetBrains Mono", monospace', size: 10 } },
            grid: { color: '#33415540' },
        }
    }
    if (usedAxes.has('yConv')) {
        scales.yConv = {
            type: 'linear',
            position: 'right',
            title: { display: true, text: 'Conversion (%)', color: '#22c55e', font: { size: 10, family: 'Inter, sans-serif' } },
            ticks: { color: '#22c55e', font: { family: '"JetBrains Mono", monospace', size: 10 } },
            grid: { drawOnChartArea: false },
            min: 0, max: 105,
        }
    }
    if (usedAxes.has('yVisc')) {
        scales.yVisc = {
            type: 'linear',
            position: 'right',
            title: { display: true, text: 'Viscosity (Pa\u00b7s)', color: '#06b6d4', font: { size: 10, family: 'Inter, sans-serif' } },
            ticks: { color: '#06b6d4', font: { family: '"JetBrains Mono", monospace', size: 10 } },
            grid: { drawOnChartArea: false },
        }
    }
    if (usedAxes.has('yMass')) {
        scales.yMass = {
            type: 'linear',
            position: 'right',
            title: { display: true, text: 'Mass (kg)', color: '#a855f7', font: { size: 10, family: 'Inter, sans-serif' } },
            ticks: { color: '#a855f7', font: { family: '"JetBrains Mono", monospace', size: 10 } },
            grid: { drawOnChartArea: false },
        }
    }

    chartInstance.value = new Chart(canvasRef.value, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: false,
                },
                tooltip: {
                    backgroundColor: '#1e293b',
                    borderColor: '#334155',
                    borderWidth: 1,
                    titleColor: '#f8fafc',
                    bodyColor: '#94a3b8',
                    bodyFont: { family: '"JetBrains Mono", monospace', size: 11 },
                    titleFont: { family: 'Inter, sans-serif', size: 11, weight: '600' },
                    padding: 10,
                    cornerRadius: 8,
                    callbacks: {
                        title(items) {
                            if (items.length > 0) {
                                return `t = ${items[0].parsed.x.toFixed(1)} min`
                            }
                            return ''
                        },
                        label(ctx) {
                            const ch = channels.find(c => c.label === ctx.dataset.label)
                            const unit = ch ? ch.unit : ''
                            return ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} ${unit}`
                        },
                    },
                },
                phaseBands: { bands },
            },
            scales,
        },
        plugins: [phaseBandsPlugin],
    })
}

function toggleChannel(id) {
    const idx = activeChannels.value.indexOf(id)
    if (idx >= 0) {
        // Don't allow disabling all channels
        if (activeChannels.value.length <= 1) return
        activeChannels.value.splice(idx, 1)
    } else {
        activeChannels.value.push(id)
    }
    buildChart()
}

async function loadData() {
    if (props.csvData) {
        data.value = props.csvData
        return
    }
    if (!props.filename) return

    loading.value = true
    error.value = ''
    try {
        data.value = await fetchBatchData(props.filename)
    } catch (e) {
        error.value = e.message
    } finally {
        loading.value = false
    }
}

watch(() => [props.filename, props.csvData], () => {
    loadData().then(buildChart)
})

onMounted(async () => {
    await loadData()
    buildChart()
})

onUnmounted(() => {
    if (chartInstance.value) {
        chartInstance.value.destroy()
        chartInstance.value = null
    }
})
</script>

<template>
  <div class="batch-chart">
    <!-- Channel toggles -->
    <div class="channel-toggles">
      <button
        v-for="ch in channels"
        :key="ch.id"
        class="channel-btn"
        :class="{ active: activeChannels.includes(ch.id) }"
        :style="{ '--ch-color': ch.color }"
        @click="toggleChannel(ch.id)"
      >
        <span class="ch-dot"></span>
        {{ ch.label }}
      </button>
    </div>

    <!-- Chart -->
    <div v-if="loading" class="chart-loading">Loading data...</div>
    <div v-else-if="error" class="chart-error">{{ error }}</div>
    <div v-else class="chart-wrapper">
      <canvas ref="canvasRef"></canvas>
    </div>

    <!-- Phase legend -->
    <div v-if="data" class="phase-legend">
      <span class="phase-legend-label">Phases:</span>
      <span v-for="(color, phase) in PHASE_COLORS" :key="phase" class="phase-tag" :style="{ background: color, borderColor: PHASE_BORDER_COLORS[phase] }">
        {{ phase }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.batch-chart {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.channel-toggles {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
}

.channel-btn {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 4px 10px;
    background: var(--bg-app);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    color: var(--text-muted);
    font-size: 10px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.channel-btn:hover { border-color: var(--ch-color); color: var(--text-secondary); }
.channel-btn.active { border-color: var(--ch-color); color: var(--text-primary); background: color-mix(in srgb, var(--ch-color) 10%, var(--bg-app)); }

.ch-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--ch-color);
    opacity: 0.4;
}
.channel-btn.active .ch-dot { opacity: 1; }

.chart-wrapper {
    height: 320px;
    width: 100%;
    position: relative;
}

.chart-loading, .chart-error {
    height: 320px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 13px;
}
.chart-error { color: var(--accent-danger); }

.phase-legend {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}
.phase-legend-label {
    font-size: 9px;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.phase-tag {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 9px;
    font-weight: 600;
    color: var(--text-secondary);
    border: 1px solid;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
</style>
