<script setup>
import { ref, computed } from 'vue'
import { DEFAULT_NODES } from '../../config/pidLayout'
import { pidVisibility, showNode, showAllNodes } from '../../services/pidVisibility'

const expanded = ref(false)

// Hidden default nodes that can be re-added
const hiddenNodes = computed(() => {
    return DEFAULT_NODES.filter(n => pidVisibility.hiddenIds.has(n.id) && n.id !== 'reactor')
})

const hasHidden = computed(() => hiddenNodes.value.length > 0)

function nodeLabel(node) {
    return node.data?.tag || node.data?.feedType || node.id
}

function restoreNode(nodeId) {
    showNode(nodeId)
}

function restoreAll() {
    showAllNodes()
}
</script>

<template>
  <div class="pid-toolbar">
    <button v-if="hasHidden" class="toolbar-toggle" @click="expanded = !expanded"
            :title="expanded ? 'Toolbar schliessen' : `${hiddenNodes.length} ausgeblendet`">
      {{ expanded ? '−' : '+' }}
      <span v-if="!expanded" class="badge">{{ hiddenNodes.length }}</span>
    </button>

    <div v-if="expanded && hasHidden" class="toolbar-panel">
      <div class="toolbar-header">
        <span class="toolbar-title">Ausgeblendet</span>
        <button class="btn-restore-all" @click="restoreAll">Alle einblenden</button>
      </div>

      <div class="chip-row">
        <button v-for="node in hiddenNodes" :key="node.id"
                class="instrument-chip"
                :title="`${nodeLabel(node)} wieder einblenden`"
                @click="restoreNode(node.id)">
          {{ nodeLabel(node) }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pid-toolbar {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 10;
    display: flex;
    align-items: flex-start;
    gap: 6px;
}

.toolbar-toggle {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    color: var(--text-muted);
    font-size: 0.85rem;
    font-weight: 700;
    min-width: 28px;
    height: 28px;
    border-radius: 6px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 0 6px;
    transition: all 0.15s;
    line-height: 1;
    flex-shrink: 0;
}
.toolbar-toggle:hover {
    color: var(--text-primary);
    border-color: var(--text-muted);
    background: var(--bg-app);
}

.badge {
    font-size: 0.55rem;
    font-weight: 700;
    background: var(--border-subtle);
    color: var(--text-secondary);
    border-radius: 3px;
    padding: 1px 4px;
    line-height: 1.2;
}

.toolbar-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 10px 12px;
    max-width: 320px;
    max-height: 400px;
    overflow-y: auto;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.toolbar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}

.toolbar-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

.btn-restore-all {
    font-size: 0.55rem;
    font-weight: 600;
    color: var(--text-muted);
    background: transparent;
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    padding: 2px 6px;
    cursor: pointer;
    transition: all 0.15s;
}
.btn-restore-all:hover {
    color: var(--text-primary);
    border-color: var(--text-muted);
}

.chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}

.instrument-chip {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.55rem;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 4px;
    border: 1px solid var(--border-subtle);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
}
.instrument-chip:hover {
    border-color: var(--text-muted);
    color: var(--text-secondary);
    background: rgba(255,255,255,0.04);
}
</style>
