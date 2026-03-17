"""Fluid mechanics correlations for stirred-tank reactors.

Provides Reynolds number, Nusselt number, heat transfer coefficient,
and mixing efficiency calculations based on impeller and fluid properties.

All correlations are optional — the physics engine falls back to
constant-UA behaviour when this module is not configured.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgitatorParams:
    """Impeller / agitator specification.

    Parameters:
        diameter_m: Impeller diameter in m (typically D_impeller ≈ D_tank / 3).
        speed_rpm: Impeller speed in rev/min.
        n_blades: Number of blades (affects power number).
        power_number: Dimensionless power number Np (Rushton ≈ 5.0, pitched-blade ≈ 1.3).
        impeller_type: Descriptive label (for logging / display only).
    """

    diameter_m: float = 0.16       # m, ~D_tank/3 for 0.50 m vessel
    speed_rpm: float = 120.0       # rpm
    n_blades: int = 6
    power_number: float = 5.0      # Rushton turbine
    impeller_type: str = "rushton"

    @classmethod
    def from_dict(cls, d: dict) -> AgitatorParams:
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: d[k] for k in d if k in fields})

    @property
    def speed_rps(self) -> float:
        """Speed in revolutions per second."""
        return self.speed_rpm / 60.0


@dataclass(frozen=True)
class FluidProps:
    """Bulk fluid properties at current conditions.

    These should be updated each timestep by the physics model.
    """

    density: float = 1100.0      # kg/m³ (typical component_a blend)
    viscosity: float = 0.5       # Pa·s (dynamic viscosity)
    thermal_conductivity: float = 0.17   # W/(m·K), typical for reactive mixture
    specific_heat: float = 1800.0        # J/(kg·K), Cp in SI

    @classmethod
    def from_dict(cls, d: dict) -> FluidProps:
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: d[k] for k in d if k in fields})


# ---------------------------------------------------------------------------
# Reynolds number
# ---------------------------------------------------------------------------

def impeller_reynolds(agitator: AgitatorParams, fluid: FluidProps) -> float:
    """Compute the impeller Reynolds number.

    Re = ρ * N * D² / μ

    where N is in rev/s, D is impeller diameter.

    Args:
        agitator: Impeller parameters.
        fluid: Current bulk fluid properties.

    Returns:
        Dimensionless Reynolds number.
    """
    N = agitator.speed_rps
    D = agitator.diameter_m
    if fluid.viscosity <= 0 or D <= 0:
        return 0.0
    return fluid.density * N * D**2 / fluid.viscosity


def flow_regime(Re: float) -> str:
    """Classify the flow regime from impeller Reynolds number.

    Returns:
        One of 'laminar', 'transitional', or 'turbulent'.
    """
    if Re < 10:
        return "laminar"
    elif Re < 10_000:
        return "transitional"
    else:
        return "turbulent"


# ---------------------------------------------------------------------------
# Nusselt number and heat transfer coefficient
# ---------------------------------------------------------------------------

def jacket_nusselt(
    Re: float,
    Pr: float,
    *,
    C: float = 0.36,
    a: float = 2 / 3,
    b: float = 1 / 3,
    mu_ratio: float = 1.0,
) -> float:
    """Compute jacket-side Nusselt number for a stirred vessel.

    Uses the standard Chilton-Drew-Jebens correlation:

        Nu = C · Re^a · Pr^b · (μ_bulk / μ_wall)^0.14

    For a Rushton turbine: C ≈ 0.36, a ≈ 2/3, b ≈ 1/3.
    For a pitched-blade turbine: C ≈ 0.53, a ≈ 2/3, b ≈ 1/3.

    Args:
        Re: Impeller Reynolds number.
        Pr: Prandtl number (Cp·μ/k).
        C: Correlation constant (depends on impeller type).
        a: Reynolds exponent.
        b: Prandtl exponent.
        mu_ratio: μ_bulk / μ_wall viscosity ratio (default 1.0).

    Returns:
        Nusselt number (dimensionless).
    """
    if Re <= 0 or Pr <= 0:
        return 1.0  # Minimum fallback (stagnant fluid)
    return C * Re**a * Pr**b * mu_ratio**0.14


def prandtl_number(fluid: FluidProps) -> float:
    """Compute Prandtl number: Pr = Cp · μ / k."""
    if fluid.thermal_conductivity <= 0:
        return 1.0
    return fluid.specific_heat * fluid.viscosity / fluid.thermal_conductivity


def jacket_htc(
    agitator: AgitatorParams,
    fluid: FluidProps,
    vessel_diameter: float,
) -> float:
    """Compute inside (process-side) heat transfer coefficient h_i.

    h_i = Nu · k / D_tank

    Args:
        agitator: Impeller specification.
        fluid: Bulk fluid properties.
        vessel_diameter: Tank inner diameter in m.

    Returns:
        Heat transfer coefficient in W/(m²·K).
    """
    Re = impeller_reynolds(agitator, fluid)
    Pr = prandtl_number(fluid)
    Nu = jacket_nusselt(Re, Pr)
    if vessel_diameter <= 0:
        return 0.0
    return Nu * fluid.thermal_conductivity / vessel_diameter


def overall_htc(
    h_inside: float,
    wall_thickness: float = 0.005,      # m, 5 mm stainless steel
    wall_conductivity: float = 16.0,    # W/(m·K), SS304
    h_jacket: float = 1000.0,           # W/(m²·K), turbulent water in jacket
) -> float:
    """Compute overall heat transfer coefficient U.

    1/U = 1/h_i + t_w/k_w + 1/h_j

    Fouling resistances are currently neglected but could be added.

    Args:
        h_inside: Process-side HTC in W/(m²·K).
        wall_thickness: Vessel wall thickness in m.
        wall_conductivity: Wall thermal conductivity in W/(m·K).
        h_jacket: Jacket-side HTC in W/(m²·K).

    Returns:
        Overall HTC (U) in W/(m²·K).
    """
    if h_inside <= 0:
        # Stagnant fluid — conduction only
        h_inside = 1.0  # minimal fallback
    R_total = 1.0 / h_inside + wall_thickness / wall_conductivity + 1.0 / h_jacket
    return 1.0 / R_total


# ---------------------------------------------------------------------------
# Mixing quality / efficiency
# ---------------------------------------------------------------------------

def mixing_efficiency(Re: float, *, Re_turb: float = 10_000.0) -> float:
    """Compute a 0-to-1 mixing efficiency factor from the Reynolds number.

    In a well-mixed (turbulent) regime the factor approaches 1.0.
    In the laminar regime it drops toward a minimum floor.

    The model uses a smooth logistic function centred on the
    transitional regime:

        η_mix = η_min + (1 - η_min) · σ(log10(Re) - log10(Re_turb))

    where σ is a sigmoid and η_min is the minimum mixing quality
    (dead zones, unmixed layers).

    Args:
        Re: Impeller Reynolds number.
        Re_turb: Reynolds number for fully turbulent regime.

    Returns:
        Mixing efficiency in [0.05, 1.0].
    """
    eta_min = 0.20  # minimum: diffusion-controlled reaction continues even in gelled material

    if Re <= 0:
        return eta_min

    # Sigmoid transition over ~2 decades of Re
    log_Re = math.log10(max(Re, 1.0))
    log_turb = math.log10(Re_turb)
    # Steepness: transition over ~2 decades (from ~100 to ~10000)
    steepness = 2.5
    x = steepness * (log_Re - log_turb + 1.0)  # shift so transition centres at Re_turb/10
    sigmoid = 1.0 / (1.0 + math.exp(-x))
    return eta_min + (1.0 - eta_min) * sigmoid


def power_draw(agitator: AgitatorParams, fluid: FluidProps) -> float:
    """Estimate shaft power draw in Watts.

    P = Np · ρ · N³ · D⁵

    Useful for energy balance (frictional heating) and operational display.

    Args:
        agitator: Impeller specification.
        fluid: Bulk fluid properties.

    Returns:
        Power draw in W.
    """
    N = agitator.speed_rps
    D = agitator.diameter_m
    return agitator.power_number * fluid.density * N**3 * D**5


# ---------------------------------------------------------------------------
# Convenience: compute all fluid-mechanics quantities in one call
# ---------------------------------------------------------------------------

@dataclass
class FluidMechanicsState:
    """Snapshot of all computed fluid-mechanics quantities.

    All values are in SI units unless noted.
    """

    Re: float = 0.0
    regime: str = "laminar"
    Pr: float = 1.0
    Nu: float = 1.0
    h_inside: float = 10.0       # W/(m²·K)
    U: float = 10.0              # W/(m²·K), overall HTC
    mixing_efficiency: float = 1.0
    power_W: float = 0.0
    UA_dynamic: float = 0.0      # W/K = U · A_wetted

    @property
    def UA_kW_per_K(self) -> float:
        """UA in kW/K (compatible with existing thermal model units)."""
        return self.UA_dynamic / 1000.0


def compute_fluid_mechanics(
    agitator: AgitatorParams,
    fluid: FluidProps,
    vessel_diameter: float,
    wetted_area: float,
    *,
    wall_thickness: float = 0.005,
    wall_conductivity: float = 16.0,
    h_jacket: float = 1000.0,
) -> FluidMechanicsState:
    """Compute all fluid-mechanics quantities in one call.

    Args:
        agitator: Impeller specification.
        fluid: Current bulk fluid properties.
        vessel_diameter: Tank inner diameter in m.
        wetted_area: Current wetted wall area in m².
        wall_thickness: Vessel wall thickness in m.
        wall_conductivity: Wall thermal conductivity in W/(m·K).
        h_jacket: Jacket-side HTC in W/(m²·K).

    Returns:
        FluidMechanicsState with all computed quantities.
    """
    Re = impeller_reynolds(agitator, fluid)
    regime = flow_regime(Re)
    Pr = prandtl_number(fluid)
    Nu = jacket_nusselt(Re, Pr)
    h_i = jacket_htc(agitator, fluid, vessel_diameter)
    U = overall_htc(h_i, wall_thickness, wall_conductivity, h_jacket)
    eta = mixing_efficiency(Re)
    P = power_draw(agitator, fluid)
    UA = U * wetted_area

    return FluidMechanicsState(
        Re=Re,
        regime=regime,
        Pr=Pr,
        Nu=Nu,
        h_inside=h_i,
        U=U,
        mixing_efficiency=eta,
        power_W=P,
        UA_dynamic=UA,
    )
