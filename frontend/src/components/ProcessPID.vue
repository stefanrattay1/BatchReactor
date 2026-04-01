<script setup>
import { ref, watch, computed, onMounted, onUnmounted, nextTick, markRaw } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'

import ReactorNode from './pid/ReactorNode.vue'
import FeedNode from './pid/FeedNode.vue'
import JacketNode from './pid/JacketNode.vue'
import AgitatorNode from './pid/AgitatorNode.vue'
import ProductNode from './pid/ProductNode.vue'
import InstrumentNode from './pid/InstrumentNode.vue'
import PipeEdge from './pid/PipeEdge.vue'
import PidToolbar from './pid/PidToolbar.vue'

import { DEFAULT_NODES, DEFAULT_EDGES } from '../config/pidLayout'
import { buildDynamicNodes } from '../config/pidUtils'
import { fetchPidTopology } from '../config/pidTopology'
import { autoLayout } from '../config/pidAutoLayout'
import {
    canonicalizeEdge,
    dedupeEdges,
    getConnectionHint,
    getReactorPortLabel,
    pruneExclusiveReactorPortEdges,
    summarizeReactorPortOccupancy,
    validateConnection,
} from '../config/pidConnectionRules'
import { sensorConfig } from '../services/sensorConfig'
import { pidVisibility, showAllNodes, showNode } from '../services/pidVisibility'
import { pidEditMode } from '../services/pidEditMode'

const emit = defineEmits(['select-equipment', 'edit-node', 'select-edge'])
const selected = defineModel('selected', { type: String, default: null })

const flowRef = ref(null)
const flowInstance = ref(null)
const flowReady = ref(false)
const nodes = ref([])
const edges = ref([])
const savedPositions = ref({})

// Config-driven base nodes/edges (or legacy fallback)
const topologyBase = ref({ nodes: [], edges: [] })

// Overlay: persisted user edits on top of topology
const overlay = ref({ node_data_overrides: {}, added_edges: [], removed_edge_ids: [] })

// Pending (unsaved) edits
const pendingNodeEdits = ref({})
const pendingNewEdges = ref([])
const pendingDeletedEdgeIds = ref(new Set())

// Selected edge (for edit mode)
const selectedEdgeId = ref(null)
const highlightedEdgeId = ref(null)
const connectionHint = ref('')
const pendingInvalidReason = ref('')
const lastInvalidResult = ref(null)
const banner = ref({ message: '', tone: 'info' })
let bannerTimeout = null
let edgeHighlightTimeout = null
let lastConnectionAcceptedAt = 0
let rebuildSequence = 0

const edgeTypes = { pipe: markRaw(PipeEdge) }

function syncFlowGraph(nextNodes, nextEdges) {
    if (!flowReady.value || !flowInstance.value) return

    const syncId = ++rebuildSequence
    nextTick(() => {
        if (syncId !== rebuildSequence || !flowInstance.value) return

        if (typeof flowInstance.value.setNodes === 'function') {
            flowInstance.value.setNodes(nextNodes)
        }

        requestAnimationFrame(() => {
            if (syncId !== rebuildSequence || !flowInstance.value) return
            if (typeof flowInstance.value.setEdges === 'function') {
                flowInstance.value.setEdges(nextEdges)
            }
        })
    })
}

function onFlowInit(instance) {
    flowInstance.value = instance
    syncFlowGraph(nodes.value, edges.value)
}

// Computed props for Vue Flow reactivity
const isConnectable = computed(() => pidEditMode.active)
const isEdgesUpdatable = computed(() => pidEditMode.active)
const deleteKeyCode = computed(() => pidEditMode.active ? 'Delete' : null)
const bgColor = computed(() =>
    pidEditMode.active ? 'rgba(210, 133, 72, 0.14)' : 'rgba(151, 162, 171, 0.16)'
)

// Build all nodes (before filtering), applying overlay + pending edits
function buildAllNodes() {
    const pos = savedPositions.value
    const overrides = { ...overlay.value.node_data_overrides, ...pendingNodeEdits.value }

    const base = topologyBase.value.nodes.map(n => {
        const edited = overrides[n.id]
        const data = edited ? { ...n.data, ...edited } : n.data
        return {
            ...n,
            data,
            position: pos[n.id] ? { x: pos[n.id].x, y: pos[n.id].y } : { ...n.position },
        }
    })
    const dynamic = buildDynamicNodes(
        sensorConfig.enabledSensorIds,
        sensorConfig.availableNodes,
        pos,
        topologyBase.value.nodes,
    )
    return [...base, ...dynamic]
}

