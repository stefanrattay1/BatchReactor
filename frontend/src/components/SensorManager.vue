<script setup>
import { computed, reactive, ref } from 'vue'

import { state } from '../services/store'
import {
  applySensorConfigChanges,
  createModeledSensor,
  discardSensorConfigChanges,
  removeSensorDefinition,
  resetSensorConfig,
  restoreCoreSensor,
  sensorConfig,
  toggleSensor,
  updateSensorSetting,
} from '../services/sensorConfig'
import ConnectionManager from './ConnectionManager.vue'

const emit = defineEmits(['close'])

const activeTab = ref('model')
const showCreateForm = ref(false)
const busyKey = ref('')
const feedback = ref({ text: '', tone: 'info' })

const createForm = reactive({
  tag: '',
  name: '',
  maps_to: 'temperature_K',
  unit: '',
})

const modeledSensors = computed(() =>
  sensorConfig.sensorRegistry.filter(sensor => sensor.origin === 'modeled')
)

const coreSensors = computed(() =>
  sensorConfig.sensorRegistry.filter(sensor => sensor.origin === 'core')
)

const suppressedCoreSensors = computed(() => sensorConfig.suppressedCoreSensors)

function setFeedback(text, tone = 'info') {
  feedback.value = { text, tone }
}

function formatApiError(error) {
  const dependencies = error?.details?.dependencies
  if (Array.isArray(dependencies) && dependencies.length) {
    return `${error.message} ${dependencies.map(dep => dep.message).join(' ')}`
  }
  return error?.message || 'Request failed.'
}

function resetCreateForm() {
  createForm.tag = ''
  createForm.name = ''
  createForm.maps_to = sensorConfig.sensorVariables[0]?.maps_to || 'temperature_K'
  createForm.unit = sensorConfig.sensorVariables[0]?.unit || ''
}

function handleVariableChange() {
  const variable = sensorConfig.sensorVariables.find(entry => entry.maps_to === createForm.maps_to)
  if (variable && !createForm.unit) {
    createForm.unit = variable.unit || ''
  }
}

function isEnabled(id) {
  return sensorConfig.enabledSensorIds.includes(id)
}

function getSettings(id) {
  return sensorConfig.sensorSettings[id] || {}
}

function getLiveValue(node) {
  if (!node.state_key) return '--'
  const value = state[node.state_key]
  if (value === undefined || value === null) return '--'
  if (typeof value === 'number') {
    if (node.unit === 'bar') return `${value.toFixed(3)} ${node.unit}`
    if (node.unit === 'K') return `${value.toFixed(1)} ${node.unit}`
    if (node.unit === '') return value.toFixed(4)
    return `${value.toFixed(2)} ${node.unit}`
  }
  return String(value)
}

function handleToggle(id) {
  toggleSensor(id)
}

function handleAliasChange(id, value) {
  updateSensorSetting(id, { alias: value })
}

function handleColorChange(id, value) {
  updateSensorSetting(id, { color: value })
}

function handleAlarmHigh(id, value) {
  updateSensorSetting(id, { alarmHigh: value === '' ? null : Number(value) })
}

function handleAlarmLow(id, value) {
  updateSensorSetting(id, { alarmLow: value === '' ? null : Number(value) })
}

function handleReset() {
  if (confirm('Reset all local sensor display settings and alarm thresholds?')) {
    resetSensorConfig()
    setFeedback('Local display settings reset.', 'success')
  }
}

async function handleCreateSensor() {
  if (!createForm.tag.trim() || !createForm.name.trim()) {
    setFeedback('Tag and name are required.', 'warning')
    return
  }

  busyKey.value = 'create'
  try {
    await createModeledSensor({
      tag: createForm.tag.trim(),
      name: createForm.name.trim(),
      maps_to: createForm.maps_to,
      unit: createForm.unit.trim(),
    })
    resetCreateForm()
    showCreateForm.value = false
    setFeedback('Modeled sensor staged. Apply config changes when ready.', 'success')
  } catch (error) {
    setFeedback(formatApiError(error), 'warning')
  } finally {
    busyKey.value = ''
  }
}

