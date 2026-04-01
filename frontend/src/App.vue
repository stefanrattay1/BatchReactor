<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import AlarmBanner from './components/AlarmBanner.vue'
import Header from './components/Header.vue'
import StatusBar from './components/StatusBar.vue'
import ProcessPID from './components/ProcessPID.vue'
import RecipeProgress from './components/RecipeProgress.vue'
import ControlSummary from './components/ControlSummary.vue'
import EquipmentModulePanel from './components/EquipmentModulePanel.vue'
import TrendPanel from './components/TrendPanel.vue'
import EquipmentDetail from './components/EquipmentDetail.vue'
import NodePropertyEditor from './components/pid/NodePropertyEditor.vue'
import EventLog from './components/EventLog.vue'
import SensorManager from './components/SensorManager.vue'
import ConfigManager from './components/ConfigManager.vue'
import BatchRunner from './components/BatchRunner.vue'
import BatchHistory from './components/BatchHistory.vue'
import ResultsOverlay from './components/ResultsOverlay.vue'
import AlarmDrawer from './components/AlarmDrawer.vue'
import ToastNotification from './components/ToastNotification.vue'
import { startPolling, stopPolling, getBatchStatus } from './services/api'
import { sensorConfig, initSensorConfig } from './services/sensorConfig'
import { state } from './services/store'
import { pidEditMode } from './services/pidEditMode'

const showConfigManager = ref(false)
const showBatchRunner = ref(false)
const showBatchHistory = ref(false)
const showResults = ref(false)
const showAlarmDrawer = ref(false)
const resultsMode = ref('live')
const batchResult = ref(null)
const liveSnapshot = ref(null)
const selectedEquipment = ref(null)
const editingNode = ref(null)
const editingEdge = ref(null)
const pidRef = ref(null)

// Track previous phase for transition detection
let prevPhase = 'IDLE'
let wasRunning = false

watch(() => state.phase, (newPhase) => {
    const terminalPhases = ['DISCHARGING']
    if (terminalPhases.includes(newPhase) && wasRunning && !showBatchRunner.value) {
        liveSnapshot.value = { ...state }
        resultsMode.value = 'live'
        showResults.value = true
    }
    if (newPhase !== 'IDLE') wasRunning = true
    if (newPhase === 'IDLE' && prevPhase !== 'IDLE') wasRunning = false
    prevPhase = newPhase
})

function onBatchClose() {
    showBatchRunner.value = false
}

async function checkBatchResult() {
    try {
        const s = await getBatchStatus()
        if (s.status === 'completed' && s.result) {
            batchResult.value = s.result
            resultsMode.value = 'batch'
            showResults.value = true
            showBatchRunner.value = false
        }
    } catch (e) { /* ignore */ }
}

function onResultsClose() {
    showResults.value = false
    batchResult.value = null
    liveSnapshot.value = null
}

function onRunAnother() {
    showResults.value = false
    batchResult.value = null
    showBatchRunner.value = true
}

function onSelectEquipment(id) {
    selectedEquipment.value = id
}

function onCloseDetail() {
    selectedEquipment.value = null
}

// Edit mode handlers
function onEditNode(node) {
    editingNode.value = node
    editingEdge.value = null
}

function onSelectEdge(edge) {
    editingEdge.value = edge
    editingNode.value = null
}

function onNodePropertyUpdate(nodeId, data) {
    pidRef.value?.onUpdateNodeData(nodeId, data)
}

function onEdgePropertyUpdate(edgeId, data) {
    pidRef.value?.onUpdateEdgeData(edgeId, data)
}

function onEdgeDelete(edgeId) {
    pidRef.value?.onDeleteEdge(edgeId)
    editingEdge.value = null
}

function clearEditSelection() {
    editingNode.value = null
    editingEdge.value = null
}

onMounted(() => {
    initSensorConfig()
    startPolling()
})

onUnmounted(() => {
    stopPolling()
})
</script>

