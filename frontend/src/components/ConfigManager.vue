<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { state } from '../services/store'
import { fetchConfigs, selectConfig, fetchModelConfig, updateModelConfig, applyPendingConfig, discardPendingConfig, fetchSimulationOptions } from '../services/api'

const emit = defineEmits(['close'])

// Config files list
const configFiles = ref([])
const activeFile = ref('')

// Full config data
const config = ref({})
const pendingEdits = ref(null)

// Tabs: derived from config sections
const SECTION_ORDER = ['reactor', 'thermal', 'kinetics', 'viscosity', 'physics', 'controller', 'solver', 'initial_conditions', 'geometry', 'mixing', 'simulation', 'reaction_network']
const SECTION_LABELS = {
    reactor: 'Reactor',
    thermal: 'Thermal',
    kinetics: 'Kinetics',
    viscosity: 'Viscosity',
    physics: 'Physics',
    controller: 'Controller',
    solver: 'Solver',
    initial_conditions: 'Initial Cond.',
    geometry: 'Geometry',
    mixing: 'Mixing',
    simulation: 'Simulation Models',
    reaction_network: 'Reaction Network'
}

const simulationOptions = ref({ current: {}, available: {}, constraints: {} })

const DROPDOWN_OPTIONS = {
    'geometry.type': ['cylindrical_torispherical', 'cylindrical_flat'],
    'mixing.impeller_type': ['rushton', 'pitched_blade'],
    'mixing.enabled': ['true', 'false'],
    'solver.solver_name': ['ipopt'],
    'solver.solver_options.mu_strategy': ['adaptive', 'monotone', 'quality-function']
}

function getDropdownKey(section, key, parentKey = null) {
    if (parentKey) return `${section}.${parentKey}.${key}`
    return `${section}.${key}`
}

function shouldUseDropdown(section, key, parentKey = null) {
    const dropdownKey = getDropdownKey(section, key, parentKey)
    return Array.isArray(DROPDOWN_OPTIONS[dropdownKey])
}

function getDropdownOptions(section, key, parentKey = null, currentValue = null) {
    const dropdownKey = getDropdownKey(section, key, parentKey)
    const base = DROPDOWN_OPTIONS[dropdownKey] || []
    const current = formatValue(currentValue)
    if (current !== '' && !base.includes(current)) {
        return [...base, current]
    }
    return base
}

const hasSimulationOptions = computed(() => {
    const available = simulationOptions.value.available || {}
    return ['viscosity', 'heat_transfer', 'mixing', 'energy']
        .some((key) => Array.isArray(available[key]) && available[key].length > 0)
})

const sections = computed(() => {
    const keys = Object.keys(config.value)
    return SECTION_ORDER.filter((s) => {
        if (keys.includes(s)) return true
        return s === 'simulation'
    })
})

const activeTab = ref('')

// Set default tab when config loads
watch(sections, (s) => {
    if (s.length > 0 && !s.includes(activeTab.value)) {
        activeTab.value = s[0]
    }
})

// Current section data
const currentSection = computed(() => {
    if (!activeTab.value || !config.value[activeTab.value]) return {}
    return config.value[activeTab.value]
})

const simulationModels = computed(() => {
    const cfgModels = config.value?.simulation?.models || {}
    const baseModels = simulationOptions.value?.current || {}
    return { ...baseModels, ...cfgModels }
})

const mixingEnabled = computed(() => {
    const mixingCfg = config.value?.mixing
    if (mixingCfg && typeof mixingCfg.enabled !== 'undefined') {
        return Boolean(mixingCfg.enabled)
    }
    return Boolean(simulationOptions.value?.constraints?.mixing_enabled)
})

const hasGeometry = computed(() => {
    const geomCfg = config.value?.geometry
    if (geomCfg && Object.keys(geomCfg).length > 0) {
        return true
    }
    return Boolean(simulationOptions.value?.constraints?.has_geometry)
})