const allNodes = computed(() => buildAllNodes())
const nodeIndex = computed(() => Object.fromEntries(allNodes.value.map(node => [node.id, node])))

function showBanner(message, tone = 'info') {
    if (!message) return
    banner.value = { message, tone }
    if (bannerTimeout) clearTimeout(bannerTimeout)
    bannerTimeout = setTimeout(() => {
        banner.value = { message: '', tone: 'info' }
    }, 2800)
}

function getNodeLabel(node) {
    return node?.data?.tag || node?.data?.label || node?.data?.name || node?.id || 'Equipment'
}

function describeExistingConnection(edge) {
    const sourceNode = nodeIndex.value[edge.source]
    const targetNode = nodeIndex.value[edge.target]
    const sourceLabel = getNodeLabel(sourceNode)
    const targetLabel = getNodeLabel(targetNode)

    if (edge.target === 'reactor') {
        return `${sourceLabel} is already connected to ${getReactorPortLabel(edge.targetHandle)} on ${targetLabel}.`
    }

    if (edge.source === 'reactor') {
        return `${targetLabel} is already connected to ${getReactorPortLabel(edge.sourceHandle)} on ${sourceLabel}.`
    }

    return `${sourceLabel} is already connected to ${targetLabel}.`
}

function focusEdge(edgeId) {
    highlightedEdgeId.value = edgeId
    if (edgeHighlightTimeout) clearTimeout(edgeHighlightTimeout)
    edgeHighlightTimeout = setTimeout(() => {
        if (highlightedEdgeId.value === edgeId) highlightedEdgeId.value = null
    }, 2600)
}

// Build all edges (base + overlay added - overlay removed + pending)
function normalizeEdge(edge) {
    return canonicalizeEdge(edge, nodeIndex.value)
}

function describeRejectedConnection(result) {
    if (!result) return ''
    if ((result.code === 'duplicate' || result.code === 'port-occupied' || result.code === 'source-already-connected') && result.existingEdge) {
        return describeExistingConnection(result.existingEdge)
    }
    return result.reason || ''
}

function focusExistingEdge(edge) {
    if (!edge) return
    selectedEdgeId.value = edge.id
    focusEdge(edge.id)
    emit('select-edge', edge)
}

function buildAllEdges() {
    const removedIds = new Set([
        ...overlay.value.removed_edge_ids,
        ...pendingDeletedEdgeIds.value,
    ])
    const baseEdges = topologyBase.value.edges
        .filter(e => !removedIds.has(e.id))
        .map(normalizeEdge)
    const overlayEdges = (overlay.value.added_edges || [])
        .filter(e => !removedIds.has(e.id))
        .map(normalizeEdge)
    const pendingEdges = pendingNewEdges.value
        .filter(e => !removedIds.has(e.id))
        .map(normalizeEdge)
    return pruneExclusiveReactorPortEdges(
        dedupeEdges([...baseEdges, ...overlayEdges, ...pendingEdges]),
        nodeIndex.value,
    )
}

// Filter out hidden nodes and edges referencing hidden nodes
function rebuildVisible() {
    const visibleIds = new Set()

    const visibleNodes = allNodes.value.filter(n => {
        if (pidVisibility.hiddenIds.has(n.id)) return false
        visibleIds.add(n.id)
        return true
    })

    const visibleEdges = buildAllEdges()
        .filter(e => visibleIds.has(e.source) && visibleIds.has(e.target))
    const reactorPortOccupancy = summarizeReactorPortOccupancy(visibleEdges, nodeIndex.value)

    nodes.value = visibleNodes.map(node => {
        if (node.id !== 'reactor') return node
        return {
            ...node,
            data: {
                ...(node.data || {}),
                portOccupancy: reactorPortOccupancy,
            },
        }
    })

    const renderedEdges = visibleEdges.map(e => {
        const emphasized = e.id === selectedEdgeId.value || e.id === highlightedEdgeId.value
        return {
            ...e,
            selected: emphasized,
            data: {
                ...(e.data || {}),
                emphasized,
            },
        }
    })

    edges.value = renderedEdges
    syncFlowGraph(nodes.value, renderedEdges)
}

