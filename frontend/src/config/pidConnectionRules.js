export const REACTOR_SENSOR_HANDLE = 'sensor'
export const REACTOR_PRODUCT_HANDLE = 'product'
export const REACTOR_INPUT_HANDLE = 'feed'
export const REACTOR_LEGACY_FEED_HANDLES = ['feed-top', 'feed-center', 'feed-right']
export const REACTOR_FEED_HANDLES = [REACTOR_INPUT_HANDLE, ...REACTOR_LEGACY_FEED_HANDLES]

const EXCLUSIVE_REACTOR_TARGET_HANDLES = new Set([
    'jacket',
    'agitator',
])

const EXCLUSIVE_REACTOR_SOURCE_HANDLES = new Set([
    REACTOR_PRODUCT_HANDLE,
])

const SINGLE_REACTOR_ATTACHMENT_SOURCE_ROLES = new Set([
    'feed',
    'sensor',
    'jacket',
    'agitator',
])

const SENSOR_PREFIXES = new Set(['TT', 'PT', 'LT', 'ST', 'XT', 'VT', 'MT'])

function getTagPrefix(tag) {
    return String(tag || '').trim().toUpperCase().split('-')[0] || ''
}

function getNodeLabel(node, fallbackId = 'Equipment') {
    return node?.data?.tag || node?.data?.label || node?.data?.name || node?.id || fallbackId
}

function normalizeReactorHandle(handleId) {
    if (REACTOR_LEGACY_FEED_HANDLES.includes(handleId)) return REACTOR_INPUT_HANDLE
    return handleId
}

export function getReactorPortLabel(handleId) {
    switch (normalizeReactorHandle(handleId)) {
        case REACTOR_INPUT_HANDLE:
            return 'Input Port'
        case REACTOR_SENSOR_HANDLE:
            return 'Sensor Port'
        case 'jacket':
            return 'Jacket Port'
        case 'agitator':
            return 'Agitator Port'
        case REACTOR_PRODUCT_HANDLE:
            return 'Product Outlet'
        default:
            return handleId || 'connected port'
    }
}

function getExclusiveReactorPortKey(edge) {
    const normalizedTargetHandle = normalizeReactorHandle(edge.targetHandle)
    if (edge.target === 'reactor' && EXCLUSIVE_REACTOR_TARGET_HANDLES.has(normalizedTargetHandle)) {
        return `target:${normalizedTargetHandle}`
    }

    const normalizedSourceHandle = normalizeReactorHandle(edge.sourceHandle)
    if (edge.source === 'reactor' && EXCLUSIVE_REACTOR_SOURCE_HANDLES.has(normalizedSourceHandle)) {
        return `source:${normalizedSourceHandle}`
    }

    return null
}

function getSingleReactorAttachmentSourceKey(edge, nodesById = {}) {
    if (edge.target !== 'reactor') return null

    const sourceRole = getConnectionRole(nodesById[edge.source])
    if (!SINGLE_REACTOR_ATTACHMENT_SOURCE_ROLES.has(sourceRole)) return null

    return `target-source:${edge.source}`
}

export function getConnectionRole(node) {
    if (!node) return 'unknown'

    const explicitRole = node.data?.connectionRole
    if (explicitRole) return explicitRole

    if (node.type === 'reactor') return 'reactor'
    if (node.type === 'feed') return 'feed'
    if (node.type === 'jacket') return 'jacket'
    if (node.type === 'agitator') return 'agitator'
    if (node.type === 'product') return 'product'

    const prefix = getTagPrefix(node.data?.tag)
    if (SENSOR_PREFIXES.has(prefix)) return 'sensor'

    return 'instrument'
}

export function getSensorFacingHandle(side) {
    switch (side) {
        case 'left':
            return 'right'
        case 'bottom':
            return 'top'
        case 'top-right':
            return 'left'
        case 'right':
        default:
            return 'left'
    }
}

function getOppositeHandle(handleId) {
    switch (handleId) {
        case 'left':
            return 'right'
        case 'right':
            return 'left'
        case 'top':
            return 'bottom'
        case 'bottom':
            return 'top'
        default:
            return null
    }
}

