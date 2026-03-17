<script setup>
import { ref, watch, onMounted } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
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
import { sensorConfig } from '../services/sensorConfig'
import { pidVisibility, showAllNodes, showNode } from '../services/pidVisibility'

const emit = defineEmits(['select-equipment'])
const selected = defineModel('selected', { type: String, default: null })

const nodes = ref([])
const edges = ref([])
const savedPositions = ref({})

const { fitView } = useVueFlow()

// Build all nodes (before filtering)
function buildAllNodes() {
    const pos = savedPositions.value
    const base = DEFAULT_NODES.map(n => ({
        ...n,
        position: pos[n.id] ? { x: pos[n.id].x, y: pos[n.id].y } : { ...n.position },
    }))
    const dynamic = buildDynamicNodes(
        sensorConfig.enabledSensorIds,
        sensorConfig.availableNodes,
        pos,
    )
    return [...base, ...dynamic]
}

// Filter out hidden nodes and edges referencing hidden nodes
function rebuildVisible() {
    const allNodes = buildAllNodes()
    const visibleIds = new Set()

    nodes.value = allNodes.filter(n => {
        if (pidVisibility.hiddenIds.has(n.id)) return false
        visibleIds.add(n.id)
        return true
    })

    edges.value = DEFAULT_EDGES
        .filter(e => visibleIds.has(e.source) && visibleIds.has(e.target))
        .map(e => ({ ...e }))
}

// Load layout from backend, fall back to defaults
async function loadLayout() {
    try {
        const res = await fetch('/api/pid/layout')
        if (res.ok) {
            const data = await res.json()
            if (data && Object.keys(data).length > 0) {
                savedPositions.value = data
            }
        }
    } catch (e) {
        // Backend not available, use defaults
    }

    rebuildVisible()
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
    } catch (e) {
        // Silently fail — layout save is best-effort
    }
}

// Reset layout to defaults (positions + hidden state)
async function resetLayout() {
    try {
        await fetch('/api/pid/layout', { method: 'DELETE' })
    } catch (e) { /* ignore */ }
    savedPositions.value = {}
    showAllNodes()
    rebuildVisible()
    setTimeout(() => fitView({ padding: 0.15 }), 50)
}

// Watch hidden node changes to rebuild
watch(
    () => pidVisibility.hiddenIds.size,
    () => {
        rebuildVisible()
        // Deselect if currently selected node got hidden
        if (selected.value && pidVisibility.hiddenIds.has(selected.value)) {
            selected.value = null
        }
    },
)

// Watch sensor config: rebuild visible nodes when enabled sensors change
watch(
    () => [...sensorConfig.enabledSensorIds],
    (newIds, oldIds) => {
        // If a dynamic sensor node was previously hidden (e.g. via the old bug
        // where removeFromCanvas called pidHideNode), clean that up so it shows.
        if (oldIds) {
            for (const id of newIds) {
                if (!oldIds.includes(id)) {
                    showNode(`sensor_${id}`)
                }
            }
        }
        rebuildVisible()
    },
)

// Also rebuild when the catalog loads (async after mount)
watch(
    () => sensorConfig.availableNodes.length,
    () => { rebuildVisible() },
)

// Handle node click -> select equipment
function onNodeClick({ node }) {
    selected.value = node.id
    emit('select-equipment', node.id)
}

// Handle pane click -> deselect
function onPaneClick() {
    selected.value = null
}

onMounted(async () => {
    await loadLayout()
    setTimeout(() => fitView({ padding: 0.15 }), 100)
})
</script>

<template>
  <div class="pid-container">
    <!-- SVG arrow marker definitions for pipe flow direction -->
    <svg width="0" height="0" style="position:absolute">
      <defs>
        <marker id="arrow-flowing" viewBox="0 0 10 10" refX="10" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#9ca3af"/>
        </marker>
        <marker id="arrow-alarm" viewBox="0 0 10 10" refX="10" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#ef4444"/>
        </marker>
        <marker id="arrow-idle" viewBox="0 0 10 10" refX="10" refY="5"
                markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 8 5 L 0 9 z" fill="#3f3f46"/>
        </marker>
      </defs>
    </svg>

    <!-- PID toolbar: shows hidden nodes for re-adding -->
    <PidToolbar />

    <!-- Reset layout button -->
    <button class="reset-layout-btn" title="Reset to default layout" @click="resetLayout">
      ↺
    </button>

    <VueFlow
        v-model:nodes="nodes"
        v-model:edges="edges"
        :default-edge-options="{ type: 'pipe' }"
        :snap-to-grid="true"
        :snap-grid="[10, 10]"
        :min-zoom="0.3"
        :max-zoom="2"
        :nodes-connectable="false"
        :edges-updatable="false"
        :delete-key-code="null"
        @node-drag-stop="onNodeDragStop"
        @node-click="onNodeClick"
        @pane-click="onPaneClick"
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

      <Background :gap="20" :size="1" pattern-color="rgba(51, 65, 85, 0.3)" />
    </VueFlow>
  </div>
</template>

<style scoped>
.pid-container {
    width: 100%;
    height: 100%;
    overflow: hidden;
    position: relative;
}

.reset-layout-btn {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 10;
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    color: var(--text-muted);
    font-size: 1rem;
    width: 28px;
    height: 28px;
    border-radius: 6px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
    line-height: 1;
}
.reset-layout-btn:hover {
    color: var(--text-primary);
    border-color: var(--accent-primary);
    background: var(--bg-app);
}
</style>
