/**
 * Pure utility functions for PID canvas node management.
 * Kept separate so they can be unit-tested without Vue or a DOM.
 */
import { DEFAULT_NODES } from './pidLayout.js'

/** Legacy set — used only when no baseNodes are passed to buildDynamicNodes. */
const LEGACY_TAGS = new Set(
    DEFAULT_NODES.map(n => n.data?.tag).filter(Boolean)
)

export const DEFAULT_TAGS = LEGACY_TAGS

const LEGACY_VALUE_KEYS = new Set(
    DEFAULT_NODES
        .filter(n => n.id.endsWith('_sensor'))
        .map(n => n.data?.valueKey)
        .filter(Boolean)
)

/** Extract active tags from any node set (config-driven or legacy). */
export function getActiveTags(baseNodes) {
    return new Set(baseNodes.map(n => n.data?.tag).filter(Boolean))
}

/** Extract active valueKeys from sensor-type nodes in any node set. */
function getActiveValueKeys(baseNodes) {
    return new Set(
        baseNodes
            .filter(n => n.type === 'instrument' || n.id.endsWith('_sensor'))
            .map(n => n.data?.valueKey)
            .filter(Boolean)
    )
}

/** Map icon letter → ISA tag prefix for synthetic tags on core sensors. */
const ICON_TO_PREFIX = { T: 'TT', P: 'PT', X: 'XT', V: 'VT', M: 'MT', L: 'LT' }
let _syntheticCounter = 101

/**
 * Build instrument nodes for enabled sensors that don't already have
 * a corresponding entry in the active base nodes.
 *
 * @param {string[]} enabledSensorIds - IDs from sensorConfig.enabledSensorIds
 * @param {object[]} availableNodes   - Full catalog from sensorConfig.availableNodes
 * @param {object}   savedPositions   - Saved {nodeId: {x, y}} from the layout API
 * @param {object[]} [baseNodes]      - Active base node set (config-driven or legacy).
 *                                      Falls back to DEFAULT_NODES if omitted.
 * @returns {object[]} Vue Flow node objects ready to push into nodes.value
 */
export function buildDynamicNodes(enabledSensorIds, availableNodes, savedPositions = {}, baseNodes = null) {
    const activeTags = baseNodes ? getActiveTags(baseNodes) : LEGACY_TAGS
    const activeValueKeys = baseNodes ? getActiveValueKeys(baseNodes) : LEGACY_VALUE_KEYS

    const result = []
    let yOffset = 0

    for (const id of enabledSensorIds) {
        const sensor = availableNodes.find(n => n.id === id)
        if (!sensor) continue

        let tag = sensor.tag
        if (tag) {
            if (activeTags.has(tag)) continue
        } else {
            if (activeValueKeys.has(sensor.state_key)) continue
            const prefix = ICON_TO_PREFIX[sensor.default_icon] || 'ST'
            tag = `${prefix}-${_syntheticCounter}`
        }

        const nodeId = `sensor_${id}`
        const saved = savedPositions[nodeId]
        result.push({
            id: nodeId,
            type: 'instrument',
            position: saved
                ? { x: saved.x, y: saved.y }
                : { x: 720, y: 200 + yOffset * 110 },
            data: {
                tag,
                name: sensor.name,
                valueKey: sensor.state_key || '',
                unit: sensor.unit || '',
            },
        })
        yOffset++
    }

    return result
}

/**
 * Return the Vue Flow node id used for a dynamically-added sensor.
 * Consistent naming avoids collisions with base node ids.
 */
export function dynamicNodeId(sensorId) {
    return `sensor_${sensorId}`
}