export function getPreferredHandleId(node, direction) {
    if (!node) return direction === 'source' ? 'out' : 'in'

    const explicit = direction === 'source'
        ? node.data?.preferredSourceHandle
        : node.data?.preferredTargetHandle
    if (explicit) return explicit

    if (getConnectionRole(node) === 'sensor') {
        const sourceHandle = getSensorFacingHandle(node.data?.attachSide)
        return direction === 'source' ? sourceHandle : getOppositeHandle(sourceHandle)
    }

    return direction === 'source' ? 'out' : 'in'
}

export function canonicalizeEdge(edge, nodesById = {}) {
    const sourceNode = nodesById[edge.source]
    const targetNode = nodesById[edge.target]
    const sourceRole = getConnectionRole(sourceNode)
    const targetRole = getConnectionRole(targetNode)

    let normalized = {
        ...edge,
        type: edge.type || 'pipe',
        data: { ...(edge.data || {}) },
    }

    let sourceHandle = normalized.sourceHandle ?? normalized.sourceHandleId ?? null
    let targetHandle = normalized.targetHandle ?? normalized.targetHandleId ?? null

    sourceHandle = normalizeReactorHandle(sourceHandle)
    targetHandle = normalizeReactorHandle(targetHandle)

    delete normalized.sourceHandle
    delete normalized.targetHandle
    delete normalized.sourceHandleId
    delete normalized.targetHandleId

    // Migrate old reactor -> sensor edges to the current sensor -> reactor contract.
    if (sourceRole === 'reactor' && targetRole === 'sensor') {
        normalized = {
            ...normalized,
            source: edge.target,
            target: edge.source,
        }
        sourceHandle = getPreferredHandleId(targetNode, 'source')
        targetHandle = REACTOR_SENSOR_HANDLE
    }

    if (normalized.source === 'reactor' && sourceHandle == null) {
        sourceHandle = REACTOR_PRODUCT_HANDLE
    }

    if (normalized.target === 'reactor') {
        if (targetHandle == null && getConnectionRole(nodesById[normalized.source]) === 'sensor') {
            targetHandle = REACTOR_SENSOR_HANDLE
        }
    } else if (targetHandle == null) {
        targetHandle = getPreferredHandleId(nodesById[normalized.target], 'target')
    }

    if (normalized.source !== 'reactor' && sourceHandle == null) {
        sourceHandle = getPreferredHandleId(nodesById[normalized.source], 'source')
    }

    if (sourceHandle != null) normalized.sourceHandle = sourceHandle
    if (targetHandle != null) normalized.targetHandle = targetHandle

    return normalized
}

export function edgeIdentity(edge) {
    return [
        edge.source,
        edge.target,
        edge.sourceHandle || '',
        edge.targetHandle || '',
    ].join('|')
}

export function dedupeEdges(edges) {
    const seen = new Set()
    const result = []

    for (const edge of edges) {
        const identity = edgeIdentity(edge)
        if (seen.has(identity)) continue
        seen.add(identity)
        result.push(edge)
    }

    return result
}

export function pruneExclusiveReactorPortEdges(edges, nodesById = {}) {
    const normalizedEdges = edges.map(edge => canonicalizeEdge(edge, nodesById))
    const lastSourceAttachmentIndex = new Map()

    normalizedEdges.forEach((edge, index) => {
        const sourceKey = getSingleReactorAttachmentSourceKey(edge, nodesById)
        if (sourceKey) lastSourceAttachmentIndex.set(sourceKey, index)
    })

    const seenIdentities = new Set()
    const seenExclusivePorts = new Set()
    const result = []

    for (const [index, normalized] of normalizedEdges.entries()) {
        const sourceKey = getSingleReactorAttachmentSourceKey(normalized, nodesById)
        if (sourceKey && lastSourceAttachmentIndex.get(sourceKey) !== index) continue

        const identity = edgeIdentity(normalized)
        if (seenIdentities.has(identity)) continue

        const exclusiveKey = getExclusiveReactorPortKey(normalized)
        if (exclusiveKey && seenExclusivePorts.has(exclusiveKey)) continue

        seenIdentities.add(identity)
        if (exclusiveKey) seenExclusivePorts.add(exclusiveKey)
        result.push(normalized)
    }

    return result
}

