<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { state } from '../../services/store'

const props = defineProps({
      data: { type: Object, default: () => ({}) },
})

const tempC = computed(() => (state.temperature_K - 273.15).toFixed(1))
const pressureBar = computed(() => state.pressure_bar.toFixed(2))
const convPct = computed(() => (state.conversion * 100).toFixed(0))
const fillPct = computed(() => Math.min(100, Math.max(0, state.fill_pct)))

const statusColor = computed(() => {
      if (state.phase === 'RUNAWAY_ALARM') return '#db6a64'
      if (!state.simulation_running) return '#56626b'
      if (state.simulation_running) return '#d6dee4'
      return '#9ca7b0'
})

const jacketFill = computed(() => {
    const temp = state.jacket_temperature_K - 273.15
      const opacity = Math.max(0.08, Math.min(0.2, 0.08 + ((temp - 20) / 140) * 0.12))
      return `rgba(168, 180, 190, ${opacity.toFixed(3)})`
})

const portOccupancy = computed(() => props.data?.portOccupancy || {})

function isPortOccupied(handleId) {
      return (portOccupancy.value[handleId] || []).length > 0
}

function getPortChipText(handleId) {
      const occupants = portOccupancy.value[handleId] || []
      if (!occupants.length) return ''
      if (occupants.length === 1) return occupants[0]
      return `${occupants[0]} +${occupants.length - 1}`
}

function getPortChipTitle(handleId) {
      const occupants = portOccupancy.value[handleId] || []
      return occupants.join(', ')
}
</script>

<template>
  <div class="reactor-node">
    <!-- Handles for connections -->
                                                      <Handle id="feed" type="target" :position="Position.Top" :class="['port-handle', 'feed-port', { 'port-handle-occupied': isPortOccupied('feed') }]" title="Shared Input Port" style="left: 50%;" />
                  <Handle id="jacket" type="target" :position="Position.Left" :class="['port-handle', { 'port-handle-occupied': isPortOccupied('jacket') }]" title="Jacket Port" style="top: 50%;" />
                  <Handle id="sensor" type="target" :position="Position.Right" :class="['port-handle', 'sensor-port', { 'port-handle-occupied': isPortOccupied('sensor') }]" title="Sensor Port" style="top: 26%;" />
                  <Handle id="agitator" type="target" :position="Position.Right" :class="['port-handle', { 'port-handle-occupied': isPortOccupied('agitator') }]" title="Agitator Port" style="top: 50%;" />
                  <Handle id="product" type="source" :position="Position.Bottom" :class="['port-handle', { 'port-handle-occupied': isPortOccupied('product') }]" title="Product Outlet" style="left: 50%;" />

                                    <div class="port-label port-label-top" style="left: 50%;">INPUT</div>
            <div class="port-label port-label-left">JKT</div>
            <div class="port-label port-label-right sensor-label">SENS</div>
            <div class="port-label port-label-right agitator-label">AGIT</div>
            <div class="port-label port-label-bottom">PRODUCT</div>

                                    <div v-if="isPortOccupied('feed')" class="port-chip port-chip-top port-chip-input" style="left: 50%;" :title="getPortChipTitle('feed')">{{ getPortChipText('feed') }}</div>
            <div v-if="isPortOccupied('jacket')" class="port-chip port-chip-left" :title="getPortChipTitle('jacket')">{{ getPortChipText('jacket') }}</div>
            <div v-if="isPortOccupied('sensor')" class="port-chip port-chip-right port-chip-sensor" :title="getPortChipTitle('sensor')">{{ getPortChipText('sensor') }}</div>
            <div v-if="isPortOccupied('agitator')" class="port-chip port-chip-right port-chip-agitator" :title="getPortChipTitle('agitator')">{{ getPortChipText('agitator') }}</div>
            <div v-if="isPortOccupied('product')" class="port-chip port-chip-bottom" :title="getPortChipTitle('product')">{{ getPortChipText('product') }}</div>

    <!-- Outer vessel -->
    <svg width="210" height="178" viewBox="0 0 260 220">
      <!-- Jacket area (outer shell) -->
      <rect x="1" y="1" width="258" height="218" rx="2"
            :fill="jacketFill" :stroke="statusColor" stroke-width="2"/>

      <!-- Inner wall -->
      <rect x="16" y="14" width="228" height="192" rx="1"
            fill="#141a20" stroke="#4a5761" stroke-width="1"/>

      <!-- Liquid level fill -->
      <clipPath id="rlClip"><rect x="17" y="15" width="226" height="190" rx="1"/></clipPath>
      <rect :y="15 + 190 - (fillPct * 190 / 100)" :height="fillPct * 190 / 100"
            x="17" width="226"
            fill="#d3dce2" fill-opacity="0.15"
            clip-path="url(#rlClip)"/>

      <!-- Tag label -->
      <text x="8" y="11" fill="#a6b1b8" font-size="7" font-weight="700" letter-spacing="0.05em">R-101</text>

      <!-- Status dot -->
      <rect x="243" y="4" width="8" height="8" rx="1" :fill="statusColor"/>

      <!-- Temperature (primary) -->
      <text x="130" y="72" text-anchor="middle" fill="#f2f5f7"
            font-size="24" font-weight="700" font-family="'JetBrains Mono', monospace">
        {{ tempC }}°C
      </text>

      <!-- Temp label -->
      <text x="130" y="84" text-anchor="middle" fill="#8f9ca6"
            font-size="7" font-weight="600" letter-spacing="0.08em">TEMPERATURE</text>

      <!-- Pressure -->
      <text x="130" y="104" text-anchor="middle" fill="#d2dbe1"
            font-size="11" font-weight="600" font-family="'JetBrains Mono', monospace">
        {{ pressureBar }} bar
      </text>

      <!-- Conversion (compact) -->
      <text x="130" y="122" text-anchor="middle" fill="#8f9ca6"
            font-size="6" font-weight="700" letter-spacing="0.1em">CONVERSION</text>
      <text x="130" y="138" text-anchor="middle" fill="#e7edf1"
            font-size="15" font-weight="700" font-family="'JetBrains Mono', monospace">
        {{ convPct }}%
      </text>

      <!-- Fill level bar (right side) -->
      <rect x="236" y="22" width="6" height="174" rx="1"
            fill="#10151a" stroke="#47545f" stroke-width="0.5"/>
      <rect x="236" :y="22 + 174 - (fillPct * 174 / 100)" width="6"
            :height="fillPct * 174 / 100" rx="1"
            fill="#d3dce2" fill-opacity="0.78"/>
      <text x="239" y="206" text-anchor="middle" fill="#8f9ca6" font-size="6">
        {{ fillPct.toFixed(0) }}%
      </text>

      <!-- Agitator shaft -->
      <line x1="130" y1="148" x2="130" y2="183" stroke="#66747f" stroke-width="2"/>
      <!-- Agitator blades -->
      <line x1="108" y1="173" x2="152" y2="178" stroke="#81909a" stroke-width="3" stroke-linecap="square"/>
    </svg>

    <div class="node-label">REACTOR VESSEL</div>
  </div>
