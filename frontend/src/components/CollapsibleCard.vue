<script setup>
import { ref } from 'vue'

const props = defineProps({
    title: { type: String, required: true },
    defaultOpen: { type: Boolean, default: true },
    highlight: { type: Boolean, default: false },
})

const isOpen = ref(props.defaultOpen)
</script>

<template>
    <div class="collapsible-card" :class="{ collapsed: !isOpen, highlight }">
        <div class="card-header" @click="isOpen = !isOpen">
            <h2>{{ title }}</h2>
            <span class="chevron">{{ isOpen ? '\u25BC' : '\u25B6' }}</span>
        </div>
        <div class="card-body" v-show="isOpen">
            <slot />
        </div>
    </div>
</template>

<style scoped>
.collapsible-card {
    background: var(--bg-card);
    border-radius: 12px;
    border: 1px solid var(--border-subtle);
    margin-bottom: 16px;
    box-shadow: var(--shadow-sm);
    overflow: hidden;
}
.collapsible-card.highlight { border-color: var(--accent-primary); box-shadow: var(--shadow-glow); }

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 14px 20px;
    cursor: pointer;
    user-select: none;
    transition: background 0.15s;
}
.card-header:hover { background: rgba(255,255,255,0.02); }

.card-header h2 {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin: 0;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 700;
}

.chevron {
    font-size: 0.6rem;
    color: var(--text-muted);
    transition: transform 0.15s;
}

.card-body {
    padding: 0 20px 20px;
}
</style>
