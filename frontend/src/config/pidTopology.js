/**
 * Fetches P&ID topology from the backend (config-driven node/edge graph).
 * Returns { nodes, edges, version } where version is null if the config
 * has no equipment.pid section (signals fallback to hardcoded layout).
 */
import { ref, computed } from 'vue'

const _cache = ref(null)
let _fetching = null

export async function fetchPidTopology() {
    if (_cache.value) return _cache.value
    if (_fetching) return _fetching

    _fetching = (async () => {
        try {
            const res = await fetch('/api/pid/topology')
            if (res.ok) {
                const data = await res.json()
                _cache.value = data
                return data
            }
        } catch (e) {
            // Backend not available
        }
        return { nodes: [], edges: [], version: null }
    })()

    const result = await _fetching
    _fetching = null
    return result
}

export function clearTopologyCache() {
    _cache.value = null
}

export const isConfigDriven = computed(() => _cache.value?.version != null)
