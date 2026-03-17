import { reactive } from 'vue'
import { pushSensorData } from './sensorConfig'
import { pushHistory, clearHistory } from './historyBuffer'

export const state = reactive({
    connected: false,
    error: null,

    // UI State
    selectedInput: null,
    logs: [], // { time, msg, type }

    // Simulation State
    simulation_running: false,
    phase: 'IDLE',

    // Physical Values
    temperature_C: 0.0,
    temperature_K: 273.15,
    temperature_measured_C: 0.0,
    temperature_measured_K: 273.15,
    jacket_temperature_K: 298.15,
    pressure_bar: 0.0,
    conversion: 0.0,
    mass_total_kg: 0.0,
    mass_component_a_kg: 0.0,
    mass_component_b_kg: 0.0,
    mass_product_kg: 0.0,
    mass_solvent_kg: 0.0,
    volume_L: 0.0,
    fill_pct: 0.0,
    viscosity_Pas: 0.0,
    viscosity_max: 100.0,

    // Agitator
    agitator_speed_rpm: 0,

    // Feed Rates
    feed_rate_component_a: 0.0,
    feed_rate_component_b: 0.0,
    feed_rate_solvent: 0.0,

    // Simulation Config
    tick_interval: 0.5,
    fake_sensors_enabled: false,

    // Recipe State
    recipe_step: '',
    recipe_elapsed_s: 0,
    dt_dt: 0.0,

    // Metadata
    actuator_overrides: {},

    // Config state
    config_pending: false,
    active_config_file: '',

    // Accumulated stats (tracked during live run for results display)
    peak_temperature_C: 0,
    run_start_time: null,  // Date when simulation started
    has_run: false,        // true once simulation has been started at least once
})

export const actions = {
    updateState(data) {
        const normalized = { ...data }

        // Detect phase change for logging
        if (normalized.phase && normalized.phase !== state.phase) {
            actions.addLog(`Phase changed to ${normalized.phase}`, 'info')

            // Track simulation lifecycle
            if (normalized.phase !== 'IDLE' && !state.has_run) {
                state.has_run = true
                state.run_start_time = new Date()
                state.peak_temperature_C = 0
            }
            if (normalized.phase === 'IDLE' && state.has_run) {
                state.has_run = false
                clearHistory()
            }
        }

        Object.assign(state, normalized)
        state.connected = true
        state.error = null

        // Track peak temperature
        if (state.has_run && normalized.temperature_C > state.peak_temperature_C) {
            state.peak_temperature_C = normalized.temperature_C
        }

        pushSensorData(normalized)

        // Record history for full-batch chart overlays
        if (state.has_run && normalized.recipe_elapsed_s !== undefined) {
            pushHistory(normalized.recipe_elapsed_s, normalized)
        }
    },
    setError(err) {
        if (state.connected) { // Only log if we were connected
            actions.addLog(`Connection lost: ${err}`, 'error')
        }
        state.connected = false
        state.error = err
    },
    selectInput(id) {
        state.selectedInput = id
    },
    addLog(msg, type = 'info') {
        const time = new Date().toLocaleTimeString('en-GB', { hour12: false })
        state.logs.unshift({ time, msg, type })
        if (state.logs.length > 50) state.logs.pop()
    }
}
