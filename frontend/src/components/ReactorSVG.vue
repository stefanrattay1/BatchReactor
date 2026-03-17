<script setup>
import { computed } from 'vue'
import { state, actions } from '../services/store'
import { sensorConfig, isInAlarm, getSparklinePoints } from '../services/sensorConfig'

const s = state

const jacketDisplay = computed(() => (s.jacket_temperature_K - 273.15).toFixed(0) + '°C')
const convDisplay = computed(() => (s.conversion * 100).toFixed(0) + '%')
const massDisplay = computed(() => s.mass_total_kg.toFixed(1) + ' kg')

// Flow Logic
const componentAFlowRate = computed(() => s.feed_rate_component_a ?? 0)
const componentBFlowRate = computed(() => s.feed_rate_component_b ?? 0)
const isComponentAFlowing = computed(() => s.simulation_running && componentAFlowRate.value > 0.001)
const isComponentBFlowing = computed(() => s.simulation_running && componentBFlowRate.value > 0.001)
const isSolventFlowing = computed(() => s.simulation_running && s.feed_rate_solvent > 0.001)

// Liquid Level Logic
const maxLiquidH = 220
const liquidHeight = computed(() => {
    const pct = Math.min(100, Math.max(0, s.fill_pct))
    return Math.max(0, (pct / 100) * maxLiquidH)
})
const liquidY = computed(() => 360 - liquidHeight.value)

// Jacket Color Logic
const jacketFill = computed(() => {
    const temp = s.jacket_temperature_K - 273.15
    const hue = Math.max(0, Math.min(200, 200 - (temp - 20) * 2.5))
    return `hsla(${hue}, 70%, 40%, 0.3)`
})

// Dynamic sensor indicators
const sensorPositions = computed(() => {
    const enabled = sensorConfig.enabledSensorIds
        .map(id => sensorConfig.availableNodes.find(n => n.id === id))
        .filter(n => n && n.state_key)
    if (enabled.length === 0) return []

    const startY = 160
    const endY = 370
    const boxH = 50
    const spacing = enabled.length > 1
        ? Math.min(boxH + 16, (endY - startY) / enabled.length)
        : 0
    const totalH = spacing * (enabled.length - 1) + boxH
    const baseY = startY + (endY - startY - totalH) / 2

    return enabled.map((node, i) => ({
        ...node,
        x: 452,
        y: Math.round(baseY + i * spacing),
    }))
})

function select(id) {
    actions.selectInput(id)
}

function getSensorColor(id) {
    const settings = sensorConfig.sensorSettings[id]
    if (settings && settings.color) return settings.color
    const node = sensorConfig.availableNodes.find(n => n.id === id)
    return node?.default_color || 'var(--text-secondary)'
}

function getSensorAlias(id) {
    const settings = sensorConfig.sensorSettings[id]
    if (settings && settings.alias) return settings.alias
    const node = sensorConfig.availableNodes.find(n => n.id === id)
    return node?.name || id
}

function getSensorValue(id) {
    const node = sensorConfig.availableNodes.find(n => n.id === id)
    if (!node || !node.state_key) return '--'
    const val = s[node.state_key]
    if (val === undefined || val === null) return '--'
    if (typeof val === 'number') {
        if (node.unit === 'bar') return val.toFixed(2)
        if (node.unit === 'K') return (val - 273.15).toFixed(0) + '°C'
        if (node.unit === '' && node.id === 'conversion') return (val * 100).toFixed(0) + '%'
        if (node.unit === 'Pa·s') return val >= (s.viscosity_max ?? 1e6) ? 'GEL' : val.toFixed(0)
        if (node.unit === 'kg') return val.toFixed(1)
        if (node.unit === 's') return val.toFixed(0)
        return val.toFixed(2)
    }
    return String(val)
}

function getSensorUnit(id) {
    const node = sensorConfig.availableNodes.find(n => n.id === id)
    if (!node) return ''
    if (node.unit === 'K') return '' // already shown as °C
    if (node.id === 'conversion') return '' // shown as %
    return node.unit
}

function sparkline(id, x, y, w, h) {
    return getSparklinePoints(id, x, y, w, h)
}

function sensorInAlarm(id) {
    return !!isInAlarm(id)
}

// Truncate label to fit in box
function shortLabel(name) {
    return name.length > 8 ? name.substring(0, 7) + '.' : name
}
</script>

