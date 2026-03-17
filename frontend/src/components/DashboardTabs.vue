<script setup>
import { ref, watch, shallowRef, computed } from 'vue'
import { state } from '../services/store'
import { INPUTS } from '../constants'
import ChartsTab from './tabs/ChartsTab.vue'
import ProcessTab from './tabs/ProcessTab.vue'
import EventsTab from './tabs/EventsTab.vue'
import RecipesTab from './tabs/RecipesTab.vue'

const tabs = [
    { id: 'charts', label: 'Charts', component: ChartsTab },
    { id: 'process', label: 'Process', component: ProcessTab },
    { id: 'events', label: 'Events', component: EventsTab },
    { id: 'recipes', label: 'Recipes', component: RecipesTab },
]

const activeTab = ref('charts')

const activeComponent = computed(() => {
    const tab = tabs.find(t => t.id === activeTab.value)
    return tab ? tab.component : ChartsTab
})

// Cross-panel: auto-switch tab when an input is selected in SVG
watch(() => state.selectedInput, (id) => {
    if (!id) return
    const input = INPUTS[id]
    if (input && input.actuator) {
        // Actuators have recipe profiles → show charts
        activeTab.value = 'charts'
    } else if (id) {
        // Sensors → show process tab with live values
        activeTab.value = 'process'
    }
})

// Event badge: count of recent events
const eventBadge = computed(() => {
    const recent = state.logs.filter(l => {
        // Show badge if there's an error or warning in last 5 entries
        return l.type === 'error' || l.type === 'warn'
    })
    return recent.length > 0 ? recent.length : null
})
</script>

<template>
  <div class="dashboard-tabs">
    <div class="tab-bar">
        <button v-for="tab in tabs" :key="tab.id"
                class="tab-btn"
                :class="{ active: activeTab === tab.id }"
                @click="activeTab = tab.id">
            {{ tab.label }}
            <span v-if="tab.id === 'events' && eventBadge" class="tab-badge">{{ eventBadge }}</span>
        </button>
    </div>
    <div class="tab-content">
        <KeepAlive>
            <component :is="activeComponent" :key="activeTab" />
        </KeepAlive>
    </div>
  </div>
</template>

<style scoped>
.dashboard-tabs {
    display: flex;
    flex-direction: column;
    height: 100%;
}

.tab-bar {
    display: flex;
    gap: 0;
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border-subtle);
    padding: 0 16px;
    flex-shrink: 0;
}

.tab-btn {
    padding: 10px 16px;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    cursor: pointer;
    transition: all 0.15s;
    position: relative;
}
.tab-btn:hover { color: var(--text-secondary); }
.tab-btn.active {
    color: var(--accent-primary);
    border-bottom-color: var(--accent-primary);
}

.tab-badge {
    position: absolute;
    top: 4px;
    right: 2px;
    background: var(--accent-danger);
    color: white;
    font-size: 0.55rem;
    font-weight: 700;
    padding: 1px 4px;
    border-radius: 999px;
    min-width: 14px;
    text-align: center;
    line-height: 1.3;
}

.tab-content {
    flex: 1;
    overflow-y: auto;
}
</style>
