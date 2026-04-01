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
  borderRadius: 12,
  offset: 22,
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

const isSignal = computed(() => !!props.data?.signal)
const isEmphasized = computed(() => !!props.data?.emphasized)
const edgeLength = computed(() => Math.hypot(props.targetX - props.sourceX, props.targetY - props.sourceY))

const strokeWidth = computed(() => {
  if (isSignal.value) return 2.4
  if (isFlowing.value) return 3
  return 3.1
})

const casingWidth = computed(() => strokeWidth.value + (isEmphasized.value ? 3 : 2))

const casingColor = computed(() => {
  if (isSignal.value) return 'rgba(17, 22, 27, 0.96)'
  return 'rgba(9, 13, 17, 0.92)'
})

const pipeColor = computed(() => {
    if (isAlarm.value) return '#db6a64'
    if (isSignal.value) return '#c2d4c1'
    if (isFlowing.value) return '#f2f5f7'
    return '#d3dce2'
})

// Valve symbol color: alarm > manual > open > closed (ISA-101: gray normal, color only on deviation)
const valveColor = computed(() => {
  if (isAlarm.value) return '#db6a64'
  if (isManual.value) return '#d28548'
  if (isFlowing.value) return '#eef2f5'
  return '#8d99a3'
})

const hasValve = computed(() => !!props.data?.valveTag)

// Arrow marker: match pipe color, suppress on mechanical connections
const markerEndId = computed(() => {
    if (props.data?.noArrow || isSignal.value || edgeLength.value < 72) return ''
    if (isAlarm.value) return 'url(#arrow-alarm)'
    if (isFlowing.value) return 'url(#arrow-flowing)'
    return ''
})
</script>

<template>
  <BaseEdge :id="`${id}-casing`" :path="path"
      :style="{
        stroke: casingColor,
        strokeWidth: `${casingWidth}px`,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        opacity: isEmphasized ? 0.96 : 0.84,
        vectorEffect: 'non-scaling-stroke',
      }" />

  <BaseEdge :id="id" :path="path" :marker-end="markerEndId"
            :style="{
                stroke: pipeColor,
                strokeWidth: `${strokeWidth}px`,
                strokeLinecap: 'round',
                strokeLinejoin: 'round',
                strokeDasharray: isSignal ? '4 6' : 'none',
                animation: 'none',
                opacity: isFlowing ? 1 : 0.95,
                vectorEffect: 'non-scaling-stroke',
                filter: isEmphasized
                    ? 'drop-shadow(0 0 7px rgba(248, 250, 252, 0.28))'
                    : (isFlowing ? 'drop-shadow(0 0 5px rgba(242, 245, 247, 0.12))' : 'none'),
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
          <rect x="-9" y="-7" width="18" height="14" rx="2"
            fill="#11161b" stroke="#46515a" stroke-width="0.6"/>

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
        fontFamily: 'IBM Plex Mono, JetBrains Mono, monospace',
        marginTop: '1px',
        whiteSpace: 'nowrap',
      }">{{ data.valveTag }}</div>
    </div>
  </EdgeLabelRenderer>
</template>
