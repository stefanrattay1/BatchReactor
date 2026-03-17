import { reactive } from 'vue'

const STORAGE_KEY = 'reactor_pid_hidden_nodes'

export const pidVisibility = reactive({
    hiddenIds: new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')),
})

function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...pidVisibility.hiddenIds]))
}

export function hideNode(nodeId) {
    if (nodeId === 'reactor') return
    pidVisibility.hiddenIds.add(nodeId)
    save()
}

export function showNode(nodeId) {
    pidVisibility.hiddenIds.delete(nodeId)
    save()
}

export function showAllNodes() {
    pidVisibility.hiddenIds.clear()
    save()
}

export function isHidden(nodeId) {
    return pidVisibility.hiddenIds.has(nodeId)
}
