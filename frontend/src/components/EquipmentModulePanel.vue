<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { state } from '../services/store'
import { setEquipmentMode } from '../services/api'

const expandedEm = ref(null)
const openDropdown = ref(null)

const modules = computed(() => state.equipment_modules || [])

const stateColor = (emState) => {
    const map = {
        active: 'var(--dcs-normal)',
        transitioning: 'var(--dcs-transition)',
        fault: 'var(--dcs-alarm)',
        idle: 'var(--dcs-off)',
    }
    return map[emState] || map.idle
}

const stateLabel = (emState) => {
    const map = {
        active: 'AKTIV',
        transitioning: 'WECHSEL',
        fault: 'STOERUNG',
        idle: 'BEREIT',
    }
    return map[emState] || emState
}

async function selectMode(emTag, mode) {
    openDropdown.value = null
    const result = await setEquipmentMode(emTag, mode)
    if (result.error) {
        console.warn('Mode change failed:', result.error)
    }
}

function toggleDropdown(tag) {
    openDropdown.value = openDropdown.value === tag ? null : tag
}

function toggleExpand(tag) {
    expandedEm.value = expandedEm.value === tag ? null : tag
}

function onClickOutside(e) {
    if (!e.target.closest('.em-select')) {
        openDropdown.value = null
    }
}

onMounted(() => document.addEventListener('click', onClickOutside))
onUnmounted(() => document.removeEventListener('click', onClickOutside))
</script>

<template>
  <div class="equipment-panel" v-if="modules.length > 0">
    <div class="section-title">Equipment Modules</div>
    <div class="em-list">
      <div v-for="em in modules" :key="em.tag"
           class="em-row"
           :class="{ expanded: expandedEm === em.tag }">

        <!-- Header row -->
        <div class="em-header" @click="toggleExpand(em.tag)">
          <span class="em-status-dot" :style="{ background: stateColor(em.state) }"></span>
          <span class="em-tag">{{ em.tag }}</span>
          <span class="em-name">{{ em.name }}</span>
          <span class="em-state-badge" :style="{ background: stateColor(em.state) }">
            {{ stateLabel(em.state) }}
          </span>
        </div>

        <!-- Mode selector -->
        <div class="em-mode-row">
          <div class="em-select" :class="{ open: openDropdown === em.tag }">
            <button class="em-select-trigger" @click.stop="toggleDropdown(em.tag)">
              <span class="em-select-value">{{ em.current_mode }}</span>
              <svg class="em-select-arrow" viewBox="0 0 10 6" width="10" height="6">
                <path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.5"
                      fill="none" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </button>
            <div class="em-select-menu" v-if="openDropdown === em.tag">
              <div v-for="mode in em.modes" :key="mode"
                   class="em-select-option"
                   :class="{ active: mode === em.current_mode }"
                   @click.stop="selectMode(em.tag, mode)">
                {{ mode }}
              </div>
            </div>
          </div>
        </div>

        <!-- Transition Vorgang (always visible while transitioning) -->
        <div class="em-vorgang" v-if="em.state === 'transitioning' && em.transition_steps?.length">
          <div class="vorgang-title">
            ⟶ {{ em.transitioning_to }}
          </div>
          <div v-for="(step, idx) in em.transition_steps" :key="idx"
               class="vorgang-step"
               :class="{
                 done: idx < em.transition_step,
                 active: idx === em.transition_step,
               }">
            <span class="step-indicator">
              <span v-if="idx < em.transition_step">✓</span>
              <span v-else-if="idx === em.transition_step" class="step-spinner">●</span>
              <span v-else>○</span>
            </span>
            <span class="step-name">{{ step }}</span>
          </div>
        </div>

        <!-- Fault message -->
        <div class="em-fault" v-if="em.fault_message">
          ⚠ {{ em.fault_message }}
        </div>

        <!-- Expanded detail -->
        <div class="em-detail" v-if="expandedEm === em.tag">
          <div class="em-detail-item">
            <span class="detail-label">Aktueller Modus:</span>
            <span class="detail-value">{{ em.current_mode }}</span>
          </div>
          <div class="em-detail-item">
            <span class="detail-label">Status:</span>
            <span class="detail-value">{{ em.state }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.equipment-panel {
    padding: 12px;
    border-top: 1px solid var(--border-subtle);
}

.section-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 8px;
}

