import { reactive } from 'vue'

export const pidEditMode = reactive({ active: false })

export function toggleEditMode() {
    pidEditMode.active = !pidEditMode.active
}

export function setEditMode(val) {
    pidEditMode.active = !!val
}
