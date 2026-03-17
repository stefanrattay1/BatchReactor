<script setup>
import { ref, onMounted, computed } from 'vue'
import {
    getOPCToolStatus,
    getOPCToolNodes,
    getOPCMappings,
    addOPCMapping,
    removeOPCMapping,
} from '../services/api'

const opcToolStatus = ref({ available: false, url: '' })
const opcNodes = ref([])
const mappings = ref([])
const loading = ref(false)

// Add mapping form
const showAddForm = ref(false)
const selectedNode = ref(null)
const newMapping = ref({
    reactor_var: 'temperature',
    direction: 'read',
    transform: 'value',
    priority: 50,
})

const reactorReadVars = [
    { key: 'temperature', label: 'Temperature (K)' },
    { key: 'jacket_temperature', label: 'Jacket Temperature (K)' },
    { key: 'volume', label: 'Volume (m³)' },
    { key: 'pressure_bar', label: 'Pressure (bar)' },
    { key: 'command', label: 'Command (START/STOP/RESET)' },
]

const reactorWriteVars = [
    { key: 'temperature', label: 'Temperature (K)' },
    { key: 'conversion', label: 'Conversion' },
    { key: 'viscosity', label: 'Viscosity (Pa·s)' },
    { key: 'pressure_bar', label: 'Pressure (bar)' },
    { key: 'mass_total', label: 'Total Mass (kg)' },
    { key: 'jacket_temperature', label: 'Jacket Temperature (K)' },
    { key: 'fsm_state', label: 'FSM State (int)' },
    { key: 'fsm_state_name', label: 'FSM State Name' },
    { key: 'batch_elapsed', label: 'Batch Elapsed (s)' },
]

const availableVars = computed(() =>
    newMapping.value.direction === 'read' ? reactorReadVars : reactorWriteVars
)

function categoryColor(cat) {
    const map = { sensor: '#3b82f6', actuator: '#22c55e', status: '#f59e0b', custom: '#8b5cf6' }
    return map[cat] || '#64748b'
}

async function loadAll() {
    loading.value = true
    try {
        const [status, nodesData, mapsData] = await Promise.all([
            getOPCToolStatus(),
            getOPCToolNodes(),
            getOPCMappings(),
        ])
        opcToolStatus.value = status
        opcNodes.value = nodesData
        mappings.value = mapsData
    } catch (e) {
        console.error('Failed to load OPC Tool data:', e)
    } finally {
        loading.value = false
    }
}

function openAddForm(node) {
    selectedNode.value = node
    newMapping.value = {
        reactor_var: 'temperature',
        direction: node.writable ? 'read' : 'write',
        transform: 'value',
        priority: 50,
    }
    showAddForm.value = true
}

async function handleAddMapping() {
    try {
        await addOPCMapping({
            opc_node_id: selectedNode.value.id,
            reactor_var: newMapping.value.reactor_var,
            direction: newMapping.value.direction,
            transform: newMapping.value.transform,
            priority: newMapping.value.priority,
            enabled: true,
        })
        showAddForm.value = false
        await loadAll()
    } catch (e) {
        alert(`Failed to add mapping: ${e.message}`)
    }
}

async function handleRemoveMapping(opcNodeId, direction) {
    if (!confirm('Remove this mapping?')) return
    try {
        await removeOPCMapping(opcNodeId, direction)
        await loadAll()
    } catch (e) {
        alert(`Failed to remove mapping: ${e.message}`)
    }
}

function nodeForMapping(mapping) {
    return opcNodes.value.find(n => n.id === mapping.opc_node_id)
}

onMounted(loadAll)
</script>

