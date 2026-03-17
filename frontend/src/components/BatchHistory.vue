<script setup>
import { ref, onMounted } from 'vue'
import { fetchBatchLogs } from '../services/api'
import BatchChart from './BatchChart.vue'

const emit = defineEmits(['close'])

const logs = ref([])
const loading = ref(true)
const selectedFile = ref(null)

onMounted(async () => {
    logs.value = await fetchBatchLogs()
    loading.value = false
})

function selectLog(filename) {
    selectedFile.value = filename
}

function back() {
    selectedFile.value = null
}

function fmtDate(ts) {
    return new Date(ts * 1000).toLocaleString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
    })
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-content" :class="{ wide: selectedFile }">
      <!-- Header -->
      <div class="modal-header">
        <h2>{{ selectedFile ? 'Batch Chart' : 'Batch History' }}</h2>
        <span class="modal-subtitle">
          <template v-if="selectedFile">{{ selectedFile }}</template>
          <template v-else>{{ logs.length }} simulation{{ logs.length !== 1 ? 's' : '' }} recorded</template>
        </span>
        <button class="close-btn" @click="emit('close')">x</button>
      </div>

      <!-- List view -->
      <div v-if="!selectedFile" class="modal-body">
        <div v-if="loading" class="loading">Loading...</div>
        <div v-else-if="logs.length === 0" class="empty">No batch simulations found.</div>
        <div v-else class="log-list">
          <div v-for="log in logs" :key="log.filename" class="log-item" @click="selectLog(log.filename)">
            <div class="log-info">
              <span class="log-date">{{ fmtDate(log.modified) }}</span>
              <span class="log-meta">{{ log.rows }} data points &middot; {{ log.size_kb }} KB</span>
            </div>
            <span class="log-filename">{{ log.filename }}</span>
            <span class="log-action">View</span>
          </div>
        </div>
      </div>

      <!-- Chart view -->
      <div v-else class="modal-body">
        <BatchChart :filename="selectedFile" />
      </div>

      <!-- Footer -->
      <div class="modal-footer">
        <button v-if="selectedFile" class="btn btn-back" @click="back">Back to list</button>
        <button class="btn btn-close" @click="emit('close')">Close</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000; backdrop-filter: blur(4px);
}
.modal-content {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 16px;
    width: 560px; max-width: 90vw; max-height: 85vh;
    display: flex; flex-direction: column;
    box-shadow: 0 24px 48px rgba(0,0,0,0.5);
    animation: slideUp 0.2s ease-out;
    transition: width 0.3s ease;
}
.modal-content.wide { width: 820px; }
@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

.modal-header {
    padding: 20px 24px 12px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.modal-header h2 { font-size: 16px; font-weight: 700; color: var(--text-primary); margin: 0; }
.modal-subtitle { font-size: 11px; color: var(--text-muted); flex: 1; }
.close-btn {
    background: var(--bg-app); border: 1px solid var(--border-subtle); color: var(--text-secondary);
    font-size: 16px; cursor: pointer; width: 28px; height: 28px; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
}
.close-btn:hover { color: var(--text-primary); border-color: var(--text-muted); }

.modal-body { padding: 20px 24px; overflow-y: auto; flex: 1; }

.loading, .empty {
    text-align: center; padding: 40px 0; color: var(--text-muted); font-size: 13px;
}

.log-list { display: flex; flex-direction: column; gap: 6px; }
.log-item {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 16px; background: var(--bg-app); border: 1px solid var(--border-subtle);
    border-radius: 8px; cursor: pointer; transition: all 0.15s;
}
.log-item:hover { border-color: var(--accent-primary); background: color-mix(in srgb, var(--accent-primary) 5%, var(--bg-app)); }

.log-info { display: flex; flex-direction: column; gap: 2px; min-width: 160px; }
.log-date { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.log-meta { font-size: 10px; color: var(--text-muted); }
.log-filename { flex: 1; font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); }
.log-action {
    font-size: 10px; font-weight: 700; color: var(--accent-primary);
    text-transform: uppercase; letter-spacing: 0.05em;
    padding: 4px 10px; border: 1px solid var(--accent-primary); border-radius: 4px;
    white-space: nowrap;
}
.log-item:hover .log-action { background: var(--accent-primary); color: white; }

.modal-footer {
    padding: 12px 24px; border-top: 1px solid var(--border-subtle);
    display: flex; justify-content: flex-end; gap: 8px;
}
.btn {
    padding: 8px 20px; border: none; border-radius: 6px;
    font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.btn:hover { opacity: 0.9; transform: translateY(-1px); }
.btn-back { background: var(--accent-info); color: white; }
.btn-close { background: var(--text-muted); color: white; }
</style>
