<script setup>
import { computed, reactive, ref } from 'vue'
import { state } from '../services/store'
import { sensorConfig, toggleSensor, updateSensorSetting, resetSensorConfig } from '../services/sensorConfig'
import ConnectionManager from './ConnectionManager.vue'

const emit = defineEmits(['close'])

const activeTab = ref('sensors')

const categories = computed(() => {
  const groups = {
    sensor: [],
    pump: [],
    valve: [],
    agitator: [],
    actuator: [],
    status: [],
    recipe: [],
  }
    for (const node of sensorConfig.availableNodes) {
        const cat = node.category || 'sensor'
        if (groups[cat]) groups[cat].push(node)
    else groups.sensor.push(node)
    }

    return [
        { key: 'sensor', label: 'Sensors', nodes: groups.sensor },
    { key: 'pump', label: 'Pumps', nodes: groups.pump },
    { key: 'valve', label: 'Valves', nodes: groups.valve },
    { key: 'agitator', label: 'Agitators', nodes: groups.agitator },
        { key: 'actuator', label: 'Actuators', nodes: groups.actuator },
        { key: 'status', label: 'Status', nodes: groups.status },
    { key: 'recipe', label: 'Recipe/Commands', nodes: groups.recipe },
    ].filter(c => c.nodes.length > 0)
})

function isEnabled(id) {
    return sensorConfig.enabledSensorIds.includes(id)
}

function getSettings(id) {
    return sensorConfig.sensorSettings[id] || {}
}

function getLiveValue(node) {
    if (!node.state_key) return '--'
    const val = state[node.state_key]
    if (val === undefined || val === null) return '--'
    if (typeof val === 'number') {
        if (node.unit === 'bar') return val.toFixed(3) + ' ' + node.unit
        if (node.unit === 'K') return val.toFixed(1) + ' ' + node.unit
        if (node.unit === '') return val.toFixed(4)
        return val.toFixed(2) + ' ' + node.unit
    }
    return String(val)
}

function handleToggle(id) {
    toggleSensor(id)
}

function handleAliasChange(id, value) {
    updateSensorSetting(id, { alias: value })
}

function handleColorChange(id, value) {
    updateSensorSetting(id, { color: value })
}

function handleAlarmHigh(id, value) {
    updateSensorSetting(id, { alarmHigh: value === '' ? null : Number(value) })
}

function handleAlarmLow(id, value) {
    updateSensorSetting(id, { alarmLow: value === '' ? null : Number(value) })
}

function handleReset() {
    if (confirm('Reset all sensor settings to defaults?')) {
        resetSensorConfig()
    }
}
</script>

