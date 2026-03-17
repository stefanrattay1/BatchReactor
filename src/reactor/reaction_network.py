"""General reaction network framework for arbitrary chemistry.

Defines species, rate laws, reactions, and networks that work with both
Pyomo symbolic expressions and numpy numerics via duck-typed math operations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Callable

import numpy as np

# --- Constants ---
R_GAS = 8.314  # J/(mol*K)
REACTANT_AVAILABILITY_EPS_KG = 0.001  # Sub-gram threshold for smooth reactant depletion cutoff


# ---------------------------------------------------------------------------
# Math operations namespace -- allows rate laws to work in both contexts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MathOps:
    """Math operations that work in both Pyomo and numpy contexts."""

    exp: Callable
    log: Callable

    @classmethod
    def numpy(cls) -> MathOps:
        return cls(exp=np.exp, log=np.log)

    @classmethod
    def pyomo(cls) -> MathOps:
        import pyomo.environ as pyo
        return cls(exp=pyo.exp, log=pyo.log)


# ---------------------------------------------------------------------------
# Species
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Species:
    """A chemical species participating in the reaction network."""

    name: str
    density: float = 1.0       # kg/L
    phase: str = "liquid"
    molar_mass: float | None = None  # g/mol, optional
    inert: bool = False        # inert species don't participate in reactions
    initial_mass: float = 0.0  # kg, default starting mass

    @classmethod
    def from_dict(cls, d: dict) -> Species:
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: d[k] for k in d if k in fields})


# ---------------------------------------------------------------------------
# Rate laws (abstract base + concrete implementations)
# ---------------------------------------------------------------------------

class RateLaw(ABC):
    """Abstract base class for reaction rate laws.

    Rate laws must work with both plain floats (numpy fallback) and
    Pyomo expression objects (DAE solver) via the injected MathOps.
    """

    @abstractmethod
    def evaluate(
        self,
        species_masses: dict[str, Any],
        conversions: dict[str, Any],
        T: Any,
        params: dict[str, float],
        ops: MathOps,
    ) -> Any:
        """Compute the reaction rate.

        Args:
            species_masses: Species name -> mass (float or Pyomo Var).
            conversions: Conversion variable name -> value.
            T: Temperature in K.
            params: Kinetic parameters for this reaction.
            ops: Math operations namespace.

        Returns:
            Rate value (float or Pyomo expression).
        """


class KamalSourourRate(RateLaw):
    """Kamal-Sourour autocatalytic rate: (k1 + k2 * alpha^m) * (1-alpha)^n.

    Requires a conversion variable. Parameters: A1, Ea1, A2, Ea2, m, n.
    """

    def __init__(self, conversion_var: str = "alpha"):
        self.conversion_var = conversion_var

    def evaluate(self, species_masses, conversions, T, params, ops):
        alpha = conversions[self.conversion_var]
        k1 = params["A1"] * ops.exp(-params["Ea1"] / (R_GAS * T))
        k2 = params["A2"] * ops.exp(-params["Ea2"] / (R_GAS * T))
        return (k1 + k2 * alpha ** params["m"]) * (1.0 - alpha) ** params["n"]


class NthOrderRate(RateLaw):
    """Simple n-th order Arrhenius rate: A * exp(-Ea/RT) * (1-alpha)^n.

    Uses a conversion variable to track extent. Parameters: A, Ea, n.
    """

    def __init__(self, conversion_var: str | None = None):
        self.conversion_var = conversion_var

    def evaluate(self, species_masses, conversions, T, params, ops):
        k = params["A"] * ops.exp(-params["Ea"] / (R_GAS * T))
        if self.conversion_var and self.conversion_var in conversions:
            alpha = conversions[self.conversion_var]
            return k * (1.0 - alpha) ** params["n"]
        # Mass-based: rate proportional to reactant mass
        return k


class ArrheniusRate(RateLaw):
    """Generalized Arrhenius rate: A * exp(-Ea/RT) * product(m_i^order_i).

    Parameters: A, Ea, plus 'order_{species}' for each participating species.
    """

    def evaluate(self, species_masses, conversions, T, params, ops):
        k = params["A"] * ops.exp(-params["Ea"] / (R_GAS * T))
        rate = k
        for key, val in params.items():
            if key.startswith("order_"):
                species_name = key[6:]  # strip "order_"
                if species_name in species_masses:
                    rate = rate * species_masses[species_name] ** val
        return rate


# Registry of built-in rate law types
RATE_LAW_REGISTRY: dict[str, type[RateLaw]] = {
    "kamal_sourour": KamalSourourRate,
    "nth_order": NthOrderRate,
    "arrhenius": ArrheniusRate,
}


# ---------------------------------------------------------------------------
# Reaction
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reaction:
    """A single reaction with stoichiometry, rate law, and thermodynamics."""

    name: str
    rate_law: RateLaw
    parameters: dict[str, float]
    stoichiometry: dict[str, float]  # species_name -> coefficient (negative = consumed)
    delta_H: float = 0.0            # kJ/kg of heat_basis species
    heat_basis: str | None = None    # species whose initial mass is the enthalpy basis
    conversion_variable: str | None = None  # optional conversion extent to track

    @property
    def consumed_species(self) -> list[str]:
        """Species with negative stoichiometric coefficients."""
        return [s for s, c in self.stoichiometry.items() if c < 0]

    @property
    def produced_species(self) -> list[str]:
        """Species with positive stoichiometric coefficients."""
        return [s for s, c in self.stoichiometry.items() if c > 0]


# ---------------------------------------------------------------------------
# Reaction Network
# ---------------------------------------------------------------------------

@dataclass
class ReactionNetwork:
    """A complete reaction network with N species and M reactions."""

    species: list[Species]
    reactions: list[Reaction]

    def __post_init__(self) -> None:
        """Validate network consistency at construction time."""
        # Check species name uniqueness
        species_names = [s.name for s in self.species]
        if len(species_names) != len(set(species_names)):
            duplicates = [name for name in set(species_names) if species_names.count(name) > 1]
            raise ValueError(f"Duplicate species names: {duplicates}")

        # Check reaction name uniqueness
        reaction_names = [r.name for r in self.reactions]
        if len(reaction_names) != len(set(reaction_names)):
            duplicates = [name for name in set(reaction_names) if reaction_names.count(name) > 1]
            raise ValueError(f"Duplicate reaction names: {duplicates}")

        # Check stoichiometry references valid species
        for rxn in self.reactions:
            for sp_name in rxn.stoichiometry:
                if sp_name not in species_names:
                    raise ValueError(
                        f"Reaction '{rxn.name}' references unknown species '{sp_name}'. "
                        f"Known species: {species_names}"
                    )

        # Check stoichiometry has at least one reactant and product
        for rxn in self.reactions:
            has_reactant = any(coeff < 0 for coeff in rxn.stoichiometry.values())
            has_product = any(coeff > 0 for coeff in rxn.stoichiometry.values())
            if not (has_reactant and has_product):
                raise ValueError(
                    f"Reaction '{rxn.name}' must have both reactants (negative coeff) "
                    f"and products (positive coeff). Got: {rxn.stoichiometry}"
                )

    @cached_property
    def species_names(self) -> list[str]:
        return [s.name for s in self.species]

    @cached_property
    def species_by_name(self) -> dict[str, Species]:
        return {s.name: s for s in self.species}

    @cached_property
    def conversion_names(self) -> list[str]:
        """All conversion variables tracked by reactions."""
        names = []
        for rxn in self.reactions:
            if rxn.conversion_variable and rxn.conversion_variable not in names:
                names.append(rxn.conversion_variable)
        return names

    def compute_rates(
        self,
        species_masses: dict[str, float],
        conversions: dict[str, float],
        T: float,
        ops: MathOps,
        feed_rates: dict[str, float] | None = None,
        initial_masses: dict[str, float] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], Any]:
        """Compute all rates of change for the network.

        Args:
            species_masses: Current mass of each species (kg).
            conversions: Current value of each conversion variable.
            T: Temperature (K).
            ops: Math operations namespace.
            feed_rates: Feed rate for each species (kg/s).
            initial_masses: Initial masses for heat-of-reaction basis.

        Returns:
            Tuple of (dm_dt dict, dconv_dt dict, Q_rxn_total).
        """
        feeds = feed_rates or {}
        bases = initial_masses or {}

        # Initialize mass rates with feed rates
        dm_dt: dict[str, Any] = {s.name: feeds.get(s.name, 0.0) for s in self.species}
        dconv_dt: dict[str, Any] = {c: 0.0 for c in self.conversion_names}
        q_rxn_total: Any = 0.0

        for rxn in self.reactions:
            # Compute raw rate from rate law
            raw_rate = rxn.rate_law.evaluate(
                species_masses, conversions, T, rxn.parameters, ops,
            )

            # Reactant availability factor: smooth cutoff when reactants depleted
            availability: Any = 1.0
            for sp_name in rxn.consumed_species:
                m_sp = species_masses.get(sp_name, 0.0)
                availability = availability * (m_sp / (m_sp + REACTANT_AVAILABILITY_EPS_KG))

            rate = raw_rate * availability

            # Heat basis mass (initial mass of the reference species)
            basis_mass = bases.get(rxn.heat_basis, 0.01) if rxn.heat_basis else 0.01
            basis_mass = max(basis_mass, 0.01)

            # Mass balance contributions
            for sp_name, coeff in rxn.stoichiometry.items():
                dm_dt[sp_name] = dm_dt.get(sp_name, 0.0) + coeff * basis_mass * rate

            # Conversion variable update
            if rxn.conversion_variable:
                dconv_dt[rxn.conversion_variable] = (
                    dconv_dt.get(rxn.conversion_variable, 0.0) + rate
                )

            # Heat generation
            q_rxn_total = q_rxn_total + rxn.delta_H * basis_mass * rate

        return dm_dt, dconv_dt, q_rxn_total


# ---------------------------------------------------------------------------
# Config-to-network builder
# ---------------------------------------------------------------------------

def _build_rate_law(rate_law_name: str, rxn_cfg: dict) -> RateLaw:
    """Instantiate a RateLaw from its name and reaction config."""
    conv_var = rxn_cfg.get("conversion_variable")
    if rate_law_name == "kamal_sourour":
        return KamalSourourRate(conversion_var=conv_var or "alpha")
    elif rate_law_name == "nth_order":
        return NthOrderRate(conversion_var=conv_var)
    elif rate_law_name == "arrhenius":
        return ArrheniusRate()
    else:
        raise ValueError(f"Unknown rate law: {rate_law_name}")


def build_network_from_yaml(network_cfg: dict) -> ReactionNetwork:
    """Build a ReactionNetwork from the 'reaction_network' YAML section."""
    species_list = [Species.from_dict(s) for s in network_cfg["species"]]

    reactions = []
    for rxn_cfg in network_cfg["reactions"]:
        rate_law = _build_rate_law(rxn_cfg["rate_law"], rxn_cfg)
        # Convert all parameter values to float (handles YAML parsing quirks)
        raw_params = rxn_cfg.get("parameters", {})
        parameters = {k: float(v) for k, v in raw_params.items()}
        # Convert all stoichiometry values to float
        raw_stoich = rxn_cfg.get("stoichiometry", {})
        stoichiometry = {k: float(v) for k, v in raw_stoich.items()}

        reactions.append(Reaction(
            name=rxn_cfg["name"],
            rate_law=rate_law,
            parameters=parameters,
            stoichiometry=stoichiometry,
            delta_H=float(rxn_cfg.get("delta_H", 0.0)),
            heat_basis=rxn_cfg.get("heat_basis"),
            conversion_variable=rxn_cfg.get("conversion_variable"),
        ))

    return ReactionNetwork(species=species_list, reactions=reactions)


def build_legacy_network(kinetics: dict, physics: dict) -> ReactionNetwork:
    """Auto-generate a ReactionNetwork from legacy kinetics/physics config.

    Reproduces the original Kamal-Sourour model with 4 species and 1 reaction.
    """
    stoich = physics.get("stoich_ratio", 0.3)

    species_list = [
        Species(name="component_a", density=physics.get("density_component_a", 1.16)),
        Species(name="component_b", density=physics.get("density_component_b", 0.97)),
        Species(name="product", density=physics.get("density_product", 1.20)),
        Species(name="solvent", density=physics.get("density_solvent", 0.87), inert=True),
    ]

    rate_law = KamalSourourRate(conversion_var="alpha")
    reaction = Reaction(
        name="main_reaction",
        rate_law=rate_law,
        parameters={
            "A1": kinetics["A1"],
            "Ea1": kinetics["Ea1"],
            "A2": kinetics["A2"],
            "Ea2": kinetics["Ea2"],
            "m": kinetics["m"],
            "n": kinetics["n"],
        },
        stoichiometry={
            "component_a": -1.0,
            "component_b": -stoich,
            "product": 1.0 + stoich,
        },
        delta_H=kinetics["delta_H"],
        heat_basis="component_a",
        conversion_variable="alpha",
    )

    return ReactionNetwork(species=species_list, reactions=[reaction])


def build_network_from_config(config) -> ReactionNetwork:
    """Build a ReactionNetwork from a ModelConfig.

    If the config has a 'reaction_network' section, parse it.
    Otherwise, auto-generate the legacy Kamal-Sourour network.
    """
    if hasattr(config, 'raw') and "reaction_network" in config.raw:
        return build_network_from_yaml(config.raw["reaction_network"])
    return build_legacy_network(config.kinetics, config.physics)
