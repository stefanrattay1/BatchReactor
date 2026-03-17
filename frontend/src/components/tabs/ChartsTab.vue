<script setup>
import { computed } from 'vue'
import { state } from '../../services/store'
import MultiChart from '../MultiChart.vue'
import CollapsibleCard from '../CollapsibleCard.vue'

const estTimeConv = computed(() => {
    if (state.conversion >= 0.95) return 'Complete'
    return '-- min'
})

const peakTempC = computed(() => {
    if (state.peak_temperature_C <= 0) return '--'
    return Math.round(state.peak_temperature_C) + '\u00b0C'
})

const estRunaway = computed(() => {
    if (state.dt_dt > 1.5 || state.temperature_K > 453) return { text: 'HIGH', color: '#ef4444' }
    if (state.dt_dt > 0.8 || state.temperature_K > 423) return { text: 'MODERATE', color: '#f59e0b' }
    if (state.dt_dt > 0.3) return { text: 'ELEVATED', color: '#eab308' }
    return { text: 'LOW', color: '#22c55e' }
})
</script>

<template>
  <div class="charts-tab">
    <div class="chart-card">
        <MultiChart />
    </div>

    <CollapsibleCard title="Live Estimates" :highlight="true" :default-open="true">
        <div class="estimate-row">
            <span class="estimate-label">Est. Batch Remaining</span>
            <span class="estimate-value">{{ estTimeConv }}</span>
        </div>
        <div class="estimate-row">
            <span class="estimate-label">Peak Temp</span>
            <span class="estimate-value">{{ peakTempC }}</span>
        </div>
        <div class="estimate-row">
            <span class="estimate-label">Runaway Risk</span>
            <span class="estimate-value" :style="{ color: estRunaway.color }">{{ estRunaway.text }}</span>
        </div>
    </CollapsibleCard>
  </div>
</template>

<style scoped>
.charts-tab { padding: 20px; }

.chart-card {
    background: var(--bg-card);
    border-radius: 12px;
    padding: 20px;
    border: 1px solid var(--border-subtle);
    margin-bottom: 16px;
    box-shadow: var(--shadow-sm);
}

.estimate-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border-subtle); font-size: 0.85rem; }
.estimate-row:last-child { border-bottom: none; }
.estimate-label { color: var(--text-secondary); }
.estimate-value { font-weight: 600; font-family: var(--font-mono); color: var(--text-primary); }
</style>