<template>
  <div class="app-container dcs-layout">
        <div class="app-shell-backdrop"></div>

    <!-- Alarm Banner (always visible, top) -->
    <AlarmBanner @open-drawer="showAlarmDrawer = !showAlarmDrawer" />

    <!-- Header (compact single row) -->
    <Header @open-config="showConfigManager = true"
            @open-batch="showBatchRunner = true"
            @open-history="showBatchHistory = true" />

    <!-- Main 3-zone layout -->
    <div class="dcs-main">
      <!-- Left Rail -->
      <aside class="left-rail">
        <RecipeProgress />
        <ControlSummary @select-equipment="onSelectEquipment" />
        <EquipmentModulePanel />
        <div class="event-log-wrapper">
          <div class="section-title">Events</div>
          <EventLog />
        </div>
      </aside>

      <!-- Center: P&ID -->
      <main class="center-pid">
        <ProcessPID ref="pidRef"
                    v-model:selected="selectedEquipment"
                    @select-equipment="onSelectEquipment"
                    @edit-node="onEditNode"
                    @select-edge="onSelectEdge" />
      </main>

      <!-- Right Rail -->
      <aside class="right-rail">
        <TrendPanel />
        <NodePropertyEditor
            v-if="pidEditMode.active && (editingNode || editingEdge)"
            :node="editingNode"
            :edge="editingEdge"
            @update:node="onNodePropertyUpdate"
            @update:edge="onEdgePropertyUpdate"
            @delete:edge="onEdgeDelete"
            @close="clearEditSelection"
        />
        <EquipmentDetail v-else
                         :equipment-id="selectedEquipment"
                         @close="onCloseDetail" />
      </aside>
    </div>

    <!-- Status Footer -->
    <StatusBar />

    <!-- Modal Overlays (unchanged) -->
    <SensorManager v-if="sensorConfig.showManager" @close="sensorConfig.showManager = false" />
    <ConfigManager v-if="showConfigManager" @close="showConfigManager = false" />
    <BatchRunner v-if="showBatchRunner" @close="onBatchClose" @completed="checkBatchResult" />
    <BatchHistory v-if="showBatchHistory" @close="showBatchHistory = false" />
    <ResultsOverlay
        v-if="showResults"
        :mode="resultsMode"
        :batch-result="batchResult"
        :live-state="liveSnapshot"
        @close="onResultsClose"
        @run-another="onRunAnother"
    />
    <AlarmDrawer v-if="showAlarmDrawer" @close="showAlarmDrawer = false" />
    <ToastNotification />
  </div>
</template>

<style scoped>
.app-container {
  position: relative;
  isolation: isolate;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.app-shell-backdrop {
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
        radial-gradient(circle at 20% 18%, rgba(255, 255, 255, 0.035), transparent 24%),
        radial-gradient(circle at 82% 0%, rgba(255, 255, 255, 0.02), transparent 18%),
    linear-gradient(180deg, rgba(13, 20, 27, 0.96) 0%, rgba(8, 12, 17, 0.98) 100%);
}

/* 3-zone DCS layout */
.dcs-main {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr) 320px;
    gap: 14px;
    flex: 1;
    overflow: hidden;
    padding: 14px 16px 12px;
}

/* Left Rail */
.left-rail {
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow-y: auto;
    min-width: 0;
    padding-right: 2px;
}

.event-log-wrapper {
    flex: 1;
    min-height: 240px;
    padding: 14px;
    border: 1px solid var(--border-subtle);
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(20, 29, 37, 0.98) 0%, rgba(15, 22, 28, 0.96) 100%);
    box-shadow: var(--inner-highlight), var(--panel-shadow);
    display: flex;
    flex-direction: column;
}

.event-log-wrapper .section-title {
    font-size: 0.58rem;
    font-weight: 700;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.16em;
    margin-bottom: 8px;
    font-family: var(--font-display);
}

.event-log-wrapper :deep(.event-log) {
    flex: 1;
    height: auto;
    min-height: 0;
}

.left-rail :deep(.recipe-progress),
.left-rail :deep(.control-summary),
.left-rail :deep(.equipment-panel),
.right-rail :deep(.trend-panel),
.right-rail :deep(.equipment-detail),
.right-rail :deep(.property-editor) {
    border: 1px solid var(--border-subtle);
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(20, 29, 37, 0.98) 0%, rgba(15, 22, 28, 0.96) 100%);
    box-shadow: var(--inner-highlight), var(--panel-shadow);
}

/* Center P&ID */
.center-pid {
    overflow: hidden;
    min-width: 0;
    position: relative;
    background: linear-gradient(180deg, rgba(16, 23, 30, 0.96) 0%, rgba(10, 16, 21, 0.98) 100%);
    border: 1px solid rgba(73, 96, 110, 0.6);
    border-radius: 22px;
    box-shadow: var(--inner-highlight), var(--panel-shadow);
}

/* Right Rail */
.right-rail {
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow-y: auto;
    min-width: 0;
    padding-right: 2px;
}

/* Responsive */
@media (max-width: 1400px) {
    .dcs-main { grid-template-columns: 0px minmax(0, 1fr) 320px; }
    .left-rail { display: none; }
}

@media (max-width: 1200px) {
    .dcs-main {
        grid-template-columns: 1fr;
        grid-template-rows: 1fr auto;
        overflow-y: auto;
        padding: 12px;
    }
    .left-rail { display: none; }
    .right-rail { max-height: 360px; }
    .center-pid { min-height: 400px; }
}

@media (max-width: 900px) {
    .dcs-main {
        grid-template-columns: 1fr;
        overflow-y: auto;
        gap: 10px;
        padding: 10px;
    }
    .center-pid { min-height: 300px; }
    .right-rail { max-height: none; }
}
</style>
