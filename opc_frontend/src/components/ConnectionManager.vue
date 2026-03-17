<script setup>
import { ref, onMounted } from 'vue'
import {
    discoverServers,
    getConnections,
    addConnection,
    setConnectionCredentials,
    removeConnection,
    browseNodes,
    addSubscription,
    removeSubscription,
    listNodes,
} from '../services/api'

const connections = ref([])
const subscriptions = ref([])
const discoveredServers = ref([])
const discovering = ref(false)
const discoveryUrl = ref('opc.tcp://localhost:4840')

// Add connection form
const showAddForm = ref(false)
const newConnection = ref({
    id: '', endpoint: '', security_mode: 'None',
    security_policy: '', certificate_path: '', private_key_path: '',
    username: '', password: '',
})

const showCredentialsForm = ref(false)
const credentialsConnectionId = ref('')
const runtimeCredentials = ref({ username: '', password: '' })

// Node browser
const browsing = ref(false)
const selectedConnectionId = ref(null)
const nodeTree = ref([])
const currentPath = ref([])

// Subscription form
const showSubscriptionForm = ref(false)
const selectedBrowseNode = ref(null)
const catalogNodes = ref([])
const newSubscription = ref({
    catalog_node_id: '',
    polling_rate_ms: 1000,
    transform: 'value',
})

async function loadConnections() {
    try {
        const data = await getConnections()
        connections.value = data.connections
        subscriptions.value = data.subscriptions
    } catch (e) {
        console.error('Failed to load connections:', e)
    }
}

async function handleDiscover() {
    discovering.value = true
    try {
        discoveredServers.value = await discoverServers(discoveryUrl.value)
    } finally {
        discovering.value = false
    }
}

function openAddForm(endpoint = '') {
    newConnection.value = {
        id: `conn-${Date.now()}`, endpoint: endpoint || '',
        security_mode: 'None', security_policy: '', certificate_path: '', private_key_path: '',
        username: '', password: '',
    }
    showAddForm.value = true
}

async function handleAddConnection() {
    try {
        const payload = {
            ...newConnection.value,
            security_policy: newConnection.value.security_policy || null,
            certificate_path: newConnection.value.certificate_path || null,
            private_key_path: newConnection.value.private_key_path || null,
            username: newConnection.value.username || null,
            password: newConnection.value.password || null,
        }
        await addConnection(payload)
        showAddForm.value = false
        await loadConnections()
    } catch (e) {
        alert(`Failed to add connection: ${e.message}`)
    }
}

function openCredentialsForm(conn) {
    credentialsConnectionId.value = conn.id
    runtimeCredentials.value = { username: conn.username || '', password: '' }
    showCredentialsForm.value = true
}

async function handleSetCredentials() {
    if (!runtimeCredentials.value.password) { alert('Password is required'); return }
    try {
        await setConnectionCredentials(credentialsConnectionId.value, {
            username: runtimeCredentials.value.username || null,
            password: runtimeCredentials.value.password,
        })
        showCredentialsForm.value = false
        await loadConnections()
    } catch (e) {
        alert(`Failed to set credentials: ${e.message}`)
    }
}

async function handleRemoveConnection(connId) {
    if (!confirm('Remove this connection and all its subscriptions?')) return
    try {
        await removeConnection(connId)
        await loadConnections()
    } catch (e) {
        console.error('Failed to remove connection:', e)
    }
}

async function handleBrowse(connId) {
    if (!connections.value.find(c => c.id === connId && c.connected)) {
        alert('Connection is not active')
        return
    }
    browsing.value = true
    selectedConnectionId.value = connId
    currentPath.value = []
    await loadNodes(null)
}

async function loadNodes(nodeId) {
    try {
        nodeTree.value = await browseNodes(selectedConnectionId.value, nodeId)
    } catch (e) {
        console.error('Failed to browse nodes:', e)
        nodeTree.value = []
    }
}

async function handleNodeClick(node) {
    if (node.node_class === 'Object') {
        currentPath.value.push({ name: node.browse_name, id: node.node_id })
        await loadNodes(node.node_id)
    } else if (node.node_class === 'Variable') {
        selectedBrowseNode.value = node
        catalogNodes.value = await listNodes()
        showSubscriptionForm.value = true
    }
}

