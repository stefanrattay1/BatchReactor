import { describe, expect, it } from 'vitest'

import {
    REACTOR_INPUT_HANDLE,
    REACTOR_SENSOR_HANDLE,
    canonicalizeEdge,
    findMatchingEdge,
    getPreferredHandleId,
    pruneExclusiveReactorPortEdges,
    validateConnection,
} from '../config/pidConnectionRules.js'

function makeNodes() {
    const reactor = { id: 'reactor', type: 'reactor', data: { connectionRole: 'reactor' } }
    const feed = { id: 'cm_FT-101', type: 'instrument', data: { tag: 'FT-101', connectionRole: 'feed' } }
    const sensor = {
        id: 'cm_PT-101',
        type: 'instrument',
        data: { tag: 'PT-101', connectionRole: 'sensor', attachSide: 'right' },
    }
    const jacket = { id: 'jacket', type: 'jacket', data: { connectionRole: 'jacket' } }
    const drain = { id: 'cm_XV-301', type: 'instrument', data: { tag: 'XV-301', connectionRole: 'drain' } }

    return {
        reactor,
        'cm_FT-101': feed,
        'cm_PT-101': sensor,
        jacket,
        'cm_XV-301': drain,
    }
}

describe('pidConnectionRules', () => {
    it('orients right-side sensors toward the reactor', () => {
        const sensor = makeNodes()['cm_PT-101']
        expect(getPreferredHandleId(sensor, 'source')).toBe('left')
        expect(getPreferredHandleId(sensor, 'target')).toBe('right')
    })

    it('migrates legacy reactor-to-sensor edges to sensor-to-reactor sensor-port edges', () => {
        const nodes = makeNodes()
        const edge = canonicalizeEdge({
            id: 'legacy',
            source: 'reactor',
            target: 'cm_PT-101',
            sourceHandle: 'product',
            type: 'pipe',
            data: {},
        }, nodes)

        expect(edge.source).toBe('cm_PT-101')
        expect(edge.target).toBe('reactor')
        expect(edge.sourceHandle).toBe('left')
        expect(edge.targetHandle).toBe(REACTOR_SENSOR_HANDLE)
    })

    it('allows PT-101 to connect to the dedicated reactor sensor port', () => {
        const result = validateConnection({
            source: 'cm_PT-101',
            target: 'reactor',
            sourceHandle: 'left',
            targetHandle: 'sensor',
        }, makeNodes(), [])

        expect(result.valid).toBe(true)
    expect(result.normalized.targetHandle).toBe('sensor')
    })

    it('rejects sensor connections to feed ports', () => {
        const result = validateConnection({
            source: 'cm_PT-101',
            target: 'reactor',
            sourceHandle: 'left',
            targetHandle: REACTOR_INPUT_HANDLE,
        }, makeNodes(), [])

        expect(result.valid).toBe(false)
        expect(result.reason).toMatch(/sensor port/i)
    })

    it('allows feed lines to land on the shared reactor input port', () => {
        const result = validateConnection({
            source: 'cm_FT-101',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: REACTOR_INPUT_HANDLE,
        }, makeNodes(), [])

        expect(result.valid).toBe(true)
    })

    it('canonicalizes legacy feed handle ids to the shared input handle', () => {
        const edge = canonicalizeEdge({
            id: 'legacy-feed',
            source: 'cm_FT-101',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: 'feed-top',
            type: 'pipe',
            data: {},
        }, makeNodes())

        expect(edge.targetHandle).toBe(REACTOR_INPUT_HANDLE)
    })

    it('returns the existing edge when a duplicate feed line is attempted', () => {
        const existingEdges = [{
            id: 'ft101-reactor',
            source: 'cm_FT-101',
            target: 'reactor',
            targetHandle: REACTOR_INPUT_HANDLE,
            type: 'pipe',
            data: { flowKey: 'feed_rate_component_a' },
        }]

        const result = validateConnection({
            source: 'cm_FT-101',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: REACTOR_INPUT_HANDLE,
        }, makeNodes(), existingEdges)

        expect(result.valid).toBe(false)
        expect(result.code).toBe('duplicate')
        expect(result.existingEdge.id).toBe('ft101-reactor')
    })

    it('does not treat the same persisted edge as a duplicate of itself', () => {
        const existingEdge = {
            id: 'ft101-reactor',
            source: 'cm_FT-101',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: REACTOR_INPUT_HANDLE,
            type: 'pipe',
            data: { flowKey: 'feed_rate_component_a' },
        }

        const result = validateConnection(existingEdge, makeNodes(), [existingEdge])

        expect(result.valid).toBe(true)
    })

    it('allows multiple different feed lines on the shared reactor input port', () => {
        const nodes = {
            ...makeNodes(),
            'cm_FT-102': { id: 'cm_FT-102', type: 'instrument', data: { tag: 'FT-102', connectionRole: 'feed' } },
        }
        const existingEdges = [{
            id: 'ft101-reactor',
            source: 'cm_FT-101',
            target: 'reactor',
            targetHandle: REACTOR_INPUT_HANDLE,
            type: 'pipe',
            data: { flowKey: 'feed_rate_component_a' },
        }]

        const result = validateConnection({
            source: 'cm_FT-102',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: REACTOR_INPUT_HANDLE,
        }, nodes, existingEdges)

        expect(result.valid).toBe(true)
    })

    it('treats reconnecting the same feed source to the shared input as a duplicate', () => {
        const existingEdges = [{
            id: 'ft101-reactor-a',
            source: 'cm_FT-101',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: REACTOR_INPUT_HANDLE,
            type: 'pipe',
            data: { flowKey: 'feed_rate_component_a' },
        }]

        const result = validateConnection({
            source: 'cm_FT-101',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: REACTOR_INPUT_HANDLE,
        }, makeNodes(), existingEdges)

        expect(result.valid).toBe(false)
        expect(result.code).toBe('duplicate')
        expect(result.existingEdge.id).toBe('ft101-reactor-a')
    })

    it('finds matching edges after canonicalization', () => {
        const match = findMatchingEdge({
            source: 'cm_FT-101',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: REACTOR_INPUT_HANDLE,
            type: 'pipe',
            data: {},
        }, [{
            id: 'ft101-reactor',
            source: 'cm_FT-101',
            target: 'reactor',
            targetHandle: REACTOR_INPUT_HANDLE,
            type: 'pipe',
            data: {},
        }], makeNodes())

        expect(match?.id).toBe('ft101-reactor')
    })

    it('keeps multiple different feed lines on the shared reactor input port', () => {
        const pruned = pruneExclusiveReactorPortEdges([
            {
                id: 'ft101-reactor',
                source: 'cm_FT-101',
                target: 'reactor',
                targetHandle: REACTOR_INPUT_HANDLE,
                type: 'pipe',
                data: {},
            },
            {
                id: 'ft102-reactor',
                source: 'cm_FT-102',
                target: 'reactor',
                targetHandle: REACTOR_INPUT_HANDLE,
                type: 'pipe',
                data: {},
            },
        ], {
            ...makeNodes(),
            'cm_FT-102': { id: 'cm_FT-102', type: 'instrument', data: { tag: 'FT-102', connectionRole: 'feed' } },
        })

        expect(pruned).toHaveLength(2)
    })

    it('keeps only the latest reactor attachment for the same feed source', () => {
        const pruned = pruneExclusiveReactorPortEdges([
            {
                id: 'ft102-reactor-b',
                source: 'cm_FT-102',
                target: 'reactor',
                sourceHandle: 'out',
                targetHandle: REACTOR_INPUT_HANDLE,
                type: 'pipe',
                data: {},
            },
            {
                id: 'ft102-reactor-a',
                source: 'cm_FT-102',
                target: 'reactor',
                sourceHandle: 'out',
                targetHandle: REACTOR_INPUT_HANDLE,
                type: 'pipe',
                data: {},
            },
        ], {
            ...makeNodes(),
            'cm_FT-102': { id: 'cm_FT-102', type: 'instrument', data: { tag: 'FT-102', connectionRole: 'feed' } },
        })

        expect(pruned).toHaveLength(1)
        expect(pruned[0].id).toBe('ft102-reactor-a')
        expect(pruned[0].targetHandle).toBe(REACTOR_INPUT_HANDLE)
    })

    it('keeps jacket connections exclusive to the jacket port', () => {
        const result = validateConnection({
            source: 'jacket',
            target: 'reactor',
            sourceHandle: 'out',
            targetHandle: 'sensor',
        }, makeNodes(), [])

        expect(result.valid).toBe(false)
        expect(result.reason).toMatch(/jacket port/i)
    })

    it('allows reactor product outlet connections into the drain train only', () => {
        const result = validateConnection({
            source: 'reactor',
            target: 'cm_XV-301',
            sourceHandle: 'product',
            targetHandle: 'in',
        }, makeNodes(), [])

        expect(result.valid).toBe(true)
    })
})