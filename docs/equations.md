# Mathematical Model Reference

Complete equation reference for the reactor digital twin simulation. For architecture and usage, see the main [README](../README.md).

## Table of Contents

- [Governing ODEs](#governing-odes)
- [Kamal-Sourour Kinetics](#kamal-sourour-kinetics)
- [Alternative Rate Laws](#alternative-rate-laws)
- [Viscosity Model](#viscosity-model)
- [Fluid Mechanics](#fluid-mechanics)
- [Heat Transfer](#heat-transfer)
- [Vessel Geometry](#vessel-geometry)
- [Controller & Safety](#controller--safety)
- [Recipe Profiles](#recipe-profiles)
- [Auxiliary Relations](#auxiliary-relations)
- [Numerical Solver](#numerical-solver)
- [ODE → DAE Compilation & Solve Flow](#ode--dae-compilation--solve-flow)
- [Default Parameters](#default-parameters)

---

## Governing ODEs

The model integrates three coupled ODEs per reaction via Pyomo DAE with Lagrange-Radau orthogonal collocation.

### Mass Balance (per species)

```
dm_i/dt = F_i + Σⱼ(ν_ij · M_basis · r_j)
```

where:
- `m_i` — mass of species i [kg]
- `F_i` — feed rate of species i [kg/s]
- `ν_ij` — stoichiometric coefficient of species i in reaction j
- `M_basis` — basis mass for rate normalization [kg]
- `r_j` — effective reaction rate for reaction j [1/s]

*Source: `pyomo_model.py`, `physics.py` (Euler fallback)*

### Energy Balance

```
dT/dt = (Q_rxn + Q_jacket) / (m_total · Cp)
```

with:

```
Q_rxn    = Σⱼ(ΔH_j · M_basis · r_j)           reaction heat generation [kW]
Q_jacket = UA · (T_jacket − T)                  jacket heat transfer [kW]
m_total  = Σᵢ(m_i) + 0.01                       total mass (+ offset) [kg]
```

- `Cp` — specific heat capacity of mixture [kJ/(kg·K)]
- `UA` — overall heat transfer coefficient × wetted area [kW/K]
- `T_jacket` — boundary condition, held constant per solver horizon (no jacket thermal lag)

The energy model's `compute_dT_dt()` method is called in both the Pyomo DAE constraint (with symbolic expressions) and the scipy BDF fallback solver (with numeric values), ensuring the two code paths always produce consistent results.

*Source: `pyomo_model.py`, `physics.py`, `energy_models.py`*

### Conversion ODE

```
dα/dt = r_eff
```

- `α` — degree of conversion (0 → 1)
- `r_eff` — effective rate [1/s] (see below)

### Effective Rate

The effective rate applied to the conversion ODE and mass balances:

```
r_eff = r_kin · availability · η_mix
```

- `r_kin` — intrinsic kinetic rate (e.g. Kamal-Sourour)
- `availability` — reactant depletion factor (see below)
- `η_mix` — mixing efficiency (see [Fluid Mechanics](#mixing-efficiency))

### Reactant Availability

Smooth depletion cutoff applied as a multiplier on each reaction rate:

```
availability = Πₛ( m_s / (m_s + ε) )       for all consumed species s
```

`ε = 0.001 kg`. Approaches 0 smoothly as any reactant is exhausted.

*Source: `pyomo_model.py`, `reaction_network.py`*

---

## Kamal-Sourour Kinetics

Dual-mechanism autocatalytic model for curing reactions:

```
r = (k₁ + k₂ · α^m) · (1 − α)^n
```

with Arrhenius rate constants:

```
k₁ = A₁ · exp(−Ea₁ / (R·T))
k₂ = A₂ · exp(−Ea₂ / (R·T))
```

| Symbol | Description | Default |
|--------|-------------|---------|
| `A₁` | Catalytic pre-exponential factor | 1.0×10⁴ s⁻¹ |
| `Ea₁` | Catalytic activation energy | 55 kJ/mol |
| `A₂` | Autocatalytic pre-exponential factor | 1.0×10⁶ s⁻¹ |
| `Ea₂` | Autocatalytic activation energy | 45 kJ/mol |
| `m` | Autocatalytic exponent | 0.5 |
| `n` | Reaction order exponent | 1.5 |
| `ΔH` | Total heat of reaction | 350 kJ/kg |
| `α_gel` | Gel point conversion | 0.6 |
| `R` | Universal gas constant | 8.314 J/(mol·K) |

**Physical interpretation:**
- `k₁` term — initial catalytic mechanism (active at α = 0)
- `k₂ · α^m` term — autocatalytic path (accelerates with cure progress)
- `(1 − α)^n` term — reactant depletion as conversion → 1

**Heat generation rate:**

```
Q_rxn = ΔH · m_component_a · dα/dt   [kW]
```

*Source: `chemistry.py`, `reaction_network.py`*

---

## Alternative Rate Laws

The reaction network framework supports pluggable rate laws beyond Kamal-Sourour.

### Nth-Order Arrhenius

```
r = A · exp(−Ea / (R·T)) · (1 − α)^n
```

Single-path consumption model without autocatalytic term.

### Generalized Arrhenius (Mass-Action)

```
r = A · exp(−Ea / (R·T)) · Πᵢ(m_i ^ order_i)
```

Product over specified species with individual reaction orders. Used for multi-species reactions not described by a single conversion variable.

*Source: `reaction_network.py`*

---

## Viscosity Model

Temperature- and conversion-dependent viscosity with gel-point divergence.

### Base Viscosity (temperature dependence)

```
η_base = η_ref · exp(E_η / R · (1/T − 1/T_ref))
```

The temperature exponent is clamped to `[-700, 700]` to prevent overflow.

If per-species viscosities are configured, a log-mixing rule is used to
compute the reference viscosity at `T_ref`:

```
ln(η_ref) = Σᵢ(w_i · ln(η_i))
```

Species not listed in the viscosity map are excluded from the mixture.
If no valid species are present, the model falls back to `η_ref` (or `η_0`).

### Conversion Effect (gel divergence)

```
η = η_base · exp(C_visc · α / (α_gel − α))
```

The exponent is clamped so the viscosity does not exceed the gel cap:

```
max_exp  = ln(η_gel / η_base)
exponent = min(C_visc · α / (α_gel − α), max_exp)
```

At `α ≥ α_gel`, returns `η_gel` directly.

| Symbol | Description | Default |
|--------|-------------|---------|
| `η_0` | Fallback reference viscosity at T_ref | 0.5 Pa·s |
| `η_ref` | Reference viscosity at T_ref (optional) | — |
| `T_ref` | Reference temperature | 298.15 K |
| `E_η` | Viscosity activation energy | 0.0 J/mol |
| `C_visc` | Gelation shape parameter | 4.0 |
| `α_gel` | Gel point conversion | 0.6 |
| `η_gel` | Viscosity cap at gel point | 100 Pa·s |

*Source: `chemistry.py`*

---

## Fluid Mechanics

### Reynolds Number (Impeller)

```
Re = ρ · N · D² / μ
```

| Symbol | Description | Default |
|--------|-------------|---------|
| `ρ` | Fluid density | 1100 kg/m³ |
| `N` | Impeller speed | 2.0 rev/s (120 rpm) |
| `D` | Impeller diameter | 0.16 m |
| `μ` | Dynamic viscosity | (from viscosity model) |

**Flow regime classification:**

| Regime | Condition |
|--------|-----------|
| Laminar | Re < 10 |
| Transitional | 10 ≤ Re < 10,000 |
| Turbulent | Re ≥ 10,000 |

### Prandtl Number

```
Pr = Cp · μ / k_f
```

### Mixing Efficiency

Logistic transition from laminar to turbulent mixing:

```
η_mix = η_min + (1 − η_min) · σ(x)

x    = steepness · (log₁₀(Re) − log₁₀(Re_turb) + 1)
σ(x) = 1 / (1 + exp(−x))
```

The `+1` shift in log-space centers the transition around `Re_turb / 10`.

| Symbol | Description | Default |
|--------|-------------|---------|
| `η_min` | Minimum mixing efficiency | 0.20 |
| `Re_turb` | Turbulent transition Re | 10,000 |
| `steepness` | Transition sharpness | 2.5 |

### Power Draw

```
P = Np · ρ · N³ · D⁵   [W]
```

| Symbol | Description | Default |
|--------|-------------|---------|
| `Np` | Power number (Rushton turbine) | 5.0 |

*Source: `fluid_mechanics.py`*

---

## Heat Transfer

### Nusselt Number (Chilton-Drew-Jebens Correlation)

```
Nu = C · Re^a · Pr^b · (μ_bulk / μ_wall)^0.14
```

| Symbol | Description | Default |
|--------|-------------|---------|
| `C` | Correlation constant (Rushton turbine) | 0.36 |
| `a` | Reynolds exponent | 2/3 |
| `b` | Prandtl exponent | 1/3 |
| `μ_bulk/μ_wall` | Viscosity ratio | 1.0 |

### Inside (Process-Side) Heat Transfer Coefficient

```
h_i = Nu · k_f / D_tank   [W/(m²·K)]
```

### Overall Heat Transfer Coefficient

Series thermal resistances through the wall:

```
1/U = 1/h_i + t_w/k_w + 1/h_j
```

| Symbol | Description | Default |
|--------|-------------|---------|
| `h_i` | Inside HTC | (calculated) |
| `t_w` | Wall thickness | 0.005 m |
| `k_w` | Wall conductivity (SS304) | 16.0 W/(m·K) |
| `h_j` | Jacket-side HTC | 1000 W/(m²·K) |

### Dynamic UA

```
UA = U · A_wetted   [kW/K]
```

A minimum floor prevents heat transfer collapse at high viscosity:

```
UA_eff = max(UA_dynamic, f_min · UA_static)
```

where `f_min = 0.30` (default).

*Source: `fluid_mechanics.py`, `physics.py`*

---

## Vessel Geometry

### Cylindrical Flat-Bottom Vessel

```
V       = π · r² · h            [m³]
A_cross = π · r²                [m²]
h_liq   = V_liquid / A_cross    [m]
A_wet   = π·r² + π·D·h_liq     [m²]   (bottom + wall)
```

Default dimensions: D = 0.50 m, H = 0.60 m

### Torispherical Head (ASME F&D)

```
depth  ≈ 0.1935 · D    [m]
V_head ≈ 0.0847 · D³   [m³]
A_head ≈ 0.9314 · D²   [m²]
```

**Liquid level:**
- If `V_liquid ≤ V_head`: `h = (V_liquid / V_head) · depth`
- If `V_liquid > V_head`: `h = depth + (V_liquid − V_head) / A_cross`

**Total vessel volume:**

```
V_total = π · r² · h_cyl + V_head   [m³]
```

*Source: `geometry.py`*

---

## Controller & Safety

### Thermal Runaway Detection

Rate of temperature rise estimated via finite difference over a sliding window:

```
dT/dt ≈ (T[k] − T[k−N]) / (N · Δt)
```

Runaway is triggered when either condition is met:

```
T > T_runaway   or   dT/dt > (dT/dt)_max
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `T_runaway` | 473.15 K | Absolute temperature limit |
| `(dT/dt)_max` | 2.0 K/s | Rate-of-rise limit |
| `N` | 10 samples | Sliding window size |
| `α_done` | 0.95 | Conversion completion threshold |
| `T_cure` | 353.15 K | Cure temperature setpoint |
| `T_cool_done` | 313.15 K | Cooldown completion temperature |

*Source: `controller.py`*

---

## Recipe Profiles

Setpoint profile generators used in batch recipe steps.

### Constant

```
f(t) = c
```

### Linear Ramp

```
f(t) = v_start + (v_end − v_start) · t / t_dur
```

### Exponential Ramp

```
f(t) = v_start · (v_end / v_start) ^ (t / t_dur)
```

Valid only when `v_start > 0` and `v_end > 0`; falls back to linear ramp otherwise.

### Sensor Noise Model

```
v_noisy = v + 𝒩(0, σ)       σ = |v| · noise_pct / 100
```

Gaussian noise proportional to reading magnitude (default `noise_pct = 0.5%`).

*Source: `recipe.py`, `physics.py`*

---

## Auxiliary Relations

### Pressure

```
P = 0.5 bar   (constant)
```

### Liquid Volume

```
V = Σᵢ(m_i / ρ_i)   [L]
```

### Fill Percentage

```
fill% = min(100, V / V_vessel · 100)
```

### Bulk Density

```
ρ_bulk = m_total / V   [kg/m³]
```

Fallback: 1100 kg/m³ when volume is zero.

### Species Densities

| Species | Density |
|---------|--------:|
| Component A | 1.16 kg/L |
| Component B | 0.97 kg/L |
| Product | 1.20 kg/L |
| Solvent | 0.87 kg/L |

*Source: `physics.py`, `reaction_network.py`*

---

## Numerical Solver

### Pyomo DAE Discretization

| Parameter | Default |
|-----------|---------|
| Horizon | 2.0 s |
| Finite elements | 5 |
| Collocation points | 3 (Legendre) |
| Solver | IPOPT |
| Max iterations | 1000 |
| Tolerance | 1.0×10⁻⁶ |
| Barrier strategy | adaptive |

### Adaptive Sub-Stepping

If IPOPT fails on a horizon, the time step is halved recursively up to 64 divisions. If all sub-steps fail, an explicit Euler step is used as fallback.

### Numerical Safeguards

| Guard | Value |
|-------|-------|
| Conversion variable bounds | [1×10⁻⁸, 1.0] |
| Reactant availability ε | 0.001 kg |
| Default basis mass | 0.01 kg |
| Minimum temperature | 200 K |
| Total mass offset | +0.01 kg |
| Minimum UA fraction | 0.30 |
| Viscosity exponent clamp | [-700, 700] |

*Source: `physics.py`, `pyomo_model.py`, `config.py`*

---

## ODE → DAE Compilation & Solve Flow

This section shows how the continuous-time ODE model is transcribed into a finite NLP and solved each simulation step.

### 1) Continuous ODE form (model level)

For state

```
x(t) = [m_1, ..., m_ns, T, α_1, ..., α_nc]
```

the simulator defines first-order dynamics:

```
dm_i/dt = f_m,i(x, u, p)
dT/dt   = f_T(x, u, p)
dα_k/dt = f_α,k(x, u, p)
```

where `u` includes feed rates and jacket temperature, and `p` includes kinetic/thermal/mixing parameters.

### 2) DAE residual form in Pyomo

Pyomo introduces derivative variables (`DerivativeVar`) and enforces residual constraints at all interior time points (`t > 0`):

```
R_m,i(t) = dmass_i/dt - f_m,i(...) = 0
R_T(t)   = dT/dt      - f_T(...)   = 0
R_α,k(t) = dα_k/dt    - f_α,k(...) = 0
```

Initial conditions are enforced by fixing state variables at `t = 0`:

```
m_i(0) = m_i,0
T(0)   = T_0
α_k(0) = α_k,0
```

Notes from implementation:
- Time domain: `ContinuousSet(bounds=(0, t_horizon))`
- Mass and conversion derivatives: `DerivativeVar(m.mass, wrt=m.t)`, `DerivativeVar(m.conv, wrt=m.t)`
- The energy ODE constraint delegates to `energy_model.compute_dT_dt()` with Pyomo symbolic expressions as arguments. The `compute_dT_dt()` method accepts both numeric floats and Pyomo expressions, so the same code path is used by both the DAE constraint and the scipy fallback solver. `isothermal` returns 0, `adiabatic` omits `Q_jacket`, `full` includes both terms, `extended` adds frictional heating. Custom energy models registered at runtime are also supported.

### 3) Compilation (transcription) to algebraic NLP

After symbolic model assembly, the DAE is discretized with Lagrange-Radau orthogonal collocation:

```
TransformationFactory("dae.collocation").apply_to(
	m, nfe=n_finite_elements, ncp=collocation_points, scheme="LAGRANGE-RADAU"
)
```

This replaces differential equations with algebraic collocation equations over each finite element, yielding a square feasibility NLP (same number of equations as unknowns; objective = 0, so IPOPT only needs to find a feasible point).

### 4) Solve and acceptance logic per step

Each simulator call to `step(dt)` runs this pipeline:

1. Update fluid mechanics / dynamic `UA` / mixing efficiency. These values are computed from the current state and injected as constant `Param` objects into the Pyomo model — they do not vary within the horizon.
2. Build horizon model for candidate step size.
3. Solve NLP with IPOPT (`load_solutions=False`; load only on optimal termination).
4. If solve is non-optimal, halve horizon and retry.
5. On success at a reduced sub-step, accept the state and restart with the full remaining time (optimistic retry), not the halved step size.
6. Continue until success or minimum sub-step (`dt / 64`).
7. If all retries fail, execute explicit Euler fallback for remaining time.

Equivalent control flow:

```
remaining = dt
while remaining > min_dt / 2:          # guard against float boundary
	attempt = remaining
	while attempt > min_dt / 2:
		if solve_pyomo(attempt) == optimal:
			accept_state()
			remaining -= attempt
			break
		attempt /= 2
	else:                               # all halvings exhausted
		euler_fallback(remaining)
		break
```

*Source: `pyomo_model.py` (`build_reactor_model_from_network`, `solve_model`), `physics.py` (`_solve_horizon`, `step`, `_fallback_step`)*

---

## Default Parameters

### Thermal Properties

| Parameter | Value | Unit |
|-----------|------:|------|
| Cp | 1.8 | kJ/(kg·K) |
| UA (static) | 0.5 | kW/K |
| Fluid thermal conductivity | 0.17 | W/(m·K) |
| Max temperature | 500 | K |

### Agitator

| Parameter | Value | Unit |
|-----------|------:|------|
| Impeller diameter | 0.16 | m |
| Speed | 120 | rpm |
| Blades | 6 | — |
| Power number (Rushton) | 5.0 | — |

### Stoichiometry

| Parameter | Value |
|-----------|------:|
| Stoichiometric ratio (component_b:component_a) | 0.3 |
| Basis mass | 0.01 kg |
