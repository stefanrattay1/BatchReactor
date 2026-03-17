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

const showConfigManager = ref(false)
const showBatchRunner = ref(false)
const showBatchHistory = ref(false)
const showResults = ref(false)
const showAlarmDrawer = ref(false)
const resultsMode = ref('live')
const batchResult = ref(null)
const liveSnapshot = ref(null)
const selectedEquipment = ref(null)

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
        <ProcessPID v-model:selected="selectedEquipment"
                    @select-equipment="onSelectEquipment" />
      </main>

      <!-- Right Rail -->
      <aside class="right-rail">
        <TrendPanel />
        <EquipmentDetail :equipment-id="selectedEquipment"
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
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-app);
}

/* 3-zone DCS layout */
.dcs-main {
    display: grid;
    grid-template-columns: 200px 1fr 280px;
    flex: 1;
    overflow: hidden;
}

/* Left Rail */
.left-rail {
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border-subtle);
    background: var(--bg-panel);
    overflow-y: auto;
}

.event-log-wrapper {
    flex: 1;
    min-height: 240px;
    padding: 12px;
    border-top: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
}

.event-log-wrapper .section-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 6px;
}

.event-log-wrapper :deep(.event-log) {
    flex: 1;
    height: auto;
    min-height: 0;
}

/* Center P&ID */
.center-pid {
    overflow: hidden;
    background: var(--bg-app);
}

/* Right Rail */
.right-rail {
    display: flex;
    flex-direction: column;
    border-left: 1px solid var(--border-subtle);
    background: var(--bg-panel);
    overflow-y: auto;
}

/* Responsive */
@media (max-width: 1400px) {
    .dcs-main { grid-template-columns: 0px 1fr 280px; }
    .left-rail { display: none; }
}

@media (max-width: 1200px) {
    .dcs-main {
        grid-template-columns: 1fr;
        grid-template-rows: 1fr auto;
        overflow-y: auto;
    }
    .left-rail { display: none; }
    .right-rail { border-left: none; border-top: 1px solid var(--border-subtle); max-height: 350px; }
    .center-pid { min-height: 400px; }
}

@media (max-width: 900px) {
    .dcs-main {
        grid-template-columns: 1fr;
        overflow-y: auto;
    }
    .center-pid { min-height: 300px; }
    .right-rail { max-height: none; }
}
</style>
