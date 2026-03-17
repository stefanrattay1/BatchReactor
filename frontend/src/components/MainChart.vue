<script setup>
import { onMounted, ref, watch, shallowRef } from 'vue'
import Chart from 'chart.js/auto'
import { state } from '../services/store'

const canvasRef = ref(null)
const nowLabelRef = ref(null)
const chartInstance = shallowRef(null)

// Data Accumulation
const chartData = { tempSim: [], tempMeas: [] }
const MAX_POINTS = 600
let lastTimeVal = 0
let currentElapsed = 0

// Recipe setpoint trajectory (jacket temp converted K→°C)
const recipeSetpoint = []
let recipeTotalDuration = 0

async function loadRecipeSetpoint() {
    try {
        const res = await fetch('/api/recipe/current')
        const data = await res.json()
        recipeSetpoint.length = 0
        let t = 0
        for (const step of data.steps) {
            const profile = step.profiles?.jacket_temp
            if (profile) {
                recipeSetpoint.push({ x: t, y: profile.start_value - 273.15 })
                recipeSetpoint.push({ x: t + step.duration, y: profile.end_value - 273.15 })
            }
            t += step.duration
        }
        recipeTotalDuration = t
        if (chartInstance.value && chartInstance.value.data.datasets.length > 2) {
            chartInstance.value.data.datasets[2].data = buildForecast()
            chartInstance.value.update('none')
        }
    } catch (e) {
        // Recipe not available yet
    }
}

// Build forecast: starts at current temp, follows jacket setpoint into the future
function buildForecast() {
    if (recipeSetpoint.length === 0 || currentElapsed <= 0) return recipeSetpoint
    const forecast = []
    // Anchor at current temperature
    forecast.push({ x: currentElapsed, y: state.temperature_C })
    // Append all future setpoint values
    for (const p of recipeSetpoint) {
        if (p.x > currentElapsed) forecast.push(p)
    }
    return forecast
}

// Plugin for NOW marker
const nowMarkerPlugin = {
    id: 'nowMarker',
    afterDraw(chart) {
        const { ctx, chartArea, scales } = chart
        if (!chartArea || !scales.x) return

        const xPos = scales.x.getPixelForValue(currentElapsed)

        // Don't draw if outside visible area
        if (xPos < chartArea.left || xPos > chartArea.right) {
            const labelEl = chart.$nowLabelEl
            if (labelEl) {
                labelEl.style.opacity = '0'
            }
            return
        }

        const labelEl = chart.$nowLabelEl
        if (labelEl) {
            const labelHeight = labelEl.offsetHeight || 18
            const labelTop = Math.max(2, chartArea.top - labelHeight - 6)
            labelEl.style.left = `${xPos}px`
            labelEl.style.top = `${labelTop}px`
            labelEl.style.opacity = '1'
        }

        ctx.save()
        ctx.strokeStyle = '#22c55e' // var(--accent-success)
        ctx.lineWidth = 2
        ctx.setLineDash([6, 4])
        ctx.beginPath()
        ctx.moveTo(xPos, chartArea.top)
        ctx.lineTo(xPos, chartArea.bottom)
        ctx.stroke()
        ctx.restore()
    }
}

