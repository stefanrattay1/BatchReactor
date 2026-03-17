<script setup>
import { ref, onMounted } from 'vue'
import { listNodes, createNode, deleteNode, writeNodeValue } from '../services/api'

const nodes = ref([])
const loading = ref(false)
const showAddForm = ref(false)
const filterCategory = ref('')
const newNode = ref({
    id: '',
    name: '',
    category: 'sensor',
    data_type: 'Double',
    writable: false,
    current_value: null,
    metadata: {},
})

const categories = ['sensor', 'actuator', 'status', 'custom']
const dataTypes = ['Double', 'Float', 'Int32', 'Int16', 'UInt32', 'Boolean', 'String']

async function loadNodes() {
    loading.value = true
    try {
        nodes.value = await listNodes(filterCategory.value || null)
    } catch (e) {
        console.error('Failed to load nodes:', e)
    } finally {
        loading.value = false
    }
}

function openAddForm() {
    newNode.value = {
        id: `node-${Date.now()}`,
        name: '',
        category: 'sensor',
        data_type: 'Double',
        writable: false,
        current_value: null,
        metadata: {},
    }
    showAddForm.value = true
}

async function handleCreate() {
    try {
        await createNode(newNode.value)
        showAddForm.value = false
        await loadNodes()
    } catch (e) {
        alert(`Failed to create node: ${e.message}`)
    }
}

async function handleDelete(nodeId) {
    if (!confirm(`Delete node "${nodeId}"?`)) return
    try {
        await deleteNode(nodeId)
        await loadNodes()
    } catch (e) {
        alert(`Failed to delete: ${e.message}`)
    }
}

async function handleWriteValue(node) {
    const input = prompt(`Write value for "${node.name}":`, node.current_value ?? '')
    if (input === null) return
    let value = input
    if (node.data_type === 'Double' || node.data_type === 'Float') value = parseFloat(input)
    else if (node.data_type.startsWith('Int') || node.data_type.startsWith('UInt')) value = parseInt(input)
    else if (node.data_type === 'Boolean') value = input.toLowerCase() === 'true'
    try {
        await writeNodeValue(node.id, value)
        await loadNodes()
    } catch (e) {
        alert(`Failed to write value: ${e.message}`)
    }
}

function categoryColor(cat) {
    const map = { sensor: '#3b82f6', actuator: '#22c55e', status: '#f59e0b', custom: '#8b5cf6' }
    return map[cat] || '#64748b'
}

onMounted(loadNodes)
</script>

<template>
  <div class="node-list-panel">
    <div class="panel-header">
      <h2>Node Catalog</h2>
      <div class="header-actions">
        <select v-model="filterCategory" @change="loadNodes" class="filter-select">
          <option value="">All categories</option>
          <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
        </select>
        <button @click="loadNodes" class="btn btn-secondary btn-sm">Refresh</button>
        <button @click="openAddForm" class="btn btn-primary btn-sm">+ Add Node</button>
      </div>
    </div>

    <div v-if="loading" class="empty-state">Loading...</div>
    <div v-else-if="nodes.length === 0" class="empty-state">
      No nodes defined. Add nodes to build your OPC information model.
    </div>

    <div class="node-grid">
      <div v-for="node in nodes" :key="node.id" class="node-card">
        <div class="node-header">
          <span class="category-badge" :style="{ background: categoryColor(node.category) }">
            {{ node.category }}
          </span>
          <span class="node-type">{{ node.data_type }}</span>
          <span v-if="node.writable" class="writable-badge">RW</span>
        </div>
        <div class="node-name">{{ node.name }}</div>
        <div class="node-id-text">{{ node.id }}</div>
        <div class="node-value">
          <span class="value-label">Value:</span>
          <span class="value-data">{{ node.current_value ?? '--' }}</span>
        </div>
        <div class="node-actions">
          <button v-if="node.writable" @click="handleWriteValue(node)" class="btn btn-info btn-xs">Write</button>
          <button @click="handleDelete(node.id)" class="btn btn-danger btn-xs">Delete</button>
        </div>
      </div>
    </div>

    <!-- Add Node Modal -->
    <div v-if="showAddForm" class="modal-overlay" @click.self="showAddForm = false">
      <div class="modal-small">
        <h3>Add Node</h3>
        <div class="form-row">
          <label>Node ID</label>
          <input v-model="newNode.id" />
        </div>
        <div class="form-row">
          <label>Display Name</label>
          <input v-model="newNode.name" placeholder="e.g., Temperature_K" />
        </div>
        <div class="form-row">
          <label>Category</label>
          <select v-model="newNode.category">
            <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>Data Type</label>
          <select v-model="newNode.data_type">
            <option v-for="dt in dataTypes" :key="dt" :value="dt">{{ dt }}</option>
          </select>
        </div>
        <div class="form-row">
          <label>
            <input type="checkbox" v-model="newNode.writable" />
            Writable (actuator / setpoint)
          </label>
        </div>
        <div class="modal-actions">
          <button @click="handleCreate" class="btn btn-primary">Create</button>
          <button @click="showAddForm = false" class="btn btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.node-list-panel { max-width: 1200px; }

.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.panel-header h2 { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.header-actions { display: flex; gap: 8px; align-items: center; }
.filter-select {
    padding: 5px 10px; background: var(--bg-input); border: 1px solid var(--border);
    color: var(--text-primary); border-radius: 4px; font-size: 11px;
}

.empty-state { padding: 40px; text-align: center; color: var(--text-muted); font-style: italic; }

.node-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.node-card {
    background: var(--bg-panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px;
    transition: border-color 0.15s;
}
.node-card:hover { border-color: var(--border-hover); }

.node-header { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.category-badge { font-size: 9px; font-weight: 700; color: white; padding: 1px 6px; border-radius: 8px; text-transform: uppercase; }
.node-type { font-size: 10px; color: var(--text-muted); font-family: monospace; }
.writable-badge { font-size: 9px; color: var(--accent-warning); font-weight: 700; border: 1px solid var(--accent-warning); padding: 0 4px; border-radius: 3px; }

.node-name { font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 2px; }
.node-id-text { font-size: 9px; font-family: monospace; color: var(--text-muted); margin-bottom: 8px; }

.node-value { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
.value-label { font-size: 10px; color: var(--text-muted); }
.value-data { font-size: 13px; font-weight: 700; color: var(--accent-success); font-family: monospace; }

.node-actions { display: flex; gap: 6px; }

.modal-small h3 { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 16px; }
</style>
