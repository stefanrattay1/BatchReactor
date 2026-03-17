/**
 * Shared value formatting utilities.
 * Consolidates duplicated formatting from StatusDashboard, ReactorSVG, SensorManager.
 */

export function formatSensorValue(value, node, viscosityCap = 100) {
    if (value === undefined || value === null) return '--'
    if (typeof value !== 'number') return String(value)

    if (node.unit === 'bar') return value.toFixed(3) + ' bar'
    if (node.unit === 'K') return value.toFixed(1) + ' K'
    if (node.unit === 'Pa\u00b7s') return value >= viscosityCap ? 'GEL' : value.toFixed(1) + ' Pa\u00b7s'
    if (node.unit === 'kg') return value.toFixed(2) + ' kg'
    if (node.unit === 's') return value.toFixed(0) + ' s'
    if (node.unit === 'kg/s') return value.toFixed(4) + ' kg/s'
    if (node.id === 'conversion') return value.toFixed(4)
    return value.toFixed(2) + (node.unit ? ' ' + node.unit : '')
}

export function formatSensorValueCompact(value, node, viscosityCap = 100) {
    if (value === undefined || value === null) return '--'
    if (typeof value !== 'number') return String(value)

    if (node.unit === 'bar') return value.toFixed(2)
    if (node.unit === 'K') return (value - 273.15).toFixed(0) + '\u00b0C'
    if (node.unit === 'Pa\u00b7s') return value >= viscosityCap ? 'GEL' : value.toFixed(0)
    if (node.unit === 'kg') return value.toFixed(1)
    if (node.unit === 's') return value.toFixed(0)
    if (node.id === 'conversion') return (value * 100).toFixed(0) + '%'
    return value.toFixed(2)
}

export function formatTemperatureC(kelvin) {
    return (kelvin - 273.15).toFixed(1) + '\u00b0C'
}

export function formatElapsed(seconds) {
    if (seconds < 60) return `${seconds.toFixed(0)}s`
    if (seconds < 3600) {
        const m = Math.floor(seconds / 60)
        const s = Math.round(seconds % 60)
        return `${m}m ${s}s`
    }
    return `${(seconds / 3600).toFixed(1)}h`
}
