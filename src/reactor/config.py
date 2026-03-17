from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


# --- Pydantic validation models for config sections ---


class ThermalConfig(BaseModel):
    """Thermal properties validation."""

    Cp: float = Field(default=1.8, gt=0, description="Specific heat (kJ/kg·K)")
    UA: float = Field(default=0.5, ge=0, description="Heat transfer coefficient (kW/K)")


class ReactorConfig(BaseModel):
    """Physical reactor properties validation."""

    volume_m3: float = Field(default=0.1, gt=0, description="Volume (m³)")
    vessel_volume_L: float = Field(default=100.0, gt=0, description="Vessel volume (L)")
    pressure_bar: float = Field(default=0.5, gt=0, description="Pressure (bar)")
    agitator_speed_rpm: float = Field(default=120.0, ge=0, description="Agitator speed (rpm)")


class SolverConfig(BaseModel):
    """Solver configuration validation."""

    horizon: float = Field(default=2.0, gt=0, description="Time horizon (s)")
    n_finite_elements: int = Field(default=5, ge=1, description="Finite elements")
    collocation_points: int = Field(default=3, ge=1, description="Collocation points")
    solver_name: str = Field(default="ipopt", description="Solver name")
    solver_options: dict = Field(default_factory=dict, description="Solver options")


class ExecutionMode(str, Enum):
    SIMULATION = "simulation"
    PHYSICAL = "physical"


class Settings(BaseSettings):
    opc_port: int = 4840
    web_port: int = 8000
    tick_interval: float = 0.5
    enable_web: bool = True
    sensors_enabled: bool = True
    noise_pct: float = 0.5
    execution_mode: ExecutionMode = ExecutionMode.SIMULATION

    # OPC Tool integration
    opc_tool_url: str = "http://localhost:8001"
    opc_tool_enabled: bool = True
    initial_temp_k: float = 298.15
    batch_mass_kg: float = 100.0
    auto_start: bool = False
    test_inputs_file: str = ""
    data_package_file: str = ""
    recipe_file: str = "recipes/default.yaml"
    model_config_file: str = "configs/default.yaml"

    # Batch mode
    batch_mode: bool = False
    batch_post_recipe_time: float = 60.0
    batch_stop_conversion: float | None = None
    batch_max_overtime: float = 3600.0

    # Physical Execution
    realtime_mode: bool = False
    batch_parameter_set: str = ""
    batch_identity: dict | None = None

    # Audit trail
    audit_trail_enabled: bool = True
    audit_trail_hash_chain: bool = True

    # Frontend build
    build_frontend: bool = True

    model_config = {"env_prefix": "REACTOR_"}


def load_data_file(path: str | Path) -> dict:
    """Load a YAML or JSON data file based on extension."""
    path = Path(path)
    with open(path) as f:
        if path.suffix == ".json":
            return json.load(f)
        return yaml.safe_load(f)


