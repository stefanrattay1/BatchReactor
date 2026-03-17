"""Pyomo DAE model builder for the batch reactor."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pyomo.environ as pyo
from pyomo.dae import ContinuousSet, DerivativeVar

if TYPE_CHECKING:
    from .energy_models import EnergyModel
    from .reaction_network import ReactionNetwork

from .reaction_network import MathOps


def _ensure_ipopt_on_path() -> None:
    """Add IDAES bin directory to PATH if IPOPT lives there."""
    idaes_bin = Path.home() / ".idaes" / "bin"
    if idaes_bin.exists() and str(idaes_bin) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(idaes_bin) + os.pathsep + os.environ.get("PATH", "")


# ---------------------------------------------------------------------------
# Helper functions for model construction
# ---------------------------------------------------------------------------


def _build_time_and_parameters(
    m: pyo.ConcreteModel,
    t_horizon: float,
    thermal: dict,
    physics: dict,
    jacket_T: float,
    mixing_efficiency: float | None,
    UA_dynamic_kW_K: float | None,
    Q_frictional_kW: float = 0.0,
    min_mass_kg: float = 0.01,
) -> None:
    """Build time set and model parameters."""
    # Normalized time [0, 1]; real time recovered via mutable time_factor
    m.t = ContinuousSet(bounds=(0, 1.0))
    m.time_factor = pyo.Param(initialize=t_horizon, mutable=True)

    # Thermal parameters (mutable for model reuse between steps)
    m.Cp = pyo.Param(initialize=thermal["Cp"], mutable=True)
    _effective_UA = UA_dynamic_kW_K if UA_dynamic_kW_K is not None else thermal["UA"]
    m.UA = pyo.Param(initialize=_effective_UA, mutable=True)
    m.T_jacket = pyo.Param(initialize=jacket_T, mutable=True)
    m.max_temp = pyo.Param(initialize=physics.get("max_temp", 500.0))

    # Mixing efficiency (mutable)
    _eta_mix = mixing_efficiency if mixing_efficiency is not None else 1.0
    m.mixing_efficiency = pyo.Param(initialize=max(min(_eta_mix, 1.0), 0.0), mutable=True)

    # Frictional heating from agitator (kW, mutable)
    m.Q_frictional = pyo.Param(initialize=Q_frictional_kW, mutable=True)

    # Minimum mass floor to prevent division by zero (kg)
    m.min_mass = pyo.Param(initialize=min_mass_kg, mutable=True)


def _build_species_variables(
    m: pyo.ConcreteModel,
    network: "ReactionNetwork",
    initial_state,
    feed_rates: dict[str, float],
    initial_masses: dict[str, float],
) -> None:
    """Build species mass variables and parameters."""
    species_names = network.species_names
    m.species_set = pyo.Set(initialize=species_names)

    # Feed rates and basis masses
    m.feed = pyo.Param(m.species_set, initialize={
        s: feed_rates.get(s, 0.0) for s in species_names
    }, mutable=True)
    m.basis_mass = pyo.Param(m.species_set, initialize={
        s: max(initial_masses.get(s, 0.01), pyo.value(m.min_mass)) for s in species_names
    }, mutable=True)

    # Species mass variables and derivatives
    def _init_mass(m, s, t):
        return initial_state.species_masses.get(s, 0.0)

    m.mass = pyo.Var(m.species_set, m.t, within=pyo.NonNegativeReals, initialize=_init_mass)
    m.dmass_dt = DerivativeVar(m.mass, wrt=m.t)


def _build_temperature_variables(
    m: pyo.ConcreteModel,
    physics: dict,
    initial_state,
) -> None:
    """Build temperature variable and derivative."""
    m.T = pyo.Var(
        m.t,
        bounds=(200, physics.get("max_temp", 500.0)),
        initialize=initial_state.temperature,
    )
    m.dT_dt = DerivativeVar(m.T, wrt=m.t)


def _build_conversion_variables(
    m: pyo.ConcreteModel,
    network: "ReactionNetwork",
    initial_state,
) -> None:
    """Build conversion variables (if present)."""
    conv_names = network.conversion_names
    if not conv_names:
        return

    m.conv_set = pyo.Set(initialize=conv_names)

    def _init_conv(m, c, t):
        return max(initial_state.conversions.get(c, 0.0), 1e-8)

    m.conv = pyo.Var(m.conv_set, m.t, bounds=(1e-8, 1.0), initialize=_init_conv)
    m.dconv_dt = DerivativeVar(m.conv, wrt=m.t)


def _build_reaction_rates(
    m: pyo.ConcreteModel,
    network: "ReactionNetwork",
    ops: MathOps,
) -> None:
    """Build reaction rate expressions (raw, availability, effective)."""
    species_names = network.species_names
    conv_names = network.conversion_names
    rxn_names = [rxn.name for rxn in network.reactions]
    m.rxn_set = pyo.Set(initialize=rxn_names)

    # Map reactions by name for quick lookup
    _rxn_by_name = {rxn.name: rxn for rxn in network.reactions}

    # Raw rate expressions
    def _rate_raw_rule(m, rxn_name, t):
        rxn = _rxn_by_name[rxn_name]
        sp_masses = {s: m.mass[s, t] for s in species_names}
        convs = {}
        if conv_names:
            convs = {c: m.conv[c, t] for c in conv_names}
        return rxn.rate_law.evaluate(sp_masses, convs, m.T[t], rxn.parameters, ops)

    m.rate_raw = pyo.Expression(m.rxn_set, m.t, rule=_rate_raw_rule)

    # Availability expressions
    def _availability_rule(m, rxn_name, t):
        rxn = _rxn_by_name[rxn_name]
        eps = 0.001  # kg, sub-gram threshold
        avail = 1.0
        for sp_name in rxn.consumed_species:
            avail = avail * (m.mass[sp_name, t] / (m.mass[sp_name, t] + eps))
        return avail

    m.availability = pyo.Expression(m.rxn_set, m.t, rule=_availability_rule)

    # Effective rates (with availability and mixing efficiency)
    def _rate_rule(m, rxn_name, t):
        return m.rate_raw[rxn_name, t] * m.availability[rxn_name, t] * m.mixing_efficiency

    m.rate = pyo.Expression(m.rxn_set, m.t, rule=_rate_rule)


def _build_energy_expressions(
    m: pyo.ConcreteModel,
    network: "ReactionNetwork",
    species_names: list[str],
) -> None:
    """Build energy-related expressions (total mass, heat of reaction, jacket heat)."""
    # Total mass
    @m.Expression(m.t)
    def m_total(m, t):
        return sum(m.mass[s, t] for s in species_names) + m.min_mass

    # Heat generation from all reactions
    @m.Expression(m.t)
    def Q_rxn(m, t):
        total = 0.0
        for rxn in network.reactions:
            basis_sp = rxn.heat_basis
            basis = m.basis_mass[basis_sp] if basis_sp else m.min_mass
            total = total + rxn.delta_H * basis * m.rate[rxn.name, t]
        return total

    # Heat transfer from jacket
    @m.Expression(m.t)
    def Q_jacket(m, t):
        return m.UA * (m.T_jacket - m.T[t])


def _build_mass_balance_ode(
    m: pyo.ConcreteModel,
    network: "ReactionNetwork",
    species_names: list[str],
) -> None:
    """Build mass balance ODE constraints."""
    def _mass_ode_rule(m, s, t):
        if t == 0:
            return pyo.Constraint.Skip
        # dm_s/dt = feed_s + sum(stoich_coeff * basis_mass * rate)
        rhs = m.feed[s]
        for rxn in network.reactions:
            coeff = rxn.stoichiometry.get(s, 0.0)
            if coeff != 0.0:
                basis_sp = rxn.heat_basis
                basis = m.basis_mass[basis_sp] if basis_sp else m.min_mass
                rhs = rhs + coeff * basis * m.rate[rxn.name, t]
        return m.dmass_dt[s, t] == m.time_factor * rhs

    m.mass_ode = pyo.Constraint(m.species_set, m.t, rule=_mass_ode_rule)


def _build_conversion_ode(
    m: pyo.ConcreteModel,
    network: "ReactionNetwork",
) -> None:
    """Build conversion variable ODE constraints."""
    conv_names = network.conversion_names
    if not conv_names:
        return

    def _conv_ode_rule(m, c, t):
        if t == 0:
            return pyo.Constraint.Skip
        # dconv/dt = sum of rates for reactions tracking this conversion
        rhs = 0.0
        for rxn in network.reactions:
            if rxn.conversion_variable == c:
                rhs = rhs + m.rate[rxn.name, t]
        return m.dconv_dt[c, t] == m.time_factor * rhs

    m.conv_ode = pyo.Constraint(m.conv_set, m.t, rule=_conv_ode_rule)


def _build_energy_ode(
    m: pyo.ConcreteModel,
    energy_model: "EnergyModel | None" = None,
) -> None:
    """Build energy balance ODE constraint delegating to the energy model.

    The energy model's compute_dT_dt() is called with Pyomo symbolic expressions,
    keeping the same computation path used by the scipy fallback solver.
    This ensures Pyomo and fallback produce consistent results for all model types,
    including custom models registered at runtime.

    Args:
        m: Pyomo model with Q_rxn, Q_jacket, Q_frictional, m_total, Cp already built.
        energy_model: Selected energy model instance. If None, uses FullEnergyModel.
    """
    from .energy_models import FullEnergyModel

    _model = energy_model if energy_model is not None else FullEnergyModel()

    @m.Constraint(m.t)
    def energy_ode(m, t):
        if t == 0:
            return pyo.Constraint.Skip
        dT_dt_rhs = _model.compute_dT_dt(
            m.Q_rxn[t], m.Q_jacket[t], m.Q_frictional, m.m_total[t], m.Cp
        )
        return m.dT_dt[t] == m.time_factor * dT_dt_rhs


def _setup_initial_conditions(
    m: pyo.ConcreteModel,
    network: "ReactionNetwork",
    initial_state,
) -> None:
    """Fix initial condition values."""
    # Fix initial species masses
    for s in network.species_names:
        m.mass[s, 0].fix(initial_state.species_masses.get(s, 0.0))

    # Fix initial temperature
    m.T[0].fix(initial_state.temperature)

    # Fix initial conversions (if present)
    conv_names = network.conversion_names
    if conv_names:
        for c in conv_names:
            m.conv[c, 0].fix(max(initial_state.conversions.get(c, 0.0), 1e-8))


# ---------------------------------------------------------------------------
# Generic network-based model builder
# ---------------------------------------------------------------------------


def build_reactor_model_from_network(
    t_horizon: float,
    n_fe: int,
    n_cp: int,
    network: "ReactionNetwork",
    initial_state,  # ReactorState
    feed_rates: dict[str, float],
    jacket_T: float,
    initial_masses: dict[str, float],
    thermal: dict,
    physics: dict,
    *,
    mixing_efficiency: float | None = None,
    UA_dynamic_kW_K: float | None = None,
    energy_model: "EnergyModel | None" = None,
    Q_frictional_kW: float = 0.0,
    min_mass_kg: float = 0.01,
) -> pyo.ConcreteModel:
    """Build and discretize a Pyomo DAE model from a ReactionNetwork.

    This is the generic builder that supports arbitrary species and reactions
    with pluggable energy balance models.

    Args:
        t_horizon: Time horizon in seconds.
        n_fe: Number of finite elements for collocation.
        n_cp: Number of collocation points per element.
        network: ReactionNetwork defining species and reactions.
        initial_state: ReactorState with current species_masses, conversions, temperature.
        feed_rates: Dict of species_name -> feed rate (kg/s).
        jacket_T: Jacket temperature in K (constant over horizon).
        initial_masses: Initial masses for heat-of-reaction basis (kg per species).
        thermal: Thermal parameters dict (Cp, UA).
        physics: Physics constants dict (max_temp, R_gas).
        mixing_efficiency: Optional 0-1 factor to scale reaction rates.
            When None or 1.0, rates are not modified (ideal mixing).
            Computed by the fluid_mechanics module from Reynolds number.
        UA_dynamic_kW_K: Optional dynamic UA in kW/K computed from
            geometry + fluid mechanics.  When None, falls back to the
            constant ``thermal["UA"]``.
        energy_model: Optional EnergyModel instance controlling the
            energy balance constraint structure. When None, uses full
            energy balance (Q_rxn + Q_jacket).
        Q_frictional_kW: Frictional heating from agitator in kW (used
            by ExtendedEnergyModel). Defaults to 0.0.

    Returns:
        Discretized ConcreteModel ready for solving.
    """
    m = pyo.ConcreteModel()
    ops = MathOps.pyomo()

    # Build model in logical sections
    _build_time_and_parameters(
        m, t_horizon, thermal, physics, jacket_T,
        mixing_efficiency, UA_dynamic_kW_K, Q_frictional_kW, min_mass_kg,
    )
    _build_species_variables(m, network, initial_state, feed_rates, initial_masses)
    _build_temperature_variables(m, physics, initial_state)
    _build_conversion_variables(m, network, initial_state)

    # Get species names for later use
    species_names = network.species_names

    _build_reaction_rates(m, network, ops)
    _build_energy_expressions(m, network, species_names)
    _build_mass_balance_ode(m, network, species_names)
    _build_conversion_ode(m, network)
    _build_energy_ode(m, energy_model=energy_model)

    # Setup and discretize
    _setup_initial_conditions(m, network, initial_state)

    # --- Dummy objective (square system, feasibility) ---
    m.obj = pyo.Objective(expr=0)

    # --- Discretize ---
    discretizer = pyo.TransformationFactory("dae.collocation")
    discretizer.apply_to(m, nfe=n_fe, ncp=n_cp, scheme="LAGRANGE-RADAU")

    return m


def update_reactor_model(
    model: pyo.ConcreteModel,
    network: "ReactionNetwork",
    initial_state,
    feed_rates: dict[str, float],
    jacket_T: float,
    initial_masses: dict[str, float],
    thermal: dict,
    t_horizon: float,
    *,
    mixing_efficiency: float | None = None,
    UA_dynamic_kW_K: float | None = None,
    Q_frictional_kW: float = 0.0,
) -> None:
    """Update mutable parameters and initial conditions on a persistent model.

    Avoids rebuilding model structure, discretization, and constraint
    generation.  Only scalar parameter values and fixed-variable values
    are changed.
    """
    # Time scaling
    model.time_factor.set_value(t_horizon)

    # Thermal parameters
    model.Cp.set_value(thermal["Cp"])
    _effective_UA = UA_dynamic_kW_K if UA_dynamic_kW_K is not None else thermal["UA"]
    model.UA.set_value(_effective_UA)
    model.T_jacket.set_value(jacket_T)

    # Mixing and frictional heating
    _eta_mix = mixing_efficiency if mixing_efficiency is not None else 1.0
    model.mixing_efficiency.set_value(max(min(_eta_mix, 1.0), 0.0))
    model.Q_frictional.set_value(Q_frictional_kW)

    # Feed rates and basis masses
    min_m = pyo.value(model.min_mass)
    for s in network.species_names:
        model.feed[s].set_value(feed_rates.get(s, 0.0))
        model.basis_mass[s].set_value(max(initial_masses.get(s, min_m), min_m))

    # Re-fix initial conditions at t=0
    for s in network.species_names:
        model.mass[s, 0].fix(initial_state.species_masses.get(s, 0.0))

    model.T[0].fix(initial_state.temperature)

    if hasattr(model, 'conv_set'):
        for c in network.conversion_names:
            model.conv[c, 0].fix(max(initial_state.conversions.get(c, 0.0), 1e-8))


def extract_final_state_from_network(
    model: pyo.ConcreteModel,
    network: "ReactionNetwork",
) -> dict:
    """Extract state values at the final time point for a network-based model.

    Returns dict with keys: species_masses, conversions, T.
    """
    t_final = max(model.t)

    species_masses = {}
    for s in network.species_names:
        species_masses[s] = max(pyo.value(model.mass[s, t_final]), 0.0)

    conversions = {}
    for c in network.conversion_names:
        val = pyo.value(model.conv[c, t_final])
        conversions[c] = min(max(val, 0.0), 1.0)

    return {
        "species_masses": species_masses,
        "conversions": conversions,
        "T": pyo.value(model.T[t_final]),
    }


def solve_model(
    model: pyo.ConcreteModel,
    solver_name: str = "ipopt",
    solver_options: dict | None = None,
) -> pyo.SolverResults:
    """Solve a discretized Pyomo model.

    Uses load_solutions=False so that solver failures don't raise
    ValueError.  Solutions are loaded manually on success.
    """
    _ensure_ipopt_on_path()
    solver = pyo.SolverFactory(solver_name)
    opts = solver_options or {}
    for k, v in opts.items():
        solver.options[k] = v
    result = solver.solve(model, tee=False, load_solutions=False)

    from pyomo.environ import TerminationCondition
    if result.solver.termination_condition == TerminationCondition.optimal:
        model.solutions.load_from(result)

    return result
