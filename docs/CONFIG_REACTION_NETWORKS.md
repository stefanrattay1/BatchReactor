# Reactor Configuration Guide

This guide explains how to configure the batch reactor simulator, including physical reactor properties, custom reaction chemistry, pluggable physics models, and batch mode settings.

For the mathematical equations behind each model, see [equations.md](equations.md).

## Table of Contents

- [Configuration Structure](#configuration-structure)
- [Reactor Section](#reactor-section)
- [Thermal Section](#thermal-section)
- [Viscosity Section](#viscosity-section)
- [Physics Section](#physics-section)
- [Geometry Section](#geometry-section)
- [Mixing Section](#mixing-section)
- [Chemistry Configuration Modes](#chemistry-configuration-modes)
  - [Legacy Mode](#legacy-mode-existing-configs)
  - [Reaction Network Mode](#reaction-network-mode)
- [Species Configuration](#species-configuration)
- [Reaction Configuration](#reaction-configuration)
- [Rate Law Types](#rate-law-types)
- [Stoichiometry](#stoichiometry)
- [Heat of Reaction](#heat-of-reaction)
- [Simulation Models](#simulation-models)
- [Controller Section](#controller-section)
- [Initial Conditions](#initial-conditions)
- [Solver Section](#solver-section)
- [Recipe Integration](#recipe-integration)
- [Conversion Variables](#conversion-variables)
- [Batch Mode](#batch-mode)
- [Complete Examples](#complete-examples)
- [Tips & Best Practices](#tips--best-practices)
- [Validation](#validation)
- [Output](#output)
- [Troubleshooting](#troubleshooting)
- [See Also](#see-also)

---

## Configuration Structure

A complete reactor config YAML includes:

```yaml
reactor:             # Physical reactor vessel properties
thermal:             # Heat capacity and static heat transfer
viscosity:           # Rheology model parameters
physics:             # Physical constants, stoichiometry, densities
geometry:            # (Optional) Vessel geometry for geometry-aware UA
mixing:              # (Optional) Agitator/impeller for dynamic UA
kinetics:            # (Legacy) Kamal-Sourour parameters
reaction_network:    # (New) Custom reaction networks (replaces kinetics)
simulation:          # (Optional) Pluggable physics model selection
controller:          # Process control logic and safety limits
initial_conditions:  # Starting state (temperature, jacket, volume)
solver:              # DAE solver settings
```

Not all sections are required. Defaults are applied for omitted sections.

---

## Reactor Section

Define the physical reactor vessel:

```yaml
reactor:
  volume_m3: 0.1              # m³, reactor working volume
  vessel_volume_L: 100.0      # L, total vessel capacity
  pressure_bar: 0.5           # bar, operating pressure
  agitator_speed_rpm: 120     # rpm, agitator speed
```

| Field | Units | Default | Constraint | Description |
|-------|-------|---------|------------|-------------|
| `volume_m3` | m³ | 0.1 | > 0 | Working volume available for reaction |
| `vessel_volume_L` | L | 100.0 | > 0 | Total vessel capacity (for fill % display) |
| `pressure_bar` | bar | 0.5 | > 0 | Operating pressure (safety display) |
| `agitator_speed_rpm` | rpm | 120 | >= 0 | Constant agitator speed |

The same chemistry can run in different reactors by changing only this section (and geometry/mixing as needed):
- [configs/default.yaml](../configs/default.yaml) — 100L pilot plant (0.1 m³, 800 rpm Rushton)
- [configs/lab_scale_reactor.yaml](../configs/lab_scale_reactor.yaml) — 10L lab reactor (0.01 m³, 200 rpm pitched-blade)

---

## Thermal Section

Static thermal properties of the reaction mixture:

```yaml
thermal:
  Cp: 1.8              # kJ/(kg·K), specific heat of mixture
  UA: 0.5              # kW/K, overall heat transfer coefficient × area
```

| Field | Units | Default | Constraint | Description |
|-------|-------|---------|------------|-------------|
| `Cp` | kJ/(kg·K) | 1.8 | > 0 | Specific heat capacity of mixture |
| `UA` | kW/K | 0.5 | >= 0 | Static overall heat transfer coefficient × area |

`UA` serves as the baseline heat transfer. When `simulation.models.heat_transfer` is set to `dynamic` or `geometry_aware`, the static `UA` is used as a reference or floor value and the actual UA is computed each time step.

---

## Viscosity Section

Rheology model parameters for temperature- and conversion-dependent viscosity:

```yaml
viscosity:
  eta_0: 0.5              # Pa·s, fallback base viscosity
  eta_ref: 0.5            # Pa·s, reference viscosity at T_ref_K
  T_ref_K: 298.15         # K, reference temperature
  E_eta_J_mol: 45000.0    # J/mol, Arrhenius activation energy for viscosity
  C_visc: 2.0             # dimensionless, gelation shape parameter
  alpha_gel: 0.8          # gel point conversion
  eta_gel: 100.0          # Pa·s, viscosity cap at/beyond gel point
  species_viscosities:    # Pa·s at T_ref_K, for log-mixing rule (optional)
    component_a: 1.5
    component_b: 0.01
    solvent: 0.001
```

| Field | Units | Default | Description |
|-------|-------|---------|-------------|
| `eta_0` | Pa·s | 0.5 | Fallback reference viscosity when no species data |
| `eta_ref` | Pa·s | 0.5 | Reference viscosity at T_ref_K |
| `T_ref_K` | K | 298.15 | Reference temperature for Arrhenius viscosity |
| `E_eta_J_mol` | J/mol | 0.0 | Activation energy for temperature dependence |
| `C_visc` | — | 4.0 | Shape parameter for gel-point divergence |
| `alpha_gel` | — | 0.6 | Gel point conversion |
| `eta_gel` | Pa·s | 100.0 | Viscosity cap at/beyond gel point |
| `species_viscosities` | Pa·s | — | Per-species viscosities for log-mixing rule |

When `species_viscosities` is provided, the reference viscosity at T_ref is computed using a log-mixing rule weighted by mass fractions. See [equations.md](equations.md#viscosity-model) for full equations.

---

## Physics Section

Physical constants and species densities (used in legacy mode):

```yaml
physics:
  stoich_ratio: 0.3       # kg component_b consumed per kg component_a consumed
  max_temp: 500.0         # K, safety cap for numerical stability
  R_gas: 8.314            # J/(mol·K), universal gas constant
  density_component_a: 1.16     # kg/L
  density_component_b: 0.97  # kg/L
  density_product: 1.20   # kg/L
  density_solvent: 0.87   # kg/L
```

In reaction network mode, species densities are defined per-species in the `reaction_network.species` list, so the `density_*` fields here are ignored. `stoich_ratio` is also superseded by explicit stoichiometry in the reaction definition.

---

## Geometry Section

Optional vessel geometry for geometry-aware heat transfer calculations:

```yaml
geometry:
  type: cylindrical_torispherical   # or: cylindrical_flat
  diameter_m: 0.50                  # m, inner diameter
  height_m: 0.60                    # m, straight-side height
```

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | `cylindrical_torispherical` (ASME F&D head) or `cylindrical_flat` |
| `diameter_m` | yes | Inner diameter in meters |
| `height_m` | yes | Straight-side (cylindrical) height in meters |

Geometry is required when `simulation.models.heat_transfer` is set to `geometry_aware`. It computes wetted surface area from the current liquid volume. Omit this section entirely if using `constant` or `dynamic` heat transfer.

See [equations.md](equations.md#vessel-geometry) for the wetted area formulas.

---

## Mixing Section

Optional agitator/impeller configuration. Enables Reynolds-based mixing efficiency and dynamic heat transfer coefficient computation:

```yaml
mixing:
  enabled: true
  impeller_diameter_m: 0.22         # m, ~D_tank/2
  power_number: 5.0                 # Rushton turbine
  impeller_type: rushton            # or: pitched_blade
  n_blades: 6
  wall_thickness_m: 0.005           # m, vessel wall thickness
  wall_conductivity: 16.0           # W/(m·K), stainless steel 304
  h_jacket: 2000.0                  # W/(m²·K), jacket-side HTC
  fluid_thermal_conductivity: 0.17  # W/(m·K), process fluid
  min_UA_fraction: 0.4              # minimum UA as fraction of static UA
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | false | Master switch for mixing calculations |
| `impeller_diameter_m` | 0.16 | Impeller diameter (m) |
| `power_number` | 5.0 | Power number (Np), depends on impeller type |
| `impeller_type` | rushton | Impeller type (affects Nusselt correlation constant) |
| `n_blades` | 6 | Number of impeller blades |
| `wall_thickness_m` | 0.005 | Vessel wall thickness for thermal resistance |
| `wall_conductivity` | 16.0 | Wall thermal conductivity, W/(m·K) |
| `h_jacket` | 1000.0 | Jacket-side heat transfer coefficient, W/(m²·K) |
| `fluid_thermal_conductivity` | 0.17 | Process fluid conductivity, W/(m·K) |
| `min_UA_fraction` | 0.30 | Floor for dynamic UA as fraction of static UA |

When `enabled: true`, the simulator computes Reynolds number, Nusselt number, and overall U from thermal resistances each time step. The `min_UA_fraction` prevents heat transfer collapse when viscosity spikes near the gel point.

**Dependencies:** Setting `simulation.models.heat_transfer: dynamic` requires `mixing.enabled: true`.

---

## Chemistry Configuration Modes

The simulator supports two chemistry configuration modes:

1. **Legacy mode** (default) — Uses the hardcoded Kamal-Sourour autocatalytic model
2. **Reaction network mode** — Define arbitrary chemistry via YAML

### Legacy Mode (Existing Configs)

Legacy configs define chemistry via separate `kinetics` and `physics` sections:

```yaml
kinetics:
  A1: 1.0e+4          # s^-1, pre-exponential (catalytic path)
  Ea1: 55000.0        # J/mol, activation energy path 1
  A2: 1.0e+6          # s^-1, pre-exponential (autocatalytic path)
  Ea2: 45000.0        # J/mol, activation energy path 2
  m: 0.5              # autocatalytic exponent
  n: 1.5              # reaction order exponent
  delta_H: 350.0      # kJ/kg of component_a, total heat of reaction
  alpha_gel: 0.6      # gel point conversion

physics:
  stoich_ratio: 0.3   # kg component_b consumed per kg component_a consumed
  # ... densities, etc.
```

This auto-generates a Kamal-Sourour reaction network with 4 species (component_a, component_b, product, solvent).

### Reaction Network Mode

Add a `reaction_network` section to define custom chemistry:

```yaml
reaction_network:
  species:
    - name: component_a
      density: 1.16          # kg/L
      initial_mass: 0.0      # kg (optional, can be set by recipe)
      phase: liquid           # optional, default "liquid"
      molar_mass: 340.0      # g/mol (optional, for molar-based rate laws)
      inert: false            # optional, default false

  reactions:
    - name: main_reaction
      rate_law: kamal_sourour
      conversion_variable: alpha
      parameters:
        A1: 1.0e4
        Ea1: 55000.0
        A2: 1.0e6
        Ea2: 45000.0
        m: 0.5
        n: 1.5
      stoichiometry:
        component_a: -1.0          # consumed (negative)
        component_b: -0.3       # consumed
        product: 1.3         # produced (positive)
      delta_H: 350.0         # kJ/kg of heat_basis species
      heat_basis: component_a      # species whose initial mass is the enthalpy reference
```

---

## Species Configuration

Each species must have:

| Field | Required | Default | Description | Example |
|-------|----------|---------|-------------|---------|
| `name` | yes | — | Unique identifier | `"component_a"`, `"intermediate"` |
| `density` | no | 1.0 | Density in kg/L | `1.16` |
| `initial_mass` | no | 0.0 | Starting mass in kg | `60.0` |
| `phase` | no | `"liquid"` | Physical phase | `"liquid"` |
| `molar_mass` | no | — | Molecular weight in g/mol | `340.0` |
| `inert` | no | false | True if doesn't participate in reactions | `true` |

### Example: Inert Solvent

```yaml
species:
  - name: solvent
    density: 0.87
    inert: true    # Won't participate in reactions
```

---

## Reaction Configuration

Each reaction must have:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | yes | — | Unique identifier |
| `rate_law` | yes | — | Rate law type (see below) |
| `parameters` | yes | — | Kinetic parameters dict |
| `stoichiometry` | yes | — | Species coefficients dict |
| `delta_H` | no | 0.0 | Heat of reaction (kJ/kg) |
| `heat_basis` | no | — | Species for enthalpy basis |
| `conversion_variable` | no | — | Conversion tracking variable name |

---

## Rate Law Types

### 1. Kamal-Sourour Autocatalytic

**Use for:** Autocatalytic curing, polymerization

```yaml
rate_law: kamal_sourour
conversion_variable: alpha
parameters:
  A1: 1.0e4      # s^-1, pre-exponential (catalytic path)
  Ea1: 55000.0   # J/mol, activation energy path 1
  A2: 1.0e6      # s^-1, pre-exponential (autocatalytic path)
  Ea2: 45000.0   # J/mol, activation energy path 2
  m: 0.5         # autocatalytic exponent
  n: 1.5         # reaction order exponent
```

**Rate equation:** `r = (k1 + k2 * alpha^m) * (1 - alpha)^n`

where:
- `k1 = A1 * exp(-Ea1 / (R*T))`
- `k2 = A2 * exp(-Ea2 / (R*T))`
- `alpha` = conversion (0 to 1)

---

### 2. N-th Order Kinetics

**Use for:** Simple reactions, consecutive steps

```yaml
rate_law: nth_order
conversion_variable: alpha_1
parameters:
  A: 1.0e4       # s^-1, pre-exponential factor
  Ea: 55000.0    # J/mol, activation energy
  n: 1.5         # reaction order
```

**Rate equation:** `r = A * exp(-Ea / (R*T)) * (1 - alpha)^n`

---

### 3. Arrhenius (Multi-species)

**Use for:** Complex reactions with multiple reactants

```yaml
rate_law: arrhenius
parameters:
  A: 1.0e4       # s^-1, pre-exponential
  Ea: 50000.0    # J/mol, activation energy
  order_A: 1.0   # reaction order for species A
  order_B: 0.5   # reaction order for species B
```

**Rate equation:** `r = A * exp(-Ea / (R*T)) * [A]^order_A * [B]^order_B`

---

## Stoichiometry

Define how each species changes during the reaction:

```yaml
stoichiometry:
  component_a: -1.0        # Consumed: 1 kg component_a
  component_b: -0.3     # Consumed: 0.3 kg component_b
  product: 1.3       # Produced: 1.3 kg product
```

**Rules:**
- Negative = consumed
- Positive = produced
- Zero = not involved (omit from dict)
- Coefficients are mass-based (kg/kg of basis species)

---

## Heat of Reaction

```yaml
delta_H: 350.0      # kJ/kg of heat_basis species
heat_basis: component_a   # Initial mass of this species is the reference
```

**Heat generation:** `Q_rxn = delta_H * initial_mass(heat_basis) * rate`

Example: If you start with 100 kg component_a and `delta_H = 350 kJ/kg`:
- At `rate = 0.001 s^-1`: `Q_rxn = 350 * 100 * 0.001 = 35 kW`

---

## Simulation Models

The simulator uses a pluggable model architecture. Each physics sub-model can be swapped independently via the `simulation` config section:

```yaml
simulation:
  models:
    viscosity: full_composition   # or: constant, arrhenius, conversion
    heat_transfer: dynamic        # or: constant, geometry_aware
    mixing: reynolds              # or: perfect, power_law
    energy: full                  # or: isothermal, adiabatic, extended
```

When this section is omitted, defaults are chosen based on the `mixing` configuration:

| Model | Default (mixing enabled) | Default (mixing disabled) |
|-------|--------------------------|---------------------------|
| `viscosity` | `full_composition` | `full_composition` |
| `heat_transfer` | `dynamic` | `constant` |
| `mixing` | `reynolds` | `perfect` |
| `energy` | `full` | `full` |

### Viscosity Models

| Name | Description |
|------|-------------|
| `constant` | Fixed viscosity, no variation with temperature or conversion |
| `arrhenius` | Temperature-dependent only: `eta = eta_ref * exp(E_eta/R * (1/T - 1/T_ref))` |
| `conversion` | Temperature + conversion dependent, with gel-point divergence |
| `full_composition` | Temperature + conversion + composition (log-mixing rule from `species_viscosities`) |

### Heat Transfer Models

| Name | Requires | Description |
|------|----------|-------------|
| `constant` | — | Fixed UA from `thermal.UA` |
| `geometry_aware` | `geometry` section | UA scales with wetted surface area based on fill level |
| `dynamic` | `mixing.enabled: true` | Full dynamic UA from Reynolds/Nusselt correlations (recomputed each step) |

### Mixing Models

| Name | Description |
|------|-------------|
| `perfect` | Ideal mixing, efficiency = 1.0 always |
| `reynolds` | Reynolds-based sigmoid transition between laminar (eta_min) and turbulent (1.0) |
| `power_law` | Power-law correlation for mixing efficiency |

### Energy Models

| Name | Description |
|------|-------------|
| `isothermal` | Temperature fixed: dT/dt = 0 (useful for kinetics-only studies) |
| `adiabatic` | No jacket cooling: dT/dt = Q_rxn / (m * Cp) |
| `full` | Full energy balance: dT/dt = (Q_rxn + Q_jacket) / (m * Cp) |
| `extended` | Adds frictional heating from agitator power draw to `full` model |

The energy model's `compute_dT_dt()` method is called with Pyomo symbolic expressions inside the DAE constraint, and with numeric values in the scipy fallback solver. This unified code path ensures both solvers produce consistent results. Custom energy models registered via `register_energy_model()` work automatically in both paths.

### Model Dependencies

The validator enforces these dependencies at config load time:

| Model | Dependency |
|-------|------------|
| `heat_transfer: dynamic` | Requires `mixing.enabled: true` |
| `heat_transfer: geometry_aware` | Requires `geometry` section |

---

## Controller Section

The controller is a rule-based finite-state machine with safety checks and completion criteria:

```yaml
controller:
  cure_temp_K: 353.15         # K, target cure temperature
  cool_done_temp_K: 313.15    # K, cool enough to discharge
  runaway_temp_K: 473.15      # K, absolute temperature alarm
  runaway_dT_dt: 2.0          # K/s, rate-of-rise alarm
  conversion_done: 0.95       # reaction essentially complete
  dt_window: 10               # rolling window for dT/dt
```

| Field | Units | Description |
|-------|-------|-------------|
| `cure_temp_K` | K | Setpoint the controller maintains during cure |
| `cool_done_temp_K` | K | Temperature below which cool-down is complete |
| `runaway_temp_K` | K | Absolute temperature alarm |
| `runaway_dT_dt` | K/s | Rate-of-rise alarm |
| `conversion_done` | — | Conversion threshold to transition from cure to cool-down |
| `dt_window` | samples | Sliding window size for dT/dt estimation |

**Tuning guidance:**
- Larger `dt_window` smooths dT/dt noise but delays detection.
- Lower `runaway_dT_dt` catches early thermal spikes but can trigger false alarms during normal heating ramps.
- `conversion_done` should align with the gel point and desired final properties.

---

## Initial Conditions

Starting state for the simulation:

```yaml
initial_conditions:
  temperature: 298.15         # K, initial reactor temperature
  jacket_temperature: 298.15  # K, initial jacket temperature
  volume: 0.1                 # m³ (optional, overrides reactor.volume_m3)
```

| Field | Units | Required | Description |
|-------|-------|----------|-------------|
| `temperature` | K | yes | Initial reactor temperature (must be > 0) |
| `jacket_temperature` | K | yes | Initial jacket/coolant temperature |
| `volume` | m³ | no | Override for initial liquid volume |

---

## Solver Section

The simulator runs an MPC-style control loop: it solves the DAE forward over a short time horizon, accepts the result, and repeats. Solver settings control how each horizon is discretized and solved:

```yaml
solver:
  horizon: 2.0                # s, prediction window per solve
  n_finite_elements: 5        # elements per horizon
  collocation_points: 3       # Radau points per element
  solver_name: ipopt
  solver_options:
    max_iter: 1000
    tol: 1.0e-6
    mu_strategy: adaptive
    print_level: 0
```

| Field | Default | Constraint | Description |
|-------|---------|------------|-------------|
| `horizon` | 2.0 | > 0 | Look-ahead time window per solve (seconds) |
| `n_finite_elements` | 5 | >= 1 | Collocation finite elements per horizon |
| `collocation_points` | 3 | >= 1 | Radau collocation points per element |
| `solver_name` | `"ipopt"` | — | NLP solver name |
| `solver_options` | see above | — | Dict passed directly to the solver |

**Tuning guidance:**
- If the solver struggles, reduce `horizon` or increase `n_finite_elements` before loosening tolerances.
- For faster runs, try fewer `n_finite_elements` or lower `max_iter`, but watch for stability issues or noisy temperature trajectories.
- Increasing `collocation_points` beyond 3 rarely helps and can hurt robustness.

---

## Recipe Integration

Feed rates in recipes use the convention `feed_{species_name}`:

```yaml
# Recipe file
steps:
  - name: CHARGE_A
    duration: 120
    profiles:
      feed_A:           # Maps to species "A"
        type: constant
        value: 0.5      # kg/s
      jacket_temp:
        type: constant
        value: 298.15
```

---

## Conversion Variables

**Optional:** Track reaction extent separately from mass balance.

```yaml
conversion_variable: alpha
```

**When to use:**
- Kamal-Sourour model (requires conversion for autocatalytic term)
- When you want to monitor reaction progress explicitly
- Multiple independent reactions that need separate progress tracking

**When to omit:**
- Simple mass-based reactions where species mass is sufficient

---

## Batch Mode

Batch mode runs the simulation to completion without real-time pacing (offline simulation). It is controlled via environment variables or the `Settings` class:

| Setting | Default | Description |
|---------|---------|-------------|
| `REACTOR_BATCH_MODE` | `false` | Enable offline batch simulation |
| `REACTOR_BATCH_POST_RECIPE_TIME` | `60.0` | Seconds to continue simulating after recipe ends |
| `REACTOR_BATCH_STOP_CONVERSION` | `0.0` | Stop early if conversion exceeds this (0 = disabled) |
| `REACTOR_BATCH_MAX_OVERTIME` | `600.0` | Maximum seconds to run past the recipe end |

**Running batch mode:**

```bash
# CLI
reactor --batch

# Web API
POST /api/batch/run
```

Batch output includes a CSV log with dynamic columns based on species and a `BatchResult` summary with peak temperature, peak dT/dt, final conversion, and total time.

### Parametric Sweep

Sweep mode runs multiple batch simulations in parallel, varying a single parameter across a list of values. Each run gets an independent reactor model instance.

**Configuration:**

```python
from reactor.batch import SweepConfig, run_sweep
from reactor.config import Settings

results = run_sweep(
    Settings(),
    SweepConfig(
        param_path="kinetics.A2",           # dot-notation into YAML config
        values=[1e7, 5e7, 1e8, 5e8, 1e9],  # one batch per value
    ),
    max_workers=4,
)
for r in results:
    if r.result:
        print(f"A2={r.param_value:.0e}  conv={r.result.final_conversions}  peak_T={r.result.peak_temperature_K:.1f}K")
    else:
        print(f"A2={r.param_value:.0e}  FAILED: {r.error}")
```

**Common `param_path` values:**

| Path | Description |
|------|-------------|
| `kinetics.A2` | Autocatalytic pre-exponential factor (s^-1) |
| `kinetics.Ea2` | Autocatalytic activation energy (J/mol) |
| `thermal.Cp` | Specific heat capacity (kJ/kg·K) |
| `thermal.UA` | Static heat transfer coefficient (kW/K) |
| `initial_conditions.temperature` | Initial reactor temperature (K) |

**Web API:**

```bash
# Start a sweep
POST /api/sweep/run
{
  "param_path": "kinetics.A2",
  "values": [1e7, 5e7, 1e8, 5e8, 1e9],
  "max_workers": 4,
  "recipe": "default.yaml",    # optional
  "config": "default.yaml"     # optional
}

# Check status / results
GET /api/sweep/status

# Cancel a running sweep
POST /api/sweep/cancel
```

The status endpoint returns `{ "status": "running", "completed": 3, "total": 5 }` while running, and includes a `results` array with per-value batch outcomes when complete.

---

## Complete Examples

### Example 1: Simple A -> B Reaction

```yaml
reaction_network:
  species:
    - name: A
      density: 1.0
    - name: B
      density: 1.0

  reactions:
    - name: conversion
      rate_law: nth_order
      conversion_variable: alpha
      parameters:
        A: 1.0e4
        Ea: 55000.0
        n: 1.0
      stoichiometry:
        A: -1.0
        B: 1.0
      delta_H: 200.0
      heat_basis: A
```

---

### Example 2: Sequential A -> B -> C

```yaml
reaction_network:
  species:
    - name: A
      density: 1.16
    - name: B
      density: 1.10
    - name: C
      density: 1.20

  reactions:
    - name: step_1
      rate_law: nth_order
      conversion_variable: alpha_1
      parameters:
        A: 1.0e4
        Ea: 55000.0
        n: 1.5
      stoichiometry:
        A: -1.0
        B: 1.0
      delta_H: 200.0
      heat_basis: A

    - name: step_2
      rate_law: nth_order
      conversion_variable: alpha_2
      parameters:
        A: 1.0e5
        Ea: 50000.0
        n: 1.0
      stoichiometry:
        B: -1.0
        C: 1.0
      delta_H: 150.0
      heat_basis: B
```

Each step tracks its own conversion (`alpha_1`, `alpha_2`).

---

### Example 3: Parallel Competing Reactions

```yaml
reaction_network:
  species:
    - name: A
      density: 1.0
    - name: B
      density: 1.0
    - name: C
      density: 1.0

  reactions:
    - name: path_1
      rate_law: nth_order
      conversion_variable: alpha_1
      parameters: {A: 1.0e4, Ea: 55000.0, n: 1.0}
      stoichiometry:
        A: -1.0
        B: 1.0
      delta_H: 150.0
      heat_basis: A

    - name: path_2
      rate_law: nth_order
      conversion_variable: alpha_2
      parameters: {A: 5.0e3, Ea: 60000.0, n: 1.0}
      stoichiometry:
        A: -1.0
        C: 1.0
      delta_H: 100.0
      heat_basis: A
```

Both reactions consume `A`, producing either `B` or `C`. Selectivity depends on temperature (different Ea values).

---

## Tips & Best Practices

### 1. Start with Legacy Mode
Use existing `kinetics`/`physics` for the default Kamal-Sourour chemistry. Only switch to `reaction_network` mode for custom chemistry.

### 2. Mass Conservation
Stoichiometric coefficients should conserve mass:
```yaml
# Good: -1.0 + (-0.3) + 1.3 = 0
stoichiometry:
  component_a: -1.0
  component_b: -0.3
  product: 1.3
```

### 3. Temperature Units
All temperatures in Kelvin:
- Room temp: `298.15 K` (25 C)
- Cure temp: `353.15 K` (80 C)

### 4. Activation Energy
Typical ranges:
- Low barrier: `Ea = 30,000 - 50,000 J/mol`
- Medium: `Ea = 50,000 - 80,000 J/mol`
- High barrier: `Ea = 80,000 - 150,000 J/mol`

### 5. Heat of Reaction
Exothermic (heat-releasing): `delta_H > 0` (typical for polymerization)

### 6. Scientific Notation in YAML
Use explicit `+` sign for scientific notation to avoid PyYAML parsing issues:
```yaml
# Good
parameters:
  A: 1.0e+4       # Parsed as float: 10000.0
  Ea: 55000.0

# Avoid (may be parsed as string by PyYAML safe_load)
parameters:
  A: 1.0e4        # Might become string "1.0e4"
```

### 7. Reactant Depletion
The model automatically slows reactions when reactants are depleted using a smooth availability factor:
```
availability = product(m_reactant / (m_reactant + 0.001)) for all consumed species
```
No need to handle this manually.

### 8. Simulation Model Selection
Start with defaults (omit the `simulation` section). Only override when you need simplified physics (e.g., `isothermal` energy model for kinetics studies) or when debugging.

---

## Validation

The simulator validates your config at startup:
- All Pydantic constraints are checked (`Cp > 0`, `volume_m3 > 0`, etc.)
- Species names must be unique
- Reaction names must be unique
- All `heat_basis` species must exist in the species list
- All `stoichiometry` species must exist in the species list
- All selected simulation models must be registered
- Model dependencies are enforced (e.g., `dynamic` heat transfer requires `mixing.enabled: true`)

Check the log output for validation errors.

---

## Output

### CSV Logs
Dynamic columns based on species:
```
elapsed,dt,solve_method,temperature_K,...,
conversion_alpha,mass_A_kg,mass_B_kg,mass_C_kg,mass_total_kg,
feed_A_kgs,feed_B_kgs,feed_C_kgs,...
```

### Web API
`/api/state` endpoint includes:
```json
{
  "species_masses": {"A": 45.2, "B": 12.3, "C": 2.1},
  "conversions": {"alpha_1": 0.45, "alpha_2": 0.12},
  "species_names": ["A", "B", "C"],
  "conversion_names": ["alpha_1", "alpha_2"],
  ...
}
```

---

## Troubleshooting

### IPOPT solver fails
- **Symptom:** Warnings about `pow(0, n)` or solver crashes
- **Cause:** Fractional exponents with zero conversion
- **Solution:** Model automatically falls back to explicit Euler integration

### Reaction doesn't proceed
- Check that reactants are being fed via recipe
- Verify temperature is high enough for reaction
- Check stoichiometry signs (consumed = negative)

### Mass not conserved
- Verify stoichiometric coefficients sum to zero
- Check `heat_basis` species exists

### Heat transfer collapses near gel point
- **Cause:** Viscosity spike kills Reynolds number, driving UA to zero
- **Solution:** Set `min_UA_fraction` in the `mixing` section (default 0.30) to maintain a conductive floor

### Unknown model error at startup
- **Cause:** Typo in `simulation.models.*` value
- **Solution:** Check the error message for available model names

---

## See Also

- [configs/default.yaml](../configs/default.yaml) — Full-featured legacy Kamal-Sourour example
- [configs/lab_scale_reactor.yaml](../configs/lab_scale_reactor.yaml) — Lab-scale reactor with different geometry and mixing
- [recipes/default.yaml](../recipes/default.yaml) — Recipe format with staged cure profile
- [equations.md](equations.md) — Mathematical model reference