function navigateUp() {
    if (currentPath.value.length === 0) return
    currentPath.value.pop()
    const parentId = currentPath.value.length > 0
        ? currentPath.value[currentPath.value.length - 1].id
        : null
    loadNodes(parentId)
}

async function handleAddSubscription() {
    if (!newSubscription.value.catalog_node_id) {
        alert('Select a catalog node to map to')
        return
    }
    const config = {
        id: `sub-${Date.now()}`,
        connection_id: selectedConnectionId.value,
        node_id: selectedBrowseNode.value.node_id,
        catalog_node_id: newSubscription.value.catalog_node_id,
        polling_rate_ms: newSubscription.value.polling_rate_ms,
        transform: newSubscription.value.transform,
        enabled: true,
    }
    try {
        await addSubscription(config)
        showSubscriptionForm.value = false
        browsing.value = false
        await loadConnections()
    } catch (e) {
        alert(`Failed to subscribe: ${e.message}`)
    }
}

async function handleRemoveSubscription(subId) {
    if (!confirm('Remove this subscription?')) return
    try {
        await removeSubscription(subId)
        await loadConnections()
    } catch (e) {
        console.error('Failed to remove subscription:', e)
    }
}

onMounted(loadConnections)
</script>

<template>
  <div class="connection-manager">
    <!-- Server Discovery -->
    <div class="section">
      <h3>Discover OPC UA Servers</h3>
      <div class="discovery-row">
        <input v-model="discoveryUrl" placeholder="opc.tcp://localhost:4840" class="discovery-input" />
        <button @click="handleDiscover" :disabled="discovering" class="btn btn-primary">
          {{ discovering ? 'Scanning...' : 'Scan Network' }}
        </button>
      </div>
      <div v-if="discoveredServers.length > 0" class="server-list">
        <div v-for="server in discoveredServers" :key="server" class="server-item">
          <span class="server-endpoint">{{ server }}</span>
          <button @click="openAddForm(server)" class="btn btn-sm btn-success">Connect</button>
        </div>
      </div>
    </div>

    <!-- Active Connections -->
    <div class="section">
      <div class="section-header">
        <h3>Active Connections</h3>
        <button @click="openAddForm()" class="btn btn-sm btn-primary">+ Add Connection</button>
      </div>
      <div v-if="connections.length === 0" class="empty-state">
        No connections configured. Discover servers or add manually.
      </div>
      <div v-for="conn in connections" :key="conn.id" class="connection-card">
        <div class="connection-header">
          <div class="connection-status" :class="{ connected: conn.connected }"></div>
          <div class="connection-info">
            <div class="connection-id">{{ conn.id }}</div>
            <div class="connection-endpoint">{{ conn.endpoint }}</div>
          </div>
          <div class="connection-actions">
            <button v-if="conn.connected" @click="handleBrowse(conn.id)" class="btn btn-sm btn-info">Browse</button>
            <button v-if="!conn.connected || conn.needs_credentials" @click="openCredentialsForm(conn)" class="btn btn-sm btn-secondary">Credentials</button>
            <button @click="handleRemoveConnection(conn.id)" class="btn btn-sm btn-danger">Remove</button>
          </div>
        </div>
        <div class="connection-meta">
          Status: <span :class="conn.connected ? 'status-ok' : 'status-err'">{{ conn.connected ? 'Connected' : 'Disconnected' }}</span>
          <span v-if="conn.needs_credentials"> · Password required</span>
          · {{ conn.subscription_count }} subscriptions
        </div>
      </div>
    </div>

    <!-- Active Subscriptions -->
    <div v-if="subscriptions.length > 0" class="section">
      <h3>Active Subscriptions</h3>
      <div v-for="sub in subscriptions" :key="sub.id" class="subscription-item">
        <div class="sub-node">{{ sub.node_id }}</div>
        <div class="sub-arrow">-></div>
        <div class="sub-key">{{ sub.catalog_node_id }}</div>
        <div class="sub-value">{{ sub.last_value !== null ? sub.last_value : '--' }}</div>
        <button @click="handleRemoveSubscription(sub.id)" class="btn btn-xs btn-danger">x</button>
      </div>
    </div>

    <!-- Add Connection Modal -->
    <div v-if="showAddForm" class="modal-overlay" @click.self="showAddForm = false">
      <div class="modal-small">
        <h3>Add OPC UA Connection</h3>
        <div class="form-row"><label>Connection ID</label><input v-model="newConnection.id" /></div>
        <div class="form-row"><label>Endpoint URL</label><input v-model="newConnection.endpoint" placeholder="opc.tcp://192.168.1.100:4840" /></div>
        <div class="form-row">
          <label>Security Mode</label>
          <select v-model="newConnection.security_mode">
            <option>None</option><option>Sign</option><option>SignAndEncrypt</option>
          </select>
        </div>
        <div v-if="newConnection.security_mode !== 'None'" class="form-row"><label>Security Policy</label><input v-model="newConnection.security_policy" placeholder="Basic256Sha256" /></div>
        <div v-if="newConnection.security_mode !== 'None'" class="form-row"><label>Certificate Path</label><input v-model="newConnection.certificate_path" /></div>
        <div v-if="newConnection.security_mode !== 'None'" class="form-row"><label>Private Key Path</label><input v-model="newConnection.private_key_path" /></div>
        <div class="form-row"><label>Username (optional)</label><input v-model="newConnection.username" /></div>
        <div class="form-row"><label>Password (runtime only)</label><input v-model="newConnection.password" type="password" /></div>
        <div class="modal-actions">
          <button @click="handleAddConnection" class="btn btn-primary">Connect</button>
          <button @click="showAddForm = false" class="btn btn-secondary">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Credentials Modal -->
    <div v-if="showCredentialsForm" class="modal-overlay" @click.self="showCredentialsForm = false">
      <div class="modal-small">
        <h3>Enter Runtime Credentials</h3>
        <div class="form-row"><label>Username</label><input v-model="runtimeCredentials.username" /></div>
        <div class="form-row"><label>Password</label><input v-model="runtimeCredentials.password" type="password" /></div>
        <div class="modal-actions">
          <button @click="handleSetCredentials" class="btn btn-primary">Apply & Connect</button>
          <button @click="showCredentialsForm = false" class="btn btn-secondary">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Node Browser Modal -->
    <div v-if="browsing" class="modal-overlay" @click.self="browsing = false">
      <div class="modal-large">
        <div class="browser-header">
          <h3>Browse OPC UA Nodes</h3>
          <button @click="browsing = false" class="close-btn">x</button>
        </div>
        <div class="breadcrumb">
          <span @click="loadNodes(null)" class="breadcrumb-item">Root</span>
          <span v-for="(p, i) in currentPath" :key="i" class="breadcrumb-item">/ {{ p.name }}</span>
          <button v-if="currentPath.length > 0" @click="navigateUp" class="btn btn-xs btn-secondary">Up</button>
        </div>
        <div class="node-browser-list">
          <div v-for="node in nodeTree" :key="node.node_id"
               class="node-row" :class="'node-' + node.node_class.toLowerCase()"
               @click="handleNodeClick(node)">
            <div class="node-icon">{{ node.node_class === 'Object' ? '>' : '#' }}</div>
            <div class="node-details">
              <div class="node-name">{{ node.browse_name }}</div>
              <div class="node-id-small">{{ node.node_id }}</div>
              <div v-if="node.data_type" class="node-type-label">{{ node.data_type }}</div>
            </div>
            <div v-if="node.node_class === 'Variable'" class="node-action">
              <button @click.stop="selectedBrowseNode = node; loadCatalogAndShowForm()" class="btn btn-xs btn-success">Subscribe</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Subscription Form Modal -->
    <div v-if="showSubscriptionForm" class="modal-overlay" @click.self="showSubscriptionForm = false">
      <div class="modal-small">
        <h3>Subscribe to Node</h3>
        <div class="node-preview">
          <strong>{{ selectedBrowseNode.browse_name }}</strong>
          <div class="node-id-preview">{{ selectedBrowseNode.node_id }}</div>
        </div>
        <div class="form-row">
          <label>Map to Catalog Node</label>
          <select v-model="newSubscription.catalog_node_id">
            <option value="">-- Select --</option>
            <option v-for="n in catalogNodes" :key="n.id" :value="n.id">{{ n.name }} ({{ n.category }})</option>
          </select>
        </div>
        <div class="form-row">
          <label>Polling Rate (ms)</label>
          <input v-model.number="newSubscription.polling_rate_ms" type="number" step="100" />
        </div>
        <div class="form-row">
          <label>Transform (e.g., "value * 1.8 + 32")</label>
          <input v-model="newSubscription.transform" placeholder="value" />
        </div>
        <div class="modal-actions">
          <button @click="handleAddSubscription" class="btn btn-primary">Subscribe</button>
          <button @click="showSubscriptionForm = false" class="btn btn-secondary">Cancel</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.connection-manager { max-width: 900px; }