function initChart() {
    if (!canvasRef.value) return

    chartInstance.value = new Chart(canvasRef.value, {
        type: 'line',
        data: {
            datasets: [
                {
                    label: 'Simulated Temp',
                    data: [],
                    borderColor: '#ef4444', // var(--sensor-temp)
                    backgroundColor: '#ef444420',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    fill: false
                },
                {
                    label: 'Measured Temp',
                    data: [],
                    borderColor: '#f59e0b', // var(--sensor-speed) -> changed to amber for measured/warning
                    backgroundColor: '#f59e0b20',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.3,
                    borderDash: [4, 3],
                    fill: false
                },
                {
                    label: 'Forecast',
                    data: [],
                    borderColor: '#ef4444',
                    backgroundColor: '#ef444410',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0,
                    borderDash: [6, 4],
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            layout: { padding: { top: 36 } },
            plugins: {
                legend: { labels: { color: '#94a3b8', boxWidth: 12, font: { size: 10 } } }
            },
            scales: {
                x: {
                    type: 'linear',
                    display: true,
                    title: { display: true, text: 'Time (s)', color: '#64748b', font: { size: 10, family: 'Inter, sans-serif' } },
                    ticks: {
                        color: '#94a3b8',
                        maxTicksLimit: 12,
                        callback: function(value) { return Math.round(value) + 's' },
                        font: { family: '"JetBrains Mono", monospace' }
                    },
                    grid: { color: '#334155' },
                    min: 0,
                    max: 120
                },
                y: {
                    title: { display: true, text: 'Temperature (°C)', color: '#64748b', font: { size: 10, family: 'Inter, sans-serif' } },
                    ticks: { color: '#94a3b8', font: { family: '"JetBrains Mono", monospace' } },
                    grid: { color: '#334155' },
                    suggestedMin: 20,
                    suggestedMax: 200
                }
            }
        },
        plugins: [nowMarkerPlugin]
    })

    if (typeof window !== 'undefined') {
        window.tempChart = chartInstance.value
    }

    if (nowLabelRef.value) {
        chartInstance.value.$nowLabelEl = nowLabelRef.value
    }
}

// Watch for state updates to push data
watch(
    () => [
        state.recipe_elapsed_s,
        state.temperature_C,
        state.temperature_measured_C,
        state.simulation_running,
        state.phase
    ],
    ([timeVal]) => {
    if (!chartInstance.value) return

    // Reset if IDLE and time is 0
    if (state.phase === 'IDLE' && timeVal === 0) {
        chartData.tempSim = []
        chartData.tempMeas = []
        lastTimeVal = 0
        currentElapsed = 0
    }

    const nextTime = typeof timeVal === 'number' ? timeVal : 0
    const xVal = nextTime > lastTimeVal ? nextTime : lastTimeVal + 1
    lastTimeVal = xVal
    currentElapsed = xVal

    chartData.tempSim.push({ x: xVal, y: state.temperature_C })
    chartData.tempMeas.push({ x: xVal, y: state.temperature_measured_C })

    if (chartData.tempSim.length > MAX_POINTS) {
        chartData.tempSim.shift()
        chartData.tempMeas.shift()
    }

    // Update Datasets
    chartInstance.value.data.datasets[0].data = chartData.tempSim
    chartInstance.value.data.datasets[1].data = chartData.tempMeas
    const forecast = buildForecast()
    chartInstance.value.data.datasets[2].data = forecast

    // Sliding Window - keep NOW near the right edge
    const elapsed = xVal || 0
    const windowSize = 120  // Fixed 2-minute window

    if (elapsed <= windowSize) {
        // Early phase: show from 0 to windowSize
        chartInstance.value.options.scales.x.min = 0
        chartInstance.value.options.scales.x.max = windowSize
    } else {
        // Sliding phase: keep NOW at 75% position (show 25% future space)
        chartInstance.value.options.scales.x.min = elapsed - windowSize * 0.75
        chartInstance.value.options.scales.x.max = elapsed + windowSize * 0.25
    }

    if (chartData.tempSim.length > 1) {
        const temps = chartData.tempSim.map((p) => p.y)
        // Include visible forecast values in y-range
        const xMin = chartInstance.value.options.scales.x.min
        const xMax = chartInstance.value.options.scales.x.max
        for (const p of forecast) {
            if (p.x >= xMin && p.x <= xMax) temps.push(p.y)
        }
        const minTemp = Math.min(...temps)
        const maxTemp = Math.max(...temps)
        const padding = Math.max(2, (maxTemp - minTemp) * 0.2)
        chartInstance.value.options.scales.y.min = minTemp - padding
        chartInstance.value.options.scales.y.max = maxTemp + padding
    } else {
        chartInstance.value.options.scales.y.min = undefined
        chartInstance.value.options.scales.y.max = undefined
    }

    chartInstance.value.update('none')
})

onMounted(() => {
    initChart()
    loadRecipeSetpoint()
})

// Reload recipe setpoint when simulation starts (in case recipe changed)
watch(() => state.phase, (newPhase, oldPhase) => {
    if (oldPhase === 'IDLE' && newPhase !== 'IDLE') {
        loadRecipeSetpoint()
    }
})
</script>

<template>
  <div class="chart-container">
        <div id="chart-now-label" ref="nowLabelRef" class="now-label">NOW</div>
        <canvas id="chart-temp" ref="canvasRef"></canvas>
  </div>
</template>

<style scoped>
.chart-container { height: 180px; width: 100%; position: relative; }
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
}
</style>