@dataclass(frozen=True)
class ModelConfig:
    """All physics/chemistry/controller parameters loaded from YAML or JSON."""

    raw: dict

    @classmethod
    def from_file(cls, path: str | Path) -> ModelConfig:
        """Load config from a YAML or JSON file (auto-detected by extension)."""
        data = load_data_file(path)
        cfg = cls(raw=data)
        cfg.validate()
        return cfg

    @classmethod
    def from_yaml(cls, path: str | Path) -> ModelConfig:
        """Load config from file. Kept for backward compatibility."""
        return cls.from_file(path)

    @classmethod
    def from_dict(cls, data: dict) -> ModelConfig:
        cfg = cls(raw=data)
        cfg.validate()  # Validate at load time
        return cfg

    def validate(self) -> None:
        """Validate config structure using Pydantic models.

        Raises ValueError with clear error messages on validation failure.
        """
        # Validate thermal config if present
        try:
            ThermalConfig(**self.thermal)
        except Exception as exc:
            raise ValueError(f"Invalid thermal config: {exc}") from exc

        # Validate reactor config if present
        try:
            ReactorConfig(**self.reactor)
        except Exception as exc:
            raise ValueError(f"Invalid reactor config: {exc}") from exc

        # Validate solver config if present
        try:
            SolverConfig(**self.solver)
        except Exception as exc:
            raise ValueError(f"Invalid solver config: {exc}") from exc

        # Additional cross-field validation
        if "initial_conditions" in self.raw:
            ic = self.raw["initial_conditions"]
            if isinstance(ic, dict) and "temperature" in ic:
                temp = ic["temperature"]
                if not isinstance(temp, (int, float)) or temp <= 0:
                    raise ValueError(f"Initial temperature must be positive, got {temp}")

        # Legacy mode requires Kamal-Sourour kinetics parameters unless a
        # full reaction_network is provided.
        if "reaction_network" not in self.raw:
            required_kinetics = ("A1", "Ea1", "A2", "Ea2", "m", "n", "delta_H")
            missing = [key for key in required_kinetics if key not in self.kinetics]
            if missing:
                missing_txt = ", ".join(missing)
                raise ValueError(
                    "Invalid kinetics config: missing required keys "
                    f"{missing_txt}. Provide a full 'kinetics' section or a "
                    "'reaction_network' section."
                )

        # Validate simulation model selections
        self.validate_simulation_models()

    @property
    def kinetics(self) -> dict:
        # Optional in reaction_network mode (kinetics defined per-reaction)
        return self.raw.get("kinetics", {})

    @property
    def thermal(self) -> dict:
        return self.raw.get("thermal", {"Cp": 1.8, "UA": 0.5})

    @property
    def viscosity(self) -> dict:
        return self.raw.get("viscosity", {
            "eta_0": 0.5,
            "eta_ref": 0.5,
            "T_ref_K": 298.15,
            "E_eta_J_mol": 0.0,
            "C_visc": 4.0,
            "alpha_gel": 0.6,
            "eta_gel": 100.0,
        })

    @property
    def physics(self) -> dict:
        return self.raw.get("physics", {"max_temp": 500.0, "R_gas": 8.314})

    @property
    def controller(self) -> dict:
        return self.raw.get("controller", {})

    @property
    def initial_conditions(self) -> dict:
        return self.raw.get("initial_conditions", {})

    @property
    def numerics(self) -> dict:
        """Numerical stability thresholds (optional).

        Provides configurable replacements for previously hard-coded
        constants used throughout the solver and energy balance.

        Example::

            numerics:
              min_mass_kg: 0.01
              reactant_eps_kg: 0.001
              min_temperature_K: 200.0
        """
        defaults = {
            "min_mass_kg": 0.001,
            "reactant_eps_kg": 0.001,
            "min_temperature_K": 200.0,
        }
        user = self.raw.get("numerics", {})
        return {**defaults, **user}

    @property
    def solver(self) -> dict:
        return self.raw.get("solver", {
            "horizon": 2.0,
            "n_finite_elements": 5,
            "collocation_points": 3,
            "solver_name": "ipopt",
            "solver_options": {"max_iter": 1000, "tol": 1e-6, "mu_strategy": "adaptive", "print_level": 0}
        })

    @property
    def reactor(self) -> dict:
        """Physical reactor properties (volume, pressure, agitator, etc.)."""
        return self.raw.get("reactor", {
            "volume_m3": 0.1,
            "vessel_volume_L": 100.0,
            "pressure_bar": 0.5,
            "agitator_speed_rpm": 120,
        })

    @property
    def geometry(self) -> dict:
        """Vessel geometry configuration (optional).

        Example::

            geometry:
              type: cylindrical_torispherical
              diameter_m: 0.50
              height_m: 0.60
        """
        return self.raw.get("geometry", {})

    @property
    def mixing(self) -> dict:
        """Mixing / agitator configuration (optional).

        When present, enables Reynolds-based mixing efficiency and
        dynamic heat transfer coefficient calculation.

        Example::

            mixing:
              enabled: true
              impeller_diameter_m: 0.16
              power_number: 5.0
              impeller_type: rushton
              wall_thickness_m: 0.005
              wall_conductivity: 16.0
              h_jacket: 1000.0
              fluid_thermal_conductivity: 0.17
        """
        return self.raw.get("mixing", {})

    @property
    def equipment(self) -> dict:
        """Equipment Module / Control Module configuration (optional).

        When present, enables ISA-88 style EM/CM procedural control layer.
        If absent, system behaves as before (direct recipe → physics).

        Example::

            equipment:
              control_modules:
                - tag: XV-101
                  type: valve_onoff
                                    name: "Component A Inlet Valve"
                                    maps_to: feed_component_a
                  flow_rate: 0.5
                  opc_node_id: "ns=2;s=Reactor.Valves.XV101"
              equipment_modules:
                - tag: EM-FILL
                  name: "Befuellen"
                  cms: [XV-101, P-101, FT-101]
                  modes:
                    - name: aus
                      display_name: "Aus"
                      steps: []
        """
        return self.raw.get("equipment", {})

    @property
    def materials(self) -> dict:
        """Default material specifications for ISA-88 Chapter 6 traceability.

        Example::

            materials:
              component_a:
                material_id: MAT-COMPA-001
                vendor: "ChemSupplier GmbH"
                cas_number: "25036-25-3"
              component_b:
                material_id: MAT-COMPB-001
                vendor: "AmineSupplier AG"
        """
        return self.raw.get("materials", {})

    @property
    def has_equipment(self) -> bool:
        """True if equipment EM/CM config is present."""
        eq = self.equipment
        return bool(eq.get("control_modules") or eq.get("equipment_modules"))

    @property
    def has_reaction_network(self) -> bool:
        return "reaction_network" in self.raw

    @property
    def reaction_network(self) -> dict:
        return self.raw.get("reaction_network", {})

    @property
    def simulation(self) -> dict:
        """Simulation model selection configuration.

        Allows fine-grained control over which physics models are used
        for viscosity, heat transfer, mixing, and energy balance.

        Default behavior (when section omitted):
            - Uses current full-fidelity models
            - Dynamic UA and Reynolds mixing if mixing.enabled: true
            - Constant UA and perfect mixing if mixing disabled

        Example::

            simulation:
              models:
                viscosity: full_composition      # or: constant | arrhenius | conversion
                heat_transfer: dynamic           # or: constant | geometry_aware
                mixing: reynolds                 # or: perfect | power_law
                energy: full                     # or: isothermal | adiabatic | extended

        Returns:
            Dict with 'models' key containing model selections.
        """
        # Default model choices based on mixing configuration
        mixing_enabled = self.mixing.get("enabled", False)

        default_models = {
            "viscosity": "full_composition",
            "heat_transfer": "dynamic" if mixing_enabled else "constant",
            "mixing": "reynolds" if mixing_enabled else "perfect",
            "energy": "full",
        }

        # Get user-provided simulation config
        sim_cfg = self.raw.get("simulation", {})

        # Start with defaults and apply user overrides
        models = default_models.copy()
        if "models" in sim_cfg:
            models.update(sim_cfg["models"])

        return {"models": models}

    def validate_simulation_models(self) -> None:
        """Validate that selected models are registered and compatible.

        Raises:
            ValueError: If model name is unknown or dependencies are not met.
        """
        # Import registries (deferred to avoid circular imports)
        try:
            from .viscosity_models import VISCOSITY_REGISTRY
            from .heat_transfer_models import HEAT_TRANSFER_REGISTRY
            from .mixing_models import MIXING_REGISTRY
            from .energy_models import ENERGY_REGISTRY
        except ImportError:
            # Registries not available (e.g., during testing), skip validation
            return

        models = self.simulation["models"]

        # Check viscosity model exists
        if models["viscosity"] not in VISCOSITY_REGISTRY:
            available = ", ".join(VISCOSITY_REGISTRY.keys())
            raise ValueError(
                f"Unknown viscosity model: '{models['viscosity']}'. "
                f"Available: {available}"
            )

        # Check heat_transfer model exists
        if models["heat_transfer"] not in HEAT_TRANSFER_REGISTRY:
            available = ", ".join(HEAT_TRANSFER_REGISTRY.keys())
            raise ValueError(
                f"Unknown heat_transfer model: '{models['heat_transfer']}'. "
                f"Available: {available}"
            )

        # Check mixing model exists
        if models["mixing"] not in MIXING_REGISTRY:
            available = ", ".join(MIXING_REGISTRY.keys())
            raise ValueError(
                f"Unknown mixing model: '{models['mixing']}'. "
                f"Available: {available}"
            )

        # Check energy model exists
        if models["energy"] not in ENERGY_REGISTRY:
            available = ", ".join(ENERGY_REGISTRY.keys())
            raise ValueError(
                f"Unknown energy model: '{models['energy']}'. "
                f"Available: {available}"
            )

        # Validate dependencies
        if models["heat_transfer"] == "dynamic" and not self.mixing.get("enabled", False):
            raise ValueError(
                "heat_transfer model 'dynamic' requires mixing.enabled: true. "
                "Either enable mixing or use 'constant' or 'geometry_aware' heat transfer."
            )

        if models["heat_transfer"] == "geometry_aware" and not self.geometry:
            raise ValueError(
                "heat_transfer model 'geometry_aware' requires geometry section in config. "
                "Either add geometry configuration or use 'constant' heat transfer."
            )
