<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { state } from '../../services/store'

const props = defineProps({
    data: { type: Object, default: () => ({}) },
})

const FEED_CONFIG = {
    component_a:    { tag: 'V-101', name: 'Component A Source', rateKey: 'feed_rate_component_a', actuator: 'feed_component_a' },
    component_b: { tag: 'V-102', name: 'Component B Source', rateKey: 'feed_rate_component_b', actuator: 'feed_component_b' },
    solvent:  { tag: 'V-103', name: 'Solvent Source', rateKey: 'feed_rate_solvent', actuator: 'feed_solvent' },
}

const config = computed(() => FEED_CONFIG[props.data.feedType] || FEED_CONFIG.component_a)

const isFlowing = computed(() => state.simulation_running && state[config.value.rateKey] > 0.001)

const statusColor = computed(() => {
    if (state.phase === 'RUNAWAY_ALARM') return '#ef4444'
    if (state.actuator_overrides?.[config.value.actuator]) return '#f97316'
    if (isFlowing.value) return '#9ca3af'
    return '#52525b'
})
</script>

<template>
  <div class="feed-node">
    <Handle type="source" :position="Position.Bottom" />

        <div class="pid-node-card feed-box" :style="{ borderColor: statusColor }">
            <div class="pid-node-head">
                <span class="pid-node-tag">{{ config.tag }}</span>
                <span class="pid-node-status" :style="{ background: statusColor }"></span>
      </div>
            <div class="feed-main">
                <svg class="pid-node-symbol" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                    <!-- Open-top cylindrical tank -->
                    <path d="M2 4 L2 11 Q7 13 12 11 L12 4" />
                    <path d="M2 4 Q7 6 12 4" />
                    <path d="M4 8 Q7 9.5 10 8" opacity="0.5" />
                </svg>
                <div class="pid-node-name">{{ config.name }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.feed-node { cursor: grab; }
.feed-node:active { cursor: grabbing; }

.feed-main {
    display: flex;
    align-items: center;
        gap: 5px;
}
</style>
