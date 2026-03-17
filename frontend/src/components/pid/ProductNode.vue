<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { state } from '../../services/store'

const massKg = computed(() => state.mass_total_kg.toFixed(1))

const statusColor = computed(() => {
    if (state.phase === 'RUNAWAY_ALARM') return '#ef4444'
    if (state.mass_total_kg > 1) return '#9ca3af'
    return '#52525b'
})
</script>

<template>
  <div class="product-node">
    <Handle type="target" :position="Position.Top" />

    <div class="pid-node-card product-box" :style="{ borderColor: statusColor }">
      <div class="pid-node-head">
        <span class="pid-node-tag">P-201</span>
        <span class="pid-node-status" :style="{ background: statusColor }"></span>
      </div>

      <div class="product-main">
        <svg class="pid-node-symbol" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
          <!-- Sealed drum / receiver vessel -->
          <path d="M3 3 Q7 1 11 3 L11 11 Q7 13 3 11 Z" />
          <path d="M3 3 Q7 5 11 3" />
        </svg>
        <div>
          <div class="pid-node-name">Product</div>
          <div class="pid-node-sub">Outlet</div>
        </div>
      </div>

      <div class="pid-node-value">
        <span class="pid-node-value-num">{{ massKg }}</span>
        <span class="pid-node-value-unit">kg</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.product-node {
    cursor: pointer;
}

.product-box {
    min-width: 96px;
}

.product-main {
    display: flex;
    align-items: center;
    gap: 5px;
}
</style>
