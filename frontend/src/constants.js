export const INPUTS = {
    component_a: { name: 'Component A Feed', icon: 'A', color: '#3b82f6', unit: 'kg/s', opc: 'Actuators/FeedComponentA_kgs', key: 'feed_rate_component_a', actuator: 'feed_component_a' },
    component_b: { name: 'Component B Feed', icon: 'B', color: '#f59e0b', unit: 'kg/s', opc: 'Actuators/FeedComponentB_kgs', key: 'feed_rate_component_b', actuator: 'feed_component_b' },
    solvent: { name: 'Solvent Feed', icon: 'S', color: '#06b6d4', unit: 'kg/s', opc: 'Actuators/FeedSolvent_kgs', key: 'feed_rate_solvent', actuator: 'feed_solvent' },
    jacket: { name: 'Jacket Temperature', icon: 'J', color: '#f59e0b', unit: 'K', opc: 'Actuators/JacketSetpoint_K', key: 'jacket_temperature_K', actuator: 'jacket_temp' },
    temperature: { name: 'Reactor Temperature', icon: 'T', color: '#ef4444', unit: 'K', opc: 'Sensors/Temperature_K', key: 'temperature_K', actuator: null },
    pressure: { name: 'Reactor Pressure', icon: 'P', color: '#a855f7', unit: 'bar', opc: 'Sensors/Pressure_bar', key: 'pressure_bar', actuator: null },
    product: { name: 'Product Mass', icon: '⬇', color: '#22c55e', unit: 'kg', opc: 'Sensors/MassTotal_kg', key: 'mass_total_kg', actuator: null }
}
