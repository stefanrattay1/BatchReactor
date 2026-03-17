<script setup>
import { computed } from 'vue'
import BatchChart from './BatchChart.vue'

const props = defineProps({
    mode: { type: String, required: true },       // 'live' or 'batch'
    batchResult: { type: Object, default: null },  // BatchResult.to_dict() for batch mode
    liveState: { type: Object, default: null },    // Snapshot of store state for live mode
})

const emit = defineEmits(['close', 'run-another'])

// Normalize data from both sources into a common format
const results = computed(() => {
    if (props.mode === 'batch' && props.batchResult) {
        const r = props.batchResult
        return {
            finalPhase: r.final_phase,
            finalTempC: r.final_temperature_C,
            peakTempC: r.peak_temperature_C,
            conversion: r.final_conversions,
            totalTimeS: r.total_time_s,
            wallTimeS: r.wall_time_s,
            speedup: r.speedup,
            totalTicks: r.total_ticks,
            csvPath: r.csv_path,
            masses: r.final_masses,
        }
    } else if (props.mode === 'live' && props.liveState) {
        const s = props.liveState
        return {
            finalPhase: s.phase,
            finalTempC: s.temperature_C,
            peakTempC: s.peak_temperature_C,
            conversion: { alpha: s.conversion },
            totalTimeS: s.recipe_elapsed_s,
            wallTimeS: null,
            speedup: null,
            totalTicks: null,
            csvPath: null,
            masses: {
              component_a: s.mass_component_a_kg,
              component_b: s.mass_component_b_kg,
                product: s.mass_product_kg,
                solvent: s.mass_solvent_kg,
            },
        }
    }
    return null
})

const phaseClass = computed(() => results.value ? `phase-${results.value.finalPhase}` : '')

const title = computed(() => props.mode === 'batch' ? 'Batch Simulation Complete' : 'Process Complete')

const csvFilename = computed(() => {
    if (!results.value || !results.value.csvPath) return null
    const parts = results.value.csvPath.replace(/\\/g, '/').split('/')
    return parts[parts.length - 1]
})

function fmtTime(s) {
    if (s == null) return '--'
    if (s < 60) return `${s.toFixed(0)}s`
    if (s < 3600) return `${(s / 60).toFixed(1)} min`
    return `${(s / 3600).toFixed(1)} h`
}
</script>

<template>
  <div class="results-overlay" @click.self="emit('close')">
    <div class="results-panel">
      <!-- Header -->
      <div class="results-header">
        <div class="results-header-left">
          <div class="results-icon">&#10003;</div>
          <div>
            <h2>{{ title }}</h2>
            <span class="results-subtitle">{{ mode === 'batch' ? 'Offline simulation finished' : 'Live simulation ended' }}</span>
          </div>
        </div>
        <span v-if="results" class="phase-badge" :class="phaseClass">{{ results.finalPhase }}</span>
        <button class="close-btn" @click="emit('close')">x</button>
      </div>

      <div v-if="results" class="results-body">
        <!-- Stats Grid -->
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">Simulated Time</div>
            <div class="stat-value">{{ fmtTime(results.totalTimeS) }}</div>
          </div>
          <div class="stat-card highlight-temp">
            <div class="stat-label">Peak Temperature</div>
            <div class="stat-value">{{ results.peakTempC.toFixed(1) }} C</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Final Temperature</div>
            <div class="stat-value">{{ results.finalTempC.toFixed(1) }} C</div>
          </div>
          <div v-if="results.wallTimeS != null" class="stat-card">
            <div class="stat-label">Wall-Clock Time</div>
            <div class="stat-value">{{ results.wallTimeS.toFixed(1) }}s</div>
          </div>
          <div v-if="results.speedup != null" class="stat-card highlight-accent">
            <div class="stat-label">Speedup</div>
            <div class="stat-value">{{ results.speedup.toFixed(0) }}x</div>
          </div>
          <div v-if="results.totalTicks != null" class="stat-card">
            <div class="stat-label">Total Ticks</div>
            <div class="stat-value">{{ results.totalTicks.toLocaleString() }}</div>
          </div>
        </div>

        <!-- Conversions -->
        <div class="section-title">Conversions</div>
        <div class="conversions">
          <div v-for="(val, key) in results.conversion" :key="key" class="conv-row">
            <span class="conv-name">{{ key }}</span>
            <div class="conv-bar-bg">
              <div class="conv-bar-fill" :style="{ width: (val * 100) + '%' }"></div>
            </div>
            <span class="conv-val">{{ (val * 100).toFixed(1) }}%</span>
          </div>
        </div>

        <!-- Masses -->
        <div class="section-title">Final Masses</div>
        <div class="masses-grid">
          <div v-for="(val, key) in results.masses" :key="key" class="mass-item">
            <span class="mass-name">{{ key }}</span>
            <span class="mass-val">{{ val != null ? val.toFixed(2) : '--' }} kg</span>
          </div>
        </div>

        <!-- CSV Path (batch only) -->
        <div v-if="results.csvPath" class="csv-section">
          <span class="csv-label">CSV log:</span>
          <code class="csv-file">{{ results.csvPath }}</code>
        </div>

        <!-- Batch Chart -->
        <div v-if="csvFilename" class="chart-section">
          <div class="section-title">Process Chart</div>
          <BatchChart :filename="csvFilename" />
        </div>
      </div>

      <!-- Footer -->
      <div class="results-footer">
        <button v-if="mode === 'batch'" class="btn btn-again" @click="emit('run-another')">Run Another</button>
        <button class="btn btn-close" @click="emit('close')">Close</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.results-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    display: flex; align-items: center; justify-content: center;
    z-index: 1000; backdrop-filter: blur(4px);
}
.results-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 16px;
    width: 820px; max-width: 90vw; max-height: 85vh;
    display: flex; flex-direction: column;
    box-shadow: 0 24px 48px rgba(0,0,0,0.5);
    animation: slideUp 0.25s ease-out;
}
@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

