<script setup>
import { computed } from 'vue'
import { state } from '../services/store'

const logs = computed(() => state.logs)

function normalizeMessage(msg = '') {
  if (msg.startsWith('Phase changed to ')) {
    const phase = msg.replace('Phase changed to ', '').trim()
    return `Phase → ${phase}`
  }
  return msg
}

function typeLabel(type = 'info') {
  if (type === 'error') return 'ALARM'
  if (type === 'warn') return 'WARN'
  if (type === 'success') return 'OK'
  return 'INFO'
}
</script>

<template>
  <div class="event-log custom-scrollbar">
  <div v-if="logs.length === 0" class="empty-log">No events yet</div>
  <div v-for="(log, i) in logs" :key="i" class="log-entry" :class="`type-${log.type || 'info'}`">
    <div class="entry-head">
      <span class="time">{{ log.time }}</span>
      <span class="badge">{{ typeLabel(log.type) }}</span>
    </div>
    <div class="msg">{{ normalizeMessage(log.msg) }}</div>
    </div>
  </div>
</template>

<style scoped>
.event-log {
    background: var(--bg-app);
    border: 1px solid var(--border-subtle); 
    border-radius: 6px;
  height: 240px;
    overflow-y: auto;
  padding: 6px;
    font-family: var(--font-mono);
  font-size: 0.72rem;
}

.log-entry {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 8px;
  margin-bottom: 4px;
  border: 1px solid var(--border-subtle);
  border-left-width: 3px;
  border-radius: 4px;
  background: var(--bg-panel);
}

.entry-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.time {
  color: var(--text-muted);
  font-size: 0.64rem;
  letter-spacing: 0.05em;
}

.badge {
  font-size: 0.56rem;
  font-weight: 700;
  letter-spacing: 0.07em;
  color: var(--text-muted);
}

.msg {
  color: var(--text-primary);
  line-height: 1.35;
  overflow-wrap: anywhere;
  word-break: normal;
}

.type-error {
  border-left-color: var(--accent-danger);
}
.type-error .badge,
.type-error .msg {
  color: var(--accent-danger);
}

.type-warn {
  border-left-color: var(--accent-warning);
}
.type-warn .badge {
  color: var(--accent-warning);
}

.type-success {
  border-left-color: var(--accent-success);
}
.type-success .badge {
  color: var(--accent-success);
}

.type-info {
  border-left-color: var(--accent-primary);
}
.type-info .badge {
  color: var(--accent-primary);
}

.empty-log {
  color: var(--text-muted);
  text-align: center;
  margin-top: 18px;
  font-size: 0.68rem;
  opacity: 0.75;
}

/* Scrollbar styling */
.custom-scrollbar::-webkit-scrollbar { width: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: var(--bg-app); }
.custom-scrollbar::-webkit-scrollbar-thumb { background: var(--border-subtle); border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
</style>
