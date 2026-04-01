<script setup>
import { computed, ref } from 'vue'
import { state, actions } from '../services/store'
import { INPUTS } from '../constants'
import { sensorConfig, getSparklinePoints, isInAlarm, toggleSensor } from '../services/sensorConfig'
import { hideNode as pidHideNode } from '../services/pidVisibility'

const props = defineProps({
    equipmentId: { type: String, default: null },
})

const emit = defineEmits(['close'])

// Map equipment IDs to INPUTS keys and additional metadata
const EQUIP_MAP = {
    reactor: { inputKey: 'temperature', tag: 'R-101', name: 'Reactor Vessel',
               sensors: ['temperature', 'pressure', 'product'] },
    component_a: { inputKey: 'component_a', tag: 'V-101', name: 'Component A Feed' },
    component_a_valve: { inputKey: 'component_a', tag: 'XV-101', name: 'Component A Inlet Valve' },
    component_a_pump: { inputKey: 'component_a', tag: 'P-101', name: 'Component A Pump' },
    component_a_flow: { inputKey: 'component_a', tag: 'FT-101', name: 'Component A Flow Sensor' },
    component_b: { inputKey: 'component_b', tag: 'V-102', name: 'Component B Feed' },
    component_b_valve: { inputKey: 'component_b', tag: 'XV-102', name: 'Component B Inlet Valve' },
    component_b_pump: { inputKey: 'component_b', tag: 'P-102', name: 'Component B Pump' },
    component_b_flow: { inputKey: 'component_b', tag: 'FT-102', name: 'Component B Flow Sensor' },
    solvent: { inputKey: 'solvent', tag: 'V-103', name: 'Solvent Feed' },
    solvent_valve: { inputKey: 'solvent', tag: 'XV-103', name: 'Solvent Inlet Valve' },
    solvent_pump: { inputKey: 'solvent', tag: 'P-103', name: 'Solvent Pump' },
    solvent_flow: { inputKey: 'solvent', tag: 'FT-103', name: 'Solvent Flow Sensor' },
    jacket: { inputKey: 'jacket', tag: 'E-101', name: 'Jacket / Cooling' },
    agitator: { inputKey: null, tag: 'M-101', name: 'Agitator Motor' },
    temp_sensor: { inputKey: 'temperature', tag: 'TT-101', name: 'Reactor Temperature Sensor' },
    pressure_sensor: { inputKey: 'pressure', tag: 'PT-101', name: 'Reactor Pressure Sensor' },
    level_sensor: { inputKey: null, tag: 'LT-101', name: 'Reactor Fill Level Sensor' },
    drain_valve: { inputKey: 'product', tag: 'XV-301', name: 'Drain Valve' },
    drain_pump: { inputKey: 'product', tag: 'P-301', name: 'Drain Pump' },
    drain_flow: { inputKey: 'product', tag: 'FT-301', name: 'Drain Flow Sensor' },
    product: { inputKey: 'product', tag: 'TK-201', name: 'Product Tank' },
}

// Dynamic sensor node: id starts with "sensor_"
const isDynamic = computed(() => props.equipmentId?.startsWith('sensor_'))
const dynamicSensorId = computed(() => isDynamic.value ? props.equipmentId.replace('sensor_', '') : null)
const dynamicSensor = computed(() => {
    if (!dynamicSensorId.value) return null
    return sensorConfig.availableNodes.find(n => n.id === dynamicSensorId.value) || null
})

// Reverse-lookup: map ISA tag prefixes to INPUTS keys for config-driven nodes
const TAG_TO_INPUT = {
    'XV-101': 'component_a', 'P-101': 'component_a', 'FT-101': 'component_a',
    'XV-102': 'component_b', 'P-102': 'component_b', 'FT-102': 'component_b',
    'XV-103': 'solvent', 'P-103': 'solvent', 'FT-103': 'solvent',
    'TT-101': 'temperature', 'PT-101': 'pressure', 'LT-101': null,
    'XV-301': 'product', 'P-301': 'product', 'FT-301': 'product',
    'HE-101': 'jacket', 'TT-201': 'jacket', 'P-201': 'jacket',
    'M-101': null, 'ST-101': null,
}

