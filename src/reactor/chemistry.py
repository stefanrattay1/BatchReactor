"""Reaction kinetics, thermodynamics, and viscosity models for batch reactor simulation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

R_GAS = 8.314  # J/(mol*K)


@dataclass(frozen=True)
class KineticParams:
    """Kamal-Sourour autocatalytic model parameters."""

    A1: float = 1.0e4       # s^-1, pre-exponential (catalytic path)
    Ea1: float = 55_000.0   # J/mol, activation energy path 1
    A2: float = 1.0e6       # s^-1, pre-exponential (autocatalytic path)
    Ea2: float = 45_000.0   # J/mol, activation energy path 2
    m: float = 0.5          # autocatalytic exponent
    n: float = 1.5          # reaction order exponent
    delta_H: float = 350.0  # kJ/kg of component_a, total heat of reaction
    alpha_gel: float = 0.6  # gel point conversion

    @classmethod
    def from_dict(cls, d: dict) -> KineticParams:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass(frozen=True)
class ThermalParams:
    """Heat transfer parameters for the reactor."""

    Cp: float = 1.8    # kJ/(kg*K), specific heat of mixture
    UA: float = 0.5    # kW/K, overall heat transfer coeff * area

    @classmethod
    def from_dict(cls, d: dict) -> ThermalParams:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass(frozen=True)
class ViscosityParams:
    """Viscosity model parameters (exponential divergence with gel cap).

    Model: eta = eta_base(T) * exp(C_visc * alpha / (alpha_gel - alpha))
    Capped at eta_gel for alpha >= alpha_gel.
    """

    eta_0: float = 0.5           # Pa*s, fallback base viscosity at T_ref_K
    eta_ref: float | None = None # Pa*s, reference viscosity at T_ref_K
    T_ref_K: float = 298.15      # K, reference temperature
    E_eta_J_mol: float = 0.0     # J/mol, viscosity activation energy (Arrhenius)
    C_visc: float = 4.0          # dimensionless shape parameter
    alpha_gel: float = 0.6       # gel point conversion
    eta_gel: float = 100.0       # Pa*s, viscosity cap at/beyond gel point

    # Per-species viscosity at T_ref_K for log-mixing rule (optional).
    # Species not listed are excluded from the mixture calculation.
    species_viscosities: dict[str, float] | None = None

    @classmethod
    def from_dict(cls, d: dict) -> ViscosityParams:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def reaction_rate(alpha: float, T: float, params: KineticParams) -> float:
    """Compute d(alpha)/dt using the Kamal-Sourour autocatalytic model.

    Args:
        alpha: Conversion (0 to 1).
        T: Temperature in Kelvin.
        params: Kinetic parameters.

    Returns:
        Rate of conversion change in s^-1.
    """
    if alpha >= 1.0:
        return 0.0
    k1 = params.A1 * np.exp(-params.Ea1 / (R_GAS * T))
    k2 = params.A2 * np.exp(-params.Ea2 / (R_GAS * T))
    alpha_safe = max(alpha, 0.0)
    return (k1 + k2 * alpha_safe ** params.m) * (1.0 - alpha_safe) ** params.n


def heat_of_reaction(d_alpha_dt: float, mass_component_a: float, params: KineticParams) -> float:
    """Compute heat generation rate in kW.

    Args:
        d_alpha_dt: Rate of conversion change in s^-1.
        mass_component_a: Initial component_a mass in kg (basis for delta_H).
        params: Kinetic parameters.

    Returns:
        Heat generation rate in kW.
    """
    return params.delta_H * mass_component_a * d_alpha_dt


def heat_transfer(T_reactor: float, T_jacket: float, thermal: ThermalParams,
                   UA_override: float | None = None) -> float:
    """Compute heat transfer rate from jacket to reactor in kW.

    Positive means heat flows into the reactor (jacket hotter than reactor).

    Args:
        T_reactor: Reactor temperature in K.
        T_jacket: Jacket temperature in K.
        thermal: Thermal parameters (used for UA if no override).
        UA_override: If provided, use this UA value (kW/K) instead of
            the constant from thermal params.  This allows the physics
            engine to inject a dynamically computed UA from the
            fluid-mechanics module.
    """
    ua = UA_override if UA_override is not None else thermal.UA
    return ua * (T_jacket - T_reactor)


def _log_mixing_viscosity(
    species_viscosities: dict[str, float],
    species_masses: dict[str, float],
) -> float:
    """Compute mixture viscosity via log-mixing rule (Arrhenius mixing).

    ln(eta_mix) = sum(w_i * ln(eta_i)) for species with known viscosity.
    Species not in *species_viscosities* are excluded (e.g. product).

    Returns 0.0 if no species with known viscosity are present (signals
    the caller to use the legacy fallback).
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
        eta_ref = _log_mixing_viscosity(params.species_viscosities, species_masses)

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


def viscosity(
    alpha: float,
    T: float,
    params: ViscosityParams,
    species_masses: dict[str, float] | None = None,
) -> float:
    """Compute viscosity in Pa*s using exponential divergence with gel cap.

    Model: eta = eta_base(T) * exp(C_visc * alpha / (alpha_gel - alpha))

    Where eta_base is either a composition-weighted mixture viscosity
    (log-mixing rule) or a single reference value with Arrhenius correction.

    At and beyond gel point (alpha >= alpha_gel), returns eta_gel.

    Args:
        alpha: Conversion (0 to 1).
        T: Temperature in Kelvin.
        params: Viscosity model parameters.
        species_masses: Current species masses in kg. Used for log-mixing
            rule when params.species_viscosities is configured.

    Returns:
        Viscosity in Pa*s, capped at eta_gel.
    """
    eta_base = _base_viscosity(T, params, species_masses)

    # At or beyond gel point, return cap
    if alpha >= params.alpha_gel:
        return params.eta_gel

    # Exponential divergence model
    exponent = params.C_visc * alpha / (params.alpha_gel - alpha)

    # Cap exponent so result doesn't exceed eta_gel
    max_exponent = np.log(params.eta_gel / eta_base) if eta_base > 0 else 700.0
    exponent = min(exponent, max_exponent)

    return eta_base * np.exp(exponent)