</template>

<style scoped>
.reactor-node {
    cursor: grab;
      position: relative;
}
.reactor-node:active { cursor: grabbing; }

.port-handle {
      box-shadow: 0 0 0 2px rgba(9, 13, 17, 0.94);
}

.port-handle-occupied {
      background: #f2f5f7;
      box-shadow: 0 0 0 2px rgba(9, 13, 17, 0.95), 0 0 10px rgba(242, 245, 247, 0.28);
}

.feed-port {
      background: #c89b4d;
}

.sensor-port {
      background: #72b47d;
}

.port-label {
      position: absolute;
      font-size: 0.44rem;
      font-weight: 700;
      letter-spacing: 0.1em;
      color: var(--text-secondary);
      transform: translateX(-50%);
      pointer-events: none;
}

.port-label-top {
      top: -16px;
}

.port-label-left {
      left: -26px;
      top: 50%;
      transform: translateY(-50%);
}

.port-label-right {
      right: -42px;
      transform: none;
}

.sensor-label {
      top: 20%;
      color: #c7d6c5;
}

.agitator-label {
      top: 44%;
}

.port-label-bottom {
      bottom: 24px;
      left: 50%;
}

.port-chip {
      position: absolute;
      max-width: 74px;
      padding: 2px 6px;
      border-radius: 999px;
      background: rgba(28, 35, 40, 0.96);
      border: 1px solid rgba(160, 173, 183, 0.34);
      color: #edf2f5;
      font-size: 0.4rem;
      font-weight: 700;
      letter-spacing: 0.05em;
      line-height: 1.4;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      pointer-events: none;
}

.port-chip-top {
      top: -30px;
      transform: translateX(-50%);
}

.port-chip-input {
      max-width: 94px;
}

.port-chip-left {
      left: -78px;
      top: 56%;
      transform: translateY(-50%);
}

.port-chip-right {
      right: -76px;
      transform: none;
}

.port-chip-sensor {
      top: 14%;
      color: #d3e0d1;
      border-color: rgba(114, 180, 125, 0.38);
}

.port-chip-agitator {
      top: 38%;
}

.port-chip-bottom {
      bottom: 8px;
      left: 50%;
      transform: translateX(-50%);
}

.node-label {
    text-align: center;
      font-size: 0.58rem;
    font-weight: 700;
      color: var(--text-secondary);
      margin-top: 6px;
      letter-spacing: 0.14em;
}
</style>