/* Header */
.results-header {
    padding: 20px 24px 16px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex; align-items: center; gap: 12px;
}
.results-header-left { display: flex; align-items: center; gap: 12px; flex: 1; }
.results-icon {
    width: 36px; height: 36px; border-radius: 10px;
    background: var(--accent-success); color: white;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 700;
}
.results-header h2 { font-size: 16px; font-weight: 700; color: var(--text-primary); margin: 0; }
.results-subtitle { font-size: 11px; color: var(--text-muted); }

.phase-badge { padding: 4px 12px; border-radius: 6px; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
.phase-IDLE { background: var(--text-muted); color: white; }
.phase-CHARGING { background: var(--accent-primary); color: white; }
.phase-HEATING { background: var(--accent-warning); color: white; }
.phase-EXOTHERM { background: var(--accent-danger); color: white; }
.phase-COOLING { background: var(--sensor-level); color: white; }
.phase-DISCHARGING { background: var(--accent-success); color: white; }
.phase-RUNAWAY_ALARM { background: var(--accent-danger); color: white; }

.close-btn {
    background: var(--bg-app); border: 1px solid var(--border-subtle); color: var(--text-secondary);
    font-size: 16px; cursor: pointer; width: 28px; height: 28px; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
}
.close-btn:hover { color: var(--text-primary); border-color: var(--text-muted); }

/* Body */
.results-body { padding: 20px 24px; overflow-y: auto; flex: 1; }

/* Stats Grid */
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px; }
.stat-card {
    padding: 14px 16px; background: var(--bg-app); border: 1px solid var(--border-subtle);
    border-radius: 10px;
}
.stat-card.highlight-temp { border-color: var(--sensor-temp); }
.stat-card.highlight-accent { border-color: var(--accent-primary); }
.stat-label { font-size: 10px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
.stat-value { font-size: 20px; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); }

/* Section titles */
.section-title {
    font-size: 11px; font-weight: 700; color: var(--text-muted);
    text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px;
}

/* Conversions */
.conversions { margin-bottom: 20px; }
.conv-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.conv-name { font-size: 12px; color: var(--text-secondary); font-family: var(--font-mono); width: 80px; }
.conv-bar-bg { flex: 1; height: 8px; background: var(--bg-app); border-radius: 4px; overflow: hidden; }
.conv-bar-fill { height: 100%; background: var(--accent-success); border-radius: 4px; transition: width 0.3s; }
.conv-val { font-size: 13px; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); width: 60px; text-align: right; }

/* Masses */
.masses-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin-bottom: 20px; }
.mass-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 12px; background: var(--bg-app); border: 1px solid var(--border-subtle);
    border-radius: 6px;
}
.mass-name { font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); text-transform: capitalize; }
.mass-val { font-size: 12px; font-weight: 600; color: var(--text-primary); font-family: var(--font-mono); }

/* Chart */
.chart-section { margin-top: 20px; }

/* CSV */
.csv-section {
    padding: 10px 14px; background: var(--bg-app); border: 1px solid var(--border-subtle);
    border-radius: 8px; display: flex; align-items: center; gap: 8px;
}
.csv-label { font-size: 11px; font-weight: 600; color: var(--text-muted); white-space: nowrap; }
.csv-file { font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); word-break: break-all; }

/* Footer */
.results-footer {
    padding: 14px 24px; border-top: 1px solid var(--border-subtle);
    display: flex; justify-content: flex-end; gap: 8px;
}
.btn {
    padding: 8px 20px; border: none; border-radius: 6px;
    font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.btn:hover { opacity: 0.9; transform: translateY(-1px); }
.btn-again { background: var(--accent-primary); color: white; }
.btn-close { background: var(--text-muted); color: white; }

@media (max-width: 640px) {
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