export function summarizeReactorPortOccupancy(edges, nodesById = {}) {
    const occupancy = {}

    for (const edge of edges) {
        const normalized = canonicalizeEdge(edge, nodesById)

        if (normalized.target === 'reactor' && normalized.targetHandle) {
            const handleId = normalized.targetHandle
            occupancy[handleId] = occupancy[handleId] || []
            occupancy[handleId].push(getNodeLabel(nodesById[normalized.source], normalized.source))
        }

        if (normalized.source === 'reactor' && normalized.sourceHandle) {
            const handleId = normalized.sourceHandle
            occupancy[handleId] = occupancy[handleId] || []
            occupancy[handleId].push(getNodeLabel(nodesById[normalized.target], normalized.target))
        }
    }

    return occupancy
}

export function findMatchingEdge(candidateEdge, existingEdges = [], nodesById = {}) {
    const normalizedCandidate = canonicalizeEdge(candidateEdge, nodesById)
    const identity = edgeIdentity(normalizedCandidate)

    return existingEdges.find(edge => {
        const normalizedEdge = canonicalizeEdge(edge, nodesById)

        if (normalizedCandidate.id && normalizedEdge.id && normalizedCandidate.id === normalizedEdge.id) {
            return false
        }

        return edgeIdentity(normalizedEdge) === identity
    }) || null
}

export function findExclusiveReactorPortConflict(candidateEdge, existingEdges = [], nodesById = {}) {
    const normalizedCandidate = canonicalizeEdge(candidateEdge, nodesById)
    const candidateIdentity = edgeIdentity(normalizedCandidate)
    const exclusiveKey = getExclusiveReactorPortKey(normalizedCandidate)
    if (!exclusiveKey) return null

    return existingEdges.find(edge => {
        const normalizedEdge = canonicalizeEdge(edge, nodesById)
        return getExclusiveReactorPortKey(normalizedEdge) === exclusiveKey
            && edgeIdentity(normalizedEdge) !== candidateIdentity
    }) || null
}

export function findSingleReactorAttachmentConflict(candidateEdge, existingEdges = [], nodesById = {}) {
    const normalizedCandidate = canonicalizeEdge(candidateEdge, nodesById)
    const candidateIdentity = edgeIdentity(normalizedCandidate)
    const sourceKey = getSingleReactorAttachmentSourceKey(normalizedCandidate, nodesById)
    if (!sourceKey) return null

    return existingEdges.find(edge => {
        const normalizedEdge = canonicalizeEdge(edge, nodesById)
        return getSingleReactorAttachmentSourceKey(normalizedEdge, nodesById) === sourceKey
            && edgeIdentity(normalizedEdge) !== candidateIdentity
    }) || null
}

function describeExpectedHandle(sourceRole) {
    switch (sourceRole) {
        case 'feed':
            return 'the shared reactor input port'
        case 'jacket':
            return 'the jacket port'
        case 'agitator':
            return 'the agitator port'
        case 'sensor':
            return 'the sensor port'
        default:
            return 'a compatible reactor port'
    }
}

export function getConnectionHint(node) {
    switch (getConnectionRole(node)) {
        case 'feed':
            return 'Feed lines can share the single reactor input port.'
        case 'sensor':
            return 'Reactor sensors attach to the dedicated reactor sensor port.'
        case 'jacket':
            return 'The jacket loop can only attach to the jacket port.'
        case 'agitator':
            return 'The agitator can only attach to the agitator port.'
        case 'reactor':
            return 'Reactor outlet connections leave from PRODUCT at the bottom.'
        default:
            return 'Connect process equipment in sequence, or land on the compatible reactor port.'
    }
}

