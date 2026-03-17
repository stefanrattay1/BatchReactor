<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { startBatchRun, getBatchStatus, cancelBatchRun, fetchBatchLogs } from '../services/api'
import BatchChart from './BatchChart.vue'

const emit = defineEmits(['close', 'completed'])

// --- State ---
const view = ref('config') // config | running | done | chart
const recipes = ref([])
const selectedRecipe = ref('')
const postRecipeTime = ref(60)
const stopConversion = ref('')
const error = ref('')
const status = ref({})
let pollId = null

// Chart state
const chartFilename = ref('')

// Batch history
const batchLogs = ref([])
const showHistory = ref(false)

// --- Load recipes + batch history ---
onMounted(async () => {
    try {
        const res = await fetch('/api/recipes')
        const data = await res.json()
        recipes.value = data.recipes || []
        if (data.current_file) {
            const parts = data.current_file.replace(/\\/g, '/').split('/')
            selectedRecipe.value = parts[parts.length - 1]
        }
    } catch (e) { console.error(e) }

    // Check if a batch is already running
    try {
        const s = await getBatchStatus()
        if (s.status === 'running') {
            status.value = s
            view.value = 'running'
            startPolling()
        } else if (s.status === 'completed' || s.status === 'cancelled') {
            status.value = s
            view.value = 'done'
        }
    } catch (e) { /* ignore */ }

    loadHistory()
})

onUnmounted(() => stopPolling())

async function loadHistory() {
    batchLogs.value = await fetchBatchLogs()
}

// --- Actions ---
async function run() {
    error.value = ''
    const opts = {}
    if (selectedRecipe.value) opts.recipe = selectedRecipe.value
    if (postRecipeTime.value !== '') opts.post_recipe_time = parseFloat(postRecipeTime.value)
    if (stopConversion.value !== '' && parseFloat(stopConversion.value) > 0) {
        opts.stop_conversion = parseFloat(stopConversion.value)
    }
    try {
        await startBatchRun(opts)
        view.value = 'running'
        startPolling()
    } catch (e) {
        error.value = e.message
    }
}

async function cancel() {
    try {
        await cancelBatchRun()
    } catch (e) {
        error.value = e.message
    }
}

function runAnother() {
    status.value = {}
    error.value = ''
    chartFilename.value = ''
    view.value = 'config'
    loadHistory()
}

function viewChart() {
    if (result.value && result.value.csv_path) {
        const parts = result.value.csv_path.replace(/\\/g, '/').split('/')
        chartFilename.value = parts[parts.length - 1]
        view.value = 'chart'
    }
}

function viewHistoryChart(filename) {
    chartFilename.value = filename
    view.value = 'chart'
}

function backFromChart() {
    if (result.value) {
        view.value = 'done'
    } else {
        view.value = 'config'
    }
}

function startPolling() {
    stopPolling()
    pollStatus()
    pollId = setInterval(pollStatus, 500)
}

function stopPolling() {
    if (pollId) { clearInterval(pollId); pollId = null }
}

async function pollStatus() {
    try {
        const s = await getBatchStatus()
        status.value = s
        if (s.status === 'completed' || s.status === 'error' || s.status === 'cancelled') {
            stopPolling()
            view.value = 'done'
            if (s.status === 'completed') {
                emit('completed')
                loadHistory()
            }
        }
    } catch (e) { /* ignore */ }
}

// --- Computed ---
const pct = computed(() => status.value.pct_complete || 0)
const elapsed = computed(() => status.value.elapsed || 0)
const totalEst = computed(() => status.value.total_estimate || 1)
const temp = computed(() => status.value.temperature || 0)
const conv = computed(() => status.value.conversion || 0)
const phase = computed(() => status.value.phase || '-')
const result = computed(() => status.value.result || null)

function fmtTime(s) {
    if (s < 60) return `${s.toFixed(0)}s`
    if (s < 3600) return `${(s / 60).toFixed(1)} min`
    return `${(s / 3600).toFixed(1)} h`
}