const heatTransferWarning = computed(() => {
    const heatModel = simulationModels.value?.heat_transfer
    if (heatModel === 'dynamic' && !mixingEnabled.value) {
        return 'Dynamic heat transfer requires mixing.enabled: true.'
    }
    if (heatModel === 'geometry_aware' && !hasGeometry.value) {
        return 'Geometry-aware heat transfer requires a geometry section.'
    }
    return ''
})

// Check if a field has pending changes
function isPending(section, key) {
    if (!pendingEdits.value) return false
    const s = pendingEdits.value[section]
    if (!s) return false
    return key in s
}

// Handle field change
async function handleChange(section, key, value) {
    // Parse numeric values
    let parsed = value
    if (typeof currentSection.value[key] === 'number' || !isNaN(Number(value))) {
        const num = Number(value)
        if (!isNaN(num)) parsed = num
    }
    if (value === 'true') parsed = true
    if (value === 'false') parsed = false

    await updateModelConfig({ [section]: { [key]: parsed } })
    await loadConfig()
}

// Handle nested field change (e.g. solver.solver_options.max_iter)
async function handleNestedChange(section, parentKey, key, value) {
    let parsed = value
    const num = Number(value)
    if (!isNaN(num) && value !== '') parsed = num

    await updateModelConfig({ [section]: { [parentKey]: { [key]: parsed } } })
    await loadConfig()
}

async function handleSimulationModelChange(modelKey, value) {
    await updateModelConfig({ simulation: { models: { [modelKey]: value } } })
    await loadConfig()
}

// Load config list
async function loadConfigList() {
    const data = await fetchConfigs()
    configFiles.value = data.configs || []
    activeFile.value = data.active_file || ''
}

// Load full config
async function loadConfig() {
    const data = await fetchModelConfig()
    config.value = data.config || {}
    pendingEdits.value = data.pending || null
    activeFile.value = data.active_file || ''
}

async function loadSimulationOptions() {
    const data = await fetchSimulationOptions()
    simulationOptions.value = data || { current: {}, available: {}, constraints: {} }
}

// Select a config file
async function handleSelectConfig(filename) {
    if (state.simulation_running) return
    const result = await selectConfig(filename)
    if (result) {
        await loadConfigList()
        await loadConfig()
    }
}

// Apply pending changes
async function handleApply() {
    const result = await applyPendingConfig()
    if (result) {
        await loadConfig()
    }
}

// Discard pending changes
async function handleDiscard() {
    await discardPendingConfig()
    await loadConfig()
}

// Format value for display
function formatValue(val) {
    if (val === null || val === undefined) return ''
    if (typeof val === 'number') {
        if (Number.isInteger(val)) return String(val)
        return String(val)
    }
    return String(val)
}

// Check if value is a nested object (e.g. solver_options)
function isObject(val) {
    return val !== null && typeof val === 'object' && !Array.isArray(val)
}

// For reaction_network, show read-only (too complex for form editing)
const isReadOnly = computed(() => activeTab.value === 'reaction_network')

// Extract active config filename from full path
const activeFilename = computed(() => {
    if (!activeFile.value) return ''
    const parts = activeFile.value.replace(/\\/g, '/').split('/')
    return parts[parts.length - 1]
})

