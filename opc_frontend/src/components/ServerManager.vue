<script setup>
import { ref, onMounted } from 'vue'
import { listServers, createServer, deleteServer } from '../services/api'

const servers = ref([])
const showAddForm = ref(false)
const newServer = ref({
    server_id: '',
    endpoint: 'opc.tcp://0.0.0.0:4840',
    name: 'OPC Tool Server',
    namespace_uri: 'urn:opctool:server',
})

async function loadServers() {
    try {
        servers.value = await listServers()
    } catch (e) {
        console.error('Failed to load servers:', e)
    }
}

function openAddForm() {
    newServer.value = {
        server_id: `server-${Date.now()}`,
        endpoint: 'opc.tcp://0.0.0.0:4840',
        name: 'OPC Tool Server',
        namespace_uri: 'urn:opctool:server',
    }
    showAddForm.value = true
}

async function handleCreate() {
    try {
        await createServer(newServer.value)
        showAddForm.value = false
        await loadServers()
    } catch (e) {
        alert(`Failed to create server: ${e.message}`)
    }
}

async function handleDelete(serverId) {
    if (!confirm(`Stop and remove server "${serverId}"?`)) return
    try {
        await deleteServer(serverId)
        await loadServers()
    } catch (e) {
        alert(`Failed to remove server: ${e.message}`)
    }
}

onMounted(loadServers)
</script>

<template>
  <div class="server-manager">
    <div class="panel-header">
      <h2>Managed OPC UA Servers</h2>
      <button @click="openAddForm" class="btn btn-primary btn-sm">+ Create Server</button>
    </div>

    <div v-if="servers.length === 0" class="empty-state">
      No OPC UA servers running. Create one to expose nodes to external clients.
    </div>

    <div v-for="srv in servers" :key="srv.server_id" class="server-card">
      <div class="server-header">
        <div class="server-status" :class="{ running: srv.running }"></div>
        <div class="server-info">
          <div class="server-name">{{ srv.name }}</div>
          <div class="server-endpoint">{{ srv.endpoint }}</div>
        </div>
        <div class="server-id-badge">{{ srv.server_id }}</div>
        <button @click="handleDelete(srv.server_id)" class="btn btn-danger btn-sm">Stop & Remove</button>
      </div>
    </div>

    <!-- Add Server Modal -->
    <div v-if="showAddForm" class="modal-overlay" @click.self="showAddForm = false">
      <div class="modal-small">
        <h3>Create OPC UA Server</h3>
        <div class="form-row">
          <label>Server ID</label>
          <input v-model="newServer.server_id" />
        </div>
        <div class="form-row">
          <label>Endpoint</label>
          <input v-model="newServer.endpoint" placeholder="opc.tcp://0.0.0.0:4840" />
        </div>
        <div class="form-row">
          <label>Server Name</label>
          <input v-model="newServer.name" />
        </div>
        <div class="form-row">
          <label>Namespace URI</label>
          <input v-model="newServer.namespace_uri" />
        </div>
        <div class="modal-actions">
          <button @click="handleCreate" class="btn btn-primary">Create & Start</button>
          <button @click="showAddForm = false" class="btn btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.server-manager { max-width: 800px; }

.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.panel-header h2 { font-size: 14px; font-weight: 700; color: var(--text-primary); }

.empty-state { padding: 40px; text-align: center; color: var(--text-muted); font-style: italic; }

.server-card {
    background: var(--bg-panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px; margin-bottom: 10px;
}
.server-header { display: flex; align-items: center; gap: 12px; }
.server-status { width: 10px; height: 10px; border-radius: 50%; background: var(--border-hover); }
.server-status.running { background: var(--accent-success); box-shadow: 0 0 8px var(--accent-success); }
.server-info { flex: 1; }
.server-name { font-size: 13px; font-weight: 700; color: var(--text-primary); }
.server-endpoint { font-size: 10px; font-family: monospace; color: var(--text-muted); }
.server-id-badge { font-size: 9px; font-family: monospace; color: var(--text-muted); background: var(--bg-input); padding: 2px 8px; border-radius: 4px; }

.modal-small h3 { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 16px; }
</style>