<template>
  <teleport to="body">
    <div class="modal-overlay" @click.self="emit('close')">
      <div class="modal-content">
        <div class="modal-header">
          <h2>Sensor Manager</h2>
          <span class="modal-subtitle">Configure OPC UA sensors for the process flow diagram</span>
          <button class="close-btn" @click="emit('close')">x</button>
        </div>

        <div class="modal-tabs">
          <div class="tab" :class="{ active: activeTab === 'sensors' }" @click="activeTab = 'sensors'">
            Sensors
          </div>
          <div class="tab" :class="{ active: activeTab === 'connections' }" @click="activeTab = 'connections'">
            OPC UA Connections
          </div>
        </div>

        <div class="modal-body" v-if="activeTab === 'sensors'">
          <div v-for="cat in categories" :key="cat.key" class="category-section">
            <h3 class="category-title">{{ cat.label }}</h3>

            <div v-for="node in cat.nodes" :key="node.id" class="sensor-row" :class="{ enabled: isEnabled(node.id) }">
              <div class="sensor-toggle">
                <label class="toggle-switch">
                  <input type="checkbox" :checked="isEnabled(node.id)" @change="handleToggle(node.id)">
                  <span class="toggle-slider"></span>
                </label>
              </div>

              <div class="sensor-icon" :style="{ color: getSettings(node.id).color || node.default_color }">
                {{ getSettings(node.id).icon || node.default_icon }}
              </div>

              <div class="sensor-info">
                <input class="alias-input"
                       :value="getSettings(node.id).alias || ''"
                       @input="handleAliasChange(node.id, $event.target.value)"
                       :placeholder="node.name" />
                <div class="opc-path">{{ node.opc_path }}</div>
              </div>

              <div class="sensor-live-value">{{ getLiveValue(node) }}</div>

              <input type="color" class="color-picker"
                     :value="getSettings(node.id).color || node.default_color"
                     @input="handleColorChange(node.id, $event.target.value)" />

              <div v-if="isEnabled(node.id) && node.data_type === 'Double'" class="alarm-inputs">
                <div class="alarm-field">
                  <label>Hi</label>
                  <input type="number" step="any"
                         :value="getSettings(node.id).alarmHigh"
                         @change="handleAlarmHigh(node.id, $event.target.value)"
                         placeholder="--" />
                </div>
                <div class="alarm-field">
                  <label>Lo</label>
                  <input type="number" step="any"
                         :value="getSettings(node.id).alarmLow"
                         @change="handleAlarmLow(node.id, $event.target.value)"
                         placeholder="--" />
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-body" v-if="activeTab === 'connections'">
          <ConnectionManager />
        </div>

        <div class="modal-footer" v-if="activeTab === 'sensors'">
          <button class="btn btn-reset" @click="handleReset">Reset Defaults</button>
          <button class="btn btn-close" @click="emit('close')">Close</button>
        </div>
        <div class="modal-footer" v-if="activeTab === 'connections'">
          <button class="btn btn-close" @click="emit('close')">Close</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.modal-overlay {
    position: fixed; inset: 0;
    background: rgba(15, 23, 42, 0.8);
    backdrop-filter: blur(4px);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000;
    animation: fadeIn 0.15s ease-out;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-content {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    width: 700px; max-width: 90vw; max-height: 80vh;
    display: flex; flex-direction: column;
    box-shadow: var(--shadow-lg);
    animation: slideUp 0.2s ease-out;
    font-family: var(--font-sans);
}
@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

.modal-header {
    padding: 20px 24px 16px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.modal-header h2 { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); margin: 0; letter-spacing: -0.01em; }
.modal-subtitle { font-size: 0.85rem; color: var(--text-muted); flex: 1; }
.close-btn {
    background: transparent; border: 1px solid var(--border-subtle); color: var(--text-muted);
    font-size: 1.2rem; cursor: pointer; width: 32px; height: 32px; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.15s;
}
.close-btn:hover { color: var(--text-primary); border-color: var(--text-muted); background: var(--bg-app); }

.modal-tabs {
    display: flex; gap: 0; border-bottom: 1px solid var(--border-subtle); padding: 0 24px;
}
.tab {
    padding: 12px 20px; cursor: pointer; font-size: 0.9rem; font-weight: 600;
    color: var(--text-muted); border-bottom: 2px solid transparent; transition: all 0.15s;
}
.tab:hover { color: var(--text-secondary); }
.tab.active { color: var(--accent-primary); border-bottom-color: var(--accent-primary); }

.modal-body { padding: 20px 24px; overflow-y: auto; flex: 1; }

.category-section { margin-bottom: 24px; }
.category-title {
    font-size: 0.75rem; font-weight: 700; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.1em;
    margin-bottom: 12px; padding-bottom: 4px;
    border-bottom: 1px solid var(--border-subtle);
}

.sensor-row {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 16px; margin-bottom: 8px;
    background: var(--bg-card); border: 1px solid var(--border-subtle);
    border-radius: 8px; transition: all 0.15s;
}
.sensor-row.enabled { border-color: var(--border-subtle); background: var(--bg-card); }
.sensor-row:not(.enabled) { opacity: 0.6; filter: grayscale(0.5); }
.sensor-row:hover { border-color: var(--border-focus); transform: translateY(-1px); box-shadow: var(--shadow-sm); }

.sensor-toggle { flex: 0 0 36px; }

/* Toggle switch */
.toggle-switch { position: relative; display: inline-block; width: 36px; height: 20px; }
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
    position: absolute; cursor: pointer; inset: 0;
    background: var(--bg-input); border: 1px solid var(--border-subtle); border-radius: 20px; transition: 0.2s;
}
.toggle-slider::before {
    content: ''; position: absolute;
    height: 14px; width: 14px; left: 2px; bottom: 2px;
    background: var(--text-muted); border-radius: 50%; transition: 0.2s;
}
.toggle-switch input:checked + .toggle-slider { background: var(--accent-primary); border-color: var(--accent-primary); }
.toggle-switch input:checked + .toggle-slider::before { transform: translateX(16px); background: #fff; }

.sensor-icon {
    font-weight: 700; font-size: 0.9rem; width: 32px; height: 32px;
    display: flex; align-items: center; justify-content: center;
    background: var(--bg-app); border-radius: 6px; flex-shrink: 0;
    border: 1px solid var(--border-subtle);
}

.sensor-info { flex: 1; min-width: 0; }
.alias-input {
    width: 100%; padding: 6px 10px;
    background: transparent; border: 1px solid transparent;
    color: var(--text-primary); font-size: 0.9rem; font-weight: 500;
    border-radius: 4px; transition: all 0.15s;
}
.alias-input:hover { border-color: var(--border-subtle); background: var(--bg-app); }
.alias-input:focus { outline: none; border-color: var(--accent-primary); background: var(--bg-app); box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2); }
.alias-input::placeholder { color: var(--text-muted); font-weight: 400; }
.opc-path { font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); padding-left: 10px; margin-top: 2px; }

