<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { state } from '../../services/store'
import { sensorConfig } from '../../services/sensorConfig'

const props = defineProps({
    data: { type: Object, default: () => ({}) },
})

const tagPrefix = computed(() => {
    const tag = String(props.data.tag || '').trim().toUpperCase()
    return tag.split('-')[0] || 'INST'
})

const isValve = computed(() => ['XV', 'PCV', 'FCV'].includes(tagPrefix.value))
const isPump = computed(() => tagPrefix.value === 'P')

const value = computed(() => {
    const key = props.data.valueKey
    if (!key) return '--'
    const raw = state[key]
    if (typeof raw !== 'number') return '--'

    if (props.data.unit === 'K') return (raw - 273.15).toFixed(1)
    if (props.data.unit === 'bar') return raw.toFixed(3)
    if (props.data.unit === 'kg/s') return raw.toFixed(3)
    if (props.data.unit === '%') return raw.toFixed(1)
    return raw.toFixed(2)
})

const showValue = computed(() => {
    if (typeof props.data.showValue === 'boolean') return props.data.showValue
    if (isValve.value || isPump.value) return false
    const key = props.data.valueKey
    if (key) {
        const sensor = sensorConfig.availableNodes.find(n => n.state_key === key)
        if (sensor) return sensorConfig.enabledSensorIds.includes(sensor.id)
    }
    return ['FT', 'TT', 'PT', 'LT'].includes(tagPrefix.value)
})

const symbolPath = computed(() => {
    const p = tagPrefix.value
    if (p === 'FT') return 'M7 2a5 5 0 1 1 0 10a5 5 0 1 1 0-10zm2.4 5L7.2 9.2L4.5 6.5'
    if (p === 'TT') return 'M6 1v8a2 2 0 1 0 2 0V1M5 6h2'
    if (p === 'PT') return 'M2 7a5 5 0 1 1 10 0H2zm5-2v2l2 1'
    if (p === 'LT') return 'M3 2h8v10H3zM4 10h6'
    if (p === 'M') return 'M2 3h10v8H2zM4 5h6v4H4z'
    return 'M2 2h10v10H2z'
})

const isActive = computed(() => {
    if (!state.simulation_running) return false
    const key = props.data.valueKey
    return typeof state[key] === 'number' && state[key] > 0.001
})

const isSensorDisabled = computed(() => {
    const key = props.data.valueKey
    if (!key) return false
    const sensor = sensorConfig.availableNodes.find(n => n.state_key === key)
    if (!sensor) return false
    return !sensorConfig.enabledSensorIds.includes(sensor.id)
})

// ISA-101: muted gray in normal state, color only on deviation
const statusColor = computed(() => {
    if (state.phase === 'RUNAWAY_ALARM') return '#ef4444'
    if (!state.simulation_running) return '#52525b'
    const key = props.data.valueKey
    const valueNum = key ? state[key] : null
    if (['XV', 'PCV', 'P', 'M'].includes(tagPrefix.value)) {
        if (typeof valueNum === 'number' && valueNum > 0.001) return '#9ca3af'
        return '#52525b'
    }
    return '#6b7280'
})
</script>

<template>
  <div class="instrument-node" :class="{ 'sensor-disabled': isSensorDisabled }">
    <Handle type="target" :position="Position.Top" />
    <Handle type="source" :position="Position.Bottom" />

    <!-- XV valve: compact inline P&ID symbol -->
    <div v-if="isValve" class="valve-node">
      <svg width="20" height="28" viewBox="-8 -16 16 28" overflow="visible">
        <!-- actuator stem -->
        <line x1="0" y1="-6" x2="0" y2="-10" :stroke="statusColor" stroke-width="1.2"/>
        <!-- pneumatic circle -->
        <circle cx="0" cy="-13" r="3" fill="#141414" :stroke="statusColor" stroke-width="1.2"/>
        <circle v-if="isActive" cx="0" cy="-13" r="1.2" :fill="statusColor"/>
        <!-- bowtie body -->
        <polygon points="-7,0 0,-6 0,6" :fill="statusColor"/>
        <polygon points="7,0 0,-6 0,6" :fill="statusColor"/>
      </svg>
      <div class="valve-tag" :style="{ color: statusColor }">{{ data.tag }}</div>
    </div>

    <!-- Pump: ISA centrifugal pump circle symbol -->
    <div v-else-if="isPump" class="pump-node">
      <svg width="30" height="34" viewBox="-15 -17 30 34" overflow="visible">
        <!-- pump body circle -->
        <circle cx="0" cy="0" r="11" fill="#1c1c1c" :stroke="statusColor" stroke-width="1.4"/>
        <!-- discharge nozzle (tangential, pointing right-up) -->
        <line x1="8" y1="-7" x2="14" y2="-7" :stroke="statusColor" stroke-width="1.4"/>
        <!-- suction nozzle (bottom) -->
        <line x1="0" y1="11" x2="0" y2="15" :stroke="statusColor" stroke-width="1.4"/>
        <!-- active indicator -->
        <circle v-if="isActive" cx="0" cy="0" r="3" :fill="statusColor" fill-opacity="0.5"/>
      </svg>
      <div class="valve-tag" :style="{ color: statusColor }">{{ data.tag }}</div>
    </div>

    <!-- Regular instrument: card -->
    <div v-else class="pid-node-card instrument-box" :style="{ borderColor: statusColor }">
      <div class="pid-node-head">
        <span class="pid-node-tag">{{ data.tag || 'INST' }}</span>
        <span class="pid-node-status" :style="{ background: statusColor }"></span>
      </div>
      <div class="instrument-main">
        <svg class="pid-node-symbol" viewBox="0 0 14 14" fill="none" stroke="currentColor"
             stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
          <path :d="symbolPath" />
        </svg>
        <div class="pid-node-name">{{ data.name || 'Instrument' }}</div>
      </div>
      <div class="pid-node-value" v-if="showValue && data.valueKey">
        <span class="pid-node-value-num">{{ value }}</span>
        <span class="pid-node-value-unit">{{ data.unit === 'K' ? '°C' : (data.unit || '') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.instrument-node { cursor: grab; }
.instrument-node:active { cursor: grabbing; }

.instrument-main {
    display: flex;
    align-items: center;
    gap: 5px;
    margin-bottom: 4px;
}

/* Compact valve symbol node */
.valve-node {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2px 6px 0;
}

/* Compact pump symbol node */
.pump-node {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 2px 6px 0;
}

.valve-tag {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.42rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    margin-top: 2px;
    white-space: nowrap;
}

.sensor-disabled {
    opacity: 0.25;
    filter: grayscale(0.8);
    transition: opacity 0.2s, filter 0.2s;
}
</style>
