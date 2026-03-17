<script setup>
import { onMounted, ref, watch, shallowRef } from 'vue'
import Chart from 'chart.js/auto'
import { state } from '../services/store'
import { useRecipeForecast } from '../composables/useRecipeForecast'

// --- Chart refs ---
const tempCanvasRef = ref(null)
const convCanvasRef = ref(null)
const tempNowRef = ref(null)
const convNowRef = ref(null)
const tempChart = shallowRef(null)
const convChart = shallowRef(null)

// --- Time range ---
const timeOptions = [
    { label: '2m', value: 120 },
    { label: '5m', value: 300 },
    { label: '15m', value: 900 },
    { label: 'Full', value: 0 },
]
const timeWindow = ref(120)

// --- Data buffers (plain objects, not reactive) ---
const tempData = []       // temperature_C
const jacketData = []     // jacket_temperature_K -> °C
const convData = []       // conversion -> %
const forecastData = []
const MAX_POINTS = 6000
let lastTimeVal = 0
let currentElapsed = 0

// --- Recipe forecast ---
const { loadRecipeSetpoint, buildForecast } = useRecipeForecast()

// --- NOW marker plugin ---
function createNowPlugin(labelRefGetter) {
    return {
        id: 'nowMarker',
        afterDraw(chart) {
            const { ctx, chartArea, scales } = chart
            if (!chartArea || !scales.x) return
            const xPos = scales.x.getPixelForValue(currentElapsed)
            if (xPos < chartArea.left || xPos > chartArea.right) {
                const el = labelRefGetter()
                if (el) el.style.opacity = '0'
                return
            }
            const el = labelRefGetter()
            if (el) {
                el.style.left = `${xPos}px`
                el.style.top = `${Math.max(2, chartArea.top - 16)}px`
                el.style.opacity = '1'
            }
            ctx.save()
            ctx.strokeStyle = '#22c55e'
            ctx.lineWidth = 1.5
            ctx.setLineDash([4, 3])
            ctx.beginPath()
            ctx.moveTo(xPos, chartArea.top)
            ctx.lineTo(xPos, chartArea.bottom)
            ctx.stroke()
            ctx.restore()
        }
    }
}

// --- Chart initialization ---
function initTempChart() {
    if (!tempCanvasRef.value) return
    tempChart.value = new Chart(tempCanvasRef.value, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'Reactor',
                    data: tempData,
                    borderColor: '#ef4444',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: false,
                    yAxisID: 'y',
                },
                {
                    label: 'Jacket',
                    data: jacketData,
                    borderColor: '#f97316',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3,
                    borderDash: [4, 2],
                    fill: false,
                    yAxisID: 'y',
                },
                {
                    label: 'Forecast',
                    data: forecastData,
                    borderColor: '#ef4444',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0,
                    borderDash: [6, 4],
                    fill: false,
                    yAxisID: 'y',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            layout: { padding: { top: 20, right: 4 } },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: '#94a3b8', boxWidth: 8, font: { size: 8 }, padding: 6 },
                },
            },
            scales: {
                x: {
                    type: 'linear',
                    title: { display: false },
                    ticks: { color: '#64748b', maxTicksLimit: 6, callback: v => Math.round(v) + 's', font: { size: 9, family: '"JetBrains Mono", monospace' } },
                    grid: { color: '#1e293b' },
                    min: 0, max: 120,
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: '°C', color: '#64748b', font: { size: 9 } },
                    ticks: { color: '#94a3b8', font: { size: 9, family: '"JetBrains Mono", monospace' } },
                    grid: { color: '#1e293b' },
                    suggestedMin: 20, suggestedMax: 200,
                },
            },
        },
        plugins: [createNowPlugin(() => tempNowRef.value)],
    })
}

function initConvChart() {
    if (!convCanvasRef.value) return
    convChart.value = new Chart(convCanvasRef.value, {
        type: 'line',
        data: {
            datasets: [{
                label: 'Conversion',
                data: convData,
                borderColor: '#10b981',
                backgroundColor: '#10b98115',
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.3,
                fill: true,
                yAxisID: 'y',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            layout: { padding: { top: 20, right: 4 } },
            plugins: {
                legend: {
                    display: true,
                    labels: { color: '#94a3b8', boxWidth: 8, font: { size: 8 }, padding: 6 },
                },
            },
            scales: {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'Time (s)', color: '#64748b', font: { size: 9 } },
                    ticks: { color: '#64748b', maxTicksLimit: 6, callback: v => Math.round(v) + 's', font: { size: 9, family: '"JetBrains Mono", monospace' } },
                    grid: { color: '#1e293b' },
                    min: 0, max: 120,
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: '%', color: '#64748b', font: { size: 9 } },
                    ticks: { color: '#94a3b8', font: { size: 9, family: '"JetBrains Mono", monospace' } },
                    grid: { color: '#1e293b' },
                    min: 0, max: 100,
                },
            },
        },
        plugins: [createNowPlugin(() => convNowRef.value)],
    })
}

