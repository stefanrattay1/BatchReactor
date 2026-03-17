<script setup>
import { computed } from 'vue'
import { sensorConfig, dismissAlarm } from '../services/sensorConfig'

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
    return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<template>
  <div class="alarm-banner" :class="{ 'has-alarms': alarmCount > 0 }">
    <template v-if="alarmCount > 0">
      <span class="alarm-indicator"></span>
      <span class="alarm-time">{{ formatTime(topAlarm.time) }}</span>
      <span class="alarm-text">
        {{ topAlarm.name }} — {{ topAlarm.type === 'high' ? 'HI' : 'LO' }}
        ({{ formatValue(topAlarm.value) }})
      </span>
      <span class="alarm-count-badge">{{ alarmCount }}</span>
      <button class="alarm-view-btn" @click="emit('open-drawer')">VIEW ALL</button>
    </template>
    <template v-else>
      <span class="no-alarms">NO ACTIVE ALARMS</span>
    </template>
  </div>
</template>

<style scoped>
.alarm-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 14px;
    height: 26px;
    background: #1a1a1a;
    border-bottom: 1px solid #2e2e2e;
    flex-shrink: 0;
    font-size: 0.68rem;
    font-family: var(--font-mono);
}

.alarm-banner.has-alarms {
    background: rgba(239, 68, 68, 0.1);
    border-bottom-color: var(--dcs-alarm);
    animation: alarm-bg-pulse 2s ease-in-out infinite;
}

@keyframes alarm-bg-pulse {
    0%, 100% { background: rgba(239, 68, 68, 0.10); }
    50% { background: rgba(239, 68, 68, 0.18); }
}

.alarm-indicator {
    width: 8px;
    height: 8px;
    border-radius: 1px;
    background: var(--dcs-alarm);
    flex-shrink: 0;
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
    letter-spacing: 0.04em;
}

.alarm-count-badge {
    background: var(--dcs-alarm);
    color: white;
    font-size: 0.58rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 1px;
    min-width: 18px;
    text-align: center;
    flex-shrink: 0;
}

.alarm-view-btn {
    background: transparent;
    border: 1px solid var(--dcs-alarm);
    color: var(--dcs-alarm);
    font-size: 0.58rem;
    font-weight: 700;
    padding: 1px 8px;
    border-radius: 1px;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    flex-shrink: 0;
    transition: background 0.1s;
}
.alarm-view-btn:hover {
    background: var(--dcs-alarm);
    color: white;
}

.no-alarms {
    color: var(--text-muted);
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.12em;
}
</style>
