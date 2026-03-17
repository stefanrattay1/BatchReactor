"""Reactor physics model with Pyomo DAE integrator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .chemistry import (
    KineticParams,
    ThermalParams,
    ViscosityParams,
)
from .config import ModelConfig
from .fluid_mechanics import (
    AgitatorParams,
    FluidMechanicsState,
    FluidProps,
    compute_fluid_mechanics,
)
from .geometry import ReactorGeometry, build_geometry
from .pyomo_model import (
    build_reactor_model_from_network,
    extract_final_state_from_network,
    solve_model,
    update_reactor_model,
)
from .reaction_network import (
    MathOps,
    ReactionNetwork,
    build_legacy_network,
    build_network_from_config,
)

logger = logging.getLogger("reactor.physics")

# --- Numerical and stability constants ---
# Solver adaptive sub-stepping
MAX_SUBSTEP_DIVISIONS = 64  # Maximum dt halving iterations before giving up

# Numerical stability thresholds
REACTANT_AVAILABILITY_EPS_KG = 0.001  # Sub-gram threshold for smooth reactant depletion cutoff
DEFAULT_BASIS_MASS_KG = 0.01  # Fallback when initial masses not explicitly set
MIN_TEMPERATURE_K = 200.0  # Absolute floor for temperature bounds (safety)

# Legacy species names in canonical order (for to_array/from_array compat)
_LEGACY_SPECIES = ["component_a", "component_b", "product", "solvent"]
_LEGACY_CONVERSIONS = ["alpha"]


class SolverStatus(Enum):
    """Status of a solver attempt."""

    SUCCESS = "success"  # Successfully converged
    FAILED_CONVERGENCE = "failed_convergence"  # Solver ran but didn't converge
    FAILED_EXCEPTION = "failed_exception"  # Solver crashed with exception


@dataclass
class SolverResult:
    """Result of a solver attempt."""

    status: SolverStatus
    state: dict | None  # Final state dict if status == SUCCESS, else None
    message: str = ""  # Error message or solver info


@dataclass
class ReactorState:
    """Snapshot of the reactor at a given instant.

    Species are tracked via ``species_masses`` (dict) and ``conversions``
    (dict).  The ``conversion`` property is a read-only shorthand for the
    first conversion value (convenience for single-conversion systems).
    """

    species_masses: dict[str, float] = field(default_factory=dict)
    conversions: dict[str, float] = field(default_factory=dict)
    temperature: float = 298.15          # K
    jacket_temperature: float = 298.15   # K
    volume: float = 0.1                  # m^3 (fixed vessel volume)

    def __init__(
        self,
        *,
        species_masses: dict[str, float] | None = None,
        conversions: dict[str, float] | None = None,
        temperature: float = 298.15,
        jacket_temperature: float = 298.15,
        volume: float = 0.1,
    ):
        self.temperature = temperature
        self.jacket_temperature = jacket_temperature
        self.volume = volume
        self.species_masses = dict(species_masses) if species_masses is not None else {}
        self.conversions = dict(conversions) if conversions is not None else {}

    @property
    def conversion(self) -> float:
        """First conversion value (convenience for single-conversion systems)."""
        if not self.conversions:
            return 0.0
        return next(iter(self.conversions.values()))

    @property
    def mass_total(self) -> float:
        return sum(self.species_masses.values())

    def to_array(
        self,
        species_order: list[str] | None = None,
        conversion_order: list[str] | None = None,
    ) -> np.ndarray:
        """Serialize state to a numpy array.

        Default ordering is legacy: [component_a, component_b, product, solvent, T, alpha].
        """
        sp_order = species_order or _LEGACY_SPECIES
        cv_order = conversion_order or _LEGACY_CONVERSIONS
        masses = [self.species_masses.get(s, 0.0) for s in sp_order]
        convs = [self.conversions.get(c, 0.0) for c in cv_order]
        return np.array(masses + [self.temperature] + convs)

    @classmethod
    def from_array(
        cls,
        y: np.ndarray,
        jacket_T: float,
        volume: float,
        species_order: list[str] | None = None,
        conversion_order: list[str] | None = None,
    ) -> ReactorState:
        """Deserialize state from a numpy array."""
        sp_order = species_order or _LEGACY_SPECIES
        cv_order = conversion_order or _LEGACY_CONVERSIONS
        n_sp = len(sp_order)
        species_masses = {sp_order[i]: float(y[i]) for i in range(n_sp)}
        temperature = float(y[n_sp])
        conversions = {cv_order[i]: float(y[n_sp + 1 + i]) for i in range(len(cv_order))}
        return cls(
            species_masses=species_masses,
            conversions=conversions,
            temperature=temperature,
            jacket_temperature=jacket_T,
            volume=volume,
        )


class ReactorModel:
    """Batch reactor physics model driven by Pyomo DAE integration."""

    def __init__(
        self,
        model_config: ModelConfig | None = None,
        initial_state: ReactorState | None = None,
        kinetics: KineticParams | None = None,
        thermal: ThermalParams | None = None,
        visc_params: ViscosityParams | None = None,
    ):
        if model_config is not None:
            self._initialize_from_config(model_config)
        else:
            self._cfg = None
            self.kinetics = kinetics or KineticParams()
            self.thermal = thermal or ThermalParams()
            self.visc_params = visc_params or ViscosityParams()
            self._solver_cfg = {
                "horizon": 2.0,
                "n_finite_elements": 5,
                "collocation_points": 3,
                "solver_name": "ipopt",
                "solver_options": {"max_iter": 1000, "tol": 1e-6, "mu_strategy": "adaptive", "print_level": 0},
            }
            self._physics_cfg = {
                "stoich_ratio": 0.3,
                "max_temp": 500.0,
                "R_gas": 8.314,
            }
            self._reactor_cfg = {
                "volume_m3": 0.1,
                "vessel_volume_L": 100.0,
                "pressure_bar": 0.5,
                "agitator_speed_rpm": 120,
            }
            # Build kinetics/thermal dicts from dataclass fields
            self._kinetics_cfg = {
                f: getattr(self.kinetics, f) for f in KineticParams.__dataclass_fields__
            }
            self._thermal_cfg = {
                f: getattr(self.thermal, f) for f in ThermalParams.__dataclass_fields__
            }
            self._network = build_legacy_network(self._kinetics_cfg, self._physics_cfg)

            # Numerical stability defaults (legacy mode)
            self._numerics_cfg = {
                "min_mass_kg": DEFAULT_BASIS_MASS_KG,
                "reactant_eps_kg": REACTANT_AVAILABILITY_EPS_KG,
                "min_temperature_K": MIN_TEMPERATURE_K,
            }

        self.state = initial_state or ReactorState()

        # Feed rates as a dict keyed by species name
        self._feed_rates: dict[str, float] = {s: 0.0 for s in self._network.species_names}

        # Track initial masses for heat-of-reaction basis
        self._initial_masses: dict[str, float] | None = None
        self._initial_masses_locked = False

        # Track which solver was used in the last step
        self.last_solve_method: str = "none"

        # --- Geometry (optional, modular) ---
        self._setup_geometry_and_mixing(model_config)

        # --- Physics models (modular) ---
        self._build_physics_models(model_config)

        # Latest fluid-mechanics snapshot (updated each step)
        self._fm_state: FluidMechanicsState | None = None

        # Persistent Pyomo model (built lazily on first step, reused thereafter)
        self._pyomo_model = None

    def _initialize_from_config(self, model_config: ModelConfig) -> None:
        """Extract config and build network from ModelConfig.

        Common initialization logic used by both __init__ and reinitialize.
        """
        self._cfg = model_config
        self.kinetics = KineticParams.from_dict(model_config.kinetics)
        self.thermal = ThermalParams.from_dict(model_config.thermal)
        self.visc_params = ViscosityParams.from_dict(model_config.viscosity)
        self._solver_cfg = model_config.solver
        self._physics_cfg = model_config.physics
        self._reactor_cfg = model_config.reactor
        self._kinetics_cfg = model_config.kinetics
        self._thermal_cfg = model_config.thermal
        self._network = build_network_from_config(model_config)
        self._numerics_cfg = model_config.numerics

    def _setup_geometry_and_mixing(self, model_config: ModelConfig | None) -> None:
        """Setup geometry and mixing subsystems (optional, modular).

        Common logic used by both __init__ and reinitialize.
        """
        # --- Geometry (optional, modular) ---
        geo_cfg = model_config.geometry if model_config is not None else {}
        self._geometry: ReactorGeometry | None = build_geometry(geo_cfg) if geo_cfg else None

        # --- Mixing / fluid mechanics (optional, modular) ---
        mixing_cfg = model_config.mixing if model_config is not None else {}
        self._mixing_enabled = bool(mixing_cfg.get("enabled", False))
        if self._mixing_enabled:
            rpm = self._reactor_cfg.get("agitator_speed_rpm", 120.0)
            self._agitator = AgitatorParams(
                diameter_m=mixing_cfg.get("impeller_diameter_m", 0.16),
                speed_rpm=rpm,
                power_number=mixing_cfg.get("power_number", 5.0),
                impeller_type=mixing_cfg.get("impeller_type", "rushton"),
                n_blades=mixing_cfg.get("n_blades", 6),
            )
            self._wall_thickness = mixing_cfg.get("wall_thickness_m", 0.005)
            self._wall_conductivity = mixing_cfg.get("wall_conductivity", 16.0)
            self._h_jacket = mixing_cfg.get("h_jacket", 1000.0)
            self._fluid_k = mixing_cfg.get("fluid_thermal_conductivity", 0.17)
            self._min_UA_fraction = mixing_cfg.get("min_UA_fraction", 0.3)
        else:
            self._agitator = None
            self._wall_thickness = 0.005
            self._wall_conductivity = 16.0
            self._h_jacket = 1000.0
            self._fluid_k = 0.17
            self._min_UA_fraction = 0.0

    def _build_physics_models(self, model_config: ModelConfig | None) -> None:
        """Build pluggable physics model instances from config.

        Instantiates viscosity, heat transfer, mixing, and energy models
        based on configuration. Falls back to full-fidelity models if no
        config provided (legacy mode).

        Common logic used by both __init__ and reinitialize.
        """
        if model_config is not None:
            # Import model builders
            from .viscosity_models import build_viscosity_model
            from .heat_transfer_models import build_heat_transfer_model
            from .mixing_models import build_mixing_model
            from .energy_models import build_energy_model

            # Get model selections from config
            models = model_config.simulation["models"]

            # Build model instances
            self._viscosity_model = build_viscosity_model(models["viscosity"])
            self._heat_transfer_model = build_heat_transfer_model(models["heat_transfer"])
            self._mixing_model = build_mixing_model(models["mixing"])
            self._energy_model = build_energy_model(models["energy"])

            # Store mixing parameters for model evaluation
            self._mixing_params = {
                "eta_min": self._mixing_cfg.get("eta_min", 0.20) if hasattr(self, "_mixing_cfg") else 0.20,
                "Re_turb": self._mixing_cfg.get("Re_turb", 10000.0) if hasattr(self, "_mixing_cfg") else 10000.0,
                "steepness": self._mixing_cfg.get("steepness", 2.5) if hasattr(self, "_mixing_cfg") else 2.5,
            }
        else:
            # Legacy fallback: use full-fidelity models
            from .viscosity_models import FullViscosity
            from .heat_transfer_models import ConstantUA
            from .mixing_models import PerfectMixing
            from .energy_models import FullEnergyModel

            self._viscosity_model = FullViscosity()
            self._heat_transfer_model = ConstantUA()
            self._mixing_model = PerfectMixing()
            self._energy_model = FullEnergyModel()
            self._mixing_params = {"eta_min": 0.20, "Re_turb": 10000.0, "steepness": 2.5}

    def reinitialize(self, model_config: ModelConfig) -> None:
        """Re-initialize the model in place with a new config.

        Replaces all internal config references, rebuilds the reaction
        network, resets state to initial conditions, and clears feed rates.
        """
        self._initialize_from_config(model_config)

        # Reset state to initial conditions
        ic = model_config.initial_conditions
        reactor_cfg = model_config.reactor
        self.state = ReactorState(
            temperature=ic.get("temperature", 298.15),
            jacket_temperature=ic.get("jacket_temperature", 298.15),
            volume=reactor_cfg.get("volume_m3", 0.1),
        )

        # Reset feed rates
        self._feed_rates = {s: 0.0 for s in self._network.species_names}
        self._initial_masses = None
        self._initial_masses_locked = False
        self.last_solve_method = "none"

        # Rebuild geometry and mixing
        self._setup_geometry_and_mixing(model_config)

        # Rebuild physics models
        self._build_physics_models(model_config)

        self._fm_state = None
        self._pyomo_model = None  # force rebuild with new network
        logger.info("Model reinitialized with new config")

    def set_feed_rate(self, species_name: str, rate: float) -> None:
        """Set feed rate for a species by name (kg/s)."""
        self._feed_rates[species_name] = rate

    def get_feed_rate(self, species_name: str) -> float:
        """Get feed rate for a species by name (kg/s)."""
        return self._feed_rates.get(species_name, 0.0)

    @property
    def network(self) -> ReactionNetwork:
        """The reaction network driving this model."""
        return self._network

    @property
    def viscosity(self) -> float:
        """Current viscosity in Pa·s, computed via selected viscosity model."""
        return self._viscosity_model.evaluate(
            T=self.state.temperature,
            conversions=self.state.conversions,
            species_masses=self.state.species_masses,
            params=self.visc_params,
        )

    @property
    def pressure_bar(self) -> float:
        """Operating pressure from reactor config."""
        return self._reactor_cfg.get("pressure_bar", 0.5)

    @property
    def volume_L(self) -> float:
        """Liquid volume in litres, computed from component masses and densities."""
        species_by_name = self._network.species_by_name
        total = 0.0
        for sp_name, mass in self.state.species_masses.items():
            if sp_name in species_by_name:
                density = species_by_name[sp_name].density
            else:
                # Fallback to physics config for legacy compatibility
                density = self._physics_cfg.get(f"density_{sp_name}", 1.0)
            total += mass / density
        return total

    @property
    def volume_m3(self) -> float:
        """Liquid volume in m³."""
        return self.volume_L / 1000.0

    @property
    def vessel_volume_L(self) -> float:
        """Vessel capacity in litres from reactor config."""
        return self._reactor_cfg.get("vessel_volume_L", 100.0)

    @property
    def agitator_speed_rpm(self) -> float:
        """Agitator speed from reactor config."""
        return self._reactor_cfg.get("agitator_speed_rpm", 120.0)

    @property
    def fill_pct(self) -> float:
        """Fill level as percentage of vessel capacity."""
        cap = self.vessel_volume_L
        if cap <= 0:
            return 0.0
        return min(100.0, self.volume_L / cap * 100.0)

    # --- Geometry and fluid-mechanics accessors ---

    @property
    def geometry(self) -> ReactorGeometry | None:
        """The vessel geometry model (None if not configured)."""
        return self._geometry

    @property
    def mixing_enabled(self) -> bool:
        """Whether advanced mixing / fluid-mechanics model is active."""
        return self._mixing_enabled

    @property
    def fluid_mechanics_state(self) -> FluidMechanicsState | None:
        """Latest fluid-mechanics snapshot (updated each physics step)."""
        return self._fm_state

    @property
    def reynolds_number(self) -> float:
        """Current impeller Reynolds number (0 if mixing not enabled)."""
        return self._fm_state.Re if self._fm_state else 0.0

    @property
    def mixing_efficiency(self) -> float:
        """Current mixing efficiency 0-1 (1.0 if mixing not enabled)."""
        return self._fm_state.mixing_efficiency if self._fm_state else 1.0

    @property
    def dynamic_UA(self) -> float | None:
        """Dynamic UA in kW/K from fluid mechanics (None if not enabled)."""
        return self._fm_state.UA_kW_per_K if self._fm_state else None

    @property
    def wetted_area(self) -> float:
        """Current wetted wall area in m² (0 if no geometry configured)."""
        if self._geometry is None:
            return 0.0
        return self._geometry.wetted_area(self.volume_m3)

    @property
    def liquid_level(self) -> float:
        """Current liquid level in m (0 if no geometry configured)."""
        if self._geometry is None:
            return 0.0
        return self._geometry.liquid_level(self.volume_m3)

    def _get_species_densities_kg_m3(self) -> dict[str, float]:
        """Get species densities in kg/m³ (config stores kg/L)."""
        species_by_name = self._network.species_by_name
        densities: dict[str, float] = {}
        for sp_name in self.state.species_masses:
            if sp_name in species_by_name:
                # Species.density is in kg/L, convert to kg/m³
                densities[sp_name] = species_by_name[sp_name].density * 1000.0
            else:
                rho_kgL = self._physics_cfg.get(f"density_{sp_name}", 1.0)
                densities[sp_name] = rho_kgL * 1000.0
        return densities

    def _compute_bulk_density(self) -> float:
        """Compute volume-averaged bulk density in kg/m³."""
        V = self.volume_m3
        m_total = self.state.mass_total
        if V <= 0 or m_total <= 0:
            return 1100.0
        return m_total / V

    def _update_fluid_mechanics(self) -> None:
        """Recompute fluid-mechanics state from current reactor conditions.

        Called at the start of each physics step.  When mixing is not
        enabled, ``_fm_state`` stays None and all callers fall back to
        constant-UA behaviour.
        """
        if not self._mixing_enabled or self._agitator is None:
            self._fm_state = None
            return

        # Build current FluidProps
        mu = self.viscosity  # Pa·s
        rho = self._compute_bulk_density()
        fluid = FluidProps(
            density=rho,
            viscosity=mu,
            thermal_conductivity=self._fluid_k,
            specific_heat=self.thermal.Cp * 1000.0,  # kJ/(kg·K) -> J/(kg·K)
        )

        # Wetted area from geometry (or fallback estimate)
        if self._geometry is not None:
            A_wet = self._geometry.wetted_area(self.volume_m3)
            D_tank = self._geometry.inner_diameter
        else:
            # Estimate from a cylinder: A ≈ π·D·h + π·(D/2)²
            V_m3 = self.volume_m3
            D_tank = self._agitator.diameter_m * 3.0  # rough D_tank
            r = D_tank / 2
            import math
            A_cyl = math.pi * r**2
            h = V_m3 / A_cyl if A_cyl > 0 else 0.0
            A_wet = math.pi * r**2 + math.pi * D_tank * h

        self._fm_state = compute_fluid_mechanics(
            agitator=self._agitator,
            fluid=fluid,
            vessel_diameter=D_tank,
            wetted_area=A_wet,
            wall_thickness=self._wall_thickness,
            wall_conductivity=self._wall_conductivity,
            h_jacket=self._h_jacket,
        )

        # Enforce minimum UA floor (even gelled fluid still conducts heat)
        if self._min_UA_fraction > 0:
            static_UA_W = self.thermal.UA * 1000.0  # kW/K -> W/K
            min_UA_W = static_UA_W * self._min_UA_fraction
            if self._fm_state.UA_dynamic < min_UA_W:
                self._fm_state.UA_dynamic = min_UA_W

    def _compute_current_UA(self) -> float:
        """Compute current UA using selected heat transfer model.

        Returns:
            UA in kW/K.
        """
        liquid_state = ReactorState(
            species_masses=dict(self.state.species_masses),
            conversions=dict(self.state.conversions),
            temperature=self.state.temperature,
            jacket_temperature=self.state.jacket_temperature,
            volume=self.volume_m3,
        )
        return self._heat_transfer_model.compute_UA(
            state=liquid_state,
            thermal=self.thermal,
            geometry=self._geometry,
            fluid_mechanics=self._fm_state,
        )

    def _get_current_mixing_efficiency(self) -> float:
        """Compute current mixing efficiency using selected mixing model.

        Returns:
            Mixing efficiency in range [0, 1].
        """
        if not self._mixing_enabled or self._fm_state is None:
            # Perfect mixing when mixing subsystem disabled
            return 1.0

        # Compute mixing efficiency from Reynolds number
        Re = self._fm_state.Re
        return self._mixing_model.compute_efficiency(Re, self._mixing_params)

    def _capture_initial_masses(self) -> None:
        """Capture initial species masses for heat-of-reaction basis."""
        if self._initial_masses_locked:
            return

        has_mass = any(m > 0 for m in self.state.species_masses.values())
        if not has_mass:
            return

        feeding = any(rate > 0 for rate in self._feed_rates.values())
        if feeding or self._initial_masses is None:
            # Update while charging so basis reflects final charged masses.
            self._initial_masses = dict(self.state.species_masses)
            return

        # Lock once feeding has stopped and we have a captured basis.
        self._initial_masses_locked = True

    def _ensure_pyomo_model(self) -> None:
        """Build the persistent Pyomo model on first use."""
        if self._pyomo_model is not None:
            return

        min_mass = self._numerics_cfg["min_mass_kg"]
        initial_masses = self._initial_masses or {
            s: max(self.state.species_masses.get(s, 0.0), min_mass)
            for s in self._network.species_names
        }
        mix_eff = self._get_current_mixing_efficiency()
        ua_kw_k = self._compute_current_UA()
        q_frictional_kw = 0.0
        if self._fm_state is not None:
            q_frictional_kw = self._fm_state.power_W / 1000.0

        self._pyomo_model = build_reactor_model_from_network(
            t_horizon=1.0,  # normalized; actual dt set via time_factor
            n_fe=self._solver_cfg["n_finite_elements"],
            n_cp=self._solver_cfg["collocation_points"],
            network=self._network,
            initial_state=self.state,
            feed_rates=self._feed_rates,
            jacket_T=self.state.jacket_temperature,
            initial_masses=initial_masses,
            thermal=self._thermal_cfg,
            physics=self._physics_cfg,
            mixing_efficiency=mix_eff,
            UA_dynamic_kW_K=ua_kw_k,
            energy_model=self._energy_model,
            Q_frictional_kW=q_frictional_kw,
            min_mass_kg=min_mass,
        )

    def _solve_horizon(self, dt: float) -> SolverResult:
        """Solve a single Pyomo horizon, reusing the persistent model.

        On first call the model is built; subsequent calls only update
        mutable parameter values and re-fix initial conditions.

        Returns:
            SolverResult with status and final state dict (if successful).
        """
        from pyomo.common.errors import ApplicationError
        from pyomo.environ import TerminationCondition

        min_mass = self._numerics_cfg["min_mass_kg"]
        initial_masses = self._initial_masses or {
            s: max(self.state.species_masses.get(s, 0.0), min_mass)
            for s in self._network.species_names
        }

        # Determine dynamic parameters using pluggable models
        mix_eff = self._get_current_mixing_efficiency()
        ua_kw_k = self._compute_current_UA()

        # Frictional heating for extended energy model (kW)
        q_frictional_kw = 0.0
        if self._fm_state is not None:
            q_frictional_kw = self._fm_state.power_W / 1000.0

        try:
            # Build once, then reuse
            self._ensure_pyomo_model()

            # Update mutable params + initial conditions (microseconds)
            update_reactor_model(
                self._pyomo_model,
                network=self._network,
                initial_state=self.state,
                feed_rates=self._feed_rates,
                jacket_T=self.state.jacket_temperature,
                initial_masses=initial_masses,
                thermal=self._thermal_cfg,
                t_horizon=dt,
                mixing_efficiency=mix_eff,
                UA_dynamic_kW_K=ua_kw_k,
                Q_frictional_kW=q_frictional_kw,
            )

            result = solve_model(
                self._pyomo_model,
                solver_name=self._solver_cfg["solver_name"],
                solver_options=self._solver_cfg.get("solver_options"),
            )
        except ApplicationError as exc:
            msg = f"Solver crashed: {exc.__class__.__name__}: {exc}"
            logger.debug(msg)
            return SolverResult(status=SolverStatus.FAILED_EXCEPTION, state=None, message=msg)
        except Exception as exc:
            msg = f"Unexpected error during solve: {exc.__class__.__name__}: {exc}"
            logger.warning(msg)
            return SolverResult(status=SolverStatus.FAILED_EXCEPTION, state=None, message=msg)

        if result.solver.termination_condition != TerminationCondition.optimal:
            msg = f"Non-optimal termination: {result.solver.termination_condition}"
            logger.debug(msg)
            return SolverResult(status=SolverStatus.FAILED_CONVERGENCE, state=None, message=msg)

        final_state = extract_final_state_from_network(self._pyomo_model, self._network)
        return SolverResult(status=SolverStatus.SUCCESS, state=final_state)

    def step(self, dt: float) -> ReactorState:
        """Advance the physics by dt seconds using Pyomo DAE.

        Uses adaptive sub-stepping: if IPOPT fails at the requested horizon,
        the remaining time is halved repeatedly.  On success at a smaller
        horizon, the state is updated and integration continues with the
        remaining time (re-trying large steps first).
        """
        self._capture_initial_masses()

        # Update fluid-mechanics state (Reynolds, mixing efficiency, dynamic UA)
        self._update_fluid_mechanics()

        # Handle edge case of zero or negative dt
        if dt <= 0:
            self.last_solve_method = "skip"
            return self.state

        remaining = dt
        configured_horizon = float(self._solver_cfg.get("horizon", dt))
        if configured_horizon <= 0:
            configured_horizon = dt
        max_step = min(dt, configured_horizon)
        min_dt = max_step / MAX_SUBSTEP_DIVISIONS  # smallest sub-step we'll attempt
        solve_method = "none"  # Track what method was used

        while remaining > min_dt * 0.5:
            attempt = min(remaining, max_step)
            solved = False
            while attempt > min_dt * 0.5:
                result = self._solve_horizon(attempt)
                if result.status == SolverStatus.SUCCESS:
                    final = result.state
                    self.state = ReactorState(
                        species_masses=final["species_masses"],
                        conversions=final["conversions"],
                        temperature=final["T"],
                        jacket_temperature=self.state.jacket_temperature,
                        volume=self.state.volume,
                    )
                    solve_method = "pyomo"
                    remaining -= attempt
                    solved = True
                    break
                attempt /= 2
                logger.debug(
                    "Solver failed at dt=%.4f (%s), halving to %.4f. %s",
                    attempt * 2, result.status.value, attempt, result.message,
                )

            if not solved:
                logger.warning(
                    "Solver did not converge at min dt=%.4f. Using fallback.",
                    min_dt,
                )
                self._fallback_step(remaining)
                solve_method = "fallback"
                break

        self.last_solve_method = solve_method
        return self.state

    def _fallback_step(self, dt: float) -> None:
        """Fallback ODE integration if the Pyomo solver fails.

        Uses ``scipy.integrate.solve_ivp`` with the BDF method (implicit,
        stiff-stable) so the fallback is robust even for fast reactions or
        high heat release.  The RHS reuses ``self._network.compute_rates``
        and the pluggable energy / heat-transfer models — no duplicated
        physics logic.
        """
        from scipy.integrate import solve_ivp

        s = self.state
        max_temp = self._physics_cfg.get("max_temp", 500.0)
        min_mass = self._numerics_cfg["min_mass_kg"]
        min_temp = self._numerics_cfg["min_temperature_K"]

        initial_masses = self._initial_masses or {
            sp: max(s.species_masses.get(sp, 0.0), min_mass)
            for sp in self._network.species_names
        }

        sp_names = self._network.species_names
        cv_names = self._network.conversion_names
        n_sp = len(sp_names)
        n_cv = len(cv_names)
        # State vector layout: [mass_0, ..., mass_N, T, conv_0, ..., conv_M]

        # Pre-compute values that are constant over the horizon
        eta = self.mixing_efficiency
        UA = self._compute_current_UA()  # kW/K
        q_frictional = 0.0
        if self._fm_state is not None:
            q_frictional = self._fm_state.power_W / 1000.0  # W -> kW

        def rhs(_t: float, y: np.ndarray) -> np.ndarray:
            """RHS for the ODE system."""
            masses = {sp_names[i]: max(y[i], 0.0) for i in range(n_sp)}
            T = y[n_sp]
            convs = {cv_names[i]: y[n_sp + 1 + i] for i in range(n_cv)}

            dm_dt, dconv_dt, q_rxn = self._network.compute_rates(
                species_masses=masses,
                conversions=convs,
                T=T,
                ops=MathOps.numpy(),
                feed_rates=self._feed_rates,
                initial_masses=initial_masses,
            )

            # Apply mixing efficiency penalty
            if eta < 1.0:
                dm_dt = {k: v * eta for k, v in dm_dt.items()}
                dconv_dt = {k: v * eta for k, v in dconv_dt.items()}
                q_rxn = q_rxn * eta

            # Energy balance via pluggable models
            m_total = sum(masses.values()) + min_mass
            q_jacket = UA * (s.jacket_temperature - T)  # kW

            dT_dt = self._energy_model.compute_dT_dt(
                Q_rxn=q_rxn,
                Q_jacket=q_jacket,
                Q_frictional=q_frictional,
                m_total=m_total,
                Cp=self.thermal.Cp,
            )

            dydt = np.empty_like(y)
            for i, sp in enumerate(sp_names):
                dydt[i] = dm_dt.get(sp, 0.0)
            dydt[n_sp] = dT_dt
            for i, cv in enumerate(cv_names):
                dydt[n_sp + 1 + i] = dconv_dt.get(cv, 0.0)
            return dydt

        # Pack initial state
        y0 = np.array(
            [s.species_masses.get(sp, 0.0) for sp in sp_names]
            + [s.temperature]
            + [s.conversions.get(cv, 0.0) for cv in cv_names]
        )

        sol = solve_ivp(
            rhs, (0.0, dt), y0,
            method="BDF",
            rtol=1e-6, atol=1e-8,
            max_step=dt,
        )

        if sol.success:
            yf = sol.y[:, -1]
        else:
            logger.warning("scipy fallback also failed: %s. Using last state.", sol.message)
            yf = y0  # keep current state unchanged

        # Unpack final state with physical clamping
        new_masses = {sp_names[i]: max(yf[i], 0.0) for i in range(n_sp)}
        new_temp = min(max(yf[n_sp], min_temp), max_temp)
        new_convs = {cv_names[i]: min(max(yf[n_sp + 1 + i], 0.0), 1.0) for i in range(n_cv)}

        self.state = ReactorState(
            species_masses=new_masses,
            conversions=new_convs,
            temperature=new_temp,
            jacket_temperature=s.jacket_temperature,
            volume=s.volume,
        )