<template>
  <div class="opc-tool-integration">
    <!-- Connection Status -->
    <div class="section">
      <h3>OPC Tool Connection</h3>
      <div class="status-card">
        <div class="status-indicator" :class="{ connected: opcToolStatus.available }"></div>
        <div class="status-info">
          <div class="status-label">
            {{ opcToolStatus.available ? 'Connected' : 'Not Connected' }}
          </div>
          <div class="status-url">{{ opcToolStatus.url || 'Not configured' }}</div>
        </div>
        <button @click="loadAll" class="btn btn-secondary btn-sm" :disabled="loading">
          {{ loading ? 'Loading...' : 'Refresh' }}
        </button>
      </div>
    </div>

    <!-- Available OPC Tool Nodes -->
    <div v-if="opcToolStatus.available" class="section">
      <div class="section-header">
        <h3>Available OPC Tool Nodes</h3>
        <span class="node-count">{{ opcNodes.length }} nodes</span>
      </div>

      <div v-if="opcNodes.length === 0" class="empty-state">
        No nodes defined in OPC Tool. Open the OPC Tool GUI to add nodes.
      </div>

      <div class="node-table">
        <div v-for="node in opcNodes" :key="node.id" class="node-row">
          <div class="node-category-dot" :style="{ background: categoryColor(node.category) }"></div>
          <div class="node-info">
            <div class="node-name">{{ node.name }}</div>
            <div class="node-meta">{{ node.id }} · {{ node.data_type }} · {{ node.category }}</div>
          </div>
          <div class="node-value-display">
            {{ node.current_value ?? '--' }}
          </div>
          <button @click="openAddForm(node)" class="btn btn-primary btn-xs">Map</button>
        </div>
      </div>
    </div>

    <!-- Active Mappings -->
    <div class="section">
      <h3>Active Mappings</h3>
      <div v-if="mappings.length === 0" class="empty-state">
        No mappings configured. Select an OPC Tool node above to map it to a reactor variable.
      </div>

      <div v-for="m in mappings" :key="m.opc_node_id + m.direction" class="mapping-card">
        <div class="mapping-direction" :class="m.direction">
          {{ m.direction === 'read' ? 'OPC -> Reactor' : 'Reactor -> OPC' }}
        </div>
        <div class="mapping-details">
          <span class="mapping-opc">{{ nodeForMapping(m)?.name || m.opc_node_id }}</span>
          <span class="mapping-arrow">{{ m.direction === 'read' ? '->' : '<-' }}</span>
          <span class="mapping-reactor">{{ m.reactor_var }}</span>
        </div>
        <div v-if="m.transform !== 'value'" class="mapping-transform">f(x) = {{ m.transform }}</div>
        <div v-if="m.direction === 'read'" class="mapping-priority">P{{ m.priority }}</div>
        <div class="mapping-enabled" :class="{ active: m.enabled }">
          {{ m.enabled ? 'ON' : 'OFF' }}
        </div>
        <button @click="handleRemoveMapping(m.opc_node_id, m.direction)" class="btn btn-danger btn-xs">x</button>
      </div>
    </div>

    <!-- Add Mapping Modal -->
    <div v-if="showAddForm" class="modal-overlay" @click.self="showAddForm = false">
      <div class="modal-small">
        <h3>Map OPC Node to Reactor</h3>
        <div class="node-preview">
          <strong>{{ selectedNode.name }}</strong>
          <div class="node-preview-meta">{{ selectedNode.id }} · {{ selectedNode.data_type }}</div>
        </div>
        <div class="form-row">
          <label>Direction</label>
          <select v-model="newMapping.direction">
            <option value="read">Read (OPC -> Reactor input)</option>
            <option value="write">Write (Reactor -> OPC output)</option>
          </select>
        </div>
        <div class="form-row">
          <label>Reactor Variable</label>
          <select v-model="newMapping.reactor_var">
            <option v-for="v in availableVars" :key="v.key" :value="v.key">{{ v.label }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>Transform (e.g., "value * 1.8 + 32")</label>
          <input v-model="newMapping.transform" placeholder="value" />
        </div>
        <div v-if="newMapping.direction === 'read'" class="form-row">
          <label>Priority (higher wins when multiple sources set same variable)</label>
          <input v-model.number="newMapping.priority" type="number" min="0" max="100" />
        </div>
        <div class="modal-actions">
          <button @click="handleAddMapping" class="btn btn-primary">Add Mapping</button>
          <button @click="showAddForm = false" class="btn btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.opc-tool-integration { padding: 16px; }

.section { margin-bottom: 24px; }
.section h3 { font-size: 13px; font-weight: 700; color: #e2e8f0; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.node-count { font-size: 10px; color: #64748b; }

.status-card {
    display: flex; align-items: center; gap: 12px;
    padding: 12px; background: #0f172a; border: 1px solid #334155; border-radius: 8px;
}
.status-indicator { width: 12px; height: 12px; border-radius: 50%; background: #475569; }
.status-indicator.connected { background: #22c55e; box-shadow: 0 0 8px #22c55e; }
.status-info { flex: 1; }
.status-label { font-size: 12px; font-weight: 700; color: #e2e8f0; }
.status-url { font-size: 10px; font-family: monospace; color: #64748b; }

.empty-state { padding: 32px; text-align: center; color: #64748b; font-size: 12px; font-style: italic; }

.node-table { display: flex; flex-direction: column; gap: 4px; }
.node-row {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px; background: #0f172a; border: 1px solid #334155; border-radius: 6px;
}
.node-category-dot { width: 8px; height: 8px; border-radius: 50%; }
.node-info { flex: 1; }
.node-name { font-size: 12px; font-weight: 600; color: #e2e8f0; }
.node-meta { font-size: 9px; color: #64748b; }
.node-value-display { font-size: 11px; font-weight: 700; color: #22c55e; font-family: monospace; min-width: 60px; text-align: right; }

.mapping-card {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 12px; background: #0f172a; border: 1px solid #334155; border-radius: 6px; margin-bottom: 4px;
}
.mapping-direction {
    font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 4px;
    text-transform: uppercase;
}
.mapping-direction.read { background: #1e3a5f; color: #3b82f6; }
.mapping-direction.write { background: #14532d; color: #22c55e; }

.mapping-details { flex: 1; display: flex; align-items: center; gap: 6px; font-size: 11px; }
.mapping-opc { color: #94a3b8; font-family: monospace; }
.mapping-arrow { color: #475569; }
.mapping-reactor { color: #3b82f6; font-weight: 600; }

.mapping-transform { font-size: 9px; color: #f59e0b; font-family: monospace; }
.mapping-priority { font-size: 9px; color: #64748b; }
.mapping-enabled { font-size: 9px; font-weight: 700; color: #475569; }
.mapping-enabled.active { color: #22c55e; }

.node-preview { padding: 12px; background: #0f172a; border: 1px solid #334155; border-radius: 6px; margin-bottom: 12px; }
.node-preview strong { display: block; color: #e2e8f0; margin-bottom: 4px; }
.node-preview-meta { font-size: 9px; font-family: monospace; color: #64748b; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 1100; }
.modal-small { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; width: 500px; max-width: 90vw; }
.modal-small h3 { font-size: 14px; font-weight: 700; color: #e2e8f0; margin-bottom: 16px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }

.form-row { margin-bottom: 12px; }
.form-row label { display: block; font-size: 11px; font-weight: 600; color: #94a3b8; margin-bottom: 4px; }
.form-row input, .form-row select { width: 100%; padding: 8px 12px; background: #0f172a; border: 1px solid #334155; color: #e2e8f0; border-radius: 6px; font-size: 12px; }
.form-row input:focus, .form-row select:focus { outline: none; border-color: #3b82f6; }

.btn { padding: 6px 12px; border: none; border-radius: 4px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.15s; }
.btn:hover { filter: brightness(1.1); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: #3b82f6; color: white; }
.btn-secondary { background: #475569; color: white; }
.btn-danger { background: #ef4444; color: white; }
.btn-sm { padding: 5px 10px; font-size: 10px; }
.btn-xs { padding: 3px 8px; font-size: 9px; }
</style>
