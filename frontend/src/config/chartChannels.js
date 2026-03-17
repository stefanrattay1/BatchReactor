/**
 * Chart channel definitions for MultiChart.
 * Each channel maps a store state key to a chart dataset with axis, color, and formatting.
 */
export const CHART_CHANNELS = [
    {
        id: 'temp_sim',
        label: 'Temperature',
        transform: v => Number.isFinite(v) ? Math.min(v, 1e6) : 1e6,
        color: '#ef4444',
        yAxis: 'left',
        unit: '\u00b0C',
        default: true,
    },
    {
        id: 'temp_meas',
        label: 'Temp (meas)',
        stateKey: 'temperature_measured_C',
        color: '#f59e0b',
        yAxis: 'left',
        unit: '\u00b0C',
        default: true,
        dash: [4, 3],
    },
    {
        id: 'conversion',
        label: 'Conversion',
        stateKey: 'conversion',
        color: '#10b981',
        yAxis: 'right',
        unit: '%',
        default: true,
        transform: v => v * 100,
    },
    {
        id: 'dt_dt',
        label: 'dT/dt',
        stateKey: 'dt_dt',
        color: '#a855f7',
        yAxis: 'right',
        unit: '\u00b0C/s',
        default: false,
    },
    {
        id: 'viscosity',
        label: 'Viscosity',
        stateKey: 'viscosity_Pas',
        color: '#06b6d4',
        yAxis: 'right',
        unit: 'Pa\u00b7s',
        default: false,
        transform: v => Number.isFinite(v) ? v : 0,
    },
    {
        id: 'pressure',
        label: 'Pressure',
        stateKey: 'pressure_bar',
        color: '#8b5cf6',
        yAxis: 'right',
        unit: 'bar',
        default: false,
    },
    {
        id: 'jacket_temp',
        label: 'Jacket Temp',
        stateKey: 'jacket_temperature_K',
        color: '#f97316',
        yAxis: 'left',
        unit: '\u00b0C',
        default: false,
        transform: v => v - 273.15,
    },
    {
        id: 'agitator',
        label: 'Agitator',
        stateKey: 'agitator_speed_rpm',
        color: '#64748b',
        yAxis: 'right',
        unit: 'rpm',
        default: false,
    },
]

const STORAGE_KEY = 'reactor_chart_channels'

export function loadActiveChannels() {
    try {
        const saved = localStorage.getItem(STORAGE_KEY)
        if (saved) return JSON.parse(saved)
    } catch (e) { /* ignore */ }
    return CHART_CHANNELS.filter(ch => ch.default).map(ch => ch.id)
}

export function saveActiveChannels(ids) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
    } catch (e) { /* ignore */ }
}
