<script setup>
import { onMounted, onActivated, ref, watch, shallowRef } from 'vue'
import Chart from 'chart.js/auto'
import { state } from '../services/store'
import { CHART_CHANNELS, loadActiveChannels, saveActiveChannels } from '../config/chartChannels'
import { useRecipeForecast } from '../composables/useRecipeForecast'

const canvasRef = ref(null)
const nowLabelRef = ref(null)
const chartInstance = shallowRef(null)

// Active channels (persisted to localStorage)
const activeChannelIds = ref(loadActiveChannels())

function isActive(id) { return activeChannelIds.value.includes(id) }
function toggleChannel(id) {
    const idx = activeChannelIds.value.indexOf(id)
    if (idx >= 0) activeChannelIds.value.splice(idx, 1)
    else activeChannelIds.value.push(id)
    saveActiveChannels(activeChannelIds.value)
    updateVisibleDatasets()
}

// Time range
const timeOptions = [
    { label: '2m', value: 120 },
    { label: '5m', value: 300 },
    { label: '15m', value: 900 },
    { label: 'Full', value: 0 },
]
const timeWindow = ref(120)
function setTimeWindow(val) { timeWindow.value = val }

// Data accumulation — collect ALL channels on every tick
// Plain object (not reactive) to avoid infinite loops when Chart.js mutates data arrays
const chartData = {}
for (const ch of CHART_CHANNELS) {
    chartData[ch.id] = []
}
const MAX_POINTS = 6000  // Large buffer for Full view
let lastTimeVal = 0
let currentElapsed = 0

// Recipe forecast
const { recipeSetpoint, loadRecipeSetpoint, buildForecast } = useRecipeForecast()

// NOW marker plugin
const nowMarkerPlugin = {
    id: 'nowMarker',
    afterDraw(chart) {
        const { ctx, chartArea, scales } = chart
        if (!chartArea || !scales.x) return

        const xPos = scales.x.getPixelForValue(currentElapsed)
        if (xPos < chartArea.left || xPos > chartArea.right) {
            if (chart.$nowLabelEl) chart.$nowLabelEl.style.opacity = '0'
            return
        }

        if (chart.$nowLabelEl) {
            const labelHeight = chart.$nowLabelEl.offsetHeight || 18
            const labelTop = Math.max(2, chartArea.top - labelHeight - 6)
            chart.$nowLabelEl.style.left = `${xPos}px`
            chart.$nowLabelEl.style.top = `${labelTop}px`
            chart.$nowLabelEl.style.opacity = '1'
        }

        ctx.save()
        ctx.strokeStyle = '#22c55e'
        ctx.lineWidth = 2
        ctx.setLineDash([6, 4])
        ctx.beginPath()
        ctx.moveTo(xPos, chartArea.top)
        ctx.lineTo(xPos, chartArea.bottom)
        ctx.stroke()
        ctx.restore()
    }
}

function buildDatasets() {
    const datasets = []

    for (const ch of CHART_CHANNELS) {
        if (!isActive(ch.id)) continue
        datasets.push({
            label: ch.label,
            data: chartData[ch.id],
            borderColor: ch.color,
            backgroundColor: ch.color + '15',
            borderWidth: ch.id === 'temp_sim' ? 2 : 1.5,
            pointRadius: 0,
            tension: 0.3,
            borderDash: ch.dash || [],
            fill: false,
            yAxisID: ch.yAxis === 'left' ? 'yLeft' : 'yRight',
        })
    }

    // Forecast dataset (always on left axis, dashed)
    datasets.push({
        label: 'Forecast',
        data: buildForecast(currentElapsed),
        borderColor: '#ef4444',
        backgroundColor: '#ef444410',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0,
        borderDash: [6, 4],
        fill: false,
        yAxisID: 'yLeft',
    })

    return datasets
}

function initChart() {
    if (!canvasRef.value) return

    chartInstance.value = new Chart(canvasRef.value, {
        type: 'line',
        data: { datasets: buildDatasets() },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            layout: { padding: { top: 36 } },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: '#94a3b8', boxWidth: 10, font: { size: 9 }, padding: 8 },
                    onClick(e, legendItem, legend) {
                        // Toggle channel via our system instead of default Chart.js behavior
                        const ch = CHART_CHANNELS.find(c => c.label === legendItem.text)
                        if (ch) toggleChannel(ch.id)
                    }
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    display: true,
                    title: { display: true, text: 'Time (s)', color: '#64748b', font: { size: 10, family: 'Inter, sans-serif' } },
                    ticks: {
                        color: '#94a3b8',
                        maxTicksLimit: 12,
                        callback: (v) => Math.round(v) + 's',
                        font: { family: '"JetBrains Mono", monospace' }
                    },
                    grid: { color: '#334155' },
                    min: 0,
                    max: 120,
                },
                yLeft: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: 'Temperature (\u00b0C)', color: '#64748b', font: { size: 10, family: 'Inter, sans-serif' } },
                    ticks: { color: '#94a3b8', font: { family: '"JetBrains Mono", monospace' } },
                    grid: { color: '#334155' },
                    suggestedMin: 20,
                    suggestedMax: 200,
                },
                yRight: {
                    type: 'linear',
                    position: 'right',
                    ticks: { color: '#94a3b8', font: { family: '"JetBrains Mono", monospace' } },
                    grid: { drawOnChartArea: false },
                },
            },
        },
        plugins: [nowMarkerPlugin],
    })

    if (nowLabelRef.value) {
        chartInstance.value.$nowLabelEl = nowLabelRef.value
    }
}

function updateVisibleDatasets() {
    if (!chartInstance.value) return
    chartInstance.value.data.datasets = buildDatasets()
    chartInstance.value.update('none')
}