const equip = computed(() => {
    if (!props.equipmentId) return null
    if (isDynamic.value && dynamicSensor.value) {
        return {
            tag: dynamicSensor.value.tag || dynamicSensorId.value,
            name: dynamicSensor.value.name || 'Sensor',
            inputKey: null,
        }
    }
    // Legacy node IDs
    if (EQUIP_MAP[props.equipmentId]) return EQUIP_MAP[props.equipmentId]
    // Config-driven node IDs (e.g., "cm_XV-101", "feed_component_a")
    if (props.equipmentId.startsWith('cm_')) {
        const tag = props.equipmentId.slice(3)
        const inputKey = TAG_TO_INPUT[tag] ?? null
        // Find CM name from sensorConfig catalog
        const sensor = sensorConfig.availableNodes.find(n => n.tag === tag)
        return { tag, name: sensor?.name || tag, inputKey }
    }
    if (props.equipmentId.startsWith('feed_')) {
        const material = props.equipmentId.slice(5)
        const key = material === 'component_a' ? 'component_a' : material === 'component_b' ? 'component_b' : material === 'solvent' ? 'solvent' : null
        return { tag: `V-${material}`, name: `${material} Feed`, inputKey: key }
    }
    return null
})

// Can remove from canvas: everything except reactor
const canRemove = computed(() => props.equipmentId && props.equipmentId !== 'reactor')

function removeFromCanvas() {
    if (!props.equipmentId) return
    if (isDynamic.value && dynamicSensorId.value) {
        // Dynamic sensor: toggle off in sensorConfig only.
        // rebuildVisible() will drop it from the canvas automatically.
        // Do NOT add to pidVisibility.hiddenIds — that would block re-enabling.
        toggleSensor(dynamicSensorId.value)
    } else {
        // Static node: hide via pidVisibility so it can be restored later
        pidHideNode(props.equipmentId)
    }
    emit('close')
}

const input = computed(() => {
    if (!equip.value || !equip.value.inputKey) return null
    return INPUTS[equip.value.inputKey] || null
})

// All values to show for this equipment
const values = computed(() => {
    if (!props.equipmentId) return []

    if (props.equipmentId === 'reactor') {
        return [
            { label: 'Temperature', value: state.temperature_C.toFixed(1), unit: '°C', key: 'temperature_K', color: 'var(--sensor-temp)' },
            { label: 'Pressure', value: state.pressure_bar.toFixed(3), unit: 'bar', key: 'pressure_bar', color: 'var(--sensor-pressure)' },
            { label: 'Conversion', value: (state.conversion * 100).toFixed(1), unit: '%', key: 'conversion', color: 'var(--sensor-flow)' },
            { label: 'Fill Level', value: state.fill_pct.toFixed(0), unit: '%', key: 'fill_pct', color: 'var(--sensor-level)' },
            { label: 'Total Mass', value: state.mass_total_kg.toFixed(1), unit: 'kg', key: 'mass_total_kg', color: 'var(--text-secondary)' },
        ]
    }

    if (props.equipmentId === 'jacket') {
        return [
            { label: 'Jacket Temp', value: (state.jacket_temperature_K - 273.15).toFixed(1), unit: '°C', key: 'jacket_temperature_K', color: 'var(--dcs-warning)' },
            { label: 'Mode', value: state.actuator_overrides?.jacket_temp ? 'MANUAL' : 'AUTO', unit: '', color: state.actuator_overrides?.jacket_temp ? 'var(--dcs-maintenance)' : 'var(--dcs-normal)' },
        ]
    }

    if (props.equipmentId === 'level_sensor') {
        return [
            { label: 'Fill Level', value: state.fill_pct.toFixed(1), unit: '%', key: 'fill_pct', color: 'var(--sensor-level)' },
            { label: 'Permissive', value: state.fill_pct < 95 ? 'OK' : 'HI-HI', unit: '', color: state.fill_pct < 95 ? 'var(--dcs-normal)' : 'var(--dcs-alarm)' },
        ]
    }

    if (props.equipmentId === 'agitator') {
        return [
            { label: 'Speed', value: (state.agitator_speed_rpm || 0).toFixed(0), unit: 'rpm', key: 'agitator_speed_rpm', color: 'var(--sensor-speed)' },
        ]
    }

    if (input.value) {
        const val = state[input.value.key]
        let display = '--'
        if (typeof val === 'number') {
            if (input.value.unit === 'K') display = (val - 273.15).toFixed(1)
            else if (input.value.unit === 'kg/s') display = val.toFixed(4)
            else display = val.toFixed(2)
        }
        const unit = input.value.unit === 'K' ? '°C' : input.value.unit
        return [
            { label: input.value.name, value: display, unit, key: input.value.key, color: input.value.color },
        ]
    }

    // Dynamic sensor node: show live value from state
    if (isDynamic.value && dynamicSensor.value?.state_key) {
        const key = dynamicSensor.value.state_key
        const raw = state[key]
        let display = '--'
        const unit = dynamicSensor.value.unit || ''
        if (typeof raw === 'number') {
            if (unit === 'K') display = (raw - 273.15).toFixed(1)
            else if (unit === 'bar') display = raw.toFixed(3)
            else if (unit === 'kg/s') display = raw.toFixed(4)
            else display = raw.toFixed(2)
        }
        return [
            { label: dynamicSensor.value.name, value: display, unit: unit === 'K' ? '°C' : unit, key, color: 'var(--text-secondary)' },
        ]
    }

    return []
})

