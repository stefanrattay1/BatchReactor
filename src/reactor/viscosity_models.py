"""Pluggable viscosity models for reactor simulation.

This module provides a modular architecture for viscosity calculations,
allowing users to select between simplified and detailed models via configuration.

Pattern:
    - Abstract base class `ViscosityModel` defines the protocol
    - Concrete implementations for different model complexities
    - Registry dict maps config names to classes
    - Factory function builds instances from config strings
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from .chemistry import ViscosityParams

R_GAS = 8.314  # J/(mol*K)


class ViscosityModel(ABC):
    """Protocol for viscosity calculations.

    All viscosity models must implement the evaluate() method which takes
    the current reactor state and returns viscosity in Pa·s.
    """

    @abstractmethod
    def evaluate(
        self,
        T: float,
        conversions: dict[str, float],
        species_masses: dict[str, float],
        params: ViscosityParams,
    ) -> float:
        """Compute viscosity in Pa·s.

        Args:
            T: Temperature in Kelvin.
            conversions: Dictionary of conversion variables (e.g., {"alpha": 0.5}).
            species_masses: Dictionary of species masses in kg (e.g., {"component_a": 60.0}).
            params: Viscosity model parameters.

        Returns:
            Viscosity in Pa·s.
        """


class ConstantViscosity(ViscosityModel):
    """Constant viscosity model: η = η₀.

    Simplest possible model - viscosity does not vary with temperature,
    conversion, or composition.

    Use cases:
        - Teaching and debugging
        - Fast simulations when viscosity effects are negligible
        - Non-reactive fluids with low temperature variation

    Performance: Fastest (no calculations)
    Accuracy: Poor for reactive systems
    """

    def evaluate(
        self,
        T: float,
        conversions: dict[str, float],
        species_masses: dict[str, float],
        params: ViscosityParams,
    ) -> float:
        """Return constant viscosity from params.eta_0."""
        return params.eta_0


class ArrheniusViscosity(ViscosityModel):
    """Temperature-dependent viscosity: η = η_ref × exp(E_η/R × (1/T - 1/T_ref)).

    Temperature-dependent viscosity following Arrhenius correlation.
    No dependence on conversion or composition.

    Use cases:
        - Non-reactive fluids
        - Sensible heat transfer studies
        - Systems where conversion effects are negligible

    Performance: Fast (simple exponential)
    Accuracy: Good for temperature effects, misses reaction-induced changes
    """

    def evaluate(
        self,
        T: float,
        conversions: dict[str, float],
        species_masses: dict[str, float],
        params: ViscosityParams,
    ) -> float:
        """Compute temperature-dependent viscosity using Arrhenius model."""
        eta_ref = params.eta_ref if params.eta_ref is not None else params.eta_0

        if eta_ref <= 0:
            raise ValueError(f"Base viscosity must be positive, got {eta_ref}")

        # No temperature correction if E_eta is zero
        if params.E_eta_J_mol == 0.0 or params.T_ref_K <= 0.0 or T <= 0.0:
            return eta_ref

        # Arrhenius temperature correction
        temp_exp = params.E_eta_J_mol / R_GAS * (1.0 / T - 1.0 / params.T_ref_K)
        # Clamp exponent to prevent overflow
        temp_exp = max(min(temp_exp, 700.0), -700.0)

        return eta_ref * np.exp(temp_exp)


class ConversionViscosity(ViscosityModel):
    """Temperature + conversion-dependent viscosity.

    Combines Arrhenius temperature dependence with exponential divergence
    as conversion approaches the gel point.

    Model: η = η_base(T) × exp(C_visc × α / (α_gel - α))

    Does NOT include composition effects (no log-mixing rule).

    Use cases:
        - Reactive systems without composition tracking
        - Single-reaction systems
        - When composition effects are negligible

    Performance: Moderate (exponential with bounds checking)
    Accuracy: Good for most reactive systems
    """

    def evaluate(
        self,
        T: float,
        conversions: dict[str, float],
        species_masses: dict[str, float],
        params: ViscosityParams,
    ) -> float:
        """Compute temperature and conversion-dependent viscosity."""
        # Get primary conversion (use "alpha" as default, or first conversion if multiple)
        alpha = conversions.get("alpha", 0.0)
        if not alpha and conversions:
            alpha = next(iter(conversions.values()))

        # Compute temperature-corrected base viscosity (no composition mixing)
        eta_ref = params.eta_ref if params.eta_ref is not None else params.eta_0

        if eta_ref <= 0:
            raise ValueError(f"Base viscosity must be positive, got {eta_ref}")

        # Arrhenius temperature correction
        eta_base = eta_ref
        if params.E_eta_J_mol != 0.0 and params.T_ref_K > 0.0 and T > 0.0:
            temp_exp = params.E_eta_J_mol / R_GAS * (1.0 / T - 1.0 / params.T_ref_K)
            temp_exp = max(min(temp_exp, 700.0), -700.0)
            eta_base = eta_ref * np.exp(temp_exp)

        # At or beyond gel point, return cap
        if alpha >= params.alpha_gel:
            return params.eta_gel

        # Exponential divergence model
        exponent = params.C_visc * alpha / (params.alpha_gel - alpha)

        # Cap exponent so result doesn't exceed eta_gel
        max_exponent = np.log(params.eta_gel / eta_base) if eta_base > 0 else 700.0
        exponent = min(exponent, max_exponent)

        return eta_base * np.exp(exponent)


class FullViscosity(ViscosityModel):
    """Full composition-aware viscosity model.

    Complete viscosity model with:
    - Temperature dependence (Arrhenius)
    - Conversion dependence (exponential divergence with gel cap)
    - Composition dependence (log-mixing rule)

    Model: η = η_base(T, composition) × exp(C_visc × α / (α_gel - α))

    Where η_base is computed via log-mixing rule when species_viscosities
    are configured, otherwise falls back to single reference viscosity.

    Use cases:
        - Production accuracy simulations
        - Multi-component systems
        - When composition effects are significant
        - Validation against experimental data

    Performance: Slower (multiple property lookups, log operations)
    Accuracy: Best (validated against experiments)
    """

    def evaluate(
        self,
        T: float,
        conversions: dict[str, float],
        species_masses: dict[str, float],
        params: ViscosityParams,
    ) -> float:
        """Compute full viscosity with temperature, conversion, and composition effects."""
        # Get primary conversion (use "alpha" as default, or first conversion if multiple)
        alpha = conversions.get("alpha", 0.0)
        if not alpha and conversions:
            alpha = next(iter(conversions.values()))

        # Compute temperature-corrected base viscosity
        eta_base = self._base_viscosity(T, params, species_masses)

        # At or beyond gel point, return cap
        if alpha >= params.alpha_gel:
            return params.eta_gel

        # Exponential divergence model
        exponent = params.C_visc * alpha / (params.alpha_gel - alpha)

        # Cap exponent so result doesn't exceed eta_gel
        max_exponent = np.log(params.eta_gel / eta_base) if eta_base > 0 else 700.0
        exponent = min(exponent, max_exponent)

        return eta_base * np.exp(exponent)

    @staticmethod
    def _log_mixing_viscosity(
        species_viscosities: dict[str, float],
        species_masses: dict[str, float],
    ) -> float:
        """Compute mixture viscosity via log-mixing rule (Arrhenius mixing).

        ln(eta_mix) = sum(w_i * ln(eta_i)) for species with known viscosity.
        Species not in species_viscosities are excluded (e.g. product).

        Returns 0.0 if no species with known viscosity are present.
        """
        total_mass = 0.0
        contributions: list[tuple[float, float]] = []
        for name, mass in species_masses.items():
            if mass > 0 and name in species_viscosities:
                eta_i = species_viscosities[name]
                if eta_i > 0:
                    contributions.append((mass, np.log(eta_i)))
                    total_mass += mass

        if total_mass <= 0 or not contributions:
            return 0.0

        ln_eta_mix = sum(m / total_mass * ln_eta for m, ln_eta in contributions)
        return np.exp(ln_eta_mix)

    @staticmethod
    def _base_viscosity(
        T: float,
        params: ViscosityParams,
        species_masses: dict[str, float] | None = None,
    ) -> float:
        """Compute temperature-corrected base viscosity.

        Uses log-mixing rule when species_viscosities are configured,
        otherwise falls back to eta_ref / eta_0.
        """
        # Try composition-based mixing rule
        eta_ref = 0.0
        if (params.species_viscosities is not None
                and species_masses is not None):
            eta_ref = FullViscosity._log_mixing_viscosity(
                params.species_viscosities, species_masses
            )

        # Legacy fallback
        if eta_ref <= 0:
            eta_ref = params.eta_ref if params.eta_ref is not None else params.eta_0

        if eta_ref <= 0:
            raise ValueError(f"Base viscosity must be positive, got {eta_ref}")

        # Arrhenius temperature correction
        if params.E_eta_J_mol != 0.0 and params.T_ref_K > 0.0 and T > 0.0:
            temp_exp = params.E_eta_J_mol / R_GAS * (1.0 / T - 1.0 / params.T_ref_K)
            temp_exp = max(min(temp_exp, 700.0), -700.0)
            return eta_ref * np.exp(temp_exp)

        return eta_ref


# Registry mapping config names to model classes
VISCOSITY_REGISTRY: dict[str, type[ViscosityModel]] = {
    "constant": ConstantViscosity,
    "arrhenius": ArrheniusViscosity,
    "conversion": ConversionViscosity,
    "full_composition": FullViscosity,
}


def build_viscosity_model(model_name: str) -> ViscosityModel:
    """Factory function to build viscosity model from config string.

    Args:
        model_name: Model identifier (e.g., "constant", "arrhenius", "conversion", "full_composition").

    Returns:
        Instantiated ViscosityModel.

    Raises:
        ValueError: If model_name is not registered.

    Example:
        >>> model = build_viscosity_model("constant")
        >>> isinstance(model, ConstantViscosity)
        True
    """
    cls = VISCOSITY_REGISTRY.get(model_name)
    if cls is None:
        available = ", ".join(VISCOSITY_REGISTRY.keys())
        raise ValueError(
            f"Unknown viscosity model: '{model_name}'. "
            f"Available models: {available}"
        )
    return cls()


def register_viscosity_model(name: str, cls: type[ViscosityModel]) -> None:
    """Register a custom viscosity model for use in YAML configs.

    Args:
        name: Model identifier for configuration.
        cls: ViscosityModel subclass.

    Example:
        >>> class MyCustomViscosity(ViscosityModel):
        ...     def evaluate(self, T, conversions, species_masses, params):
        ...         return 1.0  # Custom logic
        >>> register_viscosity_model("custom", MyCustomViscosity)
    """
    if not issubclass(cls, ViscosityModel):
        raise TypeError(f"Class {cls.__name__} must inherit from ViscosityModel")
    VISCOSITY_REGISTRY[name] = cls
