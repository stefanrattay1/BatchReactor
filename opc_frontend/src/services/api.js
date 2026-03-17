/**
 * API client for the OPC Tool backend.
 */

// ---- Health ----

export async function checkHealth() {
    const res = await fetch('/api/health')
    return await res.json()
}

// ---- Node CRUD ----

export async function listNodes(category = null) {
    const params = category ? `?category=${category}` : ''
    const res = await fetch(`/api/nodes${params}`)
    const data = await res.json()
    return data.nodes || []
}

export async function getNode(nodeId) {
    const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`)
    if (!res.ok) throw new Error('Node not found')
    return await res.json()
}

export async function createNode(config) {
    const res = await fetch('/api/nodes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    })
    if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Failed to create node')
    }
    return await res.json()
}

export async function updateNode(nodeId, updates) {
    const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
    })
    if (!res.ok) throw new Error('Failed to update node')
    return await res.json()
}

export async function deleteNode(nodeId) {
    const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete node')
    return await res.json()
}

// ---- Values ----

export async function getNodeValue(nodeId) {
    const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/value`)
    return await res.json()
}

export async function writeNodeValue(nodeId, value) {
    const res = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/value`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value })
    })
    return await res.json()
}

// ---- Servers ----

export async function listServers() {
    const res = await fetch('/api/servers')
    const data = await res.json()
    return data.servers || []
}

export async function createServer(config) {
    const res = await fetch('/api/servers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    })
    if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Failed to create server')
    }
    return await res.json()
}

export async function deleteServer(serverId) {
    const res = await fetch(`/api/servers/${encodeURIComponent(serverId)}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete server')
    return await res.json()
}

// ---- Connections ----

export async function getConnections() {
    const res = await fetch('/api/connections')
    return await res.json()
}

export async function addConnection(config) {
    const res = await fetch('/api/connections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    })
    if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Failed to add connection')
    }
    return await res.json()
}

export async function removeConnection(connId) {
    const res = await fetch(`/api/connections/${connId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to remove connection')
    return await res.json()
}

export async function setConnectionCredentials(connId, credentials) {
    const res = await fetch(`/api/connections/${connId}/credentials`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(credentials)
    })
    if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Failed to set credentials')
    }
    return await res.json()
}

export async function browseNodes(connId, nodeId = null) {
    const res = await fetch(`/api/connections/${connId}/browse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_id: nodeId })
    })
    if (!res.ok) throw new Error('Failed to browse nodes')
    const data = await res.json()
    return data.nodes || []
}

// ---- Subscriptions ----

export async function addSubscription(config) {
    const res = await fetch('/api/subscriptions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    })
    if (!res.ok) throw new Error('Failed to add subscription')
    return await res.json()
}

export async function removeSubscription(subId) {
    const res = await fetch(`/api/subscriptions/${subId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to remove subscription')
    return await res.json()
}

// ---- Discovery ----

export async function discoverServers(discoveryUrl = 'opc.tcp://localhost:4840') {
    const res = await fetch('/api/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ discovery_url: discoveryUrl })
    })
    const data = await res.json()
    return data.servers || []
}
