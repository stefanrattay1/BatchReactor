/**
 * Composable for loading recipe setpoint trajectory and building forecast overlays.
 * Extracted from MainChart.vue for reuse in MultiChart and DetailChart.
 */
import { ref } from 'vue'
import { state } from '../services/store'

export function useRecipeForecast() {
    const recipeSetpoint = ref([])
    const recipeTotalDuration = ref(0)

    async function loadRecipeSetpoint() {
        try {
            const res = await fetch('/api/recipe/current')
            const data = await res.json()
            // Flatten ISA-88 hierarchy (unit_procedures → operations → phases)
            // into a flat phase list, falling back to legacy data.steps
            const phases = []
            if (data.unit_procedures) {
                for (const up of data.unit_procedures) {
                    for (const op of up.operations) {
                        for (const phase of op.phases) {
                            phases.push(phase)
                        }
                    }
                }
            } else if (data.steps) {
                phases.push(...data.steps)
            }
            const points = []
            let t = 0
            for (const step of phases) {
                const profile = step.profiles?.jacket_temp
                if (profile) {
                    points.push({ x: t, y: profile.start_value - 273.15 })
                    points.push({ x: t + step.duration, y: profile.end_value - 273.15 })
                }
                t += step.duration
            }
            recipeSetpoint.value = points
            recipeTotalDuration.value = t
        } catch (e) {
            // Recipe not available yet
        }
    }

    function buildForecast(currentElapsed) {
        if (recipeSetpoint.value.length === 0 || currentElapsed <= 0) {
            return recipeSetpoint.value
        }
        const forecast = []
        // Anchor at current temperature
        forecast.push({ x: currentElapsed, y: state.temperature_C })
        // Append all future setpoint values
        for (const p of recipeSetpoint.value) {
            if (p.x > currentElapsed) forecast.push(p)
        }
        return forecast
    }

    return {
        recipeSetpoint,
        recipeTotalDuration,
        loadRecipeSetpoint,
        buildForecast,
    }
}