onMounted(async () => {
    await loadConfigList()
    await loadConfig()
    await loadSimulationOptions()
})
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-content">
      <!-- Header -->
      <div class="modal-header">
        <h2>Model Configuration</h2>
        <span class="modal-subtitle">View and edit simulation parameters</span>
        <button class="close-btn" @click="emit('close')">x</button>
      </div>

      <!-- Config file selector -->
      <div class="config-selector">
        <label>Config file:</label>
        <div class="config-files">
          <button v-for="cf in configFiles" :key="cf.filename"
                  class="config-chip"
                  :class="{ active: activeFilename === cf.filename }"
                  :disabled="state.simulation_running"
                  @click="handleSelectConfig(cf.filename)">
            {{ cf.name }}
            <span v-if="cf.has_reaction_network" class="chip-badge">NET</span>
          </button>
        </div>
      </div>

      <!-- Pending changes banner -->
      <div v-if="pendingEdits" class="pending-banner">
        <span>Pending changes (not yet applied)</span>
        <div class="pending-actions">
          <button class="btn btn-apply" @click="handleApply" :disabled="state.simulation_running">Apply</button>
          <button class="btn btn-discard" @click="handleDiscard">Discard</button>
        </div>
      </div>

      <!-- Section tabs -->
      <div class="modal-tabs">
        <div v-for="s in sections" :key="s"
             class="tab" :class="{ active: activeTab === s }"
             @click="activeTab = s">
          {{ SECTION_LABELS[s] || s }}
          <span v-if="pendingEdits && pendingEdits[s]" class="tab-dot"></span>
        </div>
      </div>

      <!-- Section content -->
      <div class="modal-body">
                <div v-if="isReadOnly" class="readonly-notice">
                    This section is read-only. Switch config files to change the reaction network.
                </div>

                <div v-if="activeTab === 'simulation'" class="simulation-section">
                    <div class="readonly-notice">
                        Choose the model set used for the simulation equations.
                    </div>

                    <div v-if="!hasSimulationOptions" class="empty-section">
                        Simulation model options are unavailable. Restart the backend to load registries.
                    </div>

                    <template v-else>
                        <div class="field-row">
                            <label class="field-label">viscosity</label>
                            <select
                                class="field-select"
                                :value="simulationModels.viscosity"
                                @change="handleSimulationModelChange('viscosity', $event.target.value)"
                            >
                                <option v-for="opt in simulationOptions.available.viscosity" :key="opt" :value="opt">
                                    {{ opt }}
                                </option>
                            </select>
                        </div>

                        <div class="field-row">
                            <label class="field-label">heat_transfer</label>
                            <select
                                class="field-select"
                                :value="simulationModels.heat_transfer"
                                @change="handleSimulationModelChange('heat_transfer', $event.target.value)"
                            >
                                <option v-for="opt in simulationOptions.available.heat_transfer" :key="opt" :value="opt">
                                    {{ opt }}
                                </option>
                            </select>
                        </div>
                        <div v-if="heatTransferWarning" class="warning-text">{{ heatTransferWarning }}</div>

                        <div class="field-row">
                            <label class="field-label">mixing</label>
                            <select
                                class="field-select"
                                :value="simulationModels.mixing"
                                @change="handleSimulationModelChange('mixing', $event.target.value)"
                            >
                                <option v-for="opt in simulationOptions.available.mixing" :key="opt" :value="opt">
                                    {{ opt }}
                                </option>
                            </select>
                        </div>

                        <div class="field-row">
                            <label class="field-label">energy</label>
                            <select
                                class="field-select"
                                :value="simulationModels.energy"
                                @change="handleSimulationModelChange('energy', $event.target.value)"
                            >
                                <option v-for="opt in simulationOptions.available.energy" :key="opt" :value="opt">
                                    {{ opt }}
                                </option>
                            </select>
                        </div>
                    </template>
                </div>

                <template v-else>
                    <template v-for="(val, key) in currentSection" :key="key">
          <!-- Nested object (e.g. solver_options) -->
          <div v-if="isObject(val)" class="field-group">
            <div class="field-group-label">{{ key }}</div>
            <div v-for="(subVal, subKey) in val" :key="subKey" class="field-row">
              <label class="field-label" :title="activeTab + '.' + key + '.' + subKey">{{ subKey }}</label>
                            <select v-if="!isReadOnly && shouldUseDropdown(activeTab, subKey, key)"
                                            class="field-select"
                                            :class="{ pending: isPending(activeTab, key) }"
                                            :value="formatValue(subVal)"
                                            @change="handleNestedChange(activeTab, key, subKey, $event.target.value)">
                                <option v-for="opt in getDropdownOptions(activeTab, subKey, key, subVal)" :key="opt" :value="opt">{{ opt }}</option>
                            </select>
                            <input v-else-if="!isReadOnly"
                     class="field-input"
                     :class="{ pending: isPending(activeTab, key) }"
                     :value="formatValue(subVal)"
                     @change="handleNestedChange(activeTab, key, subKey, $event.target.value)"
              />
              <span v-else class="field-value">{{ formatValue(subVal) }}</span>
            </div>
          </div>

          <!-- Simple value -->
          <div v-else class="field-row">
            <label class="field-label" :title="activeTab + '.' + key">{{ key }}</label>
                        <select v-if="!isReadOnly && shouldUseDropdown(activeTab, key)"
                                        class="field-select"
                                        :class="{ pending: isPending(activeTab, key) }"
                                        :value="formatValue(val)"
                                        @change="handleChange(activeTab, key, $event.target.value)">
                            <option v-for="opt in getDropdownOptions(activeTab, key, null, val)" :key="opt" :value="opt">{{ opt }}</option>
                        </select>
                        <input v-else-if="!isReadOnly"
                   class="field-input"
                   :class="{ pending: isPending(activeTab, key) }"
                   :value="formatValue(val)"
                   :type="typeof val === 'number' ? 'text' : 'text'"
                   @change="handleChange(activeTab, key, $event.target.value)"
            />
            <span v-else class="field-value">{{ formatValue(val) }}</span>
          </div>
                    </template>
                </template>

        <div v-if="Object.keys(currentSection).length === 0" class="empty-section">
          No parameters in this section.
        </div>
      </div>

      <!-- Footer -->
      <div class="modal-footer">
        <span v-if="pendingEdits" class="footer-hint">Changes applied when you click Apply</span>
        <button class="btn btn-close" @click="emit('close')">Close</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
    position: fixed; inset: 0;
    background: rgba(15, 23, 42, 0.8);
    backdrop-filter: blur(4px);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000;
    animation: fadeIn 0.15s ease-out;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-content {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    width: min(1100px, 94vw); max-height: 90vh;
    display: flex; flex-direction: column;
    box-shadow: var(--shadow-lg);
    animation: slideUp 0.2s ease-out;
    font-family: var(--font-sans);
}
@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

