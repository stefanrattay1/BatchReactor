<script setup>
import { computed } from 'vue'
import { sensorConfig, dismissAlarm } from '../services/sensorConfig'

const emit = defineEmits(['close'])

const alarms = computed(() => sensorConfig.activeAlarms)
const alarmCount = computed(() => alarms.value.length)

function formatTime(date) {
    if (!date) return '--'
    return new Date(date).toLocaleTimeString('en-GB', { hour12: false })
}

function dismiss(index) {
    dismissAlarm(index)
}

function clearAll() {
    sensorConfig.activeAlarms.splice(0, sensorConfig.activeAlarms.length)
}
</script>

<template>
  <Transition name="slide-right">
    <div class="alarm-drawer">
        <div class="drawer-header">
            <h3>Active Alarms <span class="count">({{ alarmCount }})</span></h3>
            <div class="drawer-actions">
                <button v-if="alarmCount > 0" class="btn-clear" @click="clearAll">Clear All</button>
                <button class="btn-close" @click="emit('close')">&times;</button>
            </div>
        </div>
        <div class="drawer-body">
            <div v-if="alarmCount === 0" class="empty-state">
                No active alarms
            </div>
            <div v-for="(alarm, i) in alarms" :key="i" class="alarm-item" :class="'alarm-' + alarm.type">
                <div class="alarm-header">
                    <span class="alarm-name">{{ alarm.name }}</span>
                    <span class="alarm-type">{{ alarm.type === 'high' ? 'HI' : 'LO' }}</span>
                    <button class="btn-dismiss" @click="dismiss(i)">&times;</button>
                </div>
                <div class="alarm-details">
                    <span>Value: <strong>{{ typeof alarm.value === 'number' ? alarm.value.toFixed(2) : alarm.value }}</strong></span>
                    <span>Limit: <strong>{{ typeof alarm.threshold === 'number' ? alarm.threshold.toFixed(2) : alarm.threshold }}</strong></span>
                    <span class="alarm-time">{{ formatTime(alarm.time) }}</span>
                </div>
            </div>
        </div>
    </div>
  </Transition>
</template>

<style scoped>
.alarm-drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: 340px;
    background: var(--bg-panel);
    border-left: 1px solid var(--border-subtle);
    box-shadow: -4px 0 24px rgba(0, 0, 0, 0.3);
    z-index: 900;
    display: flex;
    flex-direction: column;
}

.slide-right-enter-active, .slide-right-leave-active {
    transition: transform 0.25s ease;
}
.slide-right-enter-from, .slide-right-leave-to {
    transform: translateX(100%);
}

.drawer-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-subtle);
    flex-shrink: 0;
}
.drawer-header h3 {
    font-size: 0.9rem;
    font-weight: 700;
    color: var(--text-primary);
    margin: 0;
}
.count { color: var(--text-muted); font-weight: 500; }

.drawer-actions { display: flex; gap: 8px; align-items: center; }

.btn-clear {
    padding: 4px 10px;
    border-radius: 4px;
    border: 1px solid var(--border-subtle);
    background: transparent;
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
}
.btn-clear:hover { border-color: var(--accent-danger); color: var(--accent-danger); }

.btn-close {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1.2rem;
    cursor: pointer;
    padding: 4px;
    line-height: 1;
    transition: color 0.15s;
}
.btn-close:hover { color: var(--text-primary); }

.drawer-body {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
}

.empty-state {
    text-align: center;
    color: var(--text-muted);
    margin-top: 40px;
    font-style: italic;
    font-size: 0.85rem;
}

.alarm-item {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 8px;
    transition: all 0.15s;
}
.alarm-item.alarm-high { border-left: 3px solid var(--accent-danger); }
.alarm-item.alarm-low { border-left: 3px solid var(--accent-primary); }

.alarm-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}
.alarm-name { font-weight: 600; font-size: 0.85rem; color: var(--text-primary); flex: 1; }
.alarm-type {
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
}
.alarm-high .alarm-type { background: rgba(239, 68, 68, 0.15); color: var(--accent-danger); }
.alarm-low .alarm-type { background: rgba(59, 130, 246, 0.15); color: var(--accent-primary); }

.btn-dismiss {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1rem;
    cursor: pointer;
    padding: 2px;
    line-height: 1;
    transition: color 0.15s;
}
.btn-dismiss:hover { color: var(--accent-danger); }

.alarm-details {
    display: flex;
    gap: 12px;
    font-size: 0.7rem;
    color: var(--text-muted);
    font-family: var(--font-mono);
}
.alarm-details strong { color: var(--text-secondary); }
.alarm-time { margin-left: auto; }
</style>
