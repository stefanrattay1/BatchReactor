/**
 * Tests for PID canvas sensor coverage and dynamic node creation.
 *
 * Problem being tested:
 *   Sensors that appear in the SensorManager (e.g. PCV-101, XV-501) had no
 *   corresponding node in DEFAULT_NODES, so enabling them did nothing on the
 *   2D canvas. buildDynamicNodes() was introduced to fix this.
 */
import { describe, it, expect } from 'vitest'
import { DEFAULT_NODES } from '../config/pidLayout.js'
import { DEFAULT_TAGS, buildDynamicNodes, dynamicNodeId } from '../config/pidUtils.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSensor(overrides = {}) {
    return {
        id: 'test_sensor',
        name: 'Test Sensor',
        tag: 'XV-999',
        state_key: 'test_pv',
        unit: 'bar',
        category: 'valve',
        ...overrides,
    }
}

// ---------------------------------------------------------------------------
// DEFAULT_TAGS coverage — validates the hard-coded layout
// ---------------------------------------------------------------------------

describe('DEFAULT_TAGS coverage', () => {
    it('contains all core instrument tags', () => {
        const coreExpected = ['TT-101', 'PT-101', 'LT-101', 'FT-101', 'FT-102', 'FT-103']
        for (const tag of coreExpected) {
            expect(DEFAULT_TAGS.has(tag), `${tag} is missing from DEFAULT_NODES`).toBe(true)
        }
    })

    it('contains all feed valve and pump tags', () => {
        const feedExpected = ['XV-101', 'XV-102', 'XV-103', 'P-101', 'P-102', 'P-103']
        for (const tag of feedExpected) {
            expect(DEFAULT_TAGS.has(tag), `${tag} is missing from DEFAULT_NODES`).toBe(true)
        }
    })

    it('contains drain train tags', () => {
        const drainExpected = ['XV-301', 'P-301', 'FT-301']
        for (const tag of drainExpected) {
            expect(DEFAULT_TAGS.has(tag), `${tag} is missing from DEFAULT_NODES`).toBe(true)
        }
    })

    it('DEFAULT_NODES has no duplicate tags', () => {
        const tags = DEFAULT_NODES.map(n => n.data?.tag).filter(Boolean)
        const unique = new Set(tags)
        expect(tags.length).toBe(unique.size)
    })

    it('every DEFAULT_NODES instrument entry has a valueKey', () => {
        const instruments = DEFAULT_NODES.filter(n => n.type === 'instrument')
        for (const n of instruments) {
            expect(n.data?.valueKey, `${n.data?.tag} is missing valueKey`).toBeTruthy()
        }
    })
})

// ---------------------------------------------------------------------------
// buildDynamicNodes — the fix for sensors missing from the PID canvas
// ---------------------------------------------------------------------------

