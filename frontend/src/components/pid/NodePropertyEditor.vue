<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
    node: { type: Object, default: null },
    edge: { type: Object, default: null },
})

const emit = defineEmits(['update:node', 'update:edge', 'delete:edge', 'close'])

// Available state keys for dropdown
const STATE_KEYS = [
    'temperature_K', 'temperature_C', 'temperature_measured_K',
    'jacket_temperature_K', 'pressure_bar', 'conversion',
    'mass_total_kg', 'mass_component_a_kg', 'mass_component_b_kg',
    'mass_product_kg', 'mass_solvent_kg', 'volume_L', 'fill_pct',
    'viscosity_Pas', 'agitator_speed_rpm',
    'feed_rate_component_a', 'feed_rate_component_b', 'feed_rate_solvent',
    'dt_dt',
]

// --- Node editing ---
const nodeTag = ref('')
const nodeName = ref('')
const nodeValueKey = ref('')
const nodeUnit = ref('')

// Populate fields when node changes
watch(() => props.node?.id, () => {
    if (props.node?.data) {
        nodeTag.value = props.node.data.tag || ''
        nodeName.value = props.node.data.name || props.node.data.label || ''
        nodeValueKey.value = props.node.data.valueKey || props.node.data.rateKey || ''
        nodeUnit.value = props.node.data.unit || ''
    }
}, { immediate: true })

const isDynamicSensor = computed(() => props.node?.id?.startsWith('sensor_'))
const isInstrument = computed(() => props.node?.type === 'instrument')
const isFeed = computed(() => props.node?.type === 'feed')

function emitNodeUpdate() {
    if (!props.node) return
    const data = { tag: nodeTag.value, name: nodeName.value }
    if (isInstrument.value) {
        data.valueKey = nodeValueKey.value
        data.unit = nodeUnit.value
    }
    if (isFeed.value) {
        data.label = nodeName.value
        data.rateKey = nodeValueKey.value
    }
    emit('update:node', props.node.id, data)
}

// --- Edge editing ---
const edgeFlowKey = ref('')
const edgeValveTag = ref('')
const edgeNoArrow = ref(false)

watch(() => props.edge?.id, () => {
    if (props.edge?.data) {
        edgeFlowKey.value = props.edge.data.flowKey || ''
        edgeValveTag.value = props.edge.data.valveTag || ''
        edgeNoArrow.value = !!props.edge.data.noArrow
    }
}, { immediate: true })

function emitEdgeUpdate() {
    if (!props.edge) return
    emit('update:edge', props.edge.id, {
        flowKey: edgeFlowKey.value,
        valveTag: edgeValveTag.value,
        noArrow: edgeNoArrow.value,
    })
}

function deleteEdge() {
    if (!props.edge) return
    emit('delete:edge', props.edge.id)
}
</script>