// Is this an actuator (can override)?
const isActuator = computed(() => input.value?.actuator != null)

// Override logic
const overrideVal = ref('')
const showConfirm = ref(false)

function requestOverride() {
    if (!overrideVal.value) return
    showConfirm.value = true
}

async function confirmOverride() {
    if (!input.value?.actuator) return
    try {
        await fetch('/api/actuator/override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                actuator: input.value.actuator,
                value: parseFloat(overrideVal.value),
            }),
        })
        actions.addLog(`Override Applied: ${equip.value.name} -> ${overrideVal.value}`, 'warn')
        overrideVal.value = ''
    } catch (e) {
        console.error(e)
    }
    showConfirm.value = false
}

function cancelConfirm() {
    showConfirm.value = false
}

async function clearOverride() {
    try {
        await fetch('/api/actuator/override', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ actuator: 'clear', value: 0 }),
        })
        actions.addLog('Override Cleared', 'success')
    } catch (e) {
        console.error(e)
    }
}

// Sparkline helper
function sparkline(key) {
    if (!key) return null
    // Try to find matching sensor ID
    const node = sensorConfig.availableNodes.find(n => n.state_key === key)
    if (!node) return null
    return getSparklinePoints(node.id, 0, 0, 120, 20)
}

function sensorAlarm(key) {
    const node = sensorConfig.availableNodes.find(n => n.state_key === key)
    if (!node) return false
    return !!isInAlarm(node.id)
}
</script>

<template>
  <div class="equipment-detail">
    <template v-if="equip">
      <!-- Header -->
      <div class="detail-header">
        <div>
          <span class="equip-tag">{{ equip.tag }}</span>
          <span class="equip-name">{{ equip.name }}</span>
        </div>
        <button class="close-btn" @click="emit('close')">&#x2715;</button>
      </div>

      <!-- OPC path -->
      <div v-if="input?.opc" class="opc-path">Reactor/{{ input.opc }}</div>

      <!-- Values -->
      <div class="value-list">
        <div v-for="(v, i) in values" :key="i" class="value-row">
          <div class="value-label">{{ v.label }}</div>
          <div class="value-data">
            <span class="value-num" :style="{ color: v.color }"
                  :class="{ alarm: v.key && sensorAlarm(v.key) }">
              {{ v.value }}
            </span>
            <span class="value-unit">{{ v.unit }}</span>
          </div>
          <!-- Sparkline -->
          <svg v-if="v.key && sparkline(v.key)" class="sparkline-svg" viewBox="0 0 120 20" preserveAspectRatio="none">
            <polyline :points="sparkline(v.key)"
                      :stroke="v.color || 'var(--text-muted)'" stroke-width="1.5" fill="none" stroke-opacity="0.7"/>
          </svg>
        </div>
      </div>

      <!-- Actuator override -->
      <div v-if="isActuator" class="override-section">
        <div class="override-title">Manual Override</div>
        <div class="override-row">
          <input type="number" v-model="overrideVal" step="0.1"
                 :placeholder="input.unit === 'K' ? '°C' : input.unit"
                 class="override-input"/>
          <button class="btn-apply" @click="requestOverride" :disabled="!overrideVal">Apply</button>
          <button class="btn-clear" @click="clearOverride">Clear</button>
        </div>

        <!-- Confirmation dialog (Poka-Yoke) -->
        <div v-if="showConfirm" class="confirm-dialog">
          <div class="confirm-text">
            Override <strong>{{ equip.name }}</strong> to <strong>{{ overrideVal }}</strong>?
          </div>
          <div class="confirm-actions">
            <button class="btn-confirm" @click="confirmOverride">Confirm</button>
            <button class="btn-cancel" @click="cancelConfirm">Cancel</button>
          </div>
        </div>
      </div>

      <!-- Read-only indicator -->
      <div v-else-if="input" class="readonly-indicator">
        Read-only Sensor
      </div>

      <!-- Remove from canvas -->
      <div v-if="canRemove" class="remove-section">
        <button class="btn-remove" @click="removeFromCanvas">Vom Canvas entfernen</button>
      </div>
    </template>

    <!-- Empty state -->
    <template v-else>
      <div class="empty-state">
        <div class="empty-icon">&#9881;</div>
        <div class="empty-text">Select equipment on the P&ID to view details</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.equipment-detail {
    padding: 8px;
    flex: 1;
    overflow-y: auto;
}