.modal-header {
    padding: 20px 24px 12px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.modal-header h2 { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); margin: 0; letter-spacing: -0.01em; }
.modal-subtitle { font-size: 0.85rem; color: var(--text-muted); flex: 1; }
.close-btn {
    background: transparent; border: 1px solid var(--border-subtle); color: var(--text-muted);
    font-size: 1.2rem; cursor: pointer; width: 32px; height: 32px; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.15s;
}
.close-btn:hover { color: var(--text-primary); border-color: var(--text-muted); background: var(--bg-app); }

/* Config file selector */
.config-selector {
    padding: 12px 24px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex; align-items: center; gap: 12px;
}
.config-selector label {
    font-size: 0.75rem; font-weight: 700; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.05em;
    white-space: nowrap;
}
.config-files { display: flex; gap: 6px; flex-wrap: wrap; }
.config-chip {
    padding: 6px 12px; border-radius: 6px;
    background: var(--bg-input); border: 1px solid var(--border-subtle);
    color: var(--text-secondary); font-size: 0.85rem; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
    display: flex; align-items: center; gap: 6px;
}
.config-chip:hover:not(:disabled) { border-color: var(--text-muted); color: var(--text-primary); }
.config-chip.active { background: rgba(59, 130, 246, 0.15); border-color: var(--accent-primary); color: var(--accent-primary); box-shadow: 0 0 0 1px var(--accent-primary); }
.config-chip:disabled { opacity: 0.5; cursor: not-allowed; }
.chip-badge {
    font-size: 0.7rem; background: var(--sensor-pressure); color: white;
    padding: 1px 4px; border-radius: 3px; font-weight: 700;
}

