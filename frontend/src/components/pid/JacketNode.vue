<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { state } from '../../services/store'

const jacketC = computed(() => (state.jacket_temperature_K - 273.15).toFixed(0))
const mode = computed(() => state.actuator_overrides?.jacket_temp ? 'MAN' : 'AUTO')
const isManual = computed(() => !!state.actuator_overrides?.jacket_temp)

const statusColor = computed(() => {
    if (state.phase === 'RUNAWAY_ALARM') return '#ef4444'
    if (isManual.value) return '#f97316'
    if (!state.simulation_running) return '#52525b'
    return '#6b7280'
})
</script>

<template>
  <div class="jacket-node">
    <Handle type="source" :position="Position.Right" />

        <div class="pid-node-card jacket-box" :style="{ borderColor: statusColor }">
            <div class="pid-node-head">
                <span class="pid-node-tag">E-101</span>
                <span class="pid-node-status" :style="{ background: statusColor }"></span>
      </div>
            <div class="jacket-main">
                <svg class="pid-node-symbol" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M2 3h10v8H2zM3.5 10.5l2-2 1.5 1.5 2-2 1.5 1.5" />
                </svg>
                <div class="pid-node-name">Jacket Loop</div>
      </div>
            <div class="pid-node-value">
                <span class="pid-node-value-num">{{ jacketC }}</span>
                <span class="pid-node-value-unit">°C</span>
            </div>
            <div class="mode-tag" :class="{ manual: isManual }">{{ mode }}</div>
    </div>
  </div>
</template>

<style scoped>
.jacket-node { cursor: grab; }
.jacket-node:active { cursor: grabbing; }

.jacket-main {
    display: flex;
    align-items: center;
    gap: 5px;
}

.mode-tag {
    font-size: 0.48rem;
    font-weight: 700;
    padding: 1px 4px;
    border-radius: 1px;
    background: #2a2a2a;
    color: var(--text-muted);
    display: inline-block;
    letter-spacing: 0.06em;
    border: 1px solid #3a3a3a;
}
.mode-tag.manual {
    background: var(--dcs-maintenance);
    color: #111;
    border-color: var(--dcs-maintenance);
}
</style>