.section { margin-bottom: 24px; }
.section h3 { font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }

.discovery-row { display: flex; gap: 8px; margin-bottom: 12px; }
.discovery-input { flex: 1; padding: 8px 12px; background: var(--bg-input); border: 1px solid var(--border); color: var(--text-primary); border-radius: 6px; font-size: 12px; }

.server-list { display: flex; flex-direction: column; gap: 6px; }
.server-item { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 6px; }
.server-endpoint { font-size: 11px; font-family: monospace; color: var(--text-secondary); }

.connection-card { background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.connection-header { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.connection-status { width: 10px; height: 10px; border-radius: 50%; background: var(--border-hover); }
.connection-status.connected { background: var(--accent-success); box-shadow: 0 0 8px var(--accent-success); }
.connection-info { flex: 1; }
.connection-id { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.connection-endpoint { font-size: 10px; font-family: monospace; color: var(--text-muted); }
.connection-actions { display: flex; gap: 6px; }
.connection-meta { font-size: 10px; color: var(--text-muted); margin-top: 4px; }
.status-ok { color: var(--accent-success); font-weight: 600; }
.status-err { color: var(--accent-danger); font-weight: 600; }

.subscription-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 6px; margin-bottom: 4px; font-size: 11px; }
.sub-node { font-family: monospace; color: var(--text-secondary); flex: 1; }
.sub-arrow { color: var(--border-hover); }
.sub-key { color: var(--accent-primary); font-weight: 600; }
.sub-value { color: var(--accent-success); font-weight: 700; min-width: 60px; text-align: right; }

.empty-state { padding: 32px; text-align: center; color: var(--text-muted); font-size: 12px; font-style: italic; }

.browser-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.browser-header h3 { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 0; }
.close-btn { background: none; border: 1px solid var(--border); color: var(--text-secondary); font-size: 14px; cursor: pointer; width: 28px; height: 28px; border-radius: 6px; }

.breadcrumb { display: flex; align-items: center; gap: 4px; padding: 8px 12px; background: var(--bg-input); border-radius: 6px; margin-bottom: 12px; font-size: 11px; }
.breadcrumb-item { color: var(--accent-primary); cursor: pointer; }

.node-browser-list { flex: 1; overflow-y: auto; }
.node-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 6px; margin-bottom: 4px; cursor: pointer; transition: all 0.15s; }
.node-row:hover { border-color: var(--border-hover); }
.node-row.node-object { border-left: 3px solid var(--accent-primary); }
.node-row.node-variable { border-left: 3px solid var(--accent-success); }
.node-icon { font-size: 14px; color: var(--text-muted); font-weight: 700; width: 20px; text-align: center; }
.node-details { flex: 1; }
.node-name { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.node-id-small { font-size: 9px; font-family: monospace; color: var(--text-muted); }
.node-type-label { font-size: 9px; color: var(--text-muted); }

.node-preview { padding: 12px; background: var(--bg-input); border: 1px solid var(--border); border-radius: 6px; margin-bottom: 12px; }
.node-preview strong { display: block; color: var(--text-primary); margin-bottom: 4px; }
.node-id-preview { font-size: 9px; font-family: monospace; color: var(--text-muted); }

.modal-small h3 { font-size: 14px; font-weight: 700; color: var(--text-primary); margin-bottom: 16px; }
</style>
