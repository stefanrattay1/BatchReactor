<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { state, actions } from '../services/store'
import { selectRecipe } from '../services/api'
import { sensorConfig } from '../services/sensorConfig'
import MainChart from './MainChart.vue'
import EventLog from './EventLog.vue'

// KPIs
const temp = computed(() => state.temperature_C.toFixed(1))
const conv = computed(() => (state.conversion * 100).toFixed(1))
const time = computed(() => state.recipe_elapsed_s.toFixed(0))
const viscosityCap = computed(() => state.viscosity_max ?? 1e6)

// OPC Nodes
const opcValues = computed(() => ({
    temp: state.temperature_K.toFixed(1) + ' K',
    jacket: state.jacket_temperature_K.toFixed(1) + ' K',
    press: state.pressure_bar.toFixed(3) + ' bar',
    conv: state.conversion.toFixed(4),
    visc: state.viscosity_Pas >= viscosityCap.value ? 'GEL' : state.viscosity_Pas.toFixed(1) + ' Pa·s',
    mass: state.mass_total_kg.toFixed(2) + ' kg',
    vol: state.volume_L.toFixed(1) + ' L (' + state.fill_pct.toFixed(0) + '%)'
}))

function selectInput(id) { actions.selectInput(id) }

function getNodeValue(node) {
    if (!node.state_key) return '--'
    const val = state[node.state_key]
    if (val === undefined || val === null) return '--'
    if (typeof val === 'number') {
        if (node.unit === 'bar') return val.toFixed(3) + ' bar'
        if (node.unit === 'K') return val.toFixed(1) + ' K'
        if (node.unit === 'Pa·s') return val >= viscosityCap.value ? 'GEL' : val.toFixed(1) + ' Pa·s'
        if (node.unit === 'kg') return val.toFixed(2) + ' kg'
        if (node.unit === 's') return val.toFixed(0) + ' s'
        if (node.id === 'conversion') return val.toFixed(4)
        return val.toFixed(2) + (node.unit ? ' ' + node.unit : '')
    }
    return String(val)
}

// Recipes List
const recipes = ref([])
const currentRecipeFile = ref('')

async function loadRecipes() {
    try {
        const res = await fetch('/api/recipes')
        const data = await res.json()
        recipes.value = data.recipes
        currentRecipeFile.value = data.current_file
    } catch(e) {}
}
onMounted(loadRecipes)

async function handleSelectRecipe(filename) {
    if (state.simulation_running) return
    if (confirm(`Switch recipe to ${filename}?`)) {
        await selectRecipe(filename)
        // Reload details
        await loadRecipes()
        await loadSteps()
    }
}

// Steps List
const steps = ref([])
async function loadSteps() {
    try {
        const res = await fetch('/api/recipe/current')
        const data = await res.json()
        steps.value = data.steps
    } catch(e) {}
}
onMounted(loadSteps)

// Estimates Logic
const estTimeConv = computed(() => {
    if (state.conversion >= 0.95) return 'Complete'
    if (steps.value.length > 0 && state.recipe_elapsed_s > 0) {
        const totalDuration = steps.value.reduce((sum, s) => sum + s.duration, 0)
        const remaining = Math.max(0, totalDuration - state.recipe_elapsed_s)
        if (remaining <= 0) return '< 1 min'
        return (remaining / 60).toFixed(1) + ' min'
    }
    return '-- min'
})

// Track actual peak temperature observed during the run
const peakTempC = ref(0)
watch(() => state.temperature_C, (t) => {
    if (t > peakTempC.value) peakTempC.value = t
})
watch(() => state.phase, (p) => {
    if (p === 'IDLE') peakTempC.value = 0
})
const estPeakTemp = computed(() => {
    if (peakTempC.value <= 0) return '--'
    return Math.round(peakTempC.value) + '°C'
})

const estRunaway = computed(() => {
    if (state.dt_dt > 1.5 || state.temperature_K > 453) return { text: 'HIGH', color: '#ef4444' }
    if (state.dt_dt > 0.8 || state.temperature_K > 423) return { text: 'MODERATE', color: '#f59e0b' }
    if (state.dt_dt > 0.3) return { text: 'ELEVATED', color: '#eab308' }
    return { text: 'LOW', color: '#22c55e' }
})
</script>