export function validateConnection(params, nodesById, existingEdges = []) {
    const { source, target } = params
    if (!source || !target) return { valid: false, reason: 'Both source and target are required.' }
    if (source === target) return { valid: false, reason: 'Self-connections are not allowed.' }

    const sourceNode = nodesById[source]
    const targetNode = nodesById[target]
    if (!sourceNode || !targetNode) {
        return { valid: false, reason: 'The connection references a node that is not on the canvas.' }
    }

    const sourceRole = getConnectionRole(sourceNode)
    const targetRole = getConnectionRole(targetNode)

    const normalized = canonicalizeEdge({
        id: params.id || '__candidate__',
        source,
        target,
        sourceHandle: params.sourceHandle,
        targetHandle: params.targetHandle,
        type: 'pipe',
        data: params.data || {},
    }, nodesById)

    if (sourceRole === 'sensor' || targetRole === 'sensor') {
        const isValidSensorAttachment =
            getConnectionRole(nodesById[normalized.source]) === 'sensor' &&
            normalized.target === 'reactor' &&
            normalized.targetHandle === REACTOR_SENSOR_HANDLE

        if (!isValidSensorAttachment) {
            return {
                valid: false,
                reason: 'Sensor instruments can only attach to the reactor sensor port.',
            }
        }
    }

    if (sourceRole === 'jacket' || targetRole === 'jacket') {
        if (!(sourceRole === 'jacket' && normalized.target === 'reactor' && normalized.targetHandle === 'jacket')) {
            return { valid: false, reason: 'The jacket loop can only connect to the reactor jacket port.' }
        }
    }

    if (sourceRole === 'agitator' || targetRole === 'agitator') {
        if (!(sourceRole === 'agitator' && normalized.target === 'reactor' && normalized.targetHandle === 'agitator')) {
            return { valid: false, reason: 'The agitator can only connect to the reactor agitator port.' }
        }
    }

    if (normalized.target === 'reactor') {
        if (sourceRole === 'feed' && !REACTOR_FEED_HANDLES.includes(normalized.targetHandle)) {
            return {
                valid: false,
                reason: `Feed lines must connect to ${describeExpectedHandle(sourceRole)}.`,
            }
        }
        if (sourceRole === 'sensor' && normalized.targetHandle !== REACTOR_SENSOR_HANDLE) {
            return {
                valid: false,
                reason: 'Sensors must land on the reactor sensor port.',
            }
        }
        if (sourceRole === 'jacket' && normalized.targetHandle !== 'jacket') {
            return { valid: false, reason: 'The jacket loop must land on the jacket port.' }
        }
        if (sourceRole === 'agitator' && normalized.targetHandle !== 'agitator') {
            return { valid: false, reason: 'The agitator must land on the agitator port.' }
        }
        if (!['feed', 'sensor', 'jacket', 'agitator'].includes(sourceRole)) {
            return { valid: false, reason: 'That equipment cannot attach directly to the reactor.' }
        }
    }

    if (normalized.source === 'reactor') {
        if (normalized.sourceHandle !== REACTOR_PRODUCT_HANDLE) {
            return { valid: false, reason: 'Reactor outlet connections must leave from PRODUCT.' }
        }
        if (['feed', 'sensor', 'jacket', 'agitator'].includes(targetRole)) {
            return { valid: false, reason: 'Reactor outlet connections can only continue into the discharge train.' }
        }
    }

    const sourceAttachmentConflict = findSingleReactorAttachmentConflict(normalized, existingEdges, nodesById)
    if (sourceAttachmentConflict) {
        return {
            valid: false,
            reason: `${getNodeLabel(sourceNode)} is already attached to the reactor input. Remove the existing connection first.`,
            code: 'source-already-connected',
            existingEdge: canonicalizeEdge(sourceAttachmentConflict, nodesById),
        }
    }

    const portConflict = findExclusiveReactorPortConflict(normalized, existingEdges, nodesById)
    if (portConflict) {
        const blockedHandle = normalized.target === 'reactor'
            ? normalized.targetHandle
            : normalized.sourceHandle
        return {
            valid: false,
            reason: `${getReactorPortLabel(blockedHandle)} is already occupied.`,
            code: 'port-occupied',
            blockedHandle,
            existingEdge: canonicalizeEdge(portConflict, nodesById),
        }
    }

    const existingEdge = findMatchingEdge(normalized, existingEdges, nodesById)
    if (existingEdge) {
        return {
            valid: false,
            reason: 'That connection already exists.',
            code: 'duplicate',
            existingEdge: canonicalizeEdge(existingEdge, nodesById),
        }
    }

    return {
        valid: true,
        normalized,
    }
}