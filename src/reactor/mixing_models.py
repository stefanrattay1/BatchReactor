"""Pluggable mixing efficiency models for reactor simulation.

This module provides modular mixing efficiency calculations,
allowing users to select between perfect mixing and various
Reynolds-based correlations.

Pattern:
    - Abstract base class `MixingModel` defines the protocol
    - Concrete implementations for different mixing scenarios
    - Registry dict maps config names to classes
    - Factory function builds instances from config strings
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod


class MixingModel(ABC):
    """Protocol for mixing efficiency calculations.

    All mixing models must implement compute_efficiency() which returns
    a value between 0 and 1 representing the effectiveness of mixing.
    """

    @abstractmethod
    def compute_efficiency(
        self,
        Re: float,
        params: dict,
    ) -> float:
        """Compute mixing efficiency factor.

        Args:
            Re: Impeller Reynolds number (dimensionless).
            params: Model-specific parameters (e.g., eta_min, Re_turb, steepness).

        Returns:
            Mixing efficiency in range [0, 1].
        """


class PerfectMixing(MixingModel):
    """Perfect mixing model: η = 1.0 always.

    Assumes perfect macro-mixing regardless of Reynolds number, viscosity,
    or agitation intensity. All reactants are uniformly distributed.

    Use cases:
        - Turbulent regime operations (Re > 10,000)
        - Fast reactions where diffusion is not limiting
        - Low-viscosity fluids
        - Teaching and simplified simulations
        - When mixing effects are negligible

    Performance: Fastest (no calculations)
    Accuracy: Good for well-mixed systems, poor for viscous/laminar regimes
    """

    def compute_efficiency(
        self,
        Re: float,
        params: dict,
    ) -> float:
        """Return perfect mixing (η = 1.0)."""
        return 1.0


class ReynoldsMixing(MixingModel):
    """Reynolds-based mixing efficiency using logistic sigmoid function.

    Models mixing efficiency as a smooth transition from laminar
    (poor mixing) to turbulent (good mixing) based on Reynolds number.

    Model: η = η_min + (1 - η_min) · σ(log₁₀(Re) - log₁₀(Re_turb))

    Where:
        - σ is a logistic sigmoid function
        - η_min is the minimum mixing efficiency (diffusion floor)
        - Re_turb is the Reynolds number for fully turbulent regime
        - Transition spans ~2 decades of Reynolds number

    Physical basis:
        - Re < 10: Laminar, poor macro-mixing, η → η_min
        - 10 < Re < 10,000: Transitional, gradually improving mixing
        - Re > 10,000: Turbulent, excellent mixing, η → 1.0

    Parameters (in params dict):
        - eta_min: Minimum mixing efficiency (default: 0.20)
        - Re_turb: Turbulent Reynolds threshold (default: 10,000)
        - steepness: Transition steepness (default: 2.5)

    Use cases:
        - Production accuracy simulations
        - Systems with wide viscosity ranges
        - Reactive systems that gel during cure
        - Validated against experimental data

    Performance: Fast (simple math operations)
    Accuracy: Good (empirically validated)

    Notes:
        - η_min = 0.20 represents diffusion-controlled reaction
          continuing even in gelled/stagnant regions
        - Validated for reactive batch processes
    """

    def compute_efficiency(
        self,
        Re: float,
        params: dict,
    ) -> float:
        """Compute mixing efficiency using Reynolds-based sigmoid."""
        # Extract parameters with defaults
        eta_min = params.get("eta_min", 0.20)
        Re_turb = params.get("Re_turb", 10000.0)
        steepness = params.get("steepness", 2.5)

        if Re <= 0:
            return eta_min

        # Sigmoid transition over ~2 decades of Re
        log_Re = math.log10(max(Re, 1.0))
        log_turb = math.log10(Re_turb)

        # Shift so transition centres around Re_turb/10
        x = steepness * (log_Re - log_turb + 1.0)
        sigmoid = 1.0 / (1.0 + math.exp(-x))

        return eta_min + (1.0 - eta_min) * sigmoid


class PowerLawMixing(MixingModel):
    """Power-law mixing efficiency: η = min(1.0, (Re / Re_crit)^a).

    Simple power-law correlation for mixing efficiency based on
    Reynolds number ratio.

    Model: η = (Re / Re_crit)^a, capped at 1.0

    Where:
        - Re_crit is the critical Reynolds number for good mixing
        - a is the power-law exponent (typically 0.5-1.0)

    Parameters (in params dict):
        - Re_crit: Critical Reynolds number (default: 1000.0)
        - exponent: Power-law exponent (default: 0.7)
        - eta_min: Minimum floor (default: 0.1)

    Use cases:
        - Alternative correlation for validation
        - Systems with empirical Re-mixing data
        - Research and model comparison

    Performance: Fast (simple power operation)
    Accuracy: Moderate (empirical, system-dependent)

    Notes:
        - Less physically grounded than ReynoldsMixing
        - May not capture transition regime well
        - Useful for sensitivity studies
    """

    def compute_efficiency(
        self,
        Re: float,
        params: dict,
    ) -> float:
        """Compute mixing efficiency using power-law correlation."""
        # Extract parameters with defaults
        Re_crit = params.get("Re_crit", 1000.0)
        exponent = params.get("exponent", 0.7)
        eta_min = params.get("eta_min", 0.1)

        if Re <= 0:
            return eta_min

        # Power-law model
        ratio = Re / Re_crit
        eta = ratio ** exponent

        # Cap at 1.0 and floor at eta_min
        return max(min(eta, 1.0), eta_min)


# Registry mapping config names to model classes
MIXING_REGISTRY: dict[str, type[MixingModel]] = {
    "perfect": PerfectMixing,
    "reynolds": ReynoldsMixing,
    "power_law": PowerLawMixing,
}


def build_mixing_model(model_name: str) -> MixingModel:
    """Factory function to build mixing model from config string.

    Args:
        model_name: Model identifier (e.g., "perfect", "reynolds", "power_law").

    Returns:
        Instantiated MixingModel.

    Raises:
        ValueError: If model_name is not registered.

    Example:
        >>> model = build_mixing_model("perfect")
        >>> isinstance(model, PerfectMixing)
        True
    """
    cls = MIXING_REGISTRY.get(model_name)
    if cls is None:
        available = ", ".join(MIXING_REGISTRY.keys())
        raise ValueError(
            f"Unknown mixing model: '{model_name}'. "
            f"Available models: {available}"
        )
    return cls()


def register_mixing_model(name: str, cls: type[MixingModel]) -> None:
    """Register a custom mixing model for use in YAML configs.

    Args:
        name: Model identifier for configuration.
        cls: MixingModel subclass.

    Example:
        >>> class MyCustomMixing(MixingModel):
        ...     def compute_efficiency(self, Re, params):
        ...         return 0.5  # Custom logic
        >>> register_mixing_model("custom", MyCustomMixing)
    """
    if not issubclass(cls, MixingModel):
        raise TypeError(f"Class {cls.__name__} must inherit from MixingModel")
    MIXING_REGISTRY[name] = cls
