<script setup>
import { computed, ref } from 'vue'
import { state } from '../services/store'
import { sendCommand, setTickInterval } from '../services/api'
import { sensorConfig } from '../services/sensorConfig'
import PhaseBadge from './PhaseBadge.vue'

const phase = computed(() => state.phase)
const stepName = computed(() => state.recipe_step)
const isRunning = computed(() => state.simulation_running)
const isConnected = computed(() => state.connected)
const commandPending = ref(false)
const activeConfigName = computed(() => {
  const raw = state.active_config_file || 'default'
  const file = raw.split(/[/\\]/).pop() || raw
  return file.replace(/\.(json|ya?ml)$/i, '').replace(/_/g, ' ')
})
const stepLabel = computed(() => stepName.value && stepName.value !== 'DONE' ? stepName.value : 'Awaiting batch command')

const canStart = computed(() => isConnected.value && !commandPending.value && !isRunning.value && phase.value !== 'RUNAWAY_ALARM')
const canStop = computed(() => isConnected.value && !commandPending.value && isRunning.value)
const canReset = computed(() => {
  const resetAllowed = phase.value === 'RUNAWAY_ALARM' || phase.value === 'DISCHARGING' || phase.value === 'IDLE'
  return isConnected.value && !commandPending.value && resetAllowed
})

async function runCommand(cmd) {
  if (commandPending.value) return
  commandPending.value = true
  try {
    await sendCommand(cmd)
  } finally {
    setTimeout(() => {
      commandPending.value = false
    }, 250)
  }
}

function start() {
  if (!canStart.value) return
  runCommand('START')
}

function stop() {
  if (!canStop.value) return
  runCommand('STOP')
}

function reset() {
  if (!canReset.value) return
  runCommand('RESET')
}

function openSensorManager() { sensorConfig.showManager = true }

const emit = defineEmits(['open-config', 'open-batch', 'open-history'])

const tickInterval = computed(() => state.tick_interval)
const tickOptions = [0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
function handleTickChange(e) { setTickInterval(parseFloat(e.target.value)) }

const fakeSensorsEnabled = computed(() => state.fake_sensors_enabled)
async function toggleFakeSensors() {
    try { await fetch('/api/fake_sensors/toggle', { method: 'POST' }) }
    catch (e) { console.error(e) }
}
</script>

<template>
  <div class="header">
    <div class="sys-id">
      <span class="sys-kicker">ISA-88 Batch Cell</span>
      <span class="sys-name">Reactor Digital Twin</span>
    </div>

    <div class="header-phase">
      <PhaseBadge :phase="phase" />
      <div class="header-copy">
        <span class="copy-kicker">Current Operation</span>
        <span class="step-name">{{ stepLabel }}</span>
      </div>
    </div>

    <div class="header-meta">
      <span class="meta-chip">CFG {{ activeConfigName }}</span>
      <span v-if="fakeSensorsEnabled" class="meta-chip meta-chip-warn">Noise On</span>
    </div>

    <div class="divider"></div>

    <div class="btn-group btn-group-primary">
      <button class="btn btn-start" :disabled="!canStart" @click="start" title="Start batch">
        &#9654; START
      </button>
      <button class="btn btn-stop" :disabled="!canStop" @click="stop" title="Stop batch">
        &#9632; STOP
      </button>
      <button class="btn btn-reset"
              :disabled="!canReset"
              title="Reset simulation"
              @click="reset">
        &#8634; RESET
      </button>
    </div>

    <div class="divider"></div>

    <div class="btn-group">
      <button class="btn btn-fn" @click="openSensorManager">SENSORS</button>
      <button class="btn btn-fn" @click="emit('open-config')">CONFIG</button>
      <button class="btn btn-fn" @click="emit('open-batch')">BATCH RUN</button>
      <button class="btn btn-fn" @click="emit('open-history')">HISTORY</button>
    </div>

    <div class="divider"></div>

    <button class="btn btn-toggle" :class="{ active: fakeSensorsEnabled }" @click="toggleFakeSensors"
            title="Toggle simulated sensor noise">
      {{ fakeSensorsEnabled ? 'NOISE ON' : 'NOISE OFF' }}
    </button>
    <label class="tick-label">Scan
      <select class="tick-select" :value="tickInterval" @change="handleTickChange">
        <option v-for="opt in tickOptions" :key="opt" :value="opt">{{ opt }}s</option>
      </select>
    </label>

    <div class="spacer"></div>

    <div class="conn-block" :class="{ ok: isConnected, err: !isConnected }">
      <span class="conn-sq"></span>
    <div class="conn-copy">
    <span class="conn-label">Gateway</span>
    <span class="conn-text">{{ isConnected ? 'ONLINE' : 'OFFLINE' }}</span>
    </div>
    </div>
  </div>
</template>

<style scoped>
.header {
    display: flex;
    align-items: center;
  gap: 12px;
  padding: 10px 16px;
  min-height: 58px;
  background: linear-gradient(180deg, rgba(17, 24, 31, 0.98) 0%, rgba(13, 19, 25, 0.98) 100%);
  border-bottom: 1px solid rgba(73, 96, 110, 0.45);
  box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.03);
    flex-shrink: 0;
  flex-wrap: wrap;
}

