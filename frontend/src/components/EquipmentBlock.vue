<script setup>
import { computed } from 'vue'

const props = defineProps({
    tag: { type: String, default: '' },
    name: { type: String, default: '' },
    status: { type: String, default: 'off' },  // 'normal', 'alarm', 'warning', 'maintenance', 'off', 'transition'
    values: { type: Array, default: () => [] }, // [{ label, value, unit }]
    x: { type: Number, default: 0 },
    y: { type: Number, default: 0 },
    width: { type: Number, default: 120 },
    height: { type: Number, default: 80 },
    selected: { type: Boolean, default: false },
})

const emit = defineEmits(['click'])

const statusColor = computed(() => {
    const map = {
        normal: 'var(--dcs-normal)',
        alarm: 'var(--dcs-alarm)',
        warning: 'var(--dcs-warning)',
        maintenance: 'var(--dcs-maintenance)',
        off: 'var(--dcs-off)',
        transition: 'var(--dcs-transition)',
    }
    return map[props.status] || map.off
})

const statusDotFill = computed(() => statusColor.value)

const borderStroke = computed(() => {
    if (props.selected) return 'var(--accent-primary)'
    return statusColor.value
})

const borderWidth = computed(() => props.selected ? 2.5 : 1.5)
</script>

<template>
  <g class="equipment-block" @click="emit('click')" style="cursor: pointer;">
    <!-- Background -->
    <rect
        :x="x" :y="y" :width="width" :height="height"
        rx="4"
        fill="var(--equip-bg)"
        :stroke="borderStroke"
        :stroke-width="borderWidth"
    />

    <!-- Tag label (top-left) -->
    <text :x="x + 6" :y="y + 12"
          fill="var(--text-muted)" font-size="8" font-weight="700"
          letter-spacing="0.05em" style="text-transform: uppercase;">
        {{ tag }}
    </text>

    <!-- Status dot (top-right) -->
    <circle :cx="x + width - 10" :cy="y + 10" r="4"
            :fill="statusDotFill" />

    <!-- Name -->
    <text :x="x + width / 2" :y="y + 26"
          text-anchor="middle"
          fill="var(--text-secondary)" font-size="9" font-weight="600">
        {{ name }}
    </text>

    <!-- Values -->
    <text v-for="(v, i) in values.slice(0, 3)" :key="i"
          :x="x + width / 2" :y="y + 42 + i * 16"
          text-anchor="middle"
          :fill="v.alarm ? 'var(--dcs-alarm)' : 'var(--text-primary)'"
          font-size="13" font-weight="700"
          font-family="'JetBrains Mono', monospace">
        {{ v.value }}
        <tspan fill="var(--text-muted)" font-size="8" font-weight="500">{{ v.unit }}</tspan>
    </text>

    <!-- Selection glow -->
    <rect v-if="selected"
          :x="x - 2" :y="y - 2" :width="width + 4" :height="height + 4"
          rx="6" fill="none"
          stroke="var(--accent-primary)" stroke-width="1" stroke-opacity="0.4"
    />
  </g>
</template>
