<script setup>
import { ref, onMounted } from 'vue'
import { checkHealth } from './services/api'
import NodeList from './components/NodeList.vue'
import ServerManager from './components/ServerManager.vue'
import ConnectionManager from './components/ConnectionManager.vue'

const activeTab = ref('nodes')
const version = ref('...')
const healthy = ref(false)

const tabs = [
    { id: 'nodes', label: 'Nodes' },
    { id: 'servers', label: 'OPC UA Servers' },
    { id: 'connections', label: 'Connections' },
]

onMounted(async () => {
    try {
        const data = await checkHealth()
        version.value = data.version
        healthy.value = data.status === 'ok'
    } catch {
        healthy.value = false
    }
})
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="header-left">
        <h1 class="app-title">OPC Tool</h1>
        <div class="health-badge" :class="{ ok: healthy }">
          {{ healthy ? 'Online' : 'Offline' }}
        </div>
        <span class="version">v{{ version }}</span>
      </div>
    </header>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs" :key="tab.id"
        class="tab-btn" :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </nav>

    <main class="app-content">
      <NodeList v-if="activeTab === 'nodes'" />
      <ServerManager v-if="activeTab === 'servers'" />
      <ConnectionManager v-if="activeTab === 'connections'" />
    </main>
  </div>
</template>

<style scoped>
.app-shell { display: flex; flex-direction: column; min-height: 100vh; }

.app-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 20px;
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border);
}
.header-left { display: flex; align-items: center; gap: 12px; }
.app-title { font-size: 16px; font-weight: 700; color: var(--text-primary); }
.health-badge {
    font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 10px;
    background: var(--accent-danger); color: white;
}
.health-badge.ok { background: var(--accent-success); }
.version { font-size: 10px; color: var(--text-muted); }

.tab-bar {
    display: flex; gap: 0;
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border);
    padding: 0 20px;
}
.tab-btn {
    padding: 10px 16px;
    background: none; border: none; border-bottom: 2px solid transparent;
    color: var(--text-muted); font-size: 12px; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
}
.tab-btn:hover { color: var(--text-secondary); }
.tab-btn.active { color: var(--accent-primary); border-bottom-color: var(--accent-primary); }

.app-content { flex: 1; padding: 20px; overflow-y: auto; }
</style>
