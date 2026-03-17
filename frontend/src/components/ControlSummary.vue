<script setup>
import { computed } from 'vue'
import { state } from '../services/store'
import { INPUTS } from '../constants'

const emit = defineEmits(['select-equipment'])

const actuators = computed(() => {
    return Object.entries(INPUTS)
        .filter(([, v]) => v.actuator)
        .map(([id, input]) => {
            const val = state[input.key]
            const isOverride = !!state.actuator_overrides?.[input.actuator]
            let display = '--'
            if (typeof val === 'number') {
                if (input.unit === 'K') display = (val - 273.15).toFixed(0) + '°C'
                else if (input.unit === 'kg/s') display = val.toFixed(3)
                else display = val.toFixed(2)
            }
            return { id, ...input, display, isOverride }
        })
})
</script>

<template>
  <div class="control-summary">
    <div class="section-title">Controls</div>
    <div class="actuator-list">
      <div v-for="act in actuators" :key="act.id"
           class="actuator-row"
           @click="emit('select-equipment', act.id)">
        <span class="act-icon" :style="{ color: act.color }">{{ act.icon }}</span>
        <span class="act-name">{{ act.name }}</span>
        <span class="act-value">{{ act.display }}</span>
        <span class="act-mode" :class="{ manual: act.isOverride }">
          {{ act.isOverride ? 'MAN' : 'AUTO' }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.control-summary {
    padding: 12px;
    border-top: 1px solid var(--border-subtle);
}

.section-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 8px;
}

.actuator-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.actuator-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 6px;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
}
.actuator-row:hover {
    background: var(--equip-bg);
}

.act-icon {
    font-weight: 700;
    font-size: 0.8rem;
    width: 16px;
    text-align: center;
    flex-shrink: 0;
}

.act-name {
    font-size: 0.7rem;
    color: var(--text-secondary);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.act-value {
    font-size: 0.7rem;
    font-weight: 600;
    font-family: var(--font-mono);
    color: var(--text-primary);
    flex-shrink: 0;
}

.act-mode {
    font-size: 0.55rem;
    font-weight: 700;
    padding: 1px 4px;
    border-radius: 3px;
    background: var(--bg-panel);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
    flex-shrink: 0;
}
.act-mode.manual {
    background: var(--dcs-maintenance);
    color: #000;
}
</style>