function fmtDate(ts) {
    return new Date(ts * 1000).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    })
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal-content" :class="{ 'modal-wide': view === 'chart' }">
      <!-- Header -->
      <div class="modal-header">
        <h2>Batch Simulation</h2>
        <span class="modal-subtitle">
          <template v-if="view === 'chart'">{{ chartFilename }}</template>
          <template v-else>Run a complete simulation without real-time pacing</template>
        </span>
        <button class="close-btn" @click="emit('close')">x</button>
      </div>

      <!-- CONFIG VIEW -->
      <div v-if="view === 'config'" class="modal-body">
        <div class="form-section">
          <label class="form-label">Recipe</label>
          <select class="form-select" v-model="selectedRecipe">
            <option v-for="r in recipes" :key="r.filename" :value="r.filename">
              {{ r.name }} ({{ (r.total_duration / 60).toFixed(0) }} min, {{ r.steps }} steps)
            </option>
          </select>
        </div>

        <div class="form-row">
          <div class="form-section">
            <label class="form-label">Post-recipe hold (s)</label>
            <input class="form-input" type="number" v-model="postRecipeTime" min="0" step="10" />
          </div>
          <div class="form-section">
            <label class="form-label">Stop at conversion (0 = disabled)</label>
            <input class="form-input" type="number" v-model="stopConversion" min="0" max="1" step="0.01" placeholder="e.g. 0.98" />
          </div>
        </div>

        <div v-if="error" class="error-msg">{{ error }}</div>

        <!-- Batch History -->
        <div v-if="batchLogs.length > 0" class="history-section">
          <button class="history-toggle" @click="showHistory = !showHistory">
            <span class="history-title">Past Batches ({{ batchLogs.length }})</span>
            <span class="history-arrow" :class="{ open: showHistory }">&#9662;</span>
          </button>
          <div v-if="showHistory" class="history-list">
            <div v-for="log in batchLogs.slice(0, 10)" :key="log.filename" class="history-item" @click="viewHistoryChart(log.filename)">
              <div class="history-info">
                <span class="history-date">{{ fmtDate(log.modified) }}</span>
                <span class="history-meta">{{ log.rows }} pts &middot; {{ log.size_kb }} KB</span>
              </div>
              <span class="history-view">View</span>
            </div>
          </div>
        </div>
      </div>

      <!-- RUNNING VIEW -->
      <div v-if="view === 'running'" class="modal-body">
        <div class="progress-section">
          <div class="progress-header">
            <span class="progress-label">Simulating...</span>
            <span class="progress-pct">{{ pct.toFixed(1) }}%</span>
          </div>
          <div class="progress-bar-bg">
            <div class="progress-bar-fill" :style="{ width: pct + '%' }"></div>
          </div>
        </div>

        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">Elapsed</div>
            <div class="stat-value">{{ fmtTime(elapsed) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Temperature</div>
            <div class="stat-value">{{ (temp - 273.15).toFixed(1) }} C</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Conversion</div>
            <div class="stat-value">{{ (conv * 100).toFixed(1) }}%</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Phase</div>
            <div class="stat-value phase-val">{{ phase }}</div>
          </div>
        </div>
      </div>

      <!-- DONE VIEW -->
      <div v-if="view === 'done'" class="modal-body">
        <div v-if="status.status === 'error'" class="error-msg">
          Batch failed: {{ status.error }}
        </div>
        <div v-else-if="status.status === 'cancelled'" class="warn-msg">
          Batch was cancelled.
        </div>

        <div v-if="result" class="result-section">
          <h3 class="result-title">Results</h3>
          <div class="stats-grid">
            <div class="stat-card">
              <div class="stat-label">Simulated Time</div>
              <div class="stat-value">{{ fmtTime(result.total_time_s) }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Wall-Clock Time</div>
              <div class="stat-value">{{ result.wall_time_s.toFixed(1) }}s</div>
            </div>
            <div class="stat-card accent">
              <div class="stat-label">Speedup</div>
              <div class="stat-value">{{ result.speedup.toFixed(0) }}x</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Final Phase</div>
              <div class="stat-value phase-val">{{ result.final_phase }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Final Temp</div>
              <div class="stat-value">{{ result.final_temperature_C.toFixed(1) }} C</div>
            </div>
            <div class="stat-card">
              <div class="stat-label">Peak Temp</div>
              <div class="stat-value">{{ result.peak_temperature_C.toFixed(1) }} C</div>
            </div>
          </div>

          <div v-if="result.final_conversions" class="conversions">
            <div v-for="(val, key) in result.final_conversions" :key="key" class="conv-row">
              <span class="conv-name">{{ key }}</span>
              <div class="conv-bar-bg">
                <div class="conv-bar-fill" :style="{ width: (val * 100) + '%' }"></div>
              </div>
              <span class="conv-val">{{ (val * 100).toFixed(1) }}%</span>
            </div>
          </div>

          <div class="csv-path">
            <span class="csv-label">CSV log:</span>
            <code class="csv-file">{{ result.csv_path }}</code>
          </div>
        </div>
      </div>

      <!-- CHART VIEW -->
      <div v-if="view === 'chart'" class="modal-body">
        <BatchChart :filename="chartFilename" />
      </div>

      <!-- Footer -->
      <div class="modal-footer">
        <div v-if="view === 'config'">
          <button class="btn btn-run" @click="run">Run Batch</button>
        </div>
        <div v-if="view === 'running'">
          <button class="btn btn-cancel" @click="cancel">Cancel</button>
        </div>
        <div v-if="view === 'done'" class="footer-actions">
          <button v-if="result" class="btn btn-chart" @click="viewChart">View Chart</button>
          <button class="btn btn-again" @click="runAnother">Run Another</button>
          <button class="btn btn-close" @click="emit('close')">Close</button>
        </div>
        <div v-if="view === 'chart'" class="footer-actions">
          <button class="btn btn-back" @click="backFromChart">Back</button>
          <button class="btn btn-close" @click="emit('close')">Close</button>
        </div>
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
.modal-content.modal-wide {
    width: 820px;
}
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

/* --- Config form --- */
.form-section { margin-bottom: 16px; }
.form-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
.form-select, .form-input {
    width: 100%; padding: 8px 12px;
    background: var(--bg-input); border: 1px solid var(--border-subtle);
    color: var(--text-primary); font-size: 13px; border-radius: 6px;
    font-family: var(--font-mono);
}
.form-select:focus, .form-input:focus { outline: none; border-color: var(--accent-primary); }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

.error-msg { padding: 10px 14px; background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); border-radius: 8px; color: var(--accent-danger); font-size: 12px; margin-top: 8px; }
.warn-msg { padding: 10px 14px; background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.3); border-radius: 8px; color: var(--accent-warning); font-size: 12px; margin-bottom: 12px; }

/* --- Progress --- */
.progress-section { margin-bottom: 20px; }
.progress-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
.progress-label { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.progress-pct { font-size: 13px; font-weight: 700; color: var(--accent-primary); font-family: var(--font-mono); }
.progress-bar-bg { height: 8px; background: var(--bg-app); border-radius: 4px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent-primary); border-radius: 4px; transition: width 0.3s ease; }

/* --- Stats grid --- */
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; margin-bottom: 16px; }
.stat-card {
    padding: 12px 14px; background: var(--bg-app); border: 1px solid var(--border-subtle);
    border-radius: 8px;
}
.stat-card.accent { border-color: var(--accent-primary); }
.stat-label { font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
.stat-value { font-size: 18px; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); }
.phase-val { font-size: 13px; }

/* --- Results --- */
.result-title { font-size: 13px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }

.conversions { margin-bottom: 16px; }
.conv-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.conv-name { font-size: 12px; color: var(--text-secondary); font-family: var(--font-mono); width: 80px; }
.conv-bar-bg { flex: 1; height: 6px; background: var(--bg-app); border-radius: 3px; overflow: hidden; }
.conv-bar-fill { height: 100%; background: var(--accent-success); border-radius: 3px; }
.conv-val { font-size: 12px; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); width: 50px; text-align: right; }