async function handleRemoveSensor(sensor) {
  const prompt = sensor.origin === 'core'
    ? `Remove ${sensor.name} from the visible catalog? The underlying process variable stays available and the change becomes live after Apply.`
    : `Delete modeled sensor ${sensor.tag}? This stages removal until you apply the pending config.`

  if (!confirm(prompt)) return

  busyKey.value = sensor.id
  try {
    await removeSensorDefinition(sensor)
    setFeedback(
      sensor.origin === 'core'
        ? `${sensor.name} was removed from the staged catalog.`
        : `${sensor.tag} was staged for deletion.`,
      'success',
    )
  } catch (error) {
    setFeedback(formatApiError(error), 'warning')
  } finally {
    busyKey.value = ''
  }
}

async function handleRestoreSensor(sensorId) {
  busyKey.value = `restore:${sensorId}`
  try {
    await restoreCoreSensor(sensorId)
    setFeedback('Core sensor restored to the staged catalog.', 'success')
  } catch (error) {
    setFeedback(formatApiError(error), 'warning')
  } finally {
    busyKey.value = ''
  }
}

async function handleApplyChanges() {
  busyKey.value = 'apply'
  try {
    const result = await applySensorConfigChanges()
    if (result) {
      setFeedback(result.message || 'Sensor configuration applied.', 'success')
    }
  } catch (error) {
    setFeedback(formatApiError(error), 'warning')
  } finally {
    busyKey.value = ''
  }
}

async function handleDiscardChanges() {
  busyKey.value = 'discard'
  try {
    await discardSensorConfigChanges()
    setFeedback('Pending sensor changes discarded.', 'info')
  } catch (error) {
    setFeedback(formatApiError(error), 'warning')
  } finally {
    busyKey.value = ''
  }
}
</script>

