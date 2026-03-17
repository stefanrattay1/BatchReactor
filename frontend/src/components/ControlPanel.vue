<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { state, actions } from '../services/store'
import { INPUTS } from '../constants'
import { sendCommand } from '../services/api'
import { sensorConfig } from '../services/sensorConfig'
import DetailChart from './DetailChart.vue'

const selectedId = computed(() => state.selectedInput)
const input = computed(() => {
    if (!selectedId.value) return null
    // Try existing INPUTS first
    if (INPUTS[selectedId.value]) return INPUTS[selectedId.value]
    // Fall back to dynamic sensor config
    const node = sensorConfig.availableNodes.find(n => n.id === selectedId.value)
    if (!node) return null
    const settings = sensorConfig.sensorSettings[selectedId.value] || {}
    return {
        name: settings.alias || node.name,
        icon: settings.icon || node.default_icon,
        color: settings.color || node.default_color,
        unit: node.unit,
        opc: node.opc_path,
        key: node.state_key,
        actuator: node.writable ? node.id : null,
    }
})

// System Overview Helper - Which inputs have actuators?
const activeActuators = computed(() => {
    return Object.values(INPUTS).filter(i => i.actuator)
})

function select(id) {
    actions.selectInput(id)
}

function getValue(key) {
    const val = state[key]
    if (val === undefined) return '0.00'
    return val.toFixed(2)
}

// Recipe Data Fetching
const recipeData = ref(null)

async function fetchRecipe() {
    try {
        const res = await fetch('/api/recipe/current')
        if (res.ok) recipeData.value = await res.json()
    } catch (e) { console.error(e) }
}

onMounted(fetchRecipe)

// Live Value Logic
const currentValue = computed(() => {
    if (!input.value) return 0
    const val = state[input.value.key]
    if (val === undefined) return 0
    
    // Formatting matching original
    const unit = input.value.unit
    if (unit === 'K') return val.toFixed(1)
    if (unit === 'kg/s') return val.toFixed(4)
    if (unit === 'bar') return val.toFixed(3)
    return val.toFixed(2)
})

// Override Logic
const overrideVal = ref('')

async function applyOverride() {
   if (!input.value || !input.value.actuator) return
   if (!overrideVal.value) return
   try {
       await fetch('/api/actuator/override', {
           method: 'POST',
           headers: { 'Content-Type': 'application/json' },
           body: JSON.stringify({ 
               actuator: input.value.actuator, 
               value: parseFloat(overrideVal.value) 
           })
       })
       actions.addLog(`Override Applied: ${input.value.name} -> ${overrideVal.value}`, 'warn')
       overrideVal.value = ''
   } catch (e) { console.error(e) }
}

async function clearOverride() {
   try {
       await fetch('/api/actuator/override', {
           method: 'POST',
           headers: { 'Content-Type': 'application/json' },
           body: JSON.stringify({ actuator: 'clear', value: 0 })
       })
       actions.addLog(`Override Cleared`, 'success')
   } catch (e) { console.error(e) }
}
</script>

<template>
  <div class="control-panel-wrapper">
      <div v-if="input" class="input-details visible">
        <div class="header-row">
            <h3>
                <span class="icon" :style="{ background: input.color, color: 'white' }">{{ input.icon }}</span>
                <span>{{ input.name }}</span>
            </h3>
            <button class="close-btn" @click="actions.selectInput(null)">×</button>
        </div>

        <div class="current-value">{{ currentValue }} <small>{{ input.unit }}</small></div>
        <div class="opc-tag">Reactor/{{ input.opc }}</div>
        
        <div class="chart-wrapper">
            <DetailChart :input="input" :recipeData="recipeData" />
        </div>
        
        <div v-if="input.actuator" class="override-row">
            <input type="number" v-model="overrideVal" step="0.1" placeholder="Val">
            <button class="btn btn-sm btn-start" @click="applyOverride">Apply</button>
            <button class="btn btn-sm btn-reset" @click="clearOverride">Clear</button>
        </div>
        <div v-else class="override-row">
            <span style="font-size: 11px; color: #64748b;">Read-only Sensor</span>
        </div>
      </div>

      <!-- Empty State: System Overview -->
      <div v-else class="system-overview">
          <h3>System Overview</h3>
          <div class="overview-grid">
              <div v-for="act in activeActuators" :key="act.key" class="overview-item" @click="select(act.key)">
                  <div class="icon-small" :style="{ color: act.color }">{{ act.icon }}</div>
                  <div class="details">
                      <div class="name">{{ act.name }}</div>
                      <div class="value">{{ getValue(act.key) }} <small>{{ act.unit }}</small></div>
                  </div>
                  <div class="status-indicator" :class="{ active: state.actuator_overrides?.[act.actuator] }">
                    {{ state.actuator_overrides?.[act.actuator] ? 'MAN' : 'AUTO' }}
                  </div>
              </div>
          </div>
          <div class="help-text">Select a component in the diagram to view details and controls.</div>
      </div>
  </div>