.sensor-live-value {
    font-size: 0.9rem; font-weight: 600; color: var(--text-primary);
    min-width: 80px; text-align: right; white-space: nowrap;
    font-family: var(--font-mono);
}

.color-picker {
    width: 28px; height: 28px; padding: 0; border: 1px solid var(--border-subtle);
    border-radius: 6px; cursor: pointer; background: var(--bg-app);
    flex-shrink: 0;
}
.color-picker::-webkit-color-swatch-wrapper { padding: 3px; }
.color-picker::-webkit-color-swatch { border: none; border-radius: 3px; }

.alarm-inputs { display: flex; gap: 8px; flex-shrink: 0; }
.alarm-field { display: flex; align-items: center; gap: 4px; }
.alarm-field label {
    font-size: 0.7rem; font-weight: 700; color: var(--text-muted);
    text-transform: uppercase;
}
.alarm-field input {
    width: 64px; padding: 4px 8px;
    background: var(--bg-input); border: 1px solid var(--border-subtle);
    color: var(--text-primary); font-size: 0.8rem; border-radius: 4px;
    font-family: var(--font-mono); text-align: right;
}
.alarm-field input:focus { outline: none; border-color: var(--accent-primary); }
.alarm-field input::placeholder { color: var(--text-muted); }

.modal-footer {
    padding: 16px 24px; border-top: 1px solid var(--border-subtle);
    display: flex; justify-content: flex-end; gap: 12px; background: var(--bg-panel);
    border-radius: 0 0 12px 12px;
}
.btn {
    padding: 8px 16px; border: none; border-radius: 6px;
    font-size: 0.85rem; font-weight: 600; cursor: pointer; transition: all 0.15s;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.btn:hover { transform: translateY(-1px); filter: brightness(1.1); }
.btn-reset { background: var(--bg-input); color: var(--accent-warning); border: 1px solid var(--border-subtle); }
.btn-reset:hover { border-color: var(--accent-warning); }
.btn-close { background: var(--accent-primary); color: white; box-shadow: var(--shadow-sm); }
</style>