<template>
  <div class="simulation-panel">
    <div class="panel-title">Simulation & Predictions</div>
    
    <!-- KPIs -->
    <div class="kpi-grid">
        <div class="kpi temp">
            <div id="kpi-temp" class="value">{{ temp }}</div>
            <div class="label">Temperature °C</div>
        </div>
        <div class="kpi conv">
            <div id="kpi-conv" class="value">{{ conv }}</div>
            <div class="label">Conversion %</div>
        </div>
        <div class="kpi time">
            <div id="kpi-time" class="value">{{ time }}</div>
            <div class="label">Elapsed (s)</div>
        </div>
    </div>
    
    <!-- Main Chart -->
    <div class="card">
        <h2>Temperature Trend</h2>
        <MainChart />
    </div>
    
    <!-- Estimates & Logic -->
    <div class="card highlight">
        <h2>🎯 Live Estimates</h2>
        <div class="estimate-row">
            <span class="estimate-label">Est. Batch Remaining</span>
            <span class="estimate-value">{{ estTimeConv }}</span>
        </div>
        <div class="estimate-row">
            <span class="estimate-label">Peak Temp</span>
            <span class="estimate-value">{{ estPeakTemp }}</span>
        </div>
        <div class="estimate-row">
            <span class="estimate-label">Runaway Risk</span>
            <span class="estimate-value" :style="{ color: estRunaway.color }">{{ estRunaway.text }}</span>
        </div>
    </div>

    <!-- Event Log -->
    <div class="card">
        <h2>System Events</h2>
        <EventLog />
    </div>
    
    <!-- OPC Nodes (Dynamic) -->
    <div class="card">
        <h2>OPC UA Live Values</h2>
        <div class="node-list">
            <div v-for="node in sensorConfig.availableNodes.filter(n => n.state_key)"
                 :key="node.id"
                 class="node-item"
                 :class="{ 'node-enabled': sensorConfig.enabledSensorIds.includes(node.id) }"
                 @click="selectInput(node.id)">
                <div class="name">
                    <span class="node-dot" :style="{ background: sensorConfig.sensorSettings[node.id]?.color || node.default_color }"></span>
                    {{ sensorConfig.sensorSettings[node.id]?.alias || node.name }}
                </div>
                <div class="value">{{ getNodeValue(node) }}</div>
                <div class="tag">{{ node.opc_path }}</div>
            </div>
        </div>
    </div>
    
    <!-- Recipe List -->
    <div class="card">
        <h2>Available Recipes <small style="font-weight:400; color:#64748b">(Click to select)</small></h2>
        <div v-for="r in recipes" :key="r.filename"
             class="recipe-item" :class="{ active: currentRecipeFile.endsWith(r.filename) }"
             @click="handleSelectRecipe(r.filename)">
            <div class="recipe-name">
                {{ r.name }}
                <span v-if="currentRecipeFile.endsWith(r.filename)" style="color:#22c55e; margin-left:6px;">●</span>
            </div>
            <div class="recipe-meta">{{ r.steps }} steps · {{ (r.total_duration/60).toFixed(0) }} min</div>
        </div>
    </div>

  </div>
</template>

<style scoped>
.simulation-panel { background: var(--bg-app); padding: 20px; overflow-y: auto; height: 100%; font-family: var(--font-sans); }

.panel-title { 
    font-size: 0.75rem; 
    font-weight: 700; 
    color: var(--text-muted); 
    text-transform: uppercase; 
    letter-spacing: 0.1em; 
    margin-bottom: 20px; 
    display: flex; align-items: center; gap: 8px; 
}
.panel-title::before { content: ''; width: 4px; height: 16px; background: var(--accent-primary); border-radius: 2px; }

.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
.kpi { 
    background: var(--bg-card); 
    border: 1px solid var(--border-subtle); 
    border-radius: 12px; 
    padding: 16px; 
    text-align: center; 
    box-shadow: var(--shadow-sm);
    transition: transform 0.2s;
}
.kpi:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: var(--border-focus); }

.kpi .value { font-size: 1.5rem; font-weight: 700; font-family: var(--font-mono); line-height: 1.2; }
.kpi .label { font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase; margin-top: 8px; font-weight: 600; letter-spacing: 0.05em; }
.kpi.temp .value { color: var(--sensor-temp); }
.kpi.conv .value { color: var(--sensor-flow); }
.kpi.time .value { color: var(--accent-primary); }

.card { 
    background: var(--bg-card); 
    border-radius: 12px; 
    padding: 20px; 
    border: 1px solid var(--border-subtle); 
    margin-bottom: 16px; 
    box-shadow: var(--shadow-sm);
}
.card h2 { 
    font-size: 0.75rem; 
    color: var(--text-muted); 
    margin: 0 0 16px 0; 
    text-transform: uppercase; 
    letter-spacing: 0.05em; 
    font-weight: 700; 
    border-bottom: 1px solid var(--border-subtle);
    padding-bottom: 12px;
}

.card.highlight { border-color: var(--accent-primary); box-shadow: var(--shadow-glow); }

.estimate-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border-subtle); font-size: 0.9rem; }
.estimate-row:last-child { border-bottom: none; }
.estimate-label { color: var(--text-secondary); }
.estimate-value { font-weight: 600; font-family: var(--font-mono); color: var(--text-primary); }

.node-list { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.node-item { 
    background: var(--bg-app); 
    border: 1px solid var(--border-subtle); 
    border-radius: 8px; 
    padding: 12px; 
    cursor: pointer; 
    transition: all 0.2s; 
}
.node-item:hover { border-color: var(--border-focus); background: var(--bg-panel); transform: translateY(-1px); }
.node-item .name { font-size: 0.8rem; font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; color: var(--text-secondary); }
.node-item .value { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); }
.node-item .tag { font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); margin-top: 4px; opacity: 0.7; }
.node-item.node-enabled { border-color: var(--border-subtle); border-left: 3px solid var(--accent-primary); }
.node-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

.recipe-item { 
    padding: 12px; 
    margin-bottom: 8px; 
    background: var(--bg-app); 
    border-radius: 8px; 
    cursor: pointer; 
    border: 1px solid transparent; 
    transition: all 0.2s; 
}
.recipe-item:hover { border-color: var(--border-subtle); background: var(--bg-panel); transform: translateX(2px); }
.recipe-item.active { background: rgba(59, 130, 246, 0.1); border-color: var(--accent-primary); }
.recipe-name { font-weight: 600; font-size: 0.9rem; display: flex; align-items: center; color: var(--text-primary); }
.recipe-meta { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }
</style>