<template>
  <div class="reactor-panel">
    <div class="panel-title">Process Flow Diagram</div>
    <div class="reactor-svg-container">
    <svg class="reactor-svg" viewBox="0 0 550 520" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--border-subtle)" stroke-width="0.5"/>
          </pattern>
        </defs>
        <rect width="550" height="520" fill="url(#grid)"/>

        <!-- COMPONENT A -->
        <g class="input-point" :class="{ active: s.selectedInput === 'component_a' }" @click="select('component_a')">
            <path class="pipe" :class="{ flowing: isComponentAFlowing }" d="M 100 40 L 100 125 L 150 125 L 150 155" stroke="#3b82f6" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            <circle cx="100" cy="40" r="14" fill="var(--bg-panel)" stroke="#3b82f6" stroke-width="3"/>
            <text x="100" y="44" text-anchor="middle" fill="#3b82f6" font-size="11" font-weight="bold">A</text>
            <text x="100" y="20" text-anchor="middle" fill="var(--text-muted)" font-size="9">COMPONENT A</text>
            <circle :opacity="isComponentAFlowing ? 1 : 0" cx="150" cy="140" r="5" fill="var(--accent-success)"/>
        </g>

        <!-- COMPONENT B -->
        <g class="input-point" :class="{ active: s.selectedInput === 'component_b' }" @click="select('component_b')">
            <path class="pipe" :class="{ flowing: isComponentBFlowing }" d="M 180 40 L 180 110 L 220 110 L 220 155" stroke="#f59e0b" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            <circle cx="180" cy="40" r="14" fill="var(--bg-panel)" stroke="#f59e0b" stroke-width="3"/>
            <text x="180" y="44" text-anchor="middle" fill="#f59e0b" font-size="11" font-weight="bold">B</text>
            <text x="180" y="20" text-anchor="middle" fill="var(--text-muted)" font-size="9">COMPONENT B</text>
            <circle :opacity="isComponentBFlowing ? 1 : 0" cx="220" cy="140" r="5" fill="var(--accent-success)"/>
        </g>

        <!-- SOLVENT -->
        <g class="input-point" :class="{ active: s.selectedInput === 'solvent' }" @click="select('solvent')">
            <path class="pipe" :class="{ flowing: isSolventFlowing }" d="M 260 40 L 260 100 L 290 100 L 290 155" stroke="#06b6d4" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            <circle cx="260" cy="40" r="14" fill="var(--bg-panel)" stroke="#06b6d4" stroke-width="3"/>
            <text x="260" y="44" text-anchor="middle" fill="#06b6d4" font-size="11" font-weight="bold">S</text>
            <text x="260" y="20" text-anchor="middle" fill="var(--text-muted)" font-size="9">SOLVENT</text>
            <circle :opacity="isSolventFlowing ? 1 : 0" cx="290" cy="140" r="5" fill="var(--accent-success)"/>
        </g>

        <g transform="translate(0,30)">
            <!-- VESSEL -->
            <path d="M 70 110 L 70 340 Q 70 390 180 390 L 320 390 Q 430 390 430 340 L 430 110 Q 430 95 250 95 Q 70 95 70 110 Z" fill="var(--border-subtle)" stroke="var(--text-muted)" stroke-width="2"/>
            <!-- JACKET AREA -->
            <path :fill="jacketFill" d="M 75 115 L 75 335 Q 75 380 180 385 L 320 385 Q 425 380 425 335 L 425 115 Z" stroke="none"/>
            <!-- INNER WALL -->
            <path d="M 110 120 L 110 310 Q 110 350 180 360 L 320 360 Q 390 350 390 310 L 390 120 Q 390 105 250 105 Q 110 105 110 120 Z" fill="var(--bg-app)" stroke="var(--border-subtle)" stroke-width="2"/>

            <!-- LIQUID LEVEL -->
            <clipPath id="vesselClip">
                <path d="M 115 125 L 115 305 Q 115 345 180 355 L 320 355 Q 385 345 385 305 L 385 125 Z"/>
            </clipPath>
            <rect :y="liquidY" :height="liquidHeight" x="115" width="270" fill="var(--accent-primary)" fill-opacity="0.8" clip-path="url(#vesselClip)"/>

            <!-- AGITATOR -->
            <line x1="250" y1="70" x2="250" y2="280" stroke="var(--text-muted)" stroke-width="5"/>
            <line x1="190" y1="240" x2="310" y2="250" stroke="var(--text-muted)" stroke-width="7" stroke-linecap="round"/>
            <rect x="230" y="55" width="40" height="20" rx="3" fill="var(--border-subtle)" stroke="var(--text-muted)" stroke-width="1"/>
            <text x="250" y="68" text-anchor="middle" fill="var(--text-secondary)" font-size="8">M</text>
        </g>

        <!-- DYNAMIC SENSOR INDICATORS -->
        <g v-for="sp in sensorPositions" :key="sp.id"
           class="input-point" :class="{ active: s.selectedInput === sp.id }"
           @click="select(sp.id)">
            <!-- Connection line from vessel wall -->
            <line x1="430" :y1="sp.y + 20" :x2="sp.x" :y2="sp.y + 20"
                  :stroke="getSensorColor(sp.id)" stroke-width="2" stroke-dasharray="4 2"/>
            <!-- Indicator box -->
            <rect :x="sp.x" :y="sp.y" width="90" height="50" rx="6"
                  fill="var(--bg-panel)"
                  :stroke="sensorInAlarm(sp.id) ? 'var(--accent-danger)' : getSensorColor(sp.id)"
                  stroke-width="2"
                  :class="{ 'alarm-pulse': sensorInAlarm(sp.id) }"/>
            <!-- Small icon circle -->
            <circle :cx="sp.x + 12" :cy="sp.y + 12" r="7"
                    :fill="getSensorColor(sp.id)" fill-opacity="0.2"
                    :stroke="getSensorColor(sp.id)" stroke-width="1"/>
            <text :x="sp.x + 12" :y="sp.y + 15" text-anchor="middle"
                  :fill="getSensorColor(sp.id)" font-size="8" font-weight="bold">
                {{ (sensorConfig.sensorSettings[sp.id]?.icon || sp.default_icon) }}
            </text>
            <!-- Label -->
            <text :x="sp.x + 24" :y="sp.y + 15" fill="#64748b" font-size="8">
                {{ shortLabel(getSensorAlias(sp.id)) }}
            </text>
            <!-- Value -->
            <text :x="sp.x + 45" :y="sp.y + 32"
                  text-anchor="middle"
                  :fill="sensorInAlarm(sp.id) ? '#ef4444' : getSensorColor(sp.id)"
                  font-size="13" font-weight="bold">
                {{ getSensorValue(sp.id) }}
            </text>
            <!-- Unit -->
            <text :x="sp.x + 80" :y="sp.y + 32" text-anchor="end"
                  fill="#475569" font-size="7">
                {{ getSensorUnit(sp.id) }}
            </text>
            <!-- Sparkline -->
            <polyline v-if="sparkline(sp.id, sp.x + 4, sp.y + 38, 82, 8)"
                      :points="sparkline(sp.id, sp.x + 4, sp.y + 38, 82, 8)"
                      :stroke="getSensorColor(sp.id)"
                      stroke-opacity="0.6"
                      stroke-width="1"
                      fill="none"/>
            <!-- Alarm indicator triangle -->
            <g v-if="sensorInAlarm(sp.id)">
                <polygon :points="`${sp.x + 82},${sp.y + 4} ${sp.x + 86},${sp.y + 11} ${sp.x + 78},${sp.y + 11}`"
                         fill="#ef4444"/>
                <text :x="sp.x + 82" :y="sp.y + 10" text-anchor="middle"
                      fill="#fff" font-size="6" font-weight="bold">!</text>
            </g>
        </g>

        <!-- JACKET ACTUATOR -->
        <g class="input-point" :class="{ active: s.selectedInput === 'jacket' }" @click="select('jacket')">
            <rect x="5" y="200" width="55" height="55" rx="6" fill="var(--bg-panel)" stroke="var(--accent-warning)" stroke-width="2"/>
            <text x="32" y="218" text-anchor="middle" fill="var(--text-secondary)" font-size="8">JACKET</text>
            <text x="32" y="235" text-anchor="middle" fill="var(--accent-warning)" font-size="14" font-weight="bold">{{ jacketDisplay }}</text>
            <text x="32" y="248" text-anchor="middle" fill="var(--text-muted)" font-size="7">SETPOINT</text>
        </g>

        <!-- PRODUCT OUTLET -->
        <g class="input-point" :class="{ active: s.selectedInput === 'product' }" @click="select('product')">
            <path d="M 250 390 L 250 450" stroke="var(--accent-success)" stroke-width="10" stroke-linecap="round"/>
            <rect x="200" y="455" width="100" height="40" rx="6" fill="var(--bg-panel)" stroke="var(--accent-success)" stroke-width="2"/>
            <text x="250" y="475" text-anchor="middle" fill="var(--accent-success)" font-size="11" font-weight="bold">PRODUCT</text>
            <text x="250" y="490" text-anchor="middle" fill="var(--text-secondary)" font-size="10">{{ massDisplay }}</text>
        </g>

        <!-- CENTER CONVERSION -->
        <g>
            <circle cx="250" cy="290" r="32" fill="var(--bg-app)" stroke="var(--accent-success)" stroke-width="2" opacity="0.95"/>
            <text x="250" y="286" text-anchor="middle" fill="var(--accent-success)" font-size="16" font-weight="bold">{{ convDisplay }}</text>
            <text x="250" y="302" text-anchor="middle" fill="var(--text-muted)" font-size="8">CONVERSION</text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.reactor-panel {
    background: var(--bg-app);
    padding: 20px;
    border-right: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    flex: 0 0 auto;
    font-family: var(--font-sans);
}
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

.reactor-svg-container { flex: 0 1 auto; display: flex; justify-content: center; align-items: flex-start; width: 100%; max-width: 550px; margin: 0 auto; }
.reactor-svg { width: 100%; height: auto; }

.input-point { cursor: pointer; transition: all 0.15s; }
.input-point:hover { filter: brightness(1.2); }
.input-point.active { filter: drop-shadow(0 0 6px var(--accent-primary)); }

@keyframes flow { 0% { stroke-dashoffset: 20; } 100% { stroke-dashoffset: 0; } }
.pipe.flowing { stroke-dasharray: 10 5; animation: flow 0.5s linear infinite; }

@keyframes alarmPulse { 0% { stroke-opacity: 1; } 50% { stroke-opacity: 0.3; } 100% { stroke-opacity: 1; } }
.alarm-pulse { animation: alarmPulse 0.6s ease-in-out infinite; }
</style>
