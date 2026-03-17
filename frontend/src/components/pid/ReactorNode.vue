<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { state } from '../../services/store'

const tempC = computed(() => (state.temperature_K - 273.15).toFixed(1))
const pressureBar = computed(() => state.pressure_bar.toFixed(2))
const convPct = computed(() => (state.conversion * 100).toFixed(0))
const fillPct = computed(() => Math.min(100, Math.max(0, state.fill_pct)))

const statusColor = computed(() => {
    if (state.phase === 'RUNAWAY_ALARM') return '#ef4444'
    if (!state.simulation_running) return '#52525b'
    if (['CHARGING', 'HEATING', 'COOLING'].some(p => state.phase?.includes(p))) return '#9ca3af'
    return '#6b7280'
})

const jacketFill = computed(() => {
    const temp = state.jacket_temperature_K - 273.15
    const hue = Math.max(180, Math.min(240, 240 - (temp - 20) * 1.5))
    return `hsla(${hue}, 50%, 35%, 0.2)`
})
</script>

<template>
  <div class="reactor-node">
    <!-- Handles for connections -->
    <Handle id="feed-top" type="target" :position="Position.Top" style="left: 30%;" />
    <Handle id="feed-center" type="target" :position="Position.Top" style="left: 50%;" />
    <Handle id="feed-right" type="target" :position="Position.Top" style="left: 70%;" />
    <Handle id="jacket" type="target" :position="Position.Left" style="top: 50%;" />
    <Handle id="agitator" type="target" :position="Position.Right" style="top: 50%;" />
    <Handle id="product" type="source" :position="Position.Bottom" style="left: 50%;" />

    <!-- Outer vessel -->
    <svg width="260" height="220" viewBox="0 0 260 220">
      <!-- Jacket area (outer shell) -->
      <rect x="1" y="1" width="258" height="218" rx="2"
            :fill="jacketFill" :stroke="statusColor" stroke-width="2"/>

      <!-- Inner wall -->
      <rect x="16" y="14" width="228" height="192" rx="1"
            fill="#161616" stroke="#3a3a3a" stroke-width="1"/>

      <!-- Liquid level fill -->
      <clipPath id="rlClip"><rect x="17" y="15" width="226" height="190" rx="1"/></clipPath>
      <rect :y="15 + 190 - (fillPct * 190 / 100)" :height="fillPct * 190 / 100"
            x="17" width="226"
            fill="#00b4b4" fill-opacity="0.18"
            clip-path="url(#rlClip)"/>

      <!-- Tag label -->
      <text x="8" y="11" fill="#6b7280" font-size="7" font-weight="700" letter-spacing="0.05em">R-101</text>

      <!-- Status dot -->
      <rect x="243" y="4" width="8" height="8" rx="1" :fill="statusColor"/>

      <!-- Temperature (primary) -->
      <text x="130" y="72" text-anchor="middle" fill="#e8e8e8"
            font-size="24" font-weight="700" font-family="'JetBrains Mono', monospace">
        {{ tempC }}°C
      </text>

      <!-- Temp label -->
      <text x="130" y="84" text-anchor="middle" fill="#606060"
            font-size="7" font-weight="600" letter-spacing="0.08em">TEMPERATURE</text>

      <!-- Pressure -->
      <text x="130" y="104" text-anchor="middle" fill="#a855f7"
            font-size="11" font-weight="600" font-family="'JetBrains Mono', monospace">
        {{ pressureBar }} bar
      </text>

      <!-- Conversion (compact) -->
      <text x="130" y="122" text-anchor="middle" fill="#606060"
            font-size="6" font-weight="700" letter-spacing="0.1em">CONVERSION</text>
      <text x="130" y="138" text-anchor="middle" fill="var(--dcs-normal)"
            font-size="15" font-weight="700" font-family="'JetBrains Mono', monospace">
        {{ convPct }}%
      </text>

      <!-- Fill level bar (right side) -->
      <rect x="236" y="22" width="6" height="174" rx="1"
            fill="#1a1a1a" stroke="#3a3a3a" stroke-width="0.5"/>
      <rect x="236" :y="22 + 174 - (fillPct * 174 / 100)" width="6"
            :height="fillPct * 174 / 100" rx="1"
            fill="#00b4b4" fill-opacity="0.7"/>
      <text x="239" y="206" text-anchor="middle" fill="#606060" font-size="6">
        {{ fillPct.toFixed(0) }}%
      </text>

      <!-- Agitator shaft -->
      <line x1="130" y1="148" x2="130" y2="183" stroke="#4a4a4a" stroke-width="2"/>
      <!-- Agitator blades -->
      <line x1="108" y1="173" x2="152" y2="178" stroke="#5a5a5a" stroke-width="3" stroke-linecap="square"/>
    </svg>

    <div class="node-label">REACTOR VESSEL</div>
  </div>
</template>

<style scoped>
.reactor-node {
    cursor: grab;
}
.reactor-node:active { cursor: grabbing; }

.node-label {
    text-align: center;
    font-size: 0.55rem;
    font-weight: 700;
    color: var(--text-muted);
    margin-top: 3px;
    letter-spacing: 0.12em;
}
</style>