// Load overlay from backend
async function loadOverlay() {
    overlay.value = {
        node_data_overrides: {},
        added_edges: [],
        removed_edge_ids: [],
    }

    try {
        const res = await fetch('/api/pid/overlay')
        if (res.ok) {
            const data = await res.json()
            if (data && Object.keys(data).length > 0) {
                overlay.value = {
                    node_data_overrides: data.node_data_overrides || {},
                    added_edges: (data.added_edges || []).map(normalizeEdge),
                    removed_edge_ids: data.removed_edge_ids || [],
                }
            }
        }
    } catch (e) { /* ignore */ }
}

// Load topology + overlay + saved positions, then build visible nodes
async function loadLayout() {
    savedPositions.value = {}

    const topo = await fetchPidTopology()
    if (topo.version) {
        topologyBase.value = {
            nodes: autoLayout(topo.nodes),
            edges: topo.edges,
        }
    } else {
        topologyBase.value = {
            nodes: DEFAULT_NODES,
            edges: DEFAULT_EDGES,
        }
    }

    await loadOverlay()

    try {
        const res = await fetch('/api/pid/layout')
        if (res.ok) {
            const data = await res.json()
            if (data && Object.keys(data).length > 0) {
                savedPositions.value = data
            }
        }
    } catch (e) { /* ignore */ }

    rebuildVisible()
    await nextTick()
    flowReady.value = true
}

async function handleTopologyRefresh() {
    selectedEdgeId.value = null
    highlightedEdgeId.value = null
    await loadLayout()
    setTimeout(() => flowRef.value?.fitView?.({ padding: 0.15 }), 50)
}

// Save layout to backend on drag end
let saveTimeout = null
function onNodeDragStop() {
    if (saveTimeout) clearTimeout(saveTimeout)
    saveTimeout = setTimeout(saveLayout, 500)
}

async function saveLayout() {
    const positions = {}
    for (const node of nodes.value) {
        positions[node.id] = { x: node.position.x, y: node.position.y }
    }
    try {
        await fetch('/api/pid/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(positions),
        })
        savedPositions.value = positions
    } catch (e) { /* ignore */ }
}

// Reset layout to defaults
async function resetLayout() {
    try {
        await fetch('/api/pid/layout', { method: 'DELETE' })
    } catch (e) { /* ignore */ }
    savedPositions.value = {}
    showAllNodes()
    rebuildVisible()
    setTimeout(() => flowRef.value?.fitView?.({ padding: 0.15 }), 50)
}

// --- Edit mode: connection handling ---

let edgeCounter = 0

function isValidConnection({ source, target, sourceHandle, targetHandle, id, data, type }, context) {
    const existingEdges = context?.edges || buildAllEdges()
    const result = validateConnection(
        { source, target, sourceHandle, targetHandle, id, data, type },
        nodeIndex.value,
        existingEdges,
    )

    if (!context) {
        lastInvalidResult.value = result.valid ? null : result
        pendingInvalidReason.value = result.valid ? '' : result.reason
    }

    return result.valid
}

function onConnectStart({ nodeId }) {
    connectionHint.value = getConnectionHint(nodeIndex.value[nodeId])
    pendingInvalidReason.value = ''
    lastInvalidResult.value = null
}

function onConnectEnd() {
    if (lastInvalidResult.value && Date.now() - lastConnectionAcceptedAt > 150) {
        if (lastInvalidResult.value.existingEdge) {
            focusExistingEdge(lastInvalidResult.value.existingEdge)
            rebuildVisible()
            showBanner(describeRejectedConnection(lastInvalidResult.value), 'info')
        } else if (pendingInvalidReason.value) {
            showBanner(pendingInvalidReason.value, 'warning')
        }
    }
    connectionHint.value = ''
    pendingInvalidReason.value = ''
    lastInvalidResult.value = null
}

