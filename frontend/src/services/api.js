import { actions } from './store'

const POLLING_INTERVAL = 1000
let intervalId = null

export function startPolling() {
    stopPolling()
    poll()
    intervalId = setInterval(poll, POLLING_INTERVAL)
}

export function stopPolling() {
    if (intervalId) clearInterval(intervalId)
}

async function poll() {
    try {
        const res = await fetch('/api/state')
        if (!res.ok) throw new Error(`API Error: ${res.status}`)
        const data = await res.json()
        actions.updateState(data)
    } catch (e) {
        actions.setError(e.message)
    }
}

export async function setTickInterval(value) {
    try {
        await fetch('/api/config/tick_interval', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value })
        })
    } catch (e) {
        console.error(e)
    }
}

export async function sendCommand(cmd) {
    try {
        const res = await fetch('/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: cmd })
        })
        if (!res.ok) throw new Error(`Failed command ${cmd} (${res.status})`)
        // Poll immediately after command for snappier feedback
        setTimeout(poll, 100)
        return true
    } catch (e) {
        console.error(e)
        actions.addLog(`Command ${cmd} failed`, 'error')
        return false
    }
}

export async function selectRecipe(filename) {
    try {
        const res = await fetch('/api/recipes/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        })
        if (!res.ok) throw new Error('Failed to select recipe')
        return true
    } catch (e) {
        console.error(e)
        return false
    }
}

// DEPRECATED: Data package functions removed from UI but kept for API access
// These functions remain available for programmatic use but are no longer
// exposed in the web dashboard interface.

export async function selectDataPackage(filename) {
    try {
        const res = await fetch('/api/data_packages/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        })
        if (!res.ok) throw new Error('Failed to select data package')
        return true
    } catch (e) {
        console.error(e)
        return false
    }
}

export async function deactivateDataPackage() {
    try {
        const res = await fetch('/api/data_packages/deactivate', { method: 'POST' })
        if (!res.ok) throw new Error('Failed to deactivate data package')
        return true
    } catch (e) {
        console.error(e)
        return false
    }
}

// ---- Model Config Management ----

export async function fetchConfigs() {
    try {
        const res = await fetch('/api/configs')
        return await res.json()
    } catch (e) {
        console.error('Failed to fetch configs:', e)
        return { configs: [], active_file: '' }
    }
}

export async function selectConfig(filename) {
    try {
        const res = await fetch('/api/configs/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        })
        if (!res.ok) {
            const data = await res.json()
            throw new Error(data.error || 'Failed to select config')
        }
        return await res.json()
    } catch (e) {
        console.error(e)
        return null
    }
}

export async function fetchModelConfig() {
    try {
        const res = await fetch('/api/model/config/full')
        return await res.json()
    } catch (e) {
        console.error('Failed to fetch model config:', e)
        return { config: {}, pending: null, active_file: '' }
    }
}

export async function fetchSimulationOptions() {
    try {
        const res = await fetch('/api/model/simulation/options')
        return await res.json()
    } catch (e) {
        console.error('Failed to fetch simulation options:', e)
        return { current: {}, available: {}, constraints: {} }
    }
}

export async function updateModelConfig(partial) {
    try {
        const res = await fetch('/api/model/config/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config: partial })
        })
        return await res.json()
    } catch (e) {
        console.error('Failed to update config:', e)
        return null
    }
}

export async function applyPendingConfig() {
    try {
        const res = await fetch('/api/model/config/apply', { method: 'POST' })
        if (!res.ok) {
            const data = await res.json()
            throw new Error(data.error || 'Failed to apply config')
        }
        return await res.json()
    } catch (e) {
        console.error(e)
        return null
    }
}

export async function discardPendingConfig() {
    try {
        const res = await fetch('/api/model/config/discard', { method: 'POST' })
        return await res.json()
    } catch (e) {
        console.error(e)
        return null
    }
}

// ---- OPC Tool Integration ----

export async function getOPCToolStatus() {
    try {
        const res = await fetch('/api/opc-tool/status')
        return await res.json()
    } catch (e) {
        console.error('Failed to get OPC Tool status:', e)
        return { available: false, url: '' }
    }
}

export async function getOPCToolNodes(category = null) {
    try {
        const params = category ? `?category=${category}` : ''
        const res = await fetch(`/api/opc-tool/nodes${params}`)
        const data = await res.json()
        return data.nodes || []
    } catch (e) {
        console.error('Failed to get OPC Tool nodes:', e)
        return []
    }
}

export async function getOPCMappings() {
    try {
        const res = await fetch('/api/opc-tool/mappings')
        const data = await res.json()
        return data.mappings || []
    } catch (e) {
        console.error('Failed to get OPC mappings:', e)
        return []
    }
}

export async function addOPCMapping(mapping) {
    const res = await fetch('/api/opc-tool/mappings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mapping)
    })
    if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'Failed to add mapping')
    }
    return await res.json()
}

export async function removeOPCMapping(opcNodeId, direction = null) {
    const params = direction ? `?direction=${direction}` : ''
    const res = await fetch(`/api/opc-tool/mappings/${encodeURIComponent(opcNodeId)}${params}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to remove mapping')
    return await res.json()
}

// ---- Batch Simulation ----

export async function startBatchRun(options = {}) {
    const res = await fetch('/api/batch/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options)
    })
    if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error || 'Failed to start batch run')
    }
    return await res.json()
}

export async function getBatchStatus() {
    const res = await fetch('/api/batch/status')
    return await res.json()
}

export async function cancelBatchRun() {
    const res = await fetch('/api/batch/cancel', { method: 'POST' })
    if (!res.ok) {
        const data = await res.json()
        throw new Error(data.error || 'Failed to cancel batch run')
    }
    return await res.json()
}

export async function fetchBatchLogs() {
    try {
        const res = await fetch('/api/batch/logs')
        const data = await res.json()
        return data.logs || []
    } catch (e) {
        console.error('Failed to fetch batch logs:', e)
        return []
    }
}

export async function fetchBatchData(filename) {
    const res = await fetch(`/api/batch/logs/${encodeURIComponent(filename)}`)
    if (!res.ok) {
        let msg = `Failed to fetch batch data (${res.status})`
        try {
            const data = await res.json()
            if (data.error) msg = data.error
        } catch (e) { /* response wasn't JSON */ }
        throw new Error(msg)
    }
    return await res.json()
}

// --- Equipment Module / Control Module API ---

export async function fetchEquipmentStatus() {
    try {
        const res = await fetch('/api/equipment/status')
        return await res.json()
    } catch (e) {
        console.error('Failed to fetch equipment status:', e)
        return { equipment_modules: {}, control_modules: {} }
    }
}

export async function fetchEquipmentModules() {
    try {
        const res = await fetch('/api/equipment/modules')
        return await res.json()
    } catch (e) {
        console.error('Failed to fetch equipment modules:', e)
        return []
    }
}

export async function setEquipmentMode(emTag, mode) {
    try {
        const res = await fetch('/api/equipment/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ em_tag: emTag, mode })
        })
        return await res.json()
    } catch (e) {
        console.error('Failed to set equipment mode:', e)
        return { error: e.message }
    }
}