// --- Data update watcher ---
watch(
    () => [state.recipe_elapsed_s, state.temperature_C, state.simulation_running, state.phase],
    ([timeVal]) => {
        // Reset on IDLE + time 0
        if (state.phase === 'IDLE' && timeVal === 0) {
            tempData.length = 0
            jacketData.length = 0
            convData.length = 0
            lastTimeVal = 0
            currentElapsed = 0
        }

        const nextTime = typeof timeVal === 'number' ? timeVal : 0
        const xVal = nextTime > lastTimeVal ? nextTime : lastTimeVal + 1
        lastTimeVal = xVal
        currentElapsed = xVal

        // Push temperature data
        const tc = state.temperature_C
        if (typeof tc === 'number' && Number.isFinite(tc)) {
            tempData.push({ x: xVal, y: tc })
            if (tempData.length > MAX_POINTS) tempData.shift()
        }

        // Push jacket data
        const jk = state.jacket_temperature_K
        if (typeof jk === 'number' && Number.isFinite(jk)) {
            jacketData.push({ x: xVal, y: jk - 273.15 })
            if (jacketData.length > MAX_POINTS) jacketData.shift()
        }

        // Push conversion data
        const cv = state.conversion
        if (typeof cv === 'number' && Number.isFinite(cv)) {
            convData.push({ x: xVal, y: cv * 100 })
            if (convData.length > MAX_POINTS) convData.shift()
        }

        // Update sliding window for both charts
        updateWindow(tempChart.value, xVal, tempData, jacketData)
        updateWindow(convChart.value, xVal, convData)

        // Update forecast on temp chart
        if (tempChart.value) {
            const fc = buildForecast(currentElapsed)
            tempChart.value.data.datasets[2].data = fc
            tempChart.value.update('none')
        }
        if (convChart.value) {
            convChart.value.update('none')
        }
    }
)

function updateWindow(chart, elapsed, ...dataArrays) {
    if (!chart) return
    const win = timeWindow.value
    if (win === 0) {
        chart.options.scales.x.min = 0
        chart.options.scales.x.max = Math.max(120, elapsed + 30)
    } else if (elapsed <= win) {
        chart.options.scales.x.min = 0
        chart.options.scales.x.max = win
    } else {
        chart.options.scales.x.min = elapsed - win * 0.75
        chart.options.scales.x.max = elapsed + win * 0.25
    }

    // Auto-scale Y for temperature chart
    if (chart === tempChart.value) {
        const xMin = chart.options.scales.x.min
        const xMax = chart.options.scales.x.max
        const visibleVals = []
        for (const arr of dataArrays) {
            for (const p of arr) {
                if (p.x >= xMin && p.x <= xMax) visibleVals.push(p.y)
            }
        }
        const fc = buildForecast(currentElapsed)
        for (const p of fc) {
            if (p.x >= xMin && p.x <= xMax) visibleVals.push(p.y)
        }
        if (visibleVals.length > 1) {
            const minV = Math.min(...visibleVals)
            const maxV = Math.max(...visibleVals)
            const pad = Math.max(2, (maxV - minV) * 0.2)
            chart.options.scales.y.min = minV - pad
            chart.options.scales.y.max = maxV + pad
        } else {
            chart.options.scales.y.min = undefined
            chart.options.scales.y.max = undefined
        }
    }
}

// Reload recipe on simulation start
watch(() => state.phase, (newPhase, oldPhase) => {
    if (oldPhase === 'IDLE' && newPhase !== 'IDLE') loadRecipeSetpoint()
})

onMounted(() => {
    initTempChart()
    initConvChart()
    loadRecipeSetpoint()
})
</script>

<template>
  <div class="trend-panel">
    <div class="trend-header">
      <span class="section-title">Trends</span>
      <div class="time-controls">
        <button v-for="opt in timeOptions" :key="opt.value"
                class="time-btn" :class="{ active: timeWindow === opt.value }"
                @click="timeWindow = opt.value">
          {{ opt.label }}
        </button>
      </div>
    </div>

    <!-- Temperature chart -->
    <div class="chart-wrap temp-chart">
      <div ref="tempNowRef" class="now-label">NOW</div>
      <canvas ref="tempCanvasRef"></canvas>
    </div>

    <!-- Conversion chart -->
    <div class="chart-wrap conv-chart">
      <div ref="convNowRef" class="now-label">NOW</div>
      <canvas ref="convCanvasRef"></canvas>
    </div>
  </div>
</template>

<style scoped>
.trend-panel {
    padding: 8px;
    border-bottom: 1px solid var(--border-subtle);
}

.trend-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
}

.section-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

.time-controls {
    display: flex;
    gap: 1px;
    background: var(--bg-app);
    border-radius: 4px;
    padding: 1px;
    border: 1px solid var(--border-subtle);
}

.time-btn {
    padding: 2px 6px;
    border: none;
    border-radius: 3px;
    background: transparent;
    color: var(--text-muted);
    font-size: 0.6rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
}
.time-btn:hover { color: var(--text-primary); }
.time-btn.active { background: var(--accent-primary); color: white; }

.chart-wrap {
    width: 100%;
    position: relative;
}

.temp-chart {
    height: 170px;
    margin-bottom: 4px;
}

.conv-chart {
    height: 120px;
}

.now-label {
    position: absolute;
    left: 0;
    top: 0;
    transform: translateX(-50%);
    padding: 1px 4px;
    border-radius: 999px;
    font-size: 8px;
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