function onConnect(params) {
    if (!pidEditMode.active) return
    const result = validateConnection(params, nodeIndex.value, buildAllEdges())
    if (!result.valid) {
        if ((result.code === 'duplicate' || result.code === 'port-occupied' || result.code === 'source-already-connected') && result.existingEdge) {
            focusExistingEdge(result.existingEdge)
            rebuildVisible()
            showBanner(describeRejectedConnection(result), 'info')
            return
        }

        showBanner(result.reason, 'warning')
        return
    }

    const newEdge = normalizeEdge({
        id: `user_${Date.now()}_${edgeCounter++}`,
        source: result.normalized.source,
        target: result.normalized.target,
        sourceHandle: result.normalized.sourceHandle,
        targetHandle: result.normalized.targetHandle,
        type: 'pipe',
        data: result.normalized.data,
    })
    pendingNewEdges.value = [...pendingNewEdges.value, newEdge]
    lastConnectionAcceptedAt = Date.now()
    connectionHint.value = ''
    pendingInvalidReason.value = ''
    lastInvalidResult.value = null
    // Select the new edge for editing
    selectedEdgeId.value = newEdge.id
    emit('select-edge', newEdge)
    rebuildVisible()
    showBanner('Connection added.', 'success')
}

function onEdgeClick({ edge }) {
    if (!pidEditMode.active) return
    selectedEdgeId.value = edge.id
    emit('select-edge', edge)
    rebuildVisible()
}

// Note: We do NOT use @edges-change for deletion tracking because Vue Flow
// fires remove events internally when v-model:edges is updated, which
// conflicts with our explicit edge management. Deletion is handled via
// the Delete key (Vue Flow built-in) and the UI delete button.

// --- Edit mode: node click ---
function onNodeClick({ node }) {
    if (pidEditMode.active) {
        selected.value = node.id
        selectedEdgeId.value = null
        emit('edit-node', node)
    } else {
        selected.value = node.id
        emit('select-equipment', node.id)
    }
}

function onPaneClick() {
    selected.value = null
    selectedEdgeId.value = null
    rebuildVisible()
}

// --- Edit mode: save/discard ---

function onUpdateNodeData(nodeId, dataOverrides) {
    pendingNodeEdits.value = { ...pendingNodeEdits.value, [nodeId]: dataOverrides }
    rebuildVisible()
}

function onDeleteEdge(edgeId) {
    pendingDeletedEdgeIds.value = new Set([...pendingDeletedEdgeIds.value, edgeId])
    if (selectedEdgeId.value === edgeId) selectedEdgeId.value = null
    rebuildVisible()
    showBanner('Connection removed.', 'info')
}

function onUpdateEdgeData(edgeId, dataOverrides) {
    // Update edge data in pending new edges or flag for overlay
    const idx = pendingNewEdges.value.findIndex(e => e.id === edgeId)
    if (idx >= 0) {
        const updated = { ...pendingNewEdges.value[idx], data: { ...pendingNewEdges.value[idx].data, ...dataOverrides } }
        pendingNewEdges.value = [...pendingNewEdges.value.slice(0, idx), updated, ...pendingNewEdges.value.slice(idx + 1)]
    }
    // For overlay edges, we'd need to update them in the overlay — keep it simple for now
    rebuildVisible()
}

