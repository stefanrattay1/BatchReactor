<script setup>
import { computed } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from '@vue-flow/core'
import { state } from '../../services/store'

const props = defineProps({
    id: String,
    sourceX: Number,
    sourceY: Number,
    targetX: Number,
    targetY: Number,
    sourcePosition: String,
    targetPosition: String,
    data: { type: Object, default: () => ({}) },
    markerEnd: String,
})

// Destructure path + label midpoint from getSmoothStepPath
const pathData = computed(() => getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
    borderRadius: 8,
}))

const path = computed(() => pathData.value[0])
const labelX = computed(() => pathData.value[1])
const labelY = computed(() => pathData.value[2])

// Pipe state
const isAlarm = computed(() => state.phase === 'RUNAWAY_ALARM')

const isFlowing = computed(() => {
    if (!state.simulation_running) return false
    if (props.data?.flowKey) return state[props.data.flowKey] > 0.001
    // Product valve: open during discharge
    if (props.data?.valveTag === 'PV-201') return state.phase === 'DISCHARGING'
    // Jacket valve: active whenever simulation runs
    if (props.data?.valveTag === 'TV-101') return true
    return false
})

const isManual = computed(() =>
    props.data?.actuatorKey ? !!state.actuator_overrides?.[props.data.actuatorKey] : false
)

const pipeColor = computed(() => {
    if (isAlarm.value) return '#ef4444'
    if (isFlowing.value) return '#9ca3af'
    return '#3f3f46'
})

// Valve symbol color: alarm > manual > open > closed (ISA-101: gray normal, color only on deviation)
const valveColor = computed(() => {
    if (isAlarm.value) return '#ef4444'
    if (isManual.value) return '#f97316'
    if (isFlowing.value) return '#9ca3af'
    return '#52525b'
})

const hasValve = computed(() => !!props.data?.valveTag)

// Arrow marker: match pipe color, suppress on mechanical connections
const markerEndId = computed(() => {
    if (props.data?.noArrow) return ''
    if (isAlarm.value) return 'url(#arrow-alarm)'
    if (isFlowing.value) return 'url(#arrow-flowing)'
    return 'url(#arrow-idle)'
})
</script>

<template>
  <BaseEdge :id="id" :path="path" :marker-end="markerEndId"
            :style="{
                stroke: pipeColor,
          strokeWidth: '2.2px',
                strokeLinecap: 'butt',
          strokeDasharray: isFlowing ? '7 9' : 'none',
          animation: isFlowing ? 'pipeFlow 1.2s linear infinite' : 'none',
            }" />

  <!-- Valve symbol — only on edges that have a valveTag -->
  <EdgeLabelRenderer v-if="hasValve">
    <div
      :style="{
        position: 'absolute',
        transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
        pointerEvents: 'none',
      }"
    >
      <!--
        P&ID control valve symbol:
        - Bowtie body (two triangles, tips touching at center)
        - Vertical actuator stem
        - Circle actuator head (pneumatic)
        - Background rect clears the pipe line for readability
      -->
      <svg width="22" height="30" viewBox="-11 -18 22 30" overflow="visible">
        <!-- Dark background clears the pipe at valve position -->
        <rect x="-9" y="-7" width="18" height="14" rx="1"
              fill="#1c1c1c" stroke="#3a3a3a" stroke-width="0.5"/>

        <!-- Valve body: left triangle (pointing right) -->
        <polygon points="-8,0 0,-6 0,6" :fill="valveColor"/>
        <!-- Valve body: right triangle (pointing left) -->
        <polygon points="8,0 0,-6 0,6" :fill="valveColor"/>

        <!-- Actuator stem -->
        <line x1="0" y1="-6" x2="0" y2="-11"
              :stroke="valveColor" stroke-width="1.5"/>
        <!-- Pneumatic actuator circle -->
        <circle cx="0" cy="-14" r="3.5"
                fill="#1c1c1c" :stroke="valveColor" stroke-width="1.5"/>

        <!-- Open indicator dot inside actuator -->
        <circle v-if="isFlowing && !isAlarm" cx="0" cy="-14" r="1.5"
                :fill="valveColor"/>
      </svg>
      <!-- Tag label below the symbol -->
      <div :style="{
        textAlign: 'center',
        fontSize: '0.42rem',
        fontWeight: '700',
        color: valveColor,
        letterSpacing: '0.06em',
        fontFamily: '\'JetBrains Mono\', monospace',
        marginTop: '1px',
        whiteSpace: 'nowrap',
      }">{{ data.valveTag }}</div>
    </div>
  </EdgeLabelRenderer>
</template>

<style>
@keyframes pipeFlow {
  0% { stroke-dashoffset: 16; }
    100% { stroke-dashoffset: 0; }
}
</style>