.csv-path {
    padding: 10px 14px; background: var(--bg-app); border: 1px solid var(--border-subtle);
    border-radius: 8px; display: flex; align-items: center; gap: 8px;
}
.csv-label { font-size: 11px; font-weight: 600; color: var(--text-muted); white-space: nowrap; }
.csv-file { font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); word-break: break-all; }

/* --- History --- */
.history-section { margin-top: 20px; border-top: 1px solid var(--border-subtle); padding-top: 12px; }
.history-toggle {
    display: flex; align-items: center; justify-content: space-between;
    width: 100%; padding: 8px 0; background: none; border: none;
    cursor: pointer; color: var(--text-secondary);
}
.history-toggle:hover { color: var(--text-primary); }
.history-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
.history-arrow { font-size: 12px; transition: transform 0.2s; }
.history-arrow.open { transform: rotate(180deg); }

.history-list { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.history-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 12px; background: var(--bg-app); border: 1px solid var(--border-subtle);
    border-radius: 6px; cursor: pointer; transition: all 0.15s;
}
.history-item:hover { border-color: var(--accent-primary); }
.history-info { display: flex; flex-direction: column; gap: 2px; }
.history-date { font-size: 12px; color: var(--text-primary); font-family: var(--font-mono); }
.history-meta { font-size: 10px; color: var(--text-muted); }
.history-view {
    font-size: 10px; font-weight: 600; color: var(--accent-primary);
    text-transform: uppercase; letter-spacing: 0.05em;
}

/* --- Footer --- */
.modal-footer {
    padding: 12px 24px; border-top: 1px solid var(--border-subtle);
    display: flex; justify-content: flex-end;
}
.footer-actions { display: flex; gap: 8px; }

.btn {
    padding: 8px 20px; border: none; border-radius: 6px;
    font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.btn:hover { opacity: 0.9; transform: translateY(-1px); }
.btn-run { background: var(--accent-success); color: white; }
.btn-cancel { background: var(--accent-danger); color: white; }
.btn-again { background: var(--accent-primary); color: white; }
.btn-chart { background: var(--accent-info); color: white; }
.btn-back { background: var(--text-muted); color: white; }
.btn-close { background: var(--text-muted); color: white; }
</style>
