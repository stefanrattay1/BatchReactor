"""Tests for the reaction network framework."""

import math

import numpy as np
import pytest

from reactor.chemistry import KineticParams, reaction_rate
from reactor.reaction_network import (
    ArrheniusRate,
    KamalSourourRate,
    MathOps,
    NthOrderRate,
    Reaction,
    ReactionNetwork,
    Species,
    build_legacy_network,
    build_network_from_yaml,
)


class TestMathOps:
    def test_numpy_ops(self):
        ops = MathOps.numpy()
        assert pytest.approx(ops.exp(0.0)) == 1.0
        assert pytest.approx(ops.log(1.0)) == 0.0

    def test_pyomo_ops(self):
        ops = MathOps.pyomo()
        # Pyomo ops work on plain floats too
        assert pytest.approx(float(ops.exp(0.0))) == 1.0


class TestSpecies:
    def test_from_dict(self):
        sp = Species.from_dict({"name": "component_a", "density": 1.16, "phase": "liquid"})
        assert sp.name == "component_a"
        assert sp.density == 1.16

    def test_defaults(self):
        sp = Species(name="test")
        assert sp.density == 1.0
        assert sp.inert is False


class TestKamalSourourRate:
    def test_matches_legacy(self):
        """KamalSourourRate should produce the same result as chemistry.reaction_rate."""
        params = KineticParams()
        rate_law = KamalSourourRate(conversion_var="alpha")
        ops = MathOps.numpy()

        # Test at several alpha/T combinations
        # Note: alpha=0 works with numpy (0^0.5=0), but Pyomo needs alpha>=1e-8
        for alpha in [0.0, 0.1, 0.3, 0.5, 0.8]:
            for T in [320.0, 353.15, 380.0]:
                legacy_rate = reaction_rate(alpha, T, params)
                network_rate = rate_law.evaluate(
                    species_masses={},
                    conversions={"alpha": alpha},
                    T=T,
                    params={
                        "A1": params.A1, "Ea1": params.Ea1,
                        "A2": params.A2, "Ea2": params.Ea2,
                        "m": params.m, "n": params.n,
                    },
                    ops=ops,
                )
                assert pytest.approx(network_rate, rel=1e-6) == legacy_rate, \
                    f"Mismatch at alpha={alpha}, T={T}"


class TestNthOrderRate:
    def test_first_order(self):
        rate_law = NthOrderRate(conversion_var="alpha")
        ops = MathOps.numpy()
        result = rate_law.evaluate(
            species_masses={},
            conversions={"alpha": 0.5},
            T=353.15,
            params={"A": 1.0e4, "Ea": 55000.0, "n": 1.0},
            ops=ops,
        )
        # k = A * exp(-Ea/RT) * (1-0.5)^1
        k = 1.0e4 * np.exp(-55000.0 / (8.314 * 353.15))
        expected = k * 0.5
        assert pytest.approx(result, rel=1e-6) == expected

    def test_zero_conversion_max_rate(self):
        rate_law = NthOrderRate(conversion_var="alpha")
        ops = MathOps.numpy()
        result = rate_law.evaluate(
            species_masses={},
            conversions={"alpha": 1e-8},
            T=353.15,
            params={"A": 1.0e4, "Ea": 55000.0, "n": 1.5},
            ops=ops,
        )
        assert result > 0.0


class TestArrheniusRate:
    def test_with_species_orders(self):
        rate_law = ArrheniusRate()
        ops = MathOps.numpy()
        result = rate_law.evaluate(
            species_masses={"A": 10.0, "B": 5.0},
            conversions={},
            T=353.15,
            params={"A": 1.0e4, "Ea": 50000.0, "order_A": 1.0, "order_B": 0.5},
            ops=ops,
        )
        k = 1.0e4 * np.exp(-50000.0 / (8.314 * 353.15))
        expected = k * 10.0 ** 1.0 * 5.0 ** 0.5
        assert pytest.approx(result, rel=1e-6) == expected