.detail-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8px;
}

.equip-tag {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin-right: 6px;
}

.equip-name {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-primary);
}

.close-btn {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-muted);
    font-size: 14px;
    cursor: pointer;
    width: 24px;
    height: 24px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
}
.close-btn:hover { background: var(--bg-app); color: var(--text-primary); border-color: var(--border-subtle); }

.opc-path {
    font-size: 0.65rem;
    color: var(--text-muted);
    font-family: var(--font-mono);
    background: var(--bg-app);
    padding: 3px 6px;
    border-radius: 4px;
    margin-bottom: 10px;
    border: 1px solid var(--border-subtle);
    display: inline-block;
}

.value-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.value-row {
    background: var(--bg-app);
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    padding: 8px 10px;
}

.value-label {
    font-size: 0.6rem;
    color: var(--text-muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 2px;
}

.value-data {
    display: flex;
    align-items: baseline;
    gap: 4px;
}

.value-num {
    font-size: 1.2rem;
    font-weight: 700;
    font-family: var(--font-mono);
    color: var(--text-primary);
    line-height: 1;
}
.value-num.alarm {
    color: var(--dcs-alarm);
    animation: alarm-flash 0.8s ease-in-out infinite;
}
@keyframes alarm-flash { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

.value-unit {
    font-size: 0.7rem;
    color: var(--text-muted);
    font-weight: 500;
}

.sparkline-svg {
    width: 100%;
    height: 20px;
    margin-top: 4px;
}

/* Override section */
.override-section {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--border-subtle);
}

.override-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
}

.override-row {
    display: flex;
    gap: 6px;
    align-items: center;
}

.override-input {
    width: 80px;
    padding: 5px 8px;
    background: var(--bg-input);
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    color: var(--text-primary);
    font-size: 0.8rem;
    font-family: var(--font-mono);
}
.override-input:focus { outline: none; border-color: var(--accent-primary); }

.btn-apply, .btn-clear {
    border: none;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.65rem;
    padding: 5px 10px;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    transition: all 0.15s;
}
.btn-apply { background: var(--dcs-normal); color: white; }
.btn-apply:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-apply:hover:not(:disabled) { opacity: 0.9; }
.btn-clear { background: var(--dcs-warning); color: white; }
.btn-clear:hover { opacity: 0.9; }

/* Confirmation dialog */
.confirm-dialog {
    margin-top: 8px;
    padding: 10px;
    background: rgba(249, 115, 22, 0.1);
    border: 1px solid var(--dcs-maintenance);
    border-radius: 6px;
    animation: slideIn 0.15s ease-out;
}
@keyframes slideIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }

.confirm-text {
    font-size: 0.75rem;
    color: var(--text-primary);
    margin-bottom: 8px;
}
.confirm-text strong {
    color: var(--dcs-maintenance);
}

.confirm-actions {
    display: flex;
    gap: 6px;
}

.btn-confirm {
    border: none;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.65rem;
    padding: 5px 12px;
    cursor: pointer;
    background: var(--dcs-maintenance);
    color: white;
    text-transform: uppercase;
}
.btn-cancel {
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.65rem;
    padding: 5px 12px;
    cursor: pointer;
    background: transparent;
    color: var(--text-secondary);
    text-transform: uppercase;
}

.readonly-indicator {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--border-subtle);
    font-size: 0.7rem;
    color: var(--text-muted);
    font-style: italic;
}

.remove-section {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--border-subtle);
}

.btn-remove {
    width: 100%;
    padding: 6px 12px;
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    background: transparent;
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
}
.btn-remove:hover {
    border-color: #ef4444;
    color: #ef4444;
    background: rgba(239, 68, 68, 0.08);
}

/* Empty state */
.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 120px;
    padding: 20px;
}

.empty-icon {
    font-size: 2rem;
    color: var(--text-muted);
    opacity: 0.3;
    margin-bottom: 8px;
}

.empty-text {
    font-size: 0.75rem;
    color: var(--text-muted);
    text-align: center;
}
</style>