// Watch for state updates
watch(
    () => [state.recipe_elapsed_s, state.temperature_C, state.simulation_running, state.phase],
    ([timeVal]) => {
        if (!chartInstance.value) return

        // Reset on IDLE + time 0
        if (state.phase === 'IDLE' && timeVal === 0) {
            for (const ch of CHART_CHANNELS) {
                chartData[ch.id] = []
            }
            lastTimeVal = 0
            currentElapsed = 0
        }

        const nextTime = typeof timeVal === 'number' ? timeVal : 0
        const xVal = nextTime > lastTimeVal ? nextTime : lastTimeVal + 1
        lastTimeVal = xVal
        currentElapsed = xVal

        // Push data for ALL channels (even hidden, so toggling shows full history)
        for (const ch of CHART_CHANNELS) {
            let val = state[ch.stateKey]
            if (val === undefined || val === null) continue
            if (ch.transform) val = ch.transform(val)
            chartData[ch.id].push({ x: xVal, y: val })
            if (chartData[ch.id].length > MAX_POINTS) chartData[ch.id].shift()
        }

        // Rebuild visible datasets
        chartInstance.value.data.datasets = buildDatasets()

        // Sliding window
        const elapsed = xVal || 0
        const window = timeWindow.value

        if (window === 0) {
            // Full batch view
            chartInstance.value.options.scales.x.min = 0
            chartInstance.value.options.scales.x.max = Math.max(120, elapsed + 30)
        } else if (elapsed <= window) {
            chartInstance.value.options.scales.x.min = 0
            chartInstance.value.options.scales.x.max = window
        } else {
            chartInstance.value.options.scales.x.min = elapsed - window * 0.75
            chartInstance.value.options.scales.x.max = elapsed + window * 0.25
        }

        // Auto-scale y-left based on visible temperature data
        const xMin = chartInstance.value.options.scales.x.min
        const xMax = chartInstance.value.options.scales.x.max
        const leftTemps = []
        for (const ch of CHART_CHANNELS) {
            if (ch.yAxis !== 'left' || !isActive(ch.id)) continue
            for (const p of chartData[ch.id]) {
                if (p.x >= xMin && p.x <= xMax) leftTemps.push(p.y)
            }
        }
        // Include forecast
        const forecast = buildForecast(currentElapsed)
        for (const p of forecast) {
            if (p.x >= xMin && p.x <= xMax) leftTemps.push(p.y)
        }

        if (leftTemps.length > 1) {
            const minT = Math.min(...leftTemps)
            const maxT = Math.max(...leftTemps)
            const pad = Math.max(2, (maxT - minT) * 0.2)
            chartInstance.value.options.scales.yLeft.min = minT - pad
            chartInstance.value.options.scales.yLeft.max = maxT + pad
        } else {
            chartInstance.value.options.scales.yLeft.min = undefined
            chartInstance.value.options.scales.yLeft.max = undefined
        }

        chartInstance.value.update('none')
    }
)

// Reload recipe on simulation start
watch(() => state.phase, (newPhase, oldPhase) => {
    if (oldPhase === 'IDLE' && newPhase !== 'IDLE') {
        loadRecipeSetpoint()
    }
})

onMounted(() => {
    initChart()
    loadRecipeSetpoint()
})

// Resize chart when tab becomes active again (KeepAlive)
onActivated(() => {
    if (chartInstance.value) chartInstance.value.resize()
})
</script>

<template>
  <div class="multi-chart">
    <!-- Toolbar -->
    <div class="chart-toolbar">
        <div class="channel-chips">
            <button v-for="ch in CHART_CHANNELS" :key="ch.id"
                    class="chip"
                    :class="{ active: isActive(ch.id) }"
                    :style="isActive(ch.id) ? { background: ch.color + '20', borderColor: ch.color, color: ch.color } : {}"
                    @click="toggleChannel(ch.id)">
                {{ ch.label }}
            </button>
        </div>
        <div class="time-controls">
            <button v-for="opt in timeOptions" :key="opt.value"
                    class="time-btn"
                    :class="{ active: timeWindow === opt.value }"
                    @click="setTimeWindow(opt.value)">
                {{ opt.label }}
            </button>
        </div>
    </div>

    <!-- Chart -->
    <div class="chart-container">
        <div ref="nowLabelRef" class="now-label">NOW</div>
        <canvas ref="canvasRef"></canvas>
    </div>
  </div>
</template>

<style scoped>
.multi-chart { width: 100%; }

.chart-toolbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
    flex-wrap: wrap;
}

.channel-chips {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
}

.chip {
    padding: 3px 8px;
    border-radius: 999px;
    border: 1px solid var(--border-subtle);
    background: transparent;
    color: var(--text-muted);
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
}
.chip:hover { border-color: var(--border-focus); }
.chip.active { font-weight: 700; }

.time-controls {
    display: flex;
    gap: 2px;
    background: var(--bg-app);
    border-radius: 6px;
    padding: 2px;
    border: 1px solid var(--border-subtle);
}

.time-btn {
    padding: 3px 10px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-muted);
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
}
.time-btn:hover { color: var(--text-primary); }
.time-btn.active { background: var(--accent-primary); color: white; }

.chart-container {
    height: 300px;
    width: 100%;
    position: relative;
}

.now-label {
    position: absolute;
    left: 0;
    top: 0;
    transform: translateX(-50%);
    padding: 2px 6px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: var(--accent-success);
    background: rgba(34, 197, 94, 0.15);
    border: 1px solid var(--accent-success);
    pointer-events: none;
    opacity: 0;
    z-index: 10;
}
</style>