describe('buildDynamicNodes', () => {
    it('returns an empty array when no sensors are enabled', () => {
        expect(buildDynamicNodes([], [])).toEqual([])
    })

    it('creates a node for a core sensor without a tag if no DEFAULT_NODE covers its valueKey', () => {
        // "Total Mass" has no tag and no dedicated DEFAULT_NODE → should get a dynamic node
        const coreSensor = { id: 'mass_total', name: 'Total Mass', state_key: 'mass_total_kg', unit: 'kg', default_icon: 'M' }
        const nodes = buildDynamicNodes(['mass_total'], [coreSensor])
        expect(nodes).toHaveLength(1)
        expect(nodes[0].id).toBe('sensor_mass_total')
        expect(nodes[0].type).toBe('instrument')
        expect(nodes[0].data.tag).toBe('MT-101')
        expect(nodes[0].data.valueKey).toBe('mass_total_kg')
        expect(nodes[0].data.name).toBe('Total Mass')
    })

    it('skips a core sensor without a tag if a DEFAULT_NODE already shows its valueKey', () => {
        // "Temperature" has no tag but TT-101 already shows temperature_K
        const coreSensor = { id: 'temperature', name: 'Temperature', state_key: 'temperature_K', unit: 'K', default_icon: 'T' }
        const nodes = buildDynamicNodes(['temperature'], [coreSensor])
        expect(nodes).toHaveLength(0)
    })

    it('creates nodes for viscosity and conversion (no dedicated DEFAULT_NODE)', () => {
        const sensors = [
            { id: 'viscosity', name: 'Viscosity', state_key: 'viscosity_Pas', unit: 'Pa·s', default_icon: 'V' },
            { id: 'conversion', name: 'Conversion', state_key: 'conversion', unit: '', default_icon: 'X' },
        ]
        const nodes = buildDynamicNodes(['viscosity', 'conversion'], sensors)
        expect(nodes).toHaveLength(2)
        expect(nodes[0].data.valueKey).toBe('viscosity_Pas')
        expect(nodes[1].data.valueKey).toBe('conversion')
    })

    it('returns an empty array when sensor tag is already in DEFAULT_NODES', () => {
        // XV-101 already has a hard-coded node — no duplicate should be created
        const sensor = makeSensor({ id: 'xv_101', tag: 'XV-101' })
        const nodes = buildDynamicNodes(['xv_101'], [sensor])
        expect(nodes).toHaveLength(0)
    })

    it('creates a node for a sensor tag NOT in DEFAULT_NODES', () => {
        // PCV-101 is in the equipment config but has no DEFAULT_NODES entry
        const sensor = makeSensor({ id: 'pcv_101', tag: 'PCV-101', state_key: 'pcv_pv', unit: 'bar' })
        const nodes = buildDynamicNodes(['pcv_101'], [sensor])

        expect(nodes).toHaveLength(1)
        expect(nodes[0].id).toBe('sensor_pcv_101')
        expect(nodes[0].type).toBe('instrument')
        expect(nodes[0].data.tag).toBe('PCV-101')
        expect(nodes[0].data.valueKey).toBe('pcv_pv')
        expect(nodes[0].data.unit).toBe('bar')
    })

    it('creates nodes for multiple ungrouped sensors', () => {
        const sensors = [
            makeSensor({ id: 'pcv_101', tag: 'PCV-101' }),
            makeSensor({ id: 'xv_501', tag: 'XV-501' }),
            makeSensor({ id: 'xv_502', tag: 'XV-502' }),
        ]
        const ids = sensors.map(s => s.id)
        const nodes = buildDynamicNodes(ids, sensors)

        expect(nodes).toHaveLength(3)
        const tags = nodes.map(n => n.data.tag)
        expect(tags).toContain('PCV-101')
        expect(tags).toContain('XV-501')
        expect(tags).toContain('XV-502')
    })

    it('skips sensors that are enabled but missing from availableNodes catalog', () => {
        // If the catalog hasn't loaded yet enabledSensorIds may reference unknown ids
        const nodes = buildDynamicNodes(['ghost_sensor'], [])
        expect(nodes).toHaveLength(0)
    })

    it('uses savedPositions when available', () => {
        const sensor = makeSensor({ id: 'pcv_101', tag: 'PCV-101' })
        const saved = { 'sensor_pcv_101': { x: 300, y: 400 } }
        const nodes = buildDynamicNodes(['pcv_101'], [sensor], saved)

        expect(nodes[0].position).toEqual({ x: 300, y: 400 })
    })

    it('uses a default stacked position right of the main layout when no saved position exists', () => {
        const sensors = [
            makeSensor({ id: 'a', tag: 'XV-900' }),
            makeSensor({ id: 'b', tag: 'XV-901' }),
        ]
        const nodes = buildDynamicNodes(['a', 'b'], sensors)

        // Both nodes should be at the same x (right of main layout), stacked vertically
        expect(nodes[0].position.x).toBe(nodes[1].position.x)
        expect(nodes[0].position.x).toBeGreaterThan(600)   // right of rightmost default column (≈620)
        expect(nodes[1].position.y).toBeGreaterThan(nodes[0].position.y)
    })

    it('does not mix DEFAULT_NODES sensors and dynamic sensors', () => {
        // Even if both kinds are in enabledSensorIds, only uncovered ones get nodes
        const sensors = [
            makeSensor({ id: 'xv_101', tag: 'XV-101' }),  // already in DEFAULT_NODES
            makeSensor({ id: 'pcv_101', tag: 'PCV-101' }), // NOT in DEFAULT_NODES
        ]
        const nodes = buildDynamicNodes(['xv_101', 'pcv_101'], sensors)

        expect(nodes).toHaveLength(1)
        expect(nodes[0].data.tag).toBe('PCV-101')
    })
})

// ---------------------------------------------------------------------------
// dynamicNodeId — consistent ID generation
// ---------------------------------------------------------------------------

describe('dynamicNodeId', () => {
    it('prefixes sensor id with "sensor_"', () => {
        expect(dynamicNodeId('pcv_101')).toBe('sensor_pcv_101')
    })

    it('never collides with DEFAULT_NODES ids', () => {
        const defaultIds = new Set(DEFAULT_NODES.map(n => n.id))
        // All dynamic ids start with "sensor_"; verify no DEFAULT_NODES id does
        for (const id of defaultIds) {
            expect(id.startsWith('sensor_')).toBe(false)
        }
    })
})
