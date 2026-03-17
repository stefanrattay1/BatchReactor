import { reactive } from 'vue'

const STORAGE_KEY = 'reactor_sensor_config'
const MAX_SPARKLINE_POINTS = 60
const DEFAULT_ENABLED = ['temperature', 'pressure', 'conversion']

export const sensorConfig = reactive({
    availableNodes: [],
    enabledSensorIds: [],
    sensorSettings: {},
    sparklineData: {},
    activeAlarms: [],
    alarmState: {},       // tracks which sensors are currently in alarm (for hysteresis)
    showManager: false,
    initialized: false,
})

export async function initSensorConfig() {
    if (sensorConfig.initialized) return

    // Fetch node catalog from backend
    try {
        const res = await fetch('/api/connections')
        const data = await res.json()
        sensorConfig.availableNodes = data.opc_ua?.node_catalog || []
    } catch (e) {
        console.error('Failed to fetch node catalog:', e)
    }

    // Load saved preferences from localStorage
    const saved = loadFromStorage()
    if (saved) {
        sensorConfig.enabledSensorIds = saved.enabledSensorIds || DEFAULT_ENABLED.slice()
        sensorConfig.sensorSettings = saved.sensorSettings || {}
    } else {
        sensorConfig.enabledSensorIds = DEFAULT_ENABLED.slice()
    }

    // Ensure defaults exist for each node
    for (const node of sensorConfig.availableNodes) {
        if (!sensorConfig.sensorSettings[node.id]) {
            sensorConfig.sensorSettings[node.id] = {
                alias: '',
                color: node.default_color || '#94a3b8',
                icon: node.default_icon || '?',
                alarmHigh: null,
                alarmLow: null,
            }
        }
    }

    sensorConfig.initialized = true
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
    if (!sensorConfig.sensorSettings[id]) {
        sensorConfig.sensorSettings[id] = { alias: '', color: '#94a3b8', icon: '?', alarmHigh: null, alarmLow: null }
    }
    Object.assign(sensorConfig.sensorSettings[id], settings)
    saveSensorConfig()
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
        sensorConfig.sensorSettings[node.id] = {
            alias: '',
            color: node.default_color || '#94a3b8',
            icon: node.default_icon || '?',
            alarmHigh: null,
            alarmLow: null,
        }
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