<template>
  <teleport to="body">
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-content">
    <div class="modal-header">
      <div class="title-block">
      <h2>Sensor Manager</h2>
      <span class="modal-subtitle">Model logical sensors here, then bind real field sources in the OPC workspace.</span>
      </div>
      <button class="close-btn" @click="emit('close')">x</button>
    </div>

    <div class="modal-tabs">
      <div class="tab" :class="{ active: activeTab === 'model' }" @click="activeTab = 'model'">
      Model Sensors
      </div>
      <div class="tab" :class="{ active: activeTab === 'bindings' }" @click="activeTab = 'bindings'">
      Field Bindings
      </div>
    </div>

    <div v-if="activeTab === 'model'" class="modal-body">
      <div class="workspace-bar">
      <div>
        <div class="workspace-title">Canonical Sensor Catalog</div>
        <div class="workspace-copy">Modeled sensors are simulation-backed definitions. Core signals can be removed from the catalog without removing the physics variable.</div>
      </div>
      <button class="btn btn-primary-outline" @click="showCreateForm = !showCreateForm">
        {{ showCreateForm ? 'Hide Form' : 'Add Modeled Sensor' }}
      </button>
      </div>

      <div v-if="state.config_pending" class="pending-banner">
      <div>
        <div class="banner-title">Pending Config Changes</div>
        <div class="banner-copy">Sensor add and remove operations are staged. Apply when the simulation is stopped.</div>
      </div>
      <div class="banner-actions">
        <button class="btn btn-apply" :disabled="busyKey === 'apply'" @click="handleApplyChanges">Apply</button>
        <button class="btn btn-discard" :disabled="busyKey === 'discard'" @click="handleDiscardChanges">Discard</button>
      </div>
      </div>

      <div v-if="feedback.text" class="feedback-banner" :class="`tone-${feedback.tone}`">
      {{ feedback.text }}
      </div>

      <div v-if="showCreateForm" class="create-card">
      <div class="create-grid">
        <label class="form-field">
        <span>Tag</span>
        <input v-model="createForm.tag" placeholder="TT-901" />
        </label>
        <label class="form-field form-field-wide">
        <span>Name</span>
        <input v-model="createForm.name" placeholder="Batch headspace temperature" />
        </label>
        <label class="form-field form-field-wide">
        <span>Simulation Variable</span>
        <select v-model="createForm.maps_to" @change="handleVariableChange">
          <option v-for="variable in sensorConfig.sensorVariables" :key="variable.maps_to" :value="variable.maps_to">
          {{ variable.label }} · {{ variable.maps_to }}
          </option>
        </select>
        </label>
        <label class="form-field">
        <span>Unit</span>
        <input v-model="createForm.unit" placeholder="K" />
        </label>
      </div>

      <div class="create-actions">
        <button class="btn btn-create" :disabled="busyKey === 'create'" @click="handleCreateSensor">Create Sensor</button>
        <button class="btn btn-secondary-outline" @click="showCreateForm = false">Cancel</button>
      </div>
      </div>

      <div class="category-section">
      <h3 class="category-title">Modeled Sensors</h3>
      <div v-if="!modeledSensors.length" class="empty-state">
        No modeled sensors are staged in the current configuration yet.
      </div>
      <div v-for="sensor in modeledSensors" :key="sensor.id" class="sensor-row" :class="{ enabled: isEnabled(sensor.id) }">
        <div class="sensor-toggle">
        <label class="toggle-switch">
          <input type="checkbox" :checked="isEnabled(sensor.id)" @change="handleToggle(sensor.id)">
          <span class="toggle-slider"></span>
        </label>
        </div>

        <div class="sensor-icon" :style="{ color: getSettings(sensor.id).color || sensor.default_color }">
        {{ getSettings(sensor.id).icon || sensor.default_icon }}
        </div>

        <div class="sensor-info">
        <div class="sensor-name-row">
          <input class="alias-input"
             :value="getSettings(sensor.id).alias || ''"
             @input="handleAliasChange(sensor.id, $event.target.value)"
             :placeholder="sensor.name" />
          <span class="sensor-badge sensor-badge-modeled">Modeled</span>
          <span class="sensor-tag">{{ sensor.tag }}</span>
        </div>
        <div class="opc-path">{{ sensor.maps_to }}<span v-if="sensor.unit"> · {{ sensor.unit }}</span></div>
        </div>

        <div class="sensor-live-value">{{ getLiveValue(sensor) }}</div>

        <input type="color" class="color-picker"
           :value="getSettings(sensor.id).color || sensor.default_color"
           @input="handleColorChange(sensor.id, $event.target.value)" />

        <div v-if="isEnabled(sensor.id) && sensor.data_type === 'Double'" class="alarm-inputs">
        <div class="alarm-field">
          <label>Hi</label>
          <input type="number" step="any"
             :value="getSettings(sensor.id).alarmHigh"
             @change="handleAlarmHigh(sensor.id, $event.target.value)"
             placeholder="--" />
        </div>
        <div class="alarm-field">
          <label>Lo</label>
          <input type="number" step="any"
             :value="getSettings(sensor.id).alarmLow"
             @change="handleAlarmLow(sensor.id, $event.target.value)"
             placeholder="--" />
        </div>
        </div>

        <button class="row-action row-action-danger"
            :disabled="busyKey === sensor.id"
            @click="handleRemoveSensor(sensor)">
        Delete
        </button>
      </div>
      </div>

      <div class="category-section">
      <h3 class="category-title">Core Process Signals</h3>
      <div v-for="sensor in coreSensors" :key="sensor.id" class="sensor-row" :class="{ enabled: isEnabled(sensor.id) }">
        <div class="sensor-toggle">
        <label class="toggle-switch">
          <input type="checkbox" :checked="isEnabled(sensor.id)" @change="handleToggle(sensor.id)">
          <span class="toggle-slider"></span>
        </label>
        </div>

        <div class="sensor-icon" :style="{ color: getSettings(sensor.id).color || sensor.default_color }">
        {{ getSettings(sensor.id).icon || sensor.default_icon }}
        </div>

        <div class="sensor-info">
        <div class="sensor-name-row">
          <input class="alias-input"
             :value="getSettings(sensor.id).alias || ''"
             @input="handleAliasChange(sensor.id, $event.target.value)"
             :placeholder="sensor.name" />
          <span class="sensor-badge sensor-badge-core">Core</span>
        </div>
        <div class="opc-path">{{ sensor.opc_path }}</div>
        </div>

        <div class="sensor-live-value">{{ getLiveValue(sensor) }}</div>

        <input type="color" class="color-picker"
           :value="getSettings(sensor.id).color || sensor.default_color"
           @input="handleColorChange(sensor.id, $event.target.value)" />

        <div v-if="isEnabled(sensor.id) && sensor.data_type === 'Double'" class="alarm-inputs">
        <div class="alarm-field">
          <label>Hi</label>
          <input type="number" step="any"
             :value="getSettings(sensor.id).alarmHigh"
             @change="handleAlarmHigh(sensor.id, $event.target.value)"
             placeholder="--" />
        </div>
        <div class="alarm-field">
          <label>Lo</label>
          <input type="number" step="any"
             :value="getSettings(sensor.id).alarmLow"
             @change="handleAlarmLow(sensor.id, $event.target.value)"
             placeholder="--" />
        </div>
        </div>

        <button class="row-action"
            :disabled="busyKey === sensor.id"
            @click="handleRemoveSensor(sensor)">
        Remove
        </button>
      </div>
      </div>

      <div v-if="suppressedCoreSensors.length" class="category-section">
      <h3 class="category-title">Suppressed Core Signals</h3>
      <div class="suppressed-grid">
        <div v-for="sensor in suppressedCoreSensors" :key="sensor.id" class="suppressed-card">
        <div>
          <div class="suppressed-name">{{ sensor.name }}</div>
          <div class="suppressed-meta">{{ sensor.opc_path }}</div>
        </div>
        <button class="btn btn-secondary-outline"
            :disabled="busyKey === `restore:${sensor.id}`"
            @click="handleRestoreSensor(sensor.id)">
          Restore
        </button>
        </div>
      </div>
      </div>
    </div>

    <div v-if="activeTab === 'bindings'" class="modal-body modal-body-bindings">
      <ConnectionManager />
    </div>

    <div v-if="activeTab === 'model'" class="modal-footer">
      <button class="btn btn-reset" @click="handleReset">Reset Display Settings</button>
      <button class="btn btn-close" @click="emit('close')">Close</button>
    </div>
    <div v-else class="modal-footer">
      <button class="btn btn-close" @click="emit('close')">Close</button>
    </div>
    </div>
  </div>
  </teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(7, 11, 15, 0.76);
  backdrop-filter: blur(10px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.15s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-content {
  background: var(--bg-panel-elevated, var(--bg-panel));
  border: 1px solid rgba(92, 105, 115, 0.42);
  border-radius: 18px;
  width: 980px;
  max-width: 94vw;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 28px 60px rgba(0, 0, 0, 0.38);
  animation: slideUp 0.2s ease-out;
  font-family: var(--font-sans);
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

.modal-header {
  padding: 22px 24px 16px;
  border-bottom: 1px solid rgba(92, 105, 115, 0.28);
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.title-block {
  display: grid;
  gap: 4px;
}

.modal-header h2 {
  font-size: 1.12rem;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.modal-subtitle {
  font-size: 0.82rem;
  color: var(--text-muted);
  line-height: 1.45;
  max-width: 620px;
}

.close-btn {
  background: transparent;
  border: 1px solid rgba(92, 105, 115, 0.42);
  color: var(--text-muted);
  font-size: 1.1rem;
  cursor: pointer;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}

.close-btn:hover {
  color: var(--text-primary);
  border-color: var(--border-strong);
  background: rgba(255, 255, 255, 0.04);
}

.modal-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid rgba(92, 105, 115, 0.28);
  padding: 0 24px;
}

.tab {
  padding: 13px 18px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--text-muted);
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.tab:hover {
  color: var(--text-secondary);
}

.tab.active {
  color: var(--accent-primary);
  border-bottom-color: var(--accent-primary);
}

.modal-body {
  padding: 20px 24px 24px;
  overflow-y: auto;
  flex: 1;
}

.modal-body-bindings {
  padding-top: 12px;
}

.workspace-bar,
.pending-banner,
.feedback-banner,
.create-card,
.suppressed-card {
  border: 1px solid rgba(92, 105, 115, 0.28);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.02);
}

.workspace-bar {
  padding: 16px 18px;
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.workspace-title {
  font-size: 0.84rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.workspace-copy {
  font-size: 0.78rem;
  color: var(--text-muted);
  line-height: 1.45;
  max-width: 620px;
}

.pending-banner,
.feedback-banner {
  padding: 14px 16px;
  margin-bottom: 14px;
}

.pending-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  border-color: rgba(200, 155, 77, 0.36);
  background: rgba(200, 155, 77, 0.07);
}

.banner-title {
  font-size: 0.76rem;
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.09em;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.banner-copy {
  font-size: 0.78rem;
  color: var(--text-muted);
}

.banner-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.feedback-banner {
  font-size: 0.8rem;
  color: var(--text-secondary);
  line-height: 1.45;
}

.feedback-banner.tone-success {
  border-color: rgba(114, 180, 125, 0.36);
  background: rgba(114, 180, 125, 0.08);
}

.feedback-banner.tone-warning {
  border-color: rgba(219, 106, 100, 0.36);
  background: rgba(219, 106, 100, 0.08);
  color: #f0c5c1;
}

.feedback-banner.tone-info {
  border-color: rgba(142, 162, 176, 0.32);
}

.create-card {
  padding: 18px;
  margin-bottom: 18px;
}

.create-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.form-field {
  display: grid;
  gap: 6px;
}

.form-field-wide {
  grid-column: span 2;
}

.form-field span {
  font-size: 0.67rem;
  font-weight: 700;
  color: var(--text-muted);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.form-field input,
.form-field select {
  width: 100%;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid rgba(92, 105, 115, 0.38);
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 0.84rem;
}

.form-field input:focus,
.form-field select:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.create-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.category-section {
  margin-bottom: 22px;
}

.category-title {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(92, 105, 115, 0.24);
}

.empty-state {
  padding: 18px;
  border: 1px dashed rgba(92, 105, 115, 0.34);
  border-radius: 12px;
  color: var(--text-muted);
  font-size: 0.8rem;
}

.sensor-row {
  display: grid;
  grid-template-columns: 36px 32px minmax(0, 1fr) 110px 36px auto auto;
  align-items: center;
  gap: 12px;
  padding: 13px 16px;
  margin-bottom: 8px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(92, 105, 115, 0.28);
  border-radius: 12px;
  transition: all 0.15s;
}

.sensor-row:not(.enabled) {
  opacity: 0.62;
  filter: grayscale(0.45);
}

.sensor-row:hover {
  border-color: rgba(142, 162, 176, 0.48);
}

.sensor-toggle {
  flex: 0 0 36px;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--bg-input);
  border: 1px solid rgba(92, 105, 115, 0.42);
  border-radius: 20px;
  transition: 0.2s;
}

.toggle-slider::before {
  content: '';
  position: absolute;
  height: 14px;
  width: 14px;
  left: 2px;
  bottom: 2px;
  background: var(--text-muted);
  border-radius: 50%;
  transition: 0.2s;
}

.toggle-switch input:checked + .toggle-slider {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
}

.toggle-switch input:checked + .toggle-slider::before {
  transform: translateX(16px);
  background: #fff;
}

.sensor-icon {
  font-weight: 700;
  font-size: 0.9rem;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-app);
  border-radius: 8px;
  border: 1px solid rgba(92, 105, 115, 0.28);
}

.sensor-info {
  min-width: 0;
}

.sensor-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.alias-input {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-primary);
  font-size: 0.88rem;
  font-weight: 600;
  border-radius: 8px;
  transition: all 0.15s;
}

.alias-input:hover {
  border-color: rgba(92, 105, 115, 0.28);
  background: rgba(255, 255, 255, 0.03);
}

.alias-input:focus {
  outline: none;
  border-color: var(--accent-primary);
  background: rgba(255, 255, 255, 0.03);
}

.alias-input::placeholder {
  color: var(--text-muted);
}

.sensor-badge,
.sensor-tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.sensor-badge-core {
  border: 1px solid rgba(142, 162, 176, 0.34);
  color: var(--text-secondary);
  background: rgba(142, 162, 176, 0.08);
}

.sensor-badge-modeled {
  border: 1px solid rgba(114, 180, 125, 0.34);
  color: #c7d6c5;
  background: rgba(114, 180, 125, 0.1);
}

.sensor-tag {
  border: 1px solid rgba(92, 105, 115, 0.34);
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.03);
  font-family: var(--font-mono);
}

.opc-path {
  font-size: 0.73rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
  padding-left: 10px;
  margin-top: 3px;
}

.sensor-live-value {
  font-size: 0.88rem;
  font-weight: 700;
  color: var(--text-primary);
  text-align: right;
  white-space: nowrap;
  font-family: var(--font-mono);
}

.color-picker {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid rgba(92, 105, 115, 0.28);
  border-radius: 8px;
  cursor: pointer;
  background: var(--bg-app);
}

.color-picker::-webkit-color-swatch-wrapper {
  padding: 4px;
}

.color-picker::-webkit-color-swatch {
  border: none;
  border-radius: 4px;
}

.alarm-inputs {
  display: flex;
  gap: 8px;
}

.alarm-field {
  display: flex;
  align-items: center;
  gap: 4px;
}

.alarm-field label {
  font-size: 0.66rem;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
}

.alarm-field input {
  width: 72px;
  padding: 6px 8px;
  background: var(--bg-input);
  border: 1px solid rgba(92, 105, 115, 0.38);
  color: var(--text-primary);
  font-size: 0.78rem;
  border-radius: 8px;
  font-family: var(--font-mono);
  text-align: right;
}

.alarm-field input:focus {
  outline: none;
  border-color: var(--accent-primary);
}

.row-action {
  min-width: 86px;
  height: 34px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid rgba(92, 105, 115, 0.38);
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
}

.row-action-danger {
  border-color: rgba(219, 106, 100, 0.3);
  color: #f0c5c1;
}

.row-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.suppressed-grid {
  display: grid;
  gap: 10px;
}

.suppressed-card {
  padding: 14px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.suppressed-name {
  font-size: 0.84rem;
  font-weight: 700;
  color: var(--text-primary);
}

.suppressed-meta {
  font-size: 0.72rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
  margin-top: 4px;
}

.modal-footer {
  padding: 16px 24px;
  border-top: 1px solid rgba(92, 105, 115, 0.28);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn {
  height: 38px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 10px;
  font-size: 0.74rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.btn:hover:not(:disabled) {
  transform: translateY(-1px);
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-close,
.btn-create,
.btn-apply {
  background: var(--accent-primary);
  color: #0b0f13;
}

.btn-create {
  background: var(--accent-success);
}

.btn-apply {
  background: var(--accent-warning);
}

.btn-reset,
.btn-secondary-outline,
.btn-primary-outline,
.btn-discard {
  background: transparent;
  color: var(--text-secondary);
  border-color: rgba(92, 105, 115, 0.38);
}

.btn-secondary-outline,
.btn-primary-outline {
  height: 36px;
}

.btn-reset:hover:not(:disabled),
.btn-secondary-outline:hover:not(:disabled),
.btn-primary-outline:hover:not(:disabled),
.btn-discard:hover:not(:disabled) {
  border-color: rgba(142, 162, 176, 0.6);
}

@media (max-width: 1080px) {
  .sensor-row {
    grid-template-columns: 36px 32px minmax(0, 1fr);
    grid-auto-rows: auto;
  }

  .sensor-live-value,
  .color-picker,
  .alarm-inputs,
  .row-action {
    grid-column: 3;
    justify-self: start;
  }

  .create-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .modal-content {
    max-width: 100vw;
    max-height: 100vh;
    border-radius: 0;
  }

  .workspace-bar,
  .pending-banner,
  .suppressed-card {
    flex-direction: column;
    align-items: stretch;
  }

  .create-grid {
    grid-template-columns: 1fr;
  }

  .form-field-wide {
    grid-column: span 1;
  }
}
</style>
