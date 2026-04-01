<script setup>
import { computed } from 'vue'
import { state } from '../services/store'
import { formatElapsed } from '../utils/formatValue'

const runState = computed(() => state.simulation_running ? 'BATCH ACTIVE' : 'STANDBY')
const phaseLabel = computed(() => (state.phase || 'IDLE').replace(/_/g, ' '))
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
    <div class="status-stamp">
      <div class="stamp-label">Unit Status</div>
      <div class="stamp-value">{{ runState }}</div>
      <div class="stamp-copy">{{ phaseLabel }}</div>
    </div>

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
  gap: 8px;
  padding: 10px 16px;
  background: linear-gradient(180deg, rgba(15, 22, 28, 0.98) 0%, rgba(10, 16, 21, 0.98) 100%);
  border-top: 1px solid rgba(73, 96, 110, 0.45);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
    flex-shrink: 0;
    overflow-x: auto;
}

.status-stamp {
  display: grid;
  align-content: center;
  gap: 2px;
  min-width: 118px;
  padding: 6px 10px;
  border-radius: 14px;
  border: 1px solid rgba(73, 96, 110, 0.45);
  background: linear-gradient(180deg, rgba(18, 26, 33, 0.98) 0%, rgba(10, 15, 20, 0.98) 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.stamp-label {
  font-size: 0.44rem;
  color: var(--text-faint);
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.stamp-value {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.08em;
}

.stamp-copy {
  font-size: 0.56rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.kpi-box {
  position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
  background: linear-gradient(180deg, rgba(16, 23, 30, 0.98) 0%, rgba(10, 15, 20, 0.98) 100%);
  border: 1px solid rgba(73, 96, 110, 0.42);
  border-radius: 14px;
  padding: 8px 12px 7px;
  min-width: 74px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
  overflow: hidden;
}

.kpi-box::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: var(--box-accent, var(--accent-primary));
}

.kpi-label {
  font-size: 0.46rem;
    font-weight: 700;
  color: var(--text-faint);
  letter-spacing: 0.14em;
    text-transform: uppercase;
    line-height: 1;
  margin-bottom: 4px;
}

.kpi-value {
  font-size: 1rem;
    font-weight: 700;
    font-family: var(--font-mono);
    color: var(--text-primary);
    line-height: 1.1;
}

.kpi-unit {
    font-size: 0.45rem;
    color: var(--text-muted);
  letter-spacing: 0.08em;
  margin-top: 2px;
}

.kpi-box.temp { --box-accent: var(--sensor-temp); }
.kpi-box.conv { --box-accent: var(--sensor-flow); }
.kpi-box.dtdt { --box-accent: var(--accent-warning); }
.kpi-box.press { --box-accent: var(--sensor-pressure); }
.kpi-box.visc { --box-accent: var(--sensor-level); }
.kpi-box.elapsed { --box-accent: var(--accent-primary); }

.kpi-box.temp .kpi-value { color: var(--sensor-temp); }
.kpi-box.conv .kpi-value { color: var(--sensor-flow); }
.kpi-box.press .kpi-value { color: var(--sensor-pressure); }
.kpi-box.visc .kpi-value { color: var(--sensor-level); }
.kpi-box.elapsed .kpi-value { color: var(--accent-primary); }

.status-divider {
    width: 1px;
  height: 38px;
  background: linear-gradient(180deg, transparent, rgba(73, 96, 110, 0.65), transparent);
    flex-shrink: 0;
  margin: 0 2px;
}
</style>
