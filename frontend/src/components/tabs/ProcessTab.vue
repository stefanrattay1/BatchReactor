<script setup>
import { computed, watch, ref, nextTick } from 'vue'
import { state, actions } from '../../services/store'
import { sensorConfig } from '../../services/sensorConfig'
import { formatSensorValue } from '../../utils/formatValue'

const selectedId = computed(() => state.selectedInput)

function getNodeValue(node) {
    if (!node.state_key) return '--'
    const val = state[node.state_key]
    return formatSensorValue(val, node, state.viscosity_max ?? 1e6)
}

function selectInput(id) { actions.selectInput(id) }

// Auto-scroll to selected node
const nodeRefs = ref({})
function setNodeRef(id) {
    return (el) => { if (el) nodeRefs.value[id] = el }
}

watch(selectedId, async (id) => {
    if (!id) return
    await nextTick()
    const el = nodeRefs.value[id]
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
})

// Expanded node detail
const expandedNode = ref(null)
function toggleExpand(id) {
    expandedNode.value = expandedNode.value === id ? null : id
}

function getSparklineSvg(id) {
    const data = sensorConfig.sparklineData[id]
    if (!data || data.length < 2) return null

    let min = Infinity, max = -Infinity
    for (const v of data) {
        if (v < min) min = v
        if (v > max) max = v
    }
    const range = max - min || 1
    const w = 200, h = 40
    const step = w / (data.length - 1)

    return data.map((v, i) => {
        const px = i * step
        const py = h - ((v - min) / range) * h
        return `${px.toFixed(1)},${py.toFixed(1)}`
    }).join(' ')
}

function getNodeMinMax(id) {
    const data = sensorConfig.sparklineData[id]
    if (!data || data.length < 2) return { min: '--', max: '--' }
    let min = Infinity, max = -Infinity
    for (const v of data) {
        if (v < min) min = v
        if (v > max) max = v
    }
    return { min: min.toFixed(2), max: max.toFixed(2) }
}
</script>

<template>
  <div class="process-tab">
    <div class="section-title">OPC UA Live Values</div>
    <div class="node-list">
        <div v-for="node in sensorConfig.availableNodes.filter(n => n.state_key)"
             :key="node.id"
             :ref="setNodeRef(node.id)"
             class="node-item-wrapper">
            <div class="node-item"
                 :class="{
                    'node-enabled': sensorConfig.enabledSensorIds.includes(node.id),
                    'node-selected': selectedId === node.id
                 }"
                 @click="selectInput(node.id); toggleExpand(node.id)">
                <div class="name">
                    <span class="node-dot" :style="{ background: sensorConfig.sensorSettings[node.id]?.color || node.default_color }"></span>
                    {{ sensorConfig.sensorSettings[node.id]?.alias || node.name }}
                </div>
                <div class="value">{{ getNodeValue(node) }}</div>
                <div class="tag">{{ node.opc_path }}</div>
            </div>
            <!-- Expanded detail -->
            <div v-if="expandedNode === node.id" class="node-detail">
                <svg class="sparkline-chart" viewBox="0 0 200 40" preserveAspectRatio="none">
                    <polyline v-if="getSparklineSvg(node.id)"
                              :points="getSparklineSvg(node.id)"
                              :stroke="sensorConfig.sensorSettings[node.id]?.color || node.default_color"
                              stroke-width="1.5"
                              fill="none"/>
                </svg>
                <div class="detail-stats">
                    <span>Min: {{ getNodeMinMax(node.id).min }}</span>
                    <span>Max: {{ getNodeMinMax(node.id).max }}</span>
                </div>
            </div>
        </div>
    </div>
  </div>
</template>

<style scoped>
.process-tab { padding: 20px; }

.section-title {
    font-size: 0.75rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-title::before { content: ''; width: 4px; height: 14px; background: var(--accent-primary); border-radius: 2px; }

.node-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }

.node-item-wrapper { display: flex; flex-direction: column; }

.node-item {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 12px;
    cursor: pointer;
    transition: all 0.2s;
}
.node-item:hover { border-color: var(--border-focus); background: var(--bg-panel); transform: translateY(-1px); }
.node-item.node-enabled { border-left: 3px solid var(--accent-primary); }
.node-item.node-selected { border-color: var(--accent-primary); box-shadow: 0 0 8px rgba(59, 130, 246, 0.2); }

.node-item .name { font-size: 0.8rem; font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; color: var(--text-secondary); }
.node-item .value { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); }
.node-item .tag { font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); margin-top: 4px; opacity: 0.7; }
.node-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

.node-detail {
    background: var(--bg-app);
    border: 1px solid var(--border-subtle);
    border-top: none;
    border-radius: 0 0 8px 8px;
    padding: 10px 12px;
    animation: slideDown 0.15s ease-out;
}
@keyframes slideDown { from { opacity: 0; max-height: 0; } to { opacity: 1; max-height: 100px; } }

.sparkline-chart { width: 100%; height: 40px; }
.detail-stats {
    display: flex;
    justify-content: space-between;
    font-size: 0.65rem;
    color: var(--text-muted);
    font-family: var(--font-mono);
    margin-top: 4px;
}
</style>