.sys-id {
    display: flex;
    flex-direction: column;
  gap: 2px;
    flex-shrink: 0;
  min-width: 170px;
}
.sys-kicker {
  font-size: 0.46rem;
  color: var(--text-faint);
  letter-spacing: 0.18em;
  text-transform: uppercase;
}
.sys-name {
  font-size: 1rem;
    font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.04em;
    white-space: nowrap;
  font-family: var(--font-display);
}

.header-phase {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 260px;
}

.header-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.copy-kicker {
  font-size: 0.46rem;
  color: var(--text-faint);
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.header-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(73, 96, 110, 0.45);
  background: rgba(15, 22, 28, 0.9);
  color: var(--text-muted);
  font-size: 0.54rem;
    font-weight: 700;
    text-transform: uppercase;
  letter-spacing: 0.12em;
}

.meta-chip-warn {
  border-color: rgba(227, 162, 59, 0.55);
  color: var(--accent-warning);
  background: rgba(227, 162, 59, 0.08);
}

.step-name {
  font-size: 0.72rem;
  color: var(--text-secondary);
    font-family: var(--font-mono);
    white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 280px;
}

.spacer { flex: 1; }

.divider {
    width: 1px;
  align-self: stretch;
  background: linear-gradient(180deg, transparent, rgba(73, 96, 110, 0.65), transparent);
    flex-shrink: 0;
}

.btn-group {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid rgba(73, 96, 110, 0.45);
  border-radius: 10px;
  font-size: 0.58rem;
    font-weight: 700;
    cursor: pointer;
    text-transform: uppercase;
  letter-spacing: 0.12em;
    white-space: nowrap;
  background: linear-gradient(180deg, rgba(24, 35, 44, 0.98) 0%, rgba(14, 20, 25, 0.98) 100%);
  color: var(--text-muted);
  transition: background 0.15s, color 0.15s, border-color 0.15s, transform 0.15s;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
.btn:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(37, 45, 52, 1) 0%, rgba(18, 24, 29, 1) 100%);
  color: var(--text-primary);
  border-color: rgba(92, 105, 115, 0.7);
  transform: translateY(-1px);
}
.btn:disabled { opacity: 0.3; cursor: not-allowed; }

.btn-start {
  border-color: rgba(91, 199, 122, 0.65);
  color: var(--accent-success);
  background: rgba(91, 199, 122, 0.08);
}
.btn-start:hover:not(:disabled) { background: rgba(91, 199, 122, 0.16); }

.btn-stop {
  border-color: rgba(239, 99, 92, 0.6);
  color: var(--accent-danger);
  background: rgba(239, 99, 92, 0.08);
}
.btn-stop:hover:not(:disabled) { background: rgba(239, 99, 92, 0.16); }

.btn-reset {
  border-color: rgba(241, 136, 58, 0.65);
  color: var(--dcs-maintenance);
  background: rgba(241, 136, 58, 0.08);
}
.btn-reset:hover:not(:disabled) { background: rgba(241, 136, 58, 0.16); }

.btn-fn {
  color: var(--text-secondary);
}

.btn-toggle {
  min-width: 108px;
  font-size: 0.52rem;
}
.btn-toggle.active {
  border-color: rgba(227, 162, 59, 0.6);
  color: var(--dcs-warning);
  background: rgba(227, 162, 59, 0.1);
}

.tick-label {
  height: 34px;
  padding: 0 10px;
  border-radius: 10px;
  border: 1px solid rgba(73, 96, 110, 0.45);
  background: rgba(14, 20, 25, 0.96);
  font-size: 0.52rem;
  color: var(--text-faint);
    font-weight: 700;
    display: flex;
    align-items: center;
  gap: 6px;
    text-transform: uppercase;
  letter-spacing: 0.16em;
}
.tick-select {
  min-width: 74px;
  height: 24px;
  background: var(--bg-input);
  border: 1px solid rgba(73, 96, 110, 0.45);
    color: var(--text-primary);
  font-size: 0.62rem;
  padding: 2px 6px;
  border-radius: 8px;
    cursor: pointer;
    font-family: var(--font-mono);
}
.tick-select:focus { outline: none; border-color: var(--accent-primary); }

.conn-block {
    display: flex;
    align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid rgba(73, 96, 110, 0.45);
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(20, 29, 37, 0.98) 0%, rgba(13, 19, 25, 0.98) 100%);
    flex-shrink: 0;
}
.conn-sq {
  width: 8px;
  height: 8px;
  border-radius: 2px;
    flex-shrink: 0;
}
.conn-block.ok .conn-sq { background: var(--accent-success); }
.conn-block.err .conn-sq { background: var(--accent-danger); animation: pulse-sq 1s infinite; }
@keyframes pulse-sq { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }

.conn-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.conn-label {
  font-size: 0.4rem;
  color: var(--text-faint);
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.conn-text {
  font-size: 0.6rem;
    font-weight: 700;
  letter-spacing: 0.1em;
}
.conn-block.ok .conn-text { color: var(--accent-success); }
.conn-block.err .conn-text { color: var(--accent-danger); }

@media (max-width: 1500px) {
  .header-meta {
    display: none;
  }
}

@media (max-width: 1100px) {
  .divider,
  .spacer {
    display: none;
  }

  .step-name {
    max-width: 220px;
  }
}
</style>
