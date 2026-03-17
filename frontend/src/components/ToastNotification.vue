<script setup>
import { ref, watch } from 'vue'
import { sensorConfig } from '../services/sensorConfig'
import { actions } from '../services/store'

const toasts = ref([])
let toastIdCounter = 0

watch(() => sensorConfig.activeAlarms.length, (newLen, oldLen) => {
    if (newLen > oldLen) {
        // New alarms added - show toasts for the new ones
        const newAlarms = sensorConfig.activeAlarms.slice(oldLen)
        for (const alarm of newAlarms) {
            const id = ++toastIdCounter
            const toast = {
                id,
                type: alarm.type,
                name: alarm.name,
                value: typeof alarm.value === 'number' ? alarm.value.toFixed(2) : alarm.value,
                threshold: typeof alarm.threshold === 'number' ? alarm.threshold.toFixed(2) : alarm.threshold,
                unit: '',
                time: new Date().toLocaleTimeString('en-GB', { hour12: false }),
            }

            // Find unit from node catalog
            const node = sensorConfig.availableNodes.find(n => n.id === alarm.id)
            if (node) toast.unit = node.unit

            toasts.value.push(toast)

            // Log to event system
            const typeLabel = alarm.type === 'high' ? 'HIGH' : 'LOW'
            actions.addLog(`ALARM: ${alarm.name} ${typeLabel} (${toast.value} ${toast.unit})`, 'error')

            // Auto-dismiss
            const timeout = alarm.type === 'high' ? 8000 : 12000
            setTimeout(() => dismiss(id), timeout)
        }

        // Trim to max 5 visible
        while (toasts.value.length > 5) {
            toasts.value.shift()
        }
    }
})

function dismiss(id) {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx >= 0) toasts.value.splice(idx, 1)
}
</script>

<template>
  <div class="toast-container">
    <transition-group name="toast">
      <div v-for="toast in toasts" :key="toast.id"
           class="toast" :class="'toast-' + toast.type">
        <div class="toast-icon">{{ toast.type === 'high' ? '▲' : '▼' }}</div>
        <div class="toast-body">
          <div class="toast-title">{{ toast.name }} {{ toast.type === 'high' ? 'HIGH' : 'LOW' }} ALARM</div>
          <div class="toast-detail">
            {{ toast.value }} {{ toast.unit }}
            {{ toast.type === 'high' ? '>' : '<' }}
            {{ toast.threshold }} {{ toast.unit }}
          </div>
          <div class="toast-time">{{ toast.time }}</div>
        </div>
        <button class="toast-dismiss" @click="dismiss(toast.id)">x</button>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-container {
    position: fixed;
    top: 70px; right: 20px;
    z-index: 1100;
    display: flex; flex-direction: column; gap: 8px;
    pointer-events: none;
    max-width: 320px;
}

.toast {
    pointer-events: all;
    display: flex; align-items: flex-start; gap: 10px;
    padding: 12px 14px;
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    border-left: 4px solid;
}
.toast-high { border-left-color: #ef4444; }
.toast-low { border-left-color: #3b82f6; }

.toast-icon {
    font-size: 14px; font-weight: 700;
    width: 24px; height: 24px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 50%; flex-shrink: 0;
}
.toast-high .toast-icon { color: #ef4444; background: rgba(239,68,68,0.15); }
.toast-low .toast-icon { color: #3b82f6; background: rgba(59,130,246,0.15); }

.toast-body { flex: 1; min-width: 0; }
.toast-title { font-size: 12px; font-weight: 700; color: #e2e8f0; margin-bottom: 2px; }
.toast-detail { font-size: 11px; color: #94a3b8; font-family: monospace; }
.toast-time { font-size: 9px; color: #475569; margin-top: 2px; }

.toast-dismiss {
    background: none; border: none; color: #64748b;
    font-size: 14px; cursor: pointer; padding: 0; line-height: 1;
    flex-shrink: 0;
}
.toast-dismiss:hover { color: #e2e8f0; }

/* Transitions */
.toast-enter-active { animation: toastIn 0.3s ease-out; }
.toast-leave-active { animation: toastOut 0.2s ease-in; }
@keyframes toastIn { from { opacity: 0; transform: translateX(100px); } to { opacity: 1; transform: translateX(0); } }
@keyframes toastOut { from { opacity: 1; transform: translateX(0); } to { opacity: 0; transform: translateX(100px); } }
</style>
