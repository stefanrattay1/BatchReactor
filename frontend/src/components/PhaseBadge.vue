<script setup>
defineProps({
    phase: { type: String, required: true }
})
</script>

<template>
    <span class="phase-badge" :class="'phase-' + phase">{{ phase }}</span>
</template>

<style scoped>
.phase-badge {
    padding: 2px 8px;
    border-radius: 1px;
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    white-space: nowrap;
    border: 1px solid transparent;
    background: transparent;
}
.phase-IDLE { border-color: var(--text-muted); color: var(--text-muted); }
.phase-CHARGING { border-color: var(--accent-primary); color: var(--accent-primary); }
.phase-HEATING { border-color: var(--accent-warning); color: var(--accent-warning); }
.phase-EXOTHERM { border-color: var(--accent-danger); color: var(--accent-danger); animation: pulse 0.5s infinite alternate; }
.phase-COOLING { border-color: var(--sensor-level); color: var(--sensor-level); }
.phase-DISCHARGING { border-color: var(--accent-success); color: var(--accent-success); }
.phase-RUNAWAY_ALARM {
    border-color: var(--accent-danger);
    background: var(--accent-danger);
    color: white;
    animation: pulse 0.3s infinite alternate;
}

@keyframes pulse { to { opacity: 0.5; } }
</style>
