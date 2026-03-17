<script setup>
import { onMounted, ref, watch, shallowRef } from 'vue'
import Chart from 'chart.js/auto'
import { state } from '../services/store'
import { getHistory } from '../services/historyBuffer'

const props = defineProps({
  input: { type: Object, required: true },
  recipeData: { type: Object, default: null }
})

const canvasRef = ref(null)
const nowLabelRef = ref(null)
const chartInstance = shallowRef(null)
let totalDuration = 120

// Map input keys to recipe channel names
const channelMap = {
    'feed_rate_component_a': 'feed_component_a',
    'feed_rate_component_b': 'feed_component_b',
    'feed_rate_solvent': 'feed_solvent',
    'jacket_temperature_K': 'jacket_temp'
}

// Plugin for NOW marker
const nowDescPlugin = {
    id: 'nowDesc',
    afterDraw(chart) {
        if (!state.simulation_running && state.phase !== 'PAUSED') return
        const { ctx, chartArea, scales } = chart
        if (!chartArea) return

        const timeVal = state.recipe_elapsed_s
        const xPos = scales.x.getPixelForValue(timeVal)

        if (xPos >= chartArea.left && xPos <= chartArea.right) {
            const labelEl = chart.$nowLabelEl
            if (labelEl) {
                const labelHeight = labelEl.offsetHeight || 16
                const labelTop = Math.max(2, chartArea.top - labelHeight - 6)
                labelEl.style.left = `${xPos}px`
                labelEl.style.top = `${labelTop}px`
                labelEl.style.opacity = '1'
            }

            ctx.save()
            ctx.strokeStyle = '#22c55e'
            ctx.lineWidth = 2
            ctx.setLineDash([4, 4])
            ctx.beginPath()
            ctx.moveTo(xPos, chartArea.top)
            ctx.lineTo(xPos, chartArea.bottom)
            ctx.stroke()
            ctx.restore()
        }
    }
}

function updateChart() {
    if (!props.input || !canvasRef.value) return

    // Destroy existing
    if (chartInstance.value) {
        chartInstance.value.destroy()
        chartInstance.value = null
    }

    // Build recipe setpoint profile
    let profileData = []
    const channelName = channelMap[props.input.key]

    if (props.recipeData && channelName) {
        let t = 0
        for (const step of props.recipeData.steps) {
            const profile = step.profiles[channelName]
            if (profile) {
                profileData.push({ x: t, y: profile.start_value })
                profileData.push({ x: t + step.duration, y: profile.end_value })
            } else {
                profileData.push({ x: t, y: 0 })
                profileData.push({ x: t + step.duration, y: 0 })
            }
            t += step.duration
        }
        totalDuration = t
    }

    if (profileData.length === 0) {
        profileData = [{x:0, y:0}, {x:120, y:0}]
        totalDuration = 120
    }

    // Build actual measured values from history buffer
    const actualData = getHistory(props.input.key)

    const datasets = [
        {
            label: 'Setpoint',
            data: profileData,
            borderColor: props.input.color || '#3b82f6',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0,
            fill: true,
            backgroundColor: (props.input.color || '#3b82f6') + '15',
            borderDash: [6, 3],
        },
    ]

    // Add actual overlay if we have history data
    if (actualData.length > 0) {
        datasets.push({
            label: 'Actual',
            data: actualData,
            borderColor: '#22c55e',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.3,
            fill: false,
        })
    }

    chartInstance.value = new Chart(canvasRef.value, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            layout: { padding: { top: 30 } },
            plugins: {
                legend: {
                    display: actualData.length > 0,
                    labels: { color: '#94a3b8', boxWidth: 10, font: { size: 9 }, padding: 6 }
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    display: true,
                    min: 0,
                    max: totalDuration,
                    ticks: { color: '#94a3b8', maxTicksLimit: 6, font: { size: 9, family: '"JetBrains Mono", monospace' }, callback: (v) => Math.round(v) + 's' },
                    grid: { color: '#334155' },
                    title: { display: true, text: 'Batch Time (s)', color: '#64748b', font: { size: 10, family: 'Inter, sans-serif' } }
                },
                y: { ticks: { color: '#94a3b8', font: { size: 10, family: '"JetBrains Mono", monospace' } }, grid: { color: '#334155' } }
            }
        },
        plugins: [nowDescPlugin]
    })

    if (nowLabelRef.value) {
        chartInstance.value.$nowLabelEl = nowLabelRef.value
    }
}

// Watchers
watch(() => props.input, updateChart)
watch(() => props.recipeData, updateChart)

// Periodically refresh to show actual overlay updating
watch(() => state.recipe_elapsed_s, () => {
    if (chartInstance.value) {
        // Update actual data in the chart
        const actualData = getHistory(props.input.key)
        if (chartInstance.value.data.datasets.length > 1) {
            chartInstance.value.data.datasets[1].data = actualData
        } else if (actualData.length > 0) {
            // Add actual dataset if it wasn't there before
            chartInstance.value.data.datasets.push({
                label: 'Actual',
                data: actualData,
                borderColor: '#22c55e',
                borderWidth: 1.5,
                pointRadius: 0,
                tension: 0.3,
                fill: false,
            })
            chartInstance.value.options.plugins.legend.display = true
        }
        chartInstance.value.update('none')
    }
})

onMounted(updateChart)
</script>

<template>
  <div class="chart-container">
        <div ref="nowLabelRef" class="now-label">NOW</div>
    <canvas ref="canvasRef"></canvas>
  </div>
</template>

<style scoped>
.chart-container { height: 140px; width: 100%; position: relative; }
.now-label {
    position: absolute;
    left: 0;
    top: 0;
    transform: translateX(-50%);
    padding: 2px 5px;
    border-radius: 999px;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.3px;
    color: var(--accent-success);
    background: rgba(34, 197, 94, 0.15);
    border: 1px solid var(--accent-success);
    pointer-events: none;
    opacity: 0;
}
</style>