async function saveOverlay() {
    const merged = {
        node_data_overrides: { ...overlay.value.node_data_overrides, ...pendingNodeEdits.value },
        added_edges: [
            ...(overlay.value.added_edges || []).filter(e => !pendingDeletedEdgeIds.value.has(e.id)),
            ...pendingNewEdges.value,
        ].map(normalizeEdge),
        removed_edge_ids: [
            ...overlay.value.removed_edge_ids.filter(id => !pendingNewEdges.value.some(e => e.id === id)),
            ...pendingDeletedEdgeIds.value,
        ],
    }
    try {
        const res = await fetch('/api/pid/overlay', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(merged),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        overlay.value = merged
        pendingNodeEdits.value = {}
        pendingNewEdges.value = []
        pendingDeletedEdgeIds.value = new Set()
        showBanner('P&ID layout saved.', 'success')
    } catch (e) {
        console.error('Failed to save overlay:', e)
        showBanner('Save failed — changes not persisted.', 'warning')
    }
}

function discardPending() {
    pendingNodeEdits.value = {}
    pendingNewEdges.value = []
    pendingDeletedEdgeIds.value = new Set()
    selectedEdgeId.value = null
    highlightedEdgeId.value = null
    rebuildVisible()
    showBanner('Unsaved P&ID edits were discarded.', 'info')
}

// Expose for App.vue to call
defineExpose({
    onUpdateNodeData,
    onDeleteEdge,
    onUpdateEdgeData,
    saveOverlay,
    discardPending,
})

// --- Watchers ---

watch(
    () => pidVisibility.hiddenIds.size,
    () => {
        rebuildVisible()
        if (selected.value && pidVisibility.hiddenIds.has(selected.value)) {
            selected.value = null
        }
    },
)

watch(
    () => [...sensorConfig.enabledSensorIds],
    (newIds, oldIds) => {
        if (oldIds) {
            for (const id of newIds) {
                if (!oldIds.includes(id)) showNode(`sensor_${id}`)
            }
        }
        rebuildVisible()
    },
)

watch(
    () => sensorConfig.availableNodes.length,
    () => { rebuildVisible() },
)

watch(
    () => [selectedEdgeId.value, highlightedEdgeId.value],
    () => { rebuildVisible() },
)

onMounted(async () => {
    await loadLayout()
    if (typeof window !== 'undefined') {
        window.addEventListener('pid-topology-changed', handleTopologyRefresh)
    }
    setTimeout(() => flowRef.value?.fitView?.({ padding: 0.15 }), 100)
})

onUnmounted(() => {
    if (typeof window !== 'undefined') {
        window.removeEventListener('pid-topology-changed', handleTopologyRefresh)
    }
    if (bannerTimeout) clearTimeout(bannerTimeout)
    if (edgeHighlightTimeout) clearTimeout(edgeHighlightTimeout)
    if (saveTimeout) clearTimeout(saveTimeout)
})
</script>

<template>
  <div class="pid-container" :class="{ 'edit-active': pidEditMode.active }">
    <!-- SVG arrow marker definitions for pipe flow direction -->
    <svg width="0" height="0" style="position:absolute">
      <defs>
        <marker id="arrow-flowing" viewBox="0 0 8 8" refX="6.4" refY="4"
            markerWidth="6" markerHeight="6" markerUnits="userSpaceOnUse" orient="auto">
                <path d="M 0.8 0.9 L 6.4 4 L 0.8 7.1 z" fill="#f2f5f7"/>
        </marker>
        <marker id="arrow-alarm" viewBox="0 0 8 8" refX="6.4" refY="4"
            markerWidth="6" markerHeight="6" markerUnits="userSpaceOnUse" orient="auto">
          <path d="M 0.8 0.9 L 6.4 4 L 0.8 7.1 z" fill="#db6a64"/>
        </marker>
        <marker id="arrow-idle" viewBox="0 0 8 8" refX="6.4" refY="4"
            markerWidth="6" markerHeight="6" markerUnits="userSpaceOnUse" orient="auto">
                <path d="M 0.8 0.9 L 6.4 4 L 0.8 7.1 z" fill="#d3dce2"/>
        </marker>
      </defs>
    </svg>

    <!-- PID toolbar -->
    <PidToolbar @save="saveOverlay" @discard="discardPending" />

        <div v-if="pidEditMode.active" class="canvas-legend">
            <span class="legend-pill">INPUT: shared feed port</span>
            <span class="legend-pill legend-pill-sensor">SENS: TT/PT/LT</span>
            <span class="legend-pill">PRODUCT: discharge only</span>
        </div>

        <div v-if="connectionHint || banner.message" class="canvas-banner" :class="`tone-${banner.tone}`">
            <span v-if="banner.message">{{ banner.message }}</span>
            <span v-else>{{ connectionHint }}</span>
        </div>

    <!-- Reset layout button -->
    <button class="reset-layout-btn" title="Reset to default layout" @click="resetLayout">
      ↺
    </button>

    <VueFlow
        v-if="flowReady"
        ref="flowRef"
        v-model:nodes="nodes"
        :edges="edges"
        :edge-types="edgeTypes"
        :default-edge-options="{ type: 'pipe' }"
        :snap-to-grid="true"
        :snap-grid="[10, 10]"
        :min-zoom="0.3"
        :max-zoom="2"
        :nodes-connectable="isConnectable"
        :edges-updatable="isEdgesUpdatable"
        :delete-key-code="deleteKeyCode"
        :is-valid-connection="isValidConnection"
        @node-drag-stop="onNodeDragStop"
        @init="onFlowInit"
        @node-click="onNodeClick"
        @pane-click="onPaneClick"
        @connect-start="onConnectStart"
        @connect-end="onConnectEnd"
        @connect="onConnect"
        @edge-click="onEdgeClick"
    >
      <template #node-reactor="reactorProps">
        <ReactorNode v-bind="reactorProps" />
      </template>
      <template #node-feed="feedProps">
        <FeedNode v-bind="feedProps" />
      </template>
      <template #node-jacket="jacketProps">
        <JacketNode v-bind="jacketProps" />
      </template>
      <template #node-agitator="agitatorProps">
        <AgitatorNode v-bind="agitatorProps" />
      </template>
      <template #node-product="productProps">
        <ProductNode v-bind="productProps" />
      </template>
      <template #node-instrument="instrumentProps">
        <InstrumentNode v-bind="instrumentProps" />
      </template>

            <template #edge-pipe="edgeProps">
                <PipeEdge v-bind="edgeProps" />
            </template>

      <Background :gap="20" :size="1" :pattern-color="bgColor" />
    </VueFlow>
  </div>
</template>

<style scoped>
.pid-container {
    width: 100%;
    height: 100%;
    overflow: hidden;
    position: relative;
    transition: border-color 0.2s;
    border: 2px solid transparent;
}

.pid-container.edit-active {
    border-color: var(--dcs-maintenance);
}

.canvas-legend {
    position: absolute;
    top: 44px;
    left: 8px;
    z-index: 10;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    max-width: 460px;
}

.legend-pill {
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(24, 31, 37, 0.88);
    border: 1px solid rgba(92, 105, 115, 0.38);
    color: var(--text-secondary);
    font-size: 0.52rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    backdrop-filter: blur(8px);
}

.legend-pill-sensor {
    color: #c7d6c5;
    border-color: rgba(114, 180, 125, 0.42);
}

.canvas-banner {
    position: absolute;
    top: 78px;
    left: 8px;
    z-index: 10;
    max-width: 430px;
    padding: 7px 11px;
    border-radius: 10px;
    background: rgba(24, 31, 37, 0.94);
    border: 1px solid rgba(92, 105, 115, 0.42);
    color: var(--text-primary);
    font-size: 0.62rem;
    font-weight: 600;
    line-height: 1.35;
    backdrop-filter: blur(8px);
}

.canvas-banner.tone-warning {
    border-color: rgba(210, 133, 72, 0.44);
    color: #ebc086;
}

.canvas-banner.tone-success {
    border-color: rgba(114, 180, 125, 0.44);
    color: #c7d6c5;
}

.canvas-banner.tone-info {
    color: #d7e0e6;
}

/* Make handles visible in edit mode */
.pid-container.edit-active :deep(.vue-flow__handle) {
    width: 10px;
    height: 10px;
    background: var(--dcs-maintenance);
    border: 2px solid var(--bg-panel);
    opacity: 1;
    border-radius: 50%;
    transition: all 0.15s;
}
.pid-container.edit-active :deep(.vue-flow__handle:hover) {
    background: var(--dcs-maintenance);
    transform: scale(1.3);
}

.pid-container.edit-active :deep(.vue-flow__handle[data-handleid='sensor']) {
    background: var(--dcs-normal);
}

/* Highlight selected edge in edit mode */
.pid-container :deep(.vue-flow__edge.selected path) {
    stroke: var(--dcs-maintenance) !important;
    stroke-width: 4 !important;
    filter: drop-shadow(0 0 8px rgba(249, 115, 22, 0.45));
}

.reset-layout-btn {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 10;
    background: rgba(24, 31, 37, 0.94);
    border: 1px solid rgba(92, 105, 115, 0.42);
    color: var(--text-secondary);
    font-size: 1rem;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    line-height: 1;
    backdrop-filter: blur(8px);
}
.reset-layout-btn:hover {
    color: var(--text-primary);
    border-color: var(--border-strong);
    background: rgba(31, 38, 45, 0.98);
}
</style>
