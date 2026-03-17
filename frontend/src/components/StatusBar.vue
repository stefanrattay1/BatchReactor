<script setup>
import { computed } from 'vue'
import { state } from '../services/store'
import { formatElapsed } from '../utils/formatValue'

const temp = computed(() => state.temperature_C.toFixed(1))
const conv = computed(() => (state.conversion * 100).toFixed(1))
const dtdt = computed(() => {
    const v = state.dt_dt
    return (v >= 0 ? '+' : '') + v.toFixed(2)
})
const dtdtColor = computed(() => {
    const v = Math.abs(state.dt_dt)
    if (v > 1.5) return 'var(--accent-danger)'
    if (v > 0.8) return 'var(--accent-warning)'
    if (v > 0.3) return '#eab308'
    return 'var(--accent-success)'
})
const pressure = computed(() => state.pressure_bar.toFixed(3))
const viscosityCap = computed(() => state.viscosity_max ?? 1e6)
const viscosity = computed(() =>
    state.viscosity_Pas >= viscosityCap.value ? 'GEL' : state.viscosity_Pas.toFixed(1)
)
const elapsed = computed(() => formatElapsed(state.recipe_elapsed_s))
</script>

<template>
  <div class="status-footer">
    <div class="kpi-box temp">
      <div class="kpi-label">TEMP</div>
      <div class="kpi-value">{{ temp }}</div>
      <div class="kpi-unit">°C</div>
    </div>
    <div class="kpi-box conv">
      <div class="kpi-label">CONV</div>
      <div class="kpi-value">{{ conv }}</div>
      <div class="kpi-unit">%</div>
    </div>
    <div class="kpi-box dtdt">
      <div class="kpi-label">dT/dt</div>
      <div class="kpi-value" :style="{ color: dtdtColor }">{{ dtdt }}</div>
      <div class="kpi-unit">°C/s</div>
    </div>
    <div class="kpi-box press">
      <div class="kpi-label">PRESS</div>
      <div class="kpi-value">{{ pressure }}</div>
      <div class="kpi-unit">bar</div>
    </div>
    <div class="kpi-box visc">
      <div class="kpi-label">VISC</div>
      <div class="kpi-value">{{ viscosity }}</div>
      <div class="kpi-unit">Pa·s</div>
    </div>
    <div class="status-divider"></div>
    <div class="kpi-box elapsed">
      <div class="kpi-label">ELAPSED</div>
      <div class="kpi-value">{{ elapsed }}</div>
      <div class="kpi-unit">hh:mm:ss</div>
    </div>
  </div>
</template>

<style scoped>
.status-footer {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 14px;
    background: #1a1a1a;
    border-top: 2px solid #2e2e2e;
    flex-shrink: 0;
    overflow-x: auto;
}

/* DCS data box — recessed rectangular tag display */
.kpi-box {
    display: flex;
    flex-direction: column;
    align-items: center;
    background: var(--bg-data);
    border: 1px solid #2e2e2e;
    border-radius: 1px;
    padding: 3px 10px;
    min-width: 68px;
}

.kpi-label {
    font-size: 0.48rem;
    font-weight: 700;
    color: var(--text-muted);
    letter-spacing: 0.1em;
    text-transform: uppercase;
    line-height: 1;
    margin-bottom: 2px;
}

.kpi-value {
    font-size: 0.95rem;
    font-weight: 700;
    font-family: var(--font-mono);
    color: var(--text-primary);
    line-height: 1.1;
}

.kpi-unit {
    font-size: 0.45rem;
    color: var(--text-muted);
    letter-spacing: 0.06em;
    margin-top: 1px;
}

/* Per-metric value colors */
.kpi-box.temp .kpi-value { color: var(--sensor-temp); }
.kpi-box.conv .kpi-value { color: var(--sensor-flow); }
.kpi-box.press .kpi-value { color: var(--sensor-pressure); }
.kpi-box.visc .kpi-value { color: var(--sensor-level); }
.kpi-box.elapsed .kpi-value { color: var(--accent-primary); }

.status-divider {
    width: 1px;
    height: 30px;
    background: #3a3a3a;
    flex-shrink: 0;
    margin: 0 4px;
}
</style>
