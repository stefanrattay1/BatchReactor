<script setup>
import { ref, onMounted } from 'vue'
import { state } from '../../services/store'
import { selectRecipe } from '../../services/api'

const recipes = ref([])
const currentRecipeFile = ref('')
const steps = ref([])

async function loadRecipes() {
    try {
        const res = await fetch('/api/recipes')
        const data = await res.json()
        recipes.value = data.recipes
        currentRecipeFile.value = data.current_file
    } catch(e) {}
}

async function loadSteps() {
    try {
        const res = await fetch('/api/recipe/current')
        const data = await res.json()
        steps.value = data.steps
    } catch(e) {}
}

async function handleSelectRecipe(filename) {
    if (state.simulation_running) return
    if (confirm(`Switch recipe to ${filename}?`)) {
        await selectRecipe(filename)
        await loadRecipes()
        await loadSteps()
    }
}

onMounted(() => {
    loadRecipes()
    loadSteps()
})
</script>

<template>
  <div class="recipes-tab">
    <div class="section-title">Available Recipes</div>
    <div class="recipe-list">
        <div v-for="r in recipes" :key="r.filename"
             class="recipe-item" :class="{ active: currentRecipeFile.endsWith(r.filename) }"
             @click="handleSelectRecipe(r.filename)">
            <div class="recipe-name">
                {{ r.name }}
                <span v-if="currentRecipeFile.endsWith(r.filename)" class="active-dot"></span>
            </div>
            <div class="recipe-meta">{{ r.steps }} steps &middot; {{ (r.total_duration/60).toFixed(0) }} min</div>
        </div>
    </div>

    <div v-if="steps.length > 0" class="section-title" style="margin-top: 24px;">Recipe Steps</div>
    <div v-if="steps.length > 0" class="steps-list">
        <div v-for="(step, i) in steps" :key="i" class="step-item" :class="{ 'step-active': state.recipe_step === step.name }">
            <span class="step-num">{{ i + 1 }}</span>
            <div class="step-info">
                <div class="step-name">{{ step.name }}</div>
                <div class="step-duration">{{ step.duration }}s</div>
            </div>
        </div>
    </div>
  </div>
</template>

<style scoped>
.recipes-tab { padding: 20px; }

.section-title {
    font-size: 0.75rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.section-title::before { content: ''; width: 4px; height: 14px; background: var(--accent-primary); border-radius: 2px; }

.recipe-list { display: flex; flex-direction: column; gap: 8px; }

.recipe-item {
    padding: 12px 16px;
    background: var(--bg-card);
    border-radius: 8px;
    cursor: pointer;
    border: 1px solid transparent;
    transition: all 0.2s;
}
.recipe-item:hover { border-color: var(--border-subtle); background: var(--bg-panel); transform: translateX(2px); }
.recipe-item.active { background: rgba(59, 130, 246, 0.1); border-color: var(--accent-primary); }
.recipe-name { font-weight: 600; font-size: 0.9rem; display: flex; align-items: center; gap: 8px; color: var(--text-primary); }
.active-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-success); }
.recipe-meta { font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; }

.steps-list { display: flex; flex-direction: column; gap: 6px; }
.step-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 12px;
    background: var(--bg-card);
    border-radius: 6px;
    border: 1px solid transparent;
    transition: all 0.15s;
}
.step-item.step-active { border-color: var(--accent-primary); background: rgba(59, 130, 246, 0.08); }
.step-num {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: var(--bg-app);
    border: 1px solid var(--border-subtle);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    flex-shrink: 0;
}
.step-active .step-num { background: var(--accent-primary); border-color: var(--accent-primary); color: white; }
.step-info { flex: 1; min-width: 0; }
.step-name { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); }
.step-duration { font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); }
</style>
