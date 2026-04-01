import { reactive } from 'vue'

import {
    applyPendingConfig,
    createModeledSensorDefinition,
    deleteModeledSensorDefinition,
    discardPendingConfig,
    fetchSensorRegistry,
    restoreCoreSensorDefinition,
    suppressCoreSensorDefinition,
} from './api'
import { clearTopologyCache } from '../config/pidTopology'

const STORAGE_KEY = 'reactor_sensor_config'
const MAX_SPARKLINE_POINTS = 60
const DEFAULT_ENABLED = ['temperature', 'pressure', 'conversion']

export const sensorConfig = reactive({
    availableNodes: [],
    sensorRegistry: [],
    suppressedCoreSensors: [],
    sensorVariables: [],
    enabledSensorIds: [],
    sensorSettings: {},
    sparklineData: {},
    activeAlarms: [],
    alarmState: {},
    showManager: false,
    initialized: false,
})

function buildDefaultSettings(node) {
    return {
        alias: '',
        color: node?.default_color || '#94a3b8',
        icon: node?.default_icon || '?',
        alarmHigh: null,
        alarmLow: null,
    }
}

function pruneRemovedSensorState(activeIds) {
    let dirty = false

    const nextEnabled = sensorConfig.enabledSensorIds.filter(id => activeIds.has(id))
    if (nextEnabled.length !== sensorConfig.enabledSensorIds.length) {
        sensorConfig.enabledSensorIds = nextEnabled
        dirty = true
    }

    for (const id of Object.keys(sensorConfig.sensorSettings)) {
        if (activeIds.has(id)) continue
        delete sensorConfig.sensorSettings[id]
        delete sensorConfig.sparklineData[id]
        delete sensorConfig.alarmState[id]
        sensorConfig.activeAlarms = sensorConfig.activeAlarms.filter(alarm => alarm.id !== id)
        dirty = true
    }

    return dirty
}

function ensureDefaultsForActiveNodes() {
    let dirty = false
    for (const node of sensorConfig.availableNodes) {
        if (!sensorConfig.sensorSettings[node.id]) {
            sensorConfig.sensorSettings[node.id] = buildDefaultSettings(node)
            dirty = true
        }
    }
    return dirty
}

function reconcileLocalState() {
    const activeIds = new Set(sensorConfig.availableNodes.map(node => node.id))
    if (activeIds.size === 0) return

    let dirty = pruneRemovedSensorState(activeIds)
    dirty = ensureDefaultsForActiveNodes() || dirty

    if (!sensorConfig.enabledSensorIds.length) {
        const defaults = DEFAULT_ENABLED.filter(id => activeIds.has(id))
        if (defaults.length) {
            sensorConfig.enabledSensorIds = defaults.slice()
            dirty = true
        }
    }

    if (dirty) saveSensorConfig()
}

function notifyPidTopologyChanged() {
    clearTopologyCache()
    if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('pid-topology-changed'))
    }
}

export async function refreshSensorCatalog(options = {}) {
    const { refreshTopology = false } = options

    try {
        const [connectionsRes, registryRes] = await Promise.all([
            fetch('/api/connections').then(res => res.json()),
            fetchSensorRegistry(),
        ])
        sensorConfig.availableNodes = connectionsRes.opc_ua?.node_catalog || []
        sensorConfig.sensorRegistry = registryRes.sensors || []
        sensorConfig.suppressedCoreSensors = registryRes.suppressed_core_sensors || []
        sensorConfig.sensorVariables = registryRes.variables || []
        reconcileLocalState()
        if (refreshTopology) notifyPidTopologyChanged()
        return registryRes
    } catch (e) {
        console.error('Failed to refresh sensor catalog:', e)
        return {
            sensors: sensorConfig.sensorRegistry,
            suppressed_core_sensors: sensorConfig.suppressedCoreSensors,
            variables: sensorConfig.sensorVariables,
            config_pending: false,
            active_file: '',
        }
    }
}

export async function initSensorConfig() {
    if (sensorConfig.initialized) return

    const saved = loadFromStorage()
    if (saved) {
        sensorConfig.enabledSensorIds = saved.enabledSensorIds || DEFAULT_ENABLED.slice()
        sensorConfig.sensorSettings = saved.sensorSettings || {}
    } else {
        sensorConfig.enabledSensorIds = DEFAULT_ENABLED.slice()
    }

    await refreshSensorCatalog()
    sensorConfig.initialized = true
}

export function findSensorDefinition(id) {
    return sensorConfig.sensorRegistry.find(sensor => sensor.id === id)
        || sensorConfig.suppressedCoreSensors.find(sensor => sensor.id === id)
        || null
}

export function toggleSensor(id) {
    const idx = sensorConfig.enabledSensorIds.indexOf(id)
    if (idx >= 0) {
        sensorConfig.enabledSensorIds.splice(idx, 1)
    } else {
        sensorConfig.enabledSensorIds.push(id)
    }
    saveSensorConfig()
}

export function updateSensorSetting(id, settings) {
    const node = sensorConfig.availableNodes.find(entry => entry.id === id)
    if (!sensorConfig.sensorSettings[id]) {
        sensorConfig.sensorSettings[id] = buildDefaultSettings(node)
    }
    Object.assign(sensorConfig.sensorSettings[id], settings)
    saveSensorConfig()
}

