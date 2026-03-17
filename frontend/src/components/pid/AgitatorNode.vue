<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { state } from '../../services/store'

const rpm = computed(() => (state.agitator_speed_rpm || 0).toFixed(0))

const statusColor = computed(() => {
    if (state.phase === 'RUNAWAY_ALARM') return '#ef4444'
    if (!state.simulation_running) return '#52525b'
    return '#6b7280'
})
</script>

<template>
  <div class="agitator-node">
    <Handle type="source" :position="Position.Left" />

    <div class="pid-node-card agitator-box" :style="{ borderColor: statusColor }">
      <div class="pid-node-head">
        <span class="pid-node-tag">M-101</span>
        <span class="pid-node-status" :style="{ background: statusColor }"></span>
      </div>
      <div class="agitator-main">
        <svg class="pid-node-symbol" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M7 2v10M3 5l4 2 4-2M3 9l4-2 4 2" />
        </svg>
        <div class="pid-node-name">Agitator</div>
      </div>
      <div class="pid-node-value">
        <span class="pid-node-value-num">{{ rpm }}</span>
        <span class="pid-node-value-unit">rpm</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agitator-node { cursor: grab; }
.agitator-node:active { cursor: grabbing; }

.agitator-main {
    display: flex;
    align-items: center;
  gap: 5px;
}
</style>
