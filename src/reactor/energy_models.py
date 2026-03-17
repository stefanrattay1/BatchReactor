"""Pluggable energy balance models for reactor simulation.

This module provides modular energy balance calculations,
allowing users to select between isothermal, adiabatic, full, and
extended energy balance models.

Pattern:
    - Abstract base class `EnergyModel` defines the protocol
    - Concrete implementations for different thermal scenarios
    - Registry dict maps config names to classes
    - Factory function builds instances from config strings
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EnergyModel(ABC):
    """Protocol for energy balance calculations.

    All energy models must implement compute_dT_dt() which returns
    the rate of temperature change given the various heat flows.
    """

    @abstractmethod
    def compute_dT_dt(self, Q_rxn, Q_jacket, Q_frictional, m_total, Cp):
        """Compute rate of temperature change.

        Accepts both numeric (float) and Pyomo symbolic expression arguments,
        enabling use in both the scipy fallback solver and Pyomo DAE constraints.

        Args:
            Q_rxn: Heat of reaction in kW (positive = exothermic).
            Q_jacket: Heat transfer from jacket in kW (positive = heating).
            Q_frictional: Frictional heating from agitator in kW.
            m_total: Total mass in reactor in kg. Must be > 0.
            Cp: Specific heat capacity in kJ/(kg·K). Must be > 0.

        Returns:
            Temperature rate of change in K/s (or Pyomo expression).
        """


class IsothermalModel(EnergyModel):
    """Isothermal energy balance: dT/dt = 0.

    Temperature is held constant - perfect temperature control.
    All reaction heat is instantly removed by the jacket.

    Use cases:
        - Isothermal reactor studies
        - Kinetic parameter estimation (eliminate thermal effects)
        - Studying kinetics without thermal coupling
        - Perfect temperature control assumption

    Performance: Fastest (no calculation)
    Accuracy: Good for isothermal reactors, unrealistic otherwise

    Notes:
        - Physically equivalent to infinite jacket cooling capacity
        - Useful for decoupling kinetics from thermal effects
        - Temperature must be set via initial conditions or control
    """

    def compute_dT_dt(
        self,
        Q_rxn: float,
        Q_jacket: float,
        Q_frictional: float,
        m_total: float,
        Cp: float,
    ) -> float:
        """Return zero temperature change (isothermal)."""
        return 0.0


class AdiabaticModel(EnergyModel):
    """Adiabatic energy balance: dT/dt = Q_rxn / (m · Cp).

    No heat exchange with surroundings - all reaction heat accumulates
    in the reactor mass. Represents worst-case scenario for runaway.

    Model: dT/dt = Q_rxn / (m_total · Cp)

    Ignores:
        - Jacket heat transfer (Q_jacket)
        - Frictional heating (Q_frictional)

    Use cases:
        - Worst-case thermal runaway analysis
        - Safety studies (vent sizing, DIERS)
        - Cooling failure scenarios
        - Adiabatic temperature rise calculations

    Performance: Fast (simple division)
    Accuracy: Conservative (worst-case) for safety analysis

    Notes:
        - Predicts maximum possible temperature rise
        - Used in process safety: ΔT_ad = (-ΔH_rxn × conversion) / Cp
        - Jacket temperature setting ignored
    """

    def compute_dT_dt(
        self,
        Q_rxn,
        Q_jacket,
        Q_frictional,
        m_total,
        Cp,
    ):
        """Compute adiabatic temperature rise from reaction heat only."""
        return Q_rxn / (m_total * Cp)


class FullEnergyModel(EnergyModel):
    """Full energy balance: dT/dt = (Q_rxn + Q_jacket) / (m · Cp).

    Standard batch reactor energy balance including reaction heat
    and jacket heat transfer.

    Model: dT/dt = (Q_rxn + Q_jacket) / (m_total · Cp)

    Includes:
        - Reaction heat (Q_rxn)
        - Jacket heat transfer (Q_jacket)

    Ignores:
        - Frictional heating from agitator (typically negligible)
        - Heat of mixing, vaporization

    Use cases:
        - Standard batch reactor operation
        - Production simulations
        - Process development
        - Most realistic for jacketed batch reactors

    Performance: Fast (simple arithmetic)
    Accuracy: Good for jacketed batch reactors

    Notes:
        - This is the standard energy balance for batch reactors
        - Frictional heating typically <1% of reaction heat
        - Assumes constant Cp (reasonable for liquid-phase reactions)
    """

    def compute_dT_dt(
        self,
        Q_rxn,
        Q_jacket,
        Q_frictional,
        m_total,
        Cp,
    ):
        """Compute temperature change from reaction and jacket heat."""
        return (Q_rxn + Q_jacket) / (m_total * Cp)


class ExtendedEnergyModel(EnergyModel):
    """Extended energy balance: dT/dt = (Q_rxn + Q_jacket + Q_fric) / (m · Cp).

    Full energy balance including frictional heating from agitation.
    Most complete thermal model.

    Model: dT/dt = (Q_rxn + Q_jacket + Q_frictional) / (m_total · Cp)

    Includes:
        - Reaction heat (Q_rxn)
        - Jacket heat transfer (Q_jacket)
        - Frictional heating from impeller (Q_frictional)

    Additional terms (not yet implemented):
        - Heat of mixing (typically negligible)
        - Vaporization/condensation (not applicable for closed systems)

    Use cases:
        - High-speed mixing operations (>1000 RPM)
        - Very viscous fluids (η > 10 Pa·s)
        - Large-scale reactors with significant agitator power
        - When frictional heating is >5% of reaction heat

    Performance: Fast (simple arithmetic)
    Accuracy: Best (most complete)

    Notes:
        - Frictional heating: Q_fric = P_agitator = Np·ρ·N³·D⁵
        - Typically negligible (<1%) for low-viscosity fluids
        - Can be significant (>10%) for highly viscous materials
        - Important for accurate prediction in gelation regimes
    """

    def compute_dT_dt(
        self,
        Q_rxn,
        Q_jacket,
        Q_frictional,
        m_total,
        Cp,
    ):
        """Compute temperature change including frictional heating."""
        return (Q_rxn + Q_jacket + Q_frictional) / (m_total * Cp)


# Registry mapping config names to model classes
ENERGY_REGISTRY: dict[str, type[EnergyModel]] = {
    "isothermal": IsothermalModel,
    "adiabatic": AdiabaticModel,
    "full": FullEnergyModel,
    "extended": ExtendedEnergyModel,
}


def build_energy_model(model_name: str) -> EnergyModel:
    """Factory function to build energy model from config string.

    Args:
        model_name: Model identifier (e.g., "isothermal", "adiabatic", "full", "extended").

    Returns:
        Instantiated EnergyModel.

    Raises:
        ValueError: If model_name is not registered.

    Example:
        >>> model = build_energy_model("full")
        >>> isinstance(model, FullEnergyModel)
        True
    """
    cls = ENERGY_REGISTRY.get(model_name)
    if cls is None:
        available = ", ".join(ENERGY_REGISTRY.keys())
        raise ValueError(
            f"Unknown energy model: '{model_name}'. "
            f"Available models: {available}"
        )
    return cls()


def register_energy_model(name: str, cls: type[EnergyModel]) -> None:
    """Register a custom energy model for use in YAML configs.

    Args:
        name: Model identifier for configuration.
        cls: EnergyModel subclass.

    Example:
        >>> class MyCustomEnergy(EnergyModel):
        ...     def compute_dT_dt(self, Q_rxn, Q_jacket, Q_frictional, m_total, Cp):
        ...         return 0.1  # Custom logic
        >>> register_energy_model("custom", MyCustomEnergy)
    """
    if not issubclass(cls, EnergyModel):
        raise TypeError(f"Class {cls.__name__} must inherit from EnergyModel")
    ENERGY_REGISTRY[name] = cls