/* Pending banner */
.pending-banner {
    padding: 8px 24px;
    background: rgba(245, 158, 11, 0.1);
    border-bottom: 1px solid var(--accent-warning);
    display: flex; align-items: center; justify-content: space-between;
    font-size: 0.85rem; color: var(--accent-warning);
}
.pending-actions { display: flex; gap: 8px; }

/* Tabs */
.modal-tabs {
    display: flex; gap: 0; border-bottom: 1px solid var(--border-subtle); padding: 0 24px;
    overflow-x: auto;
}
.tab {
    padding: 12px 16px; cursor: pointer; font-size: 0.85rem; font-weight: 600;
    color: var(--text-muted); border-bottom: 2px solid transparent; transition: all 0.15s;
    white-space: nowrap; position: relative;
}
.tab:hover { color: var(--text-secondary); }
.tab.active { color: var(--accent-primary); border-bottom-color: var(--accent-primary); }
.tab-dot {
    position: absolute; top: 8px; right: 6px;
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent-warning);
}

/* Body */
.modal-body { padding: 20px 24px; overflow-y: auto; flex: 1; }

.readonly-notice {
    padding: 8px 12px; margin-bottom: 12px;
    background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.2);
    border-radius: 6px; font-size: 0.85rem; color: var(--accent-primary);
}

.field-row {
    display: flex; align-items: center; gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid var(--bg-app);
}
.field-label {
    flex: 0 0 220px; font-size: 0.85rem; color: var(--text-secondary);
    font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis;
}
.field-input {
    flex: 1; padding: 6px 10px;
    background: var(--bg-input); border: 1px solid var(--border-subtle);
    color: var(--text-primary); font-size: 0.9rem; border-radius: 4px;
    font-family: var(--font-mono); transition: all 0.15s;
}
.field-input:focus { outline: none; border-color: var(--accent-primary); background: var(--bg-app); }
.field-input.pending { border-color: var(--accent-warning); background: rgba(245, 158, 11, 0.1); }
.field-select {
    flex: 1; padding: 6px 10px;
    background: var(--bg-input); border: 1px solid var(--border-subtle);
    color: var(--text-primary); font-size: 0.9rem; border-radius: 4px;
    font-family: var(--font-mono); transition: all 0.15s;
}
.field-select:focus { outline: none; border-color: var(--accent-primary); background: var(--bg-app); }
.field-value {
    flex: 1; font-size: 0.9rem; color: var(--text-primary);
    font-family: var(--font-mono); padding: 6px 10px;
}

.field-group {
    margin: 12px 0;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    overflow: hidden;
}
.field-group-label {
    padding: 8px 12px;
    background: var(--bg-app);
    font-size: 0.75rem; font-weight: 700; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.05em;
    border-bottom: 1px solid var(--border-subtle);
}
.field-group .field-row {
    padding: 6px 12px;
}

.empty-section {
    padding: 24px; text-align: center;
    font-size: 0.9rem; color: var(--text-muted); font-style: italic;
}

.warning-text {
    padding: 6px 10px; margin: 0 0 8px 0;
    background: rgba(245, 158, 11, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.35);
    border-radius: 6px; font-size: 0.8rem; color: var(--accent-warning);
}

/* Footer */
.modal-footer {
    padding: 16px 24px; border-top: 1px solid var(--border-subtle);
    display: flex; justify-content: flex-end; align-items: center; gap: 12px;
    background: var(--bg-panel); border-radius: 0 0 12px 12px;
}
.footer-hint { font-size: 0.8rem; color: var(--accent-warning); flex: 1; font-weight: 500; }

.btn {
    padding: 6px 12px; border: none; border-radius: 6px;
    font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: all 0.15s;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.btn:hover { transform: translateY(-1px); filter: brightness(1.1); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.btn-apply { background: var(--accent-success); color: white; }
.btn-discard { background: var(--accent-danger); color: white; }
.btn-close { background: var(--accent-primary); color: white; padding: 8px 16px; font-size: 0.85rem; }
</style>
