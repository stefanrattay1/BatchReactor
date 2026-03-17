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
    <!-- System identity block -->
    <div class="sys-id">
      <span class="sys-name">REACTOR DIGITAL TWIN</span>
      <span class="sys-sub">BATCH CONTROL SYSTEM</span>
    </div>

    <PhaseBadge :phase="phase" />
    <span v-if="fakeSensorsEnabled" class="fake-badge">SIM</span>
    <span class="step-name">{{ stepName }}</span>

    <div class="divider"></div>

    <!-- Primary controls -->
    <div class="btn-group">
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

    <!-- Function keys -->
    <div class="btn-group">
      <button class="btn btn-fn" @click="openSensorManager">SENSORS</button>
      <button class="btn btn-fn" @click="emit('open-config')">CONFIG</button>
      <button class="btn btn-fn" @click="emit('open-batch')">FULL SIM</button>
      <button class="btn btn-fn" @click="emit('open-history')">HISTORY</button>
    </div>

    <div class="divider"></div>

    <button class="btn btn-toggle" :class="{ active: fakeSensorsEnabled }" @click="toggleFakeSensors"
            title="Toggle simulated sensor noise">
      {{ fakeSensorsEnabled ? 'FAKE' : 'TRUE' }}
    </button>
    <label class="tick-label">DT
      <select class="tick-select" :value="tickInterval" @change="handleTickChange">
        <option v-for="opt in tickOptions" :key="opt" :value="opt">{{ opt }}s</option>
      </select>
    </label>

    <div class="spacer"></div>

    <!-- Connection status -->
    <div class="conn-block" :class="{ ok: isConnected, err: !isConnected }">
      <span class="conn-sq"></span>
      <span class="conn-text">{{ isConnected ? 'ONLINE' : 'OFFLINE' }}</span>
    </div>
  </div>
</template>

<style scoped>
.header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 14px;
    height: 40px;
    background: #1a1a1a;
    border-bottom: 2px solid #2e2e2e;
    flex-shrink: 0;
    flex-wrap: nowrap;
    overflow: hidden;
}

/* System identity */
.sys-id {
    display: flex;
    flex-direction: column;
    line-height: 1;
    flex-shrink: 0;
    margin-right: 4px;
}
.sys-name {
    font-size: 0.72rem;
    font-weight: 700;
    color: var(--accent-primary);
    letter-spacing: 0.08em;
    white-space: nowrap;
}
.sys-sub {
    font-size: 0.48rem;
    color: var(--text-muted);
    letter-spacing: 0.1em;
    white-space: nowrap;
    margin-top: 1px;
}

.fake-badge {
    padding: 1px 5px;
    border-radius: 1px;
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: uppercase;
    background: var(--accent-warning);
    color: #111;
    flex-shrink: 0;
}

.step-name {
    font-size: 0.65rem;
    color: var(--text-muted);
    font-family: var(--font-mono);
    white-space: nowrap;
}

.spacer { flex: 1; }

.divider {
    width: 1px;
    height: 22px;
    background: #3a3a3a;
    flex-shrink: 0;
}

.btn-group { display: flex; gap: 2px; align-items: center; }

/* Base button — DCS function key style */
.btn {
    padding: 3px 9px;
    border: 1px solid #4a4a4a;
    border-radius: 1px;
    font-size: 0.6rem;
    font-weight: 700;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    white-space: nowrap;
    background: #2a2a2a;
    color: #a0a0a0;
    transition: background 0.1s, color 0.1s;
}
.btn:hover { background: #333; color: #e8e8e8; }
.btn:disabled { opacity: 0.3; cursor: not-allowed; }

/* Primary control buttons — bordered color style */
.btn-start {
    border-color: #22c55e;
    color: #22c55e;
    background: rgba(34, 197, 94, 0.08);
}
.btn-start:hover:not(:disabled) { background: rgba(34, 197, 94, 0.2); }

.btn-stop {
    border-color: #ef4444;
    color: #ef4444;
    background: rgba(239, 68, 68, 0.08);
}
.btn-stop:hover:not(:disabled) { background: rgba(239, 68, 68, 0.2); }

.btn-reset {
    border-color: #f97316;
    color: #f97316;
    background: rgba(249, 115, 22, 0.08);
}
.btn-reset:hover:not(:disabled) { background: rgba(249, 115, 22, 0.2); }

/* Function key buttons */
.btn-fn {
    border-color: #3a3a3a;
    color: #808080;
    background: #222;
}
.btn-fn:hover { background: #2e2e2e; color: #c0c0c0; }

.btn-toggle {
    border-color: #3a3a3a;
    background: #222;
    color: #606060;
    font-size: 0.55rem;
}
.btn-toggle.active {
    border-color: var(--dcs-warning);
    color: var(--dcs-warning);
    background: rgba(245, 158, 11, 0.1);
}

.tick-label {
    font-size: 0.55rem;
    color: var(--text-muted);
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 3px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.tick-select {
    background: #181818;
    border: 1px solid #3a3a3a;
    color: var(--text-primary);
    font-size: 0.6rem;
    padding: 2px 4px;
    border-radius: 1px;
    cursor: pointer;
    font-family: var(--font-mono);
}
.tick-select:focus { outline: none; border-color: var(--accent-primary); }

/* Connection status block */
.conn-block {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 2px 7px;
    border: 1px solid #3a3a3a;
    border-radius: 1px;
    background: #1e1e1e;
    flex-shrink: 0;
}
.conn-sq {
    width: 6px;
    height: 6px;
    border-radius: 1px;
    flex-shrink: 0;
}
.conn-block.ok .conn-sq { background: var(--accent-success); }
.conn-block.err .conn-sq { background: var(--accent-danger); animation: pulse-sq 1s infinite; }
@keyframes pulse-sq { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }

.conn-text {
    font-size: 0.58rem;
    font-weight: 700;
    letter-spacing: 0.06em;
}
.conn-block.ok .conn-text { color: var(--accent-success); }
.conn-block.err .conn-text { color: var(--accent-danger); }
</style>
