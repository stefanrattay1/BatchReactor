<script setup>
import { computed } from 'vue'
import { sensorConfig } from '../services/sensorConfig'

const emit = defineEmits(['open-drawer'])

const alarms = computed(() => sensorConfig.activeAlarms)
const alarmCount = computed(() => alarms.value.length)
const topAlarm = computed(() => alarms.value[alarms.value.length - 1] || null)

function formatValue(val) {
    if (typeof val !== 'number') return String(val)
    return val.toFixed(1)
}

function formatTime(date) {
    if (!date) return ''
    const d = date instanceof Date ? date : new Date(date)
        return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}
</script>

<template>
  <div class="alarm-banner" :class="{ 'has-alarms': alarmCount > 0 }">
        <div class="alarm-heading">
            <span class="alarm-indicator"></span>
            <span class="alarm-label">{{ alarmCount > 0 ? 'Alarm Summary' : 'Alarm Status' }}</span>
        </div>

    <template v-if="alarmCount > 0">
      <span class="alarm-time">{{ formatTime(topAlarm.time) }}</span>
      <span class="alarm-text">
                {{ topAlarm.name }} · {{ topAlarm.type === 'high' ? 'HIGH' : 'LOW' }}
        ({{ formatValue(topAlarm.value) }})
      </span>
            <span class="alarm-count-badge">{{ alarmCount }} active</span>
            <button class="alarm-view-btn" @click="emit('open-drawer')">Open Alarm List</button>
    </template>
    <template v-else>
            <span class="no-alarms">No active alarms. All monitored signals are within configured limits.</span>
    </template>
  </div>
</template>

<style scoped>
.alarm-banner {
    display: flex;
    align-items: center;
        gap: 12px;
        padding: 8px 16px;
        min-height: 38px;
        background: linear-gradient(180deg, rgba(15, 22, 28, 0.98) 0%, rgba(12, 18, 24, 0.98) 100%);
        border-bottom: 1px solid rgba(73, 96, 110, 0.45);
    flex-shrink: 0;
        font-size: 0.66rem;
    font-family: var(--font-mono);
        flex-wrap: wrap;
}

.alarm-banner.has-alarms {
        background: linear-gradient(180deg, rgba(68, 19, 19, 0.86) 0%, rgba(29, 12, 15, 0.94) 100%);
    border-bottom-color: var(--dcs-alarm);
    animation: alarm-bg-pulse 2s ease-in-out infinite;
}

@keyframes alarm-bg-pulse {
        0%, 100% { box-shadow: inset 0 0 0 0 rgba(239, 99, 92, 0.08); }
        50% { box-shadow: inset 0 0 0 999px rgba(239, 99, 92, 0.03); }
}

.alarm-heading {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 132px;
}

.alarm-label {
        font-size: 0.52rem;
        color: var(--text-faint);
        font-weight: 700;
        letter-spacing: 0.16em;
        text-transform: uppercase;
}

.alarm-indicator {
    width: 8px;
    height: 8px;
        border-radius: 2px;
        background: var(--dcs-normal);
    flex-shrink: 0;
}
.alarm-banner.has-alarms .alarm-indicator {
        background: var(--dcs-alarm);
        animation: pulse-sq 1s infinite;
}
@keyframes pulse-sq { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

.alarm-time {
    color: var(--text-muted);
    flex-shrink: 0;
}

.alarm-text {
    color: var(--dcs-alarm);
    font-weight: 700;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    letter-spacing: 0.06em;
}

.alarm-count-badge {
    border: 1px solid rgba(239, 99, 92, 0.42);
    background: rgba(239, 99, 92, 0.12);
    color: #ffd5d2;
    font-size: 0.54rem;
    font-weight: 700;
    padding: 4px 8px;
    border-radius: 999px;
    text-align: center;
    flex-shrink: 0;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.alarm-view-btn {
    background: rgba(239, 99, 92, 0.1);
    border: 1px solid rgba(239, 99, 92, 0.42);
    color: #ffd5d2;
    font-size: 0.54rem;
    font-weight: 700;
    padding: 6px 10px;
    border-radius: 999px;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    flex-shrink: 0;
    transition: background 0.12s, border-color 0.12s;
}
.alarm-view-btn:hover {
    background: rgba(239, 99, 92, 0.2);
    border-color: rgba(255, 213, 210, 0.35);
}

.no-alarms {
    color: var(--text-secondary);
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.05em;
}
</style>
