<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { state } from '../services/store'

const recipe = ref(null)

async function loadRecipe() {
    try {
        const res = await fetch('/api/recipe/current')
        if (res.ok) recipe.value = await res.json()
    } catch (e) { /* ignore */ }
}

onMounted(loadRecipe)

// Reload when simulation starts and when run ends (recipe may have been switched while idle)
watch(() => state.phase, (newPhase, oldPhase) => {
    if (oldPhase === 'IDLE' && newPhase !== 'IDLE') loadRecipe()
    if (newPhase === 'IDLE' && oldPhase !== 'IDLE') loadRecipe()
})

const steps = computed(() => {
    if (!recipe.value?.unit_procedures) {
        return (recipe.value?.steps || []).map((step, idx) => ({ ...step, index: idx }))
    }
    return recipe.value.unit_procedures.flatMap(up =>
        up.operations.flatMap(op => op.phases)
    )
})
const recipeName = computed(() => recipe.value?.name || 'No Recipe')
const currentIdx = computed(() => {
    if (typeof state.recipe_step_idx === 'number' && state.recipe_step_idx >= 0) {
        return state.recipe_step_idx
    }
    if (typeof recipe.value?.current_phase_idx === 'number') {
        return recipe.value.current_phase_idx
    }
    return -1
})
const elapsed = computed(() => state.recipe_elapsed_s || 0)
const totalDuration = computed(() => steps.value.reduce((sum, step) => sum + (Number(step.duration) || 0), 0))
const remaining = computed(() => Math.max(0, totalDuration.value - elapsed.value))

function formatDuration(seconds) {
    if (!seconds) return '--'
    if (seconds < 60) return `${seconds}s`
    return `${Math.floor(seconds / 60)}m`
}

const runtimeStatus = computed(() => {
    if (!state.simulation_running) return 'Ready'
    return `T+ ${formatDuration(elapsed.value)} · Left ${formatDuration(remaining.value)}`
})

function stepStatus(idx) {
    if (idx < currentIdx.value) return 'done'
    if (idx === currentIdx.value) return 'active'
    return 'pending'
}

watch(() => state.recipe_step_idx, (newIdx) => {
    if (!steps.value.length) return
    if (typeof newIdx !== 'number') return
    if (newIdx >= steps.value.length && !state.simulation_running) {
        loadRecipe()
    }
})
</script>

<template>
  <div class="recipe-progress">
    <div class="section-title">Recipe</div>
    <div class="recipe-name">{{ recipeName }}</div>
        <div class="runtime-status">{{ runtimeStatus }}</div>

    <div class="step-list">
      <div v-for="(step, idx) in steps" :key="idx"
           class="step-row" :class="stepStatus(idx)">
        <div class="step-dot-col">
          <div class="step-dot" :class="stepStatus(idx)">
            <span v-if="stepStatus(idx) === 'done'" class="check">&#10003;</span>
            <span v-else>{{ idx + 1 }}</span>
          </div>
          <div v-if="idx < steps.length - 1" class="step-line" :class="{ filled: idx < currentIdx }"></div>
        </div>
        <div class="step-info">
          <div class="step-name">{{ step.action || step.name || 'Step ' + (idx + 1) }}</div>
          <div class="step-duration">{{ formatDuration(step.duration) }}</div>
        </div>
      </div>
    </div>

    <div v-if="steps.length === 0" class="empty-state">No recipe loaded</div>
  </div>
</template>

<style scoped>
.recipe-progress {
    padding: 12px;
}

.section-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 4px;
}

.recipe-name {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 6px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-subtle);
}

.runtime-status {
    font-size: 0.58rem;
    color: var(--text-muted);
    font-family: var(--font-mono);
    margin-bottom: 10px;
}

.step-list {
    display: flex;
    flex-direction: column;
}

.step-row {
    display: flex;
    gap: 8px;
    min-height: 32px;
}

.step-dot-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 20px;
    flex-shrink: 0;
}

.step-dot {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    font-weight: 700;
    flex-shrink: 0;
    border: 2px solid var(--equip-border);
    background: var(--equip-bg);
    color: var(--text-muted);
}

.step-dot.done {
    background: var(--dcs-normal);
    border-color: var(--dcs-normal);
    color: white;
}

.step-dot.active {
    background: var(--dcs-transition);
    border-color: var(--dcs-transition);
    color: white;
    box-shadow: 0 0 8px rgba(59, 130, 246, 0.4);
}

.check { font-size: 0.55rem; }

.step-line {
    width: 2px;
    flex: 1;
    min-height: 8px;
    background: var(--equip-border);
}
.step-line.filled {
    background: var(--dcs-normal);
}

.step-info {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex: 1;
    min-width: 0;
    padding: 2px 0;
}

.step-name {
    font-size: 0.7rem;
    font-weight: 500;
    color: var(--text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.step-row.active .step-name {
    color: var(--text-primary);
    font-weight: 600;
}
.step-row.done .step-name {
    color: var(--text-muted);
}

.step-duration {
    font-size: 0.6rem;
    color: var(--text-muted);
    font-family: var(--font-mono);
    flex-shrink: 0;
    margin-left: 4px;
}

.empty-state {
    color: var(--text-muted);
    font-size: 0.75rem;
    text-align: center;
    padding: 16px 0;
    font-style: italic;
}
</style>