export async function createModeledSensor(sensor) {
    const result = await createModeledSensorDefinition(sensor)
    await refreshSensorCatalog()

    const sensorId = result?.sensor?.id
    if (sensorId && !sensorConfig.enabledSensorIds.includes(sensorId)) {
        sensorConfig.enabledSensorIds.push(sensorId)
        saveSensorConfig()
    }

    return result
}

export async function removeSensorDefinition(sensor) {
    if (!sensor) return null

    const result = sensor.origin === 'core'
        ? await suppressCoreSensorDefinition(sensor.id)
        : await deleteModeledSensorDefinition(sensor.tag)

    await refreshSensorCatalog()
    return result
}

export async function restoreCoreSensor(sensorId) {
    const result = await restoreCoreSensorDefinition(sensorId)
    await refreshSensorCatalog()
    return result
}

export async function applySensorConfigChanges() {
    const result = await applyPendingConfig()
    if (result) {
        await refreshSensorCatalog({ refreshTopology: true })
    }
    return result
}

export async function discardSensorConfigChanges() {
    const result = await discardPendingConfig()
    if (result) {
        await refreshSensorCatalog({ refreshTopology: true })
    }
    return result
}

export function pushSensorData(stateData) {
    const newAlarms = []

    for (const id of sensorConfig.enabledSensorIds) {
        const node = sensorConfig.availableNodes.find(n => n.id === id)
        if (!node) continue

        const value = stateData[node.state_key]
        if (value === undefined || value === null) continue

        // Update sparkline ring buffer
        if (!sensorConfig.sparklineData[id]) {
            sensorConfig.sparklineData[id] = []
        }
        const buf = sensorConfig.sparklineData[id]
        buf.push(value)
        if (buf.length > MAX_SPARKLINE_POINTS) {
            buf.shift()
        }

        // Check alarm thresholds
        const settings = sensorConfig.sensorSettings[id]
        if (!settings) continue

        const wasInAlarm = sensorConfig.alarmState[id] || null

        if (settings.alarmHigh !== null && settings.alarmHigh !== '' && typeof value === 'number') {
            const threshold = Number(settings.alarmHigh)
            const hysteresis = Math.abs(threshold) * 0.02
            if (value > threshold && wasInAlarm !== 'high') {
                sensorConfig.alarmState[id] = 'high'
                const alarm = { id, type: 'high', value, threshold, time: new Date(), name: settings.alias || node.name }
                sensorConfig.activeAlarms.push(alarm)
                newAlarms.push(alarm)
            } else if (wasInAlarm === 'high' && value < threshold - hysteresis) {
                sensorConfig.alarmState[id] = null
            }
        }

        if (settings.alarmLow !== null && settings.alarmLow !== '' && typeof value === 'number') {
            const threshold = Number(settings.alarmLow)
            const hysteresis = Math.abs(threshold) * 0.02
            if (value < threshold && wasInAlarm !== 'low') {
                sensorConfig.alarmState[id] = 'low'
                const alarm = { id, type: 'low', value, threshold, time: new Date(), name: settings.alias || node.name }
                sensorConfig.activeAlarms.push(alarm)
                newAlarms.push(alarm)
            } else if (wasInAlarm === 'low' && value > threshold + hysteresis) {
                sensorConfig.alarmState[id] = null
            }
        }
    }

    // Trim old alarms (keep last 50)
    if (sensorConfig.activeAlarms.length > 50) {
        sensorConfig.activeAlarms.splice(0, sensorConfig.activeAlarms.length - 50)
    }

    return newAlarms
}

export function dismissAlarm(index) {
    sensorConfig.activeAlarms.splice(index, 1)
}

export function saveSensorConfig() {
    try {
        const data = {
            enabledSensorIds: sensorConfig.enabledSensorIds,
            sensorSettings: sensorConfig.sensorSettings,
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
    } catch (e) {
        console.error('Failed to save sensor config:', e)
    }
}

export function resetSensorConfig() {
    sensorConfig.enabledSensorIds = DEFAULT_ENABLED.slice()
    sensorConfig.sensorSettings = {}
    sensorConfig.sparklineData = {}
    sensorConfig.activeAlarms = []
    sensorConfig.alarmState = {}
    for (const node of sensorConfig.availableNodes) {
        sensorConfig.sensorSettings[node.id] = buildDefaultSettings(node)
    }
    localStorage.removeItem(STORAGE_KEY)
}

function loadFromStorage() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY)
        return raw ? JSON.parse(raw) : null
    } catch (e) {
        return null
    }
}

// Helper: check if a sensor is currently in alarm
export function isInAlarm(id) {
    return sensorConfig.alarmState[id] || null
}

// Helper: get sparkline points as SVG polyline string
export function getSparklinePoints(id, x, y, width, height) {
    const data = sensorConfig.sparklineData[id]
    if (!data || data.length < 2) return null

    let min = Infinity, max = -Infinity
    for (const v of data) {
        if (v < min) min = v
        if (v > max) max = v
    }
    const range = max - min || 1
    const step = width / (data.length - 1)

    return data.map((v, i) => {
        const px = x + i * step
        const py = y + height - ((v - min) / range) * height
        return `${px.toFixed(1)},${py.toFixed(1)}`
    }).join(' ')
}
