/**
 * Long-running value history store for full-batch chart overlays
 * and DetailChart actual-vs-setpoint comparisons.
 *
 * Stores up to MAX_HISTORY points per state key (~100 min at 1s intervals).
 */
const MAX_HISTORY = 6000

// Plain object (not reactive) — avoids infinite reactivity loops
// when Chart.js mutates data arrays internally.
const history = {}

export function pushHistory(time, stateData) {
    for (const [key, value] of Object.entries(stateData)) {
        if (typeof value !== 'number') continue
        if (!history[key]) history[key] = []
        history[key].push({ x: time, y: value })
        if (history[key].length > MAX_HISTORY) history[key].shift()
    }
}

export function getHistory(stateKey) {
    return history[stateKey] || []
}

export function clearHistory() {
    for (const key of Object.keys(history)) {
        history[key] = []
    }
}