.em-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.em-row {
    border-radius: 4px;
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    overflow: visible;
}
.em-row.expanded {
    border-color: var(--accent-primary);
}

.em-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    cursor: pointer;
    transition: background 0.15s;
}
.em-header:hover {
    background: var(--equip-bg);
}

.em-status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.em-tag {
    font-size: 0.6rem;
    font-weight: 700;
    color: var(--text-muted);
    letter-spacing: 0.05em;
    flex-shrink: 0;
}

.em-name {
    font-size: 0.7rem;
    color: var(--text-secondary);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.em-state-badge {
    font-size: 0.5rem;
    font-weight: 700;
    padding: 1px 4px;
    border-radius: 3px;
    color: #000;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    flex-shrink: 0;
}

.em-mode-row {
    padding: 0 8px 6px;
}

/* ── Custom dropdown ─────────────────────────────────── */
.em-select {
    position: relative;
    width: 100%;
}

.em-select-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 4px 8px;
    border-radius: 3px;
    border: 1px solid var(--border-subtle);
    background: var(--bg-input);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 0.7rem;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    text-align: left;
}
.em-select-trigger:hover {
    border-color: var(--accent-primary);
    background: var(--equip-bg);
}
.em-select.open .em-select-trigger {
    border-color: var(--accent-primary);
    background: var(--equip-bg);
}

.em-select-arrow {
    color: var(--text-muted);
    flex-shrink: 0;
    margin-left: 6px;
    transition: transform 0.15s;
}
.em-select.open .em-select-arrow {
    transform: rotate(180deg);
    color: var(--accent-primary);
}

.em-select-value {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.em-select-menu {
    position: absolute;
    top: calc(100% + 2px);
    left: 0;
    right: 0;
    z-index: 100;
    background: var(--bg-input);
    border: 1px solid var(--accent-primary);
    border-radius: 3px;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
}

.em-select-option {
    padding: 5px 8px;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
}
.em-select-option:hover {
    background: var(--equip-bg);
    color: var(--text-primary);
}
.em-select-option.active {
    color: var(--accent-primary);
    background: rgba(0, 180, 180, 0.08);
}
.em-select-option + .em-select-option {
    border-top: 1px solid var(--border-subtle);
}
/* ───────────────────────────────────────────────────── */

/* ── Transition Vorgang ──────────────────────────────── */
.em-vorgang {
    padding: 4px 8px 6px;
    border-top: 1px solid var(--border-subtle);
}

.vorgang-title {
    font-size: 0.6rem;
    font-weight: 700;
    color: var(--dcs-transition);
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 4px;
}

.vorgang-step {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 2px 0;
    font-size: 0.65rem;
    color: var(--text-muted);
    transition: color 0.2s;
}

.vorgang-step.done {
    color: var(--dcs-normal);
}

.vorgang-step.active {
    color: var(--text-primary);
    font-weight: 600;
}

.step-indicator {
    font-size: 0.6rem;
    width: 10px;
    text-align: center;
    flex-shrink: 0;
    color: inherit;
}

.step-spinner {
    display: inline-block;
    color: var(--dcs-transition);
    animation: pulse-dot 1s ease-in-out infinite;
}

@keyframes pulse-dot {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.3; }
}

.step-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* ── Fault message ───────────────────────────────────── */
.em-fault {
    padding: 4px 8px 6px;
    border-top: 1px solid var(--border-subtle);
    font-size: 0.65rem;
    color: var(--dcs-alarm);
    font-weight: 600;
}

/* ── Expanded detail ─────────────────────────────────── */
.em-detail {
    padding: 4px 8px 8px;
    border-top: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.em-detail-item {
    display: flex;
    justify-content: space-between;
    font-size: 0.65rem;
}

.detail-label {
    color: var(--text-muted);
}

.detail-value {
    font-weight: 600;
    color: var(--text-primary);
    font-family: var(--font-mono);
}
</style>
