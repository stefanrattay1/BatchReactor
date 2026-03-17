/**
 * Pure utility functions for PID canvas node management.
 * Kept separate so they can be unit-tested without Vue or a DOM.
 */
import { DEFAULT_NODES } from './pidLayout.js'

/** Set of P&ID tags that already have a hard-coded entry in DEFAULT_NODES. */
export const DEFAULT_TAGS = new Set(
    DEFAULT_NODES.map(n => n.data?.tag).filter(Boolean)
)

/** Set of valueKeys already covered by a dedicated sensor node in DEFAULT_NODES. */
const DEFAULT_VALUE_KEYS = new Set(
    DEFAULT_NODES
        .filter(n => n.id.endsWith('_sensor'))
        .map(n => n.data?.valueKey)
        .filter(Boolean)
)

/** Map icon letter → ISA tag prefix for synthetic tags on core sensors. */
const ICON_TO_PREFIX = { T: 'TT', P: 'PT', X: 'XT', V: 'VT', M: 'MT', L: 'LT' }
let _syntheticCounter = 101

/**
 * Build instrument nodes for enabled sensors that don't already have
 * a corresponding entry in DEFAULT_NODES.
 *
 * Handles two cases:
 *   1. Equipment sensors with a `tag` — created if tag not in DEFAULT_TAGS
 *   2. Core sensors without a `tag` — created with a synthetic tag if no
 *      DEFAULT_NODE already shows their valueKey as a dedicated sensor
 *
 * @param {string[]} enabledSensorIds - IDs from sensorConfig.enabledSensorIds
 * @param {object[]} availableNodes   - Full catalog from sensorConfig.availableNodes
 * @param {object}   savedPositions   - Saved {nodeId: {x, y}} from the layout API
 * @returns {object[]} Vue Flow node objects ready to push into nodes.value
 */
export function buildDynamicNodes(enabledSensorIds, availableNodes, savedPositions = {}) {
    const result = []
    let yOffset = 0

    for (const id of enabledSensorIds) {
        const sensor = availableNodes.find(n => n.id === id)
        if (!sensor) continue

        let tag = sensor.tag
        if (tag) {
            // Equipment sensor: skip if DEFAULT_NODES already has this tag
            if (DEFAULT_TAGS.has(tag)) continue
        } else {
            // Core sensor: skip if a dedicated sensor node already covers this valueKey
            if (DEFAULT_VALUE_KEYS.has(sensor.state_key)) continue
            // Generate a synthetic tag from the icon letter
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
 * Consistent naming avoids collisions with DEFAULT_NODES ids.
 */
export function dynamicNodeId(sensorId) {
    return `sensor_${sensorId}`
}
