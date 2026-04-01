<script setup>
import { computed } from 'vue'

const props = defineProps({
    phase: { type: String, required: true }
})

const phaseLabel = computed(() => (props.phase || 'IDLE').replace(/_/g, ' '))
const phaseTone = computed(() => {
    const phase = (props.phase || '').toUpperCase()
    if (phase === 'RUNAWAY_ALARM') return 'alarm'
    if (phase === 'HEATING' || phase === 'EXOTHERM') return 'hot'
    if (phase === 'COOLING') return 'cool'
    if (phase === 'CHARGING' || phase === 'DISCHARGING') return 'active'
    return 'idle'
})
</script>

<template>
    <span class="phase-badge" :class="`tone-${phaseTone}`">{{ phaseLabel }}</span>
</template>

<style scoped>
.phase-badge {
    display: inline-flex;
    align-items: center;
    min-height: 30px;
    padding: 0 12px;
    border-radius: 999px;
    font-size: 0.56rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    white-space: nowrap;
    border: 1px solid transparent;
    background: rgba(15, 22, 28, 0.9);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.tone-idle {
    border-color: rgba(93, 112, 123, 0.45);
    color: var(--text-muted);
}

.tone-active {
    border-color: rgba(142, 162, 176, 0.55);
    color: var(--accent-primary);
    background: rgba(142, 162, 176, 0.1);
}

.tone-hot {
    border-color: rgba(227, 162, 59, 0.55);
    color: var(--accent-warning);
    background: rgba(227, 162, 59, 0.08);
}

.tone-cool {
    border-color: rgba(165, 183, 195, 0.55);
    color: var(--sensor-level);
    background: rgba(165, 183, 195, 0.1);
}

.tone-alarm {
    border-color: rgba(239, 99, 92, 0.6);
    background: rgba(239, 99, 92, 0.14);
    color: #ffd5d2;
    animation: pulse 0.6s infinite alternate;
}

@keyframes pulse {
    to {
        box-shadow: 0 0 0 1px rgba(239, 99, 92, 0.18), 0 0 16px rgba(239, 99, 92, 0.18);
    }
}
</style>