<template>
  <div class="property-editor">
    <!-- Node editing -->
    <template v-if="node && !edge">
      <div class="editor-header">
        <div>
          <span class="editor-badge">NODE</span>
          <span class="editor-type">{{ node.type }}</span>
        </div>
        <button class="close-btn" @click="emit('close')">&#x2715;</button>
      </div>

      <!-- Dynamic sensor: read-only message -->
      <div v-if="isDynamicSensor" class="readonly-msg">
        Dynamic sensor — configure via Sensor Manager.
      </div>

      <!-- Editable node properties -->
      <template v-else>
        <div class="field-group">
          <label class="field-label">Tag</label>
          <input class="field-input" v-model="nodeTag" @change="emitNodeUpdate" placeholder="e.g. XV-101" />
        </div>

        <div class="field-group">
          <label class="field-label">Name</label>
          <input class="field-input" v-model="nodeName" @change="emitNodeUpdate" placeholder="Display name" />
        </div>

        <template v-if="isInstrument || isFeed">
          <div class="field-group">
            <label class="field-label">State Key</label>
            <select class="field-input" v-model="nodeValueKey" @change="emitNodeUpdate">
              <option value="">— none —</option>
              <option v-for="key in STATE_KEYS" :key="key" :value="key">{{ key }}</option>
            </select>
          </div>

          <div class="field-group">
            <label class="field-label">Unit</label>
            <input class="field-input" v-model="nodeUnit" @change="emitNodeUpdate" placeholder="K, bar, kg/s, %" />
          </div>
        </template>

        <div class="node-id-hint">ID: {{ node.id }}</div>
      </template>
    </template>

    <!-- Edge editing -->
    <template v-else-if="edge">
      <div class="editor-header">
        <div>
          <span class="editor-badge edge-badge">EDGE</span>
          <span class="editor-type">{{ edge.source }} → {{ edge.target }}</span>
        </div>
        <button class="close-btn" @click="emit('close')">&#x2715;</button>
      </div>

      <div class="field-group">
        <label class="field-label">Flow Key</label>
        <select class="field-input" v-model="edgeFlowKey" @change="emitEdgeUpdate">
          <option value="">— none —</option>
          <option v-for="key in STATE_KEYS" :key="key" :value="key">{{ key }}</option>
        </select>
      </div>

      <div class="field-group">
        <label class="field-label">Valve Tag</label>
        <input class="field-input" v-model="edgeValveTag" @change="emitEdgeUpdate" placeholder="e.g. XV-101" />
      </div>

      <div class="field-group checkbox-group">
        <label class="field-label">
          <input type="checkbox" v-model="edgeNoArrow" @change="emitEdgeUpdate" />
          No Arrow (mechanical connection)
        </label>
      </div>

      <button class="btn-delete-edge" @click="deleteEdge">Delete Edge</button>

      <div class="node-id-hint">Edge: {{ edge.id }}</div>
    </template>

    <!-- Empty state -->
    <template v-else>
      <div class="empty-state">
        <div class="empty-icon">&#9881;</div>
        <div class="empty-text">Click a node or edge to edit properties</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.property-editor {
    padding: 8px;
    flex: 1;
    overflow-y: auto;
}

.editor-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 12px;
}

.editor-badge {
    font-size: 0.5rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    padding: 2px 6px;
    border-radius: 3px;
    background: var(--dcs-maintenance);
    color: #111;
    margin-right: 6px;
    text-transform: uppercase;
}

.edge-badge {
    background: var(--accent-primary);
}

.editor-type {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text-secondary);
}

.close-btn {
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-muted);
    font-size: 14px;
    cursor: pointer;
    width: 24px;
    height: 24px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
}
.close-btn:hover { background: var(--bg-app); color: var(--text-primary); border-color: var(--border-subtle); }

.field-group {
    margin-bottom: 10px;
}

.field-label {
    display: block;
    font-size: 0.6rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 3px;
}

.field-input {
    width: 100%;
    padding: 6px 8px;
    background: var(--bg-input, var(--bg-app));
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    color: var(--text-primary);
    font-size: 0.8rem;
    font-family: 'JetBrains Mono', monospace;
    box-sizing: border-box;
}
.field-input:focus {
    outline: none;
    border-color: var(--dcs-maintenance);
}

select.field-input {
    cursor: pointer;
}

.checkbox-group .field-label {
    display: flex;
    align-items: center;
    gap: 6px;
    text-transform: none;
    font-size: 0.7rem;
    cursor: pointer;
}

.node-id-hint {
    margin-top: 12px;
    font-size: 0.55rem;
    color: var(--text-muted);
    font-family: 'JetBrains Mono', monospace;
    opacity: 0.6;
}

.readonly-msg {
    font-size: 0.75rem;
    color: var(--text-muted);
    font-style: italic;
    padding: 10px 0;
}

.btn-delete-edge {
    width: 100%;
    padding: 7px 12px;
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    background: transparent;
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    margin-top: 8px;
}
.btn-delete-edge:hover {
    border-color: #ef4444;
    color: #ef4444;
    background: rgba(239, 68, 68, 0.08);
}

.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 120px;
    padding: 20px;
}

.empty-icon {
    font-size: 2rem;
    color: var(--text-muted);
    opacity: 0.3;
    margin-bottom: 8px;
}

.empty-text {
    font-size: 0.75rem;
    color: var(--text-muted);
    text-align: center;
}
</style>
