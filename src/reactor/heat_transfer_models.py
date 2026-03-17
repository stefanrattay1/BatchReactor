"""Pluggable heat transfer models for reactor simulation.

This module provides modular heat transfer coefficient (UA) calculations,
allowing users to select between constant, geometry-aware, and dynamic models.

Pattern:
    - Abstract base class `HeatTransferModel` defines the protocol
    - Concrete implementations for different complexity levels
    - Registry dict maps config names to classes
    - Factory function builds instances from config strings
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chemistry import ThermalParams
    from .geometry import ReactorGeometry
    from .fluid_mechanics import FluidMechanicsState
    from .physics import ReactorState


class HeatTransferModel(ABC):
    """Protocol for heat transfer coefficient calculations.

    All heat transfer models must implement compute_UA() which returns
    the overall heat transfer coefficient times area (UA) in kW/K.
    """

    @abstractmethod
    def compute_UA(
        self,
        state: ReactorState,
        thermal: ThermalParams,
        geometry: ReactorGeometry | None,
        fluid_mechanics: FluidMechanicsState | None,
    ) -> float:
        """Compute overall heat transfer coefficient times area (UA).

        Args:
            state: Current reactor state (temperature, masses, volume, etc.).
            thermal: Thermal parameters (includes constant UA).
            geometry: Reactor geometry (optional, for wetted area calculations).
            fluid_mechanics: Fluid mechanics state (optional, for dynamic UA).

        Returns:
            UA in kW/K.
        """


class ConstantUA(HeatTransferModel):
    """Constant heat transfer coefficient: UA = constant.

    Simplest model - UA does not vary with fill level, viscosity, or
    mixing intensity.

    Use cases:
        - Simple heat transfer studies
        - Systems with constant fill level
        - When geometry and mixing effects are negligible
        - Teaching and debugging

    Performance: Fastest (no calculations)
    Accuracy: Poor for systems with varying fill or viscosity
    """

    def compute_UA(
        self,
        state: ReactorState,
        thermal: ThermalParams,
        geometry: ReactorGeometry | None,
        fluid_mechanics: FluidMechanicsState | None,
    ) -> float:
        """Return constant UA from thermal parameters."""
        return thermal.UA


class GeometryAwareUA(HeatTransferModel):
    """Geometry-aware heat transfer: UA scales with wetted area.

    Heat transfer coefficient scales proportionally with the wetted
    wall area, which varies with fill level.

    Model: UA = U₀ × A_wet(V) / A_ref

    Where:
        - U₀ is the base heat transfer coefficient
        - A_wet is the current wetted area (from geometry)
        - A_ref is a reference area (initial or full fill)

    Requires: geometry subsystem configured

    Use cases:
        - Variable fill level operations
        - Charging/discharging reactors
        - When fill level significantly affects heat transfer

    Performance: Fast (geometry calculation only)
    Accuracy: Good for fill level effects, misses viscosity effects
    """

    def compute_UA(
        self,
        state: ReactorState,
        thermal: ThermalParams,
        geometry: ReactorGeometry | None,
        fluid_mechanics: FluidMechanicsState | None,
    ) -> float:
        """Compute UA scaled by wetted area."""
        if geometry is None:
            # Fallback to constant if no geometry available
            return thermal.UA

        # Get current liquid volume (m³) from the state.
        # Prefer explicit liquid-volume fields if present, then fall back to
        # legacy `state.volume`.
        V_liquid = (
            getattr(state, "liquid_volume_m3", None)
            or getattr(state, "volume_m3", None)
            or state.volume
        )

        # Compute wetted area at current fill level
        A_wet = geometry.wetted_area(V_liquid)

        # Reference area (use full vessel for now, could be configurable)
        A_ref = geometry.wetted_area(geometry.vessel_volume)

        # Scale UA proportionally with area ratio
        # thermal.UA is interpreted as the UA at reference fill
        if A_ref > 0:
            return thermal.UA * (A_wet / A_ref)
        else:
            return thermal.UA


class DynamicUA(HeatTransferModel):
    """Dynamic heat transfer from fluid mechanics correlations.

    Full dynamic heat transfer model using Reynolds and Nusselt correlations
    to compute process-side heat transfer coefficient. Accounts for:
        - Viscosity effects on film coefficient
        - Agitation intensity (mixing speed)
        - Geometry effects (wetted area)

    Model: UA = U(Re, Nu, geometry) × A_wet(V)

    Where U is computed from fluid mechanics correlations:
        - Re = ρ·N·D²/μ (Reynolds number)
        - Nu = f(Re, Pr) (Nusselt correlation)
        - h_inside = Nu·k/D (process-side film coefficient)
        - U = overall HTC from resistances network

    Requires: mixing subsystem enabled

    Use cases:
        - Production accuracy simulations
        - Viscosity-dependent heat transfer
        - Scale-up studies
        - Systems with wide viscosity variation

    Performance: Slower (fluid mechanics calculations)
    Accuracy: Best (validated correlations)

        Notes:
                - Falls back to constant UA if fluid mechanics not available
                - UA flooring is handled upstream by the physics/fluid-mechanics
                    integration so there is a single authoritative floor path
    """

    def compute_UA(
        self,
        state: ReactorState,
        thermal: ThermalParams,
        geometry: ReactorGeometry | None,
        fluid_mechanics: FluidMechanicsState | None,
    ) -> float:
        """Compute dynamic UA from fluid mechanics state."""
        if fluid_mechanics is None:
            # Fallback to constant UA if fluid mechanics not computed
            return thermal.UA

        return fluid_mechanics.UA_kW_per_K


# Registry mapping config names to model classes
HEAT_TRANSFER_REGISTRY: dict[str, type[HeatTransferModel]] = {
    "constant": ConstantUA,
    "geometry_aware": GeometryAwareUA,
    "dynamic": DynamicUA,
}


def build_heat_transfer_model(model_name: str) -> HeatTransferModel:
    """Factory function to build heat transfer model from config string.

    Args:
        model_name: Model identifier (e.g., "constant", "geometry_aware", "dynamic").

    Returns:
        Instantiated HeatTransferModel.

    Raises:
        ValueError: If model_name is not registered.

    Example:
        >>> model = build_heat_transfer_model("constant")
        >>> isinstance(model, ConstantUA)
        True
    """
    cls = HEAT_TRANSFER_REGISTRY.get(model_name)
    if cls is None:
        available = ", ".join(HEAT_TRANSFER_REGISTRY.keys())
        raise ValueError(
            f"Unknown heat transfer model: '{model_name}'. "
            f"Available models: {available}"
        )
    return cls()


def register_heat_transfer_model(name: str, cls: type[HeatTransferModel]) -> None:
    """Register a custom heat transfer model for use in YAML configs.

    Args:
        name: Model identifier for configuration.
        cls: HeatTransferModel subclass.

    Example:
        >>> class MyCustomHeatTransfer(HeatTransferModel):
        ...     def compute_UA(self, state, thermal, geometry, fluid_mechanics):
        ...         return 1.0  # Custom logic
        >>> register_heat_transfer_model("custom", MyCustomHeatTransfer)
    """
    if not issubclass(cls, HeatTransferModel):
        raise TypeError(f"Class {cls.__name__} must inherit from HeatTransferModel")
    HEAT_TRANSFER_REGISTRY[name] = cls