</template>

<style scoped>
.control-panel-wrapper { margin-top: 16px; font-family: var(--font-sans); }

.input-details, .system-overview { 
    background: var(--bg-card);
    border: 1px solid var(--border-subtle); 
    border-radius: 12px; 
    padding: 20px; 
    box-shadow: var(--shadow-lg);
    animation: slideIn 0.2s ease-out;
}
@keyframes slideIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

.header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.close-btn { 
    background: transparent; 
    border: 1px solid transparent; 
    color: var(--text-muted); 
    font-size: 20px; 
    cursor: pointer; 
    width: 32px; height: 32px; 
    border-radius: 8px; 
    display: flex; align-items: center; justify-content: center;
    transition: all 0.2s;
}
.close-btn:hover { background: var(--bg-app); color: var(--text-primary); border-color: var(--border-subtle); }

.input-details h3, .system-overview h3 { 
    font-size: 1rem; 
    font-weight: 600; 
    margin: 0; 
    display: flex; align-items: center; gap: 12px; 
    color: var(--text-primary); 
    letter-spacing: -0.01em; 
}
.input-details h3 .icon { 
    width: 32px; height: 32px; 
    border-radius: 8px; 
    display: flex; align-items: center; justify-content: center; 
    font-size: 14px; 
    box-shadow: inset 0 1px 1px rgba(255,255,255,0.1); 
}

.current-value { font-size: 2.5rem; font-weight: 700; margin-bottom: 4px; color: var(--text-primary); letter-spacing: -0.02em; line-height: 1; }
.current-value small { font-size: 1rem; color: var(--text-muted); font-weight: 500; margin-left: 4px; }

.opc-tag { 
    font-size: 0.75rem; 
    color: var(--text-muted); 
    font-family: var(--font-mono); 
    background: var(--bg-app); 
    padding: 4px 8px; 
    border-radius: 6px; 
    margin-bottom: 20px; 
    border: 1px solid var(--border-subtle); 
    display: inline-block;
}

.chart-wrapper { 
    margin-bottom: 20px; 
    background: var(--bg-app); 
    border: 1px solid var(--border-subtle); 
    border-radius: 8px; 
    padding: 16px; 
}

.override-row { margin-top: 16px; display: flex; gap: 10px; align-items: center; padding-top: 16px; border-top: 1px solid var(--border-subtle); }
.override-row input { 
    width: 100px; 
    padding: 8px 12px; 
    background: var(--bg-input); 
    border: 1px solid var(--border-subtle); 
    border-radius: 6px; 
    color: var(--text-primary); 
    font-size: 0.875rem; 
    font-family: var(--font-mono);
    transition: border-color 0.2s;
}
.override-row input:focus { outline: none; border-color: var(--accent-primary); }

.btn { border: none; border-radius: 6px; font-weight: 600; cursor: pointer; color: white; transition: all 0.2s; }
.btn:hover { opacity: 0.9; transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn-sm { padding: 8px 12px; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.btn-start { background: var(--accent-success); }
.btn-reset { background: var(--accent-warning); }

/* System Overview Styles */
.overview-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; padding-top: 16px; }
.overview-item { 
    background: var(--bg-app); 
    border: 1px solid var(--border-subtle); 
    border-radius: 8px; 
    padding: 12px; 
    display: flex; align-items: center; gap: 12px; 
    cursor: pointer; 
    transition: all 0.2s;
}
.overview-item:hover { border-color: var(--border-focus); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
.icon-small { font-weight: bold; width: 24px; text-align: center; font-size: 1.1em; }
.details { flex: 1; min-width: 0; }
.details .name { font-size: 0.75rem; color: var(--text-muted); font-weight: 600; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.details .value { font-size: 0.9rem; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); }
.status-indicator { 
    font-size: 0.65rem; padding: 2px 6px; border-radius: 4px; background: var(--bg-panel); color: var(--text-muted); font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
}
.status-indicator.active { background: var(--accent-warning); color: #000; }

.help-text { font-size: 0.8rem; color: var(--text-muted); text-align: center; margin-top: 12px; }
</style>