class TestReactionNetwork:
    @pytest.fixture
    def legacy_network(self) -> ReactionNetwork:
        kinetics = {
            "A1": 1.0e4, "Ea1": 55000.0, "A2": 1.0e6, "Ea2": 45000.0,
            "m": 0.5, "n": 1.5, "delta_H": 350.0, "alpha_gel": 0.6,
        }
        physics = {"stoich_ratio": 0.3, "density_component_a": 1.16, "density_component_b": 0.97,
                    "density_product": 1.20, "density_solvent": 0.87}
        return build_legacy_network(kinetics, physics)

    def test_legacy_species_names(self, legacy_network):
        assert legacy_network.species_names == ["component_a", "component_b", "product", "solvent"]

    def test_legacy_conversion_names(self, legacy_network):
        assert legacy_network.conversion_names == ["alpha"]

    def test_legacy_reaction_count(self, legacy_network):
        assert len(legacy_network.reactions) == 1
        assert legacy_network.reactions[0].name == "main_reaction"

    def test_compute_rates_nonzero(self, legacy_network):
        dm_dt, dconv_dt, q_rxn = legacy_network.compute_rates(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.1},
            T=353.15,
            ops=MathOps.numpy(),
            initial_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
        )
        assert dconv_dt["alpha"] > 0.0
        assert dm_dt["component_a"] < 0.0  # component_a consumed
        assert dm_dt["component_b"] < 0.0  # component_b consumed
        assert dm_dt["product"] > 0.0  # product formed
        assert q_rxn > 0.0  # exothermic

    def test_mass_conservation(self, legacy_network):
        """Net mass change from reaction should be zero (stoich balances)."""
        dm_dt, _, _ = legacy_network.compute_rates(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.1},
            T=353.15,
            ops=MathOps.numpy(),
            initial_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
        )
        # Total dm_dt should be ~0 (no feeds, stoich sums to 0)
        net_dm = sum(dm_dt.values())
        assert pytest.approx(net_dm, abs=1e-10) == 0.0


class TestBuildNetworkFromYaml:
    def test_sequential_network(self):
        cfg = {
            "species": [
                {"name": "component_a", "density": 1.16},
                {"name": "intermediate", "density": 1.10},
                {"name": "product", "density": 1.20},
            ],
            "reactions": [
                {
                    "name": "step_1",
                    "rate_law": "nth_order",
                    "conversion_variable": "alpha_1",
                    "parameters": {"A": 1.0e4, "Ea": 55000.0, "n": 1.5},
                    "stoichiometry": {"component_a": -1.0, "intermediate": 1.0},
                    "delta_H": 200.0,
                    "heat_basis": "component_a",
                },
                {
                    "name": "step_2",
                    "rate_law": "nth_order",
                    "conversion_variable": "alpha_2",
                    "parameters": {"A": 1.0e5, "Ea": 50000.0, "n": 1.0},
                    "stoichiometry": {"intermediate": -1.0, "product": 1.0},
                    "delta_H": 150.0,
                    "heat_basis": "intermediate",
                },
            ],
        }
        network = build_network_from_yaml(cfg)
        assert network.species_names == ["component_a", "intermediate", "product"]
        assert network.conversion_names == ["alpha_1", "alpha_2"]
        assert len(network.reactions) == 2

    def test_sequential_rates(self):
        cfg = {
            "species": [
                {"name": "A", "density": 1.0},
                {"name": "B", "density": 1.0},
                {"name": "C", "density": 1.0},
            ],
            "reactions": [
                {
                    "name": "rxn_1",
                    "rate_law": "nth_order",
                    "conversion_variable": "alpha_1",
                    "parameters": {"A": 1.0e4, "Ea": 50000.0, "n": 1.0},
                    "stoichiometry": {"A": -1.0, "B": 1.0},
                    "delta_H": 100.0,
                    "heat_basis": "A",
                },
                {
                    "name": "rxn_2",
                    "rate_law": "nth_order",
                    "conversion_variable": "alpha_2",
                    "parameters": {"A": 1.0e3, "Ea": 40000.0, "n": 1.0},
                    "stoichiometry": {"B": -1.0, "C": 1.0},
                    "delta_H": 50.0,
                    "heat_basis": "B",
                },
            ],
        }
        network = build_network_from_yaml(cfg)
        dm_dt, dconv_dt, q_rxn = network.compute_rates(
            species_masses={"A": 50.0, "B": 20.0, "C": 0.0},
            conversions={"alpha_1": 0.1, "alpha_2": 0.1},
            T=353.15,
            ops=MathOps.numpy(),
            initial_masses={"A": 50.0, "B": 20.0, "C": 0.0},
        )
        # Both reactions should have positive conversion rates
        assert dconv_dt["alpha_1"] > 0.0
        assert dconv_dt["alpha_2"] > 0.0
        # A is consumed by rxn_1, B is produced by rxn_1 and consumed by rxn_2
        assert dm_dt["A"] < 0.0
        assert dm_dt["C"] > 0.0
        assert q_rxn > 0.0
