"""Unit tests for chemistry module."""

import math

import numpy as np
import pytest

from reactor.chemistry import (
    KineticParams,
    ThermalParams,
    ViscosityParams,
    heat_of_reaction,
    heat_transfer,
    reaction_rate,
    viscosity,
)


class TestReactionRate:
    def test_zero_conversion_nonzero_rate(self):
        params = KineticParams()
        rate = reaction_rate(0.0, 353.15, params)  # 80 C
        assert rate > 0.0

    def test_full_conversion_zero_rate(self):
        params = KineticParams()
        rate = reaction_rate(1.0, 353.15, params)
        assert rate == 0.0

    def test_rate_increases_with_temperature(self):
        params = KineticParams()
        rate_low = reaction_rate(0.1, 320.0, params)
        rate_high = reaction_rate(0.1, 380.0, params)
        assert rate_high > rate_low

    def test_autocatalytic_peak(self):
        """Rate should increase then decrease as conversion goes from 0 to 1."""
        params = KineticParams()
        T = 353.15
        rates = [reaction_rate(a, T, params) for a in np.linspace(0, 0.99, 50)]
        peak_idx = np.argmax(rates)
        # Peak should not be at the endpoints
        assert 0 < peak_idx < 49

    def test_negative_conversion_clamped(self):
        params = KineticParams()
        rate = reaction_rate(-0.1, 353.15, params)
        assert rate > 0.0  # should treat as alpha=0


class TestHeatOfReaction:
    def test_positive_heat_generation(self):
        params = KineticParams()
        Q = heat_of_reaction(0.001, 100.0, params)  # 100 kg component_a
        assert Q > 0.0

    def test_zero_rate_no_heat(self):
        params = KineticParams()
        Q = heat_of_reaction(0.0, 100.0, params)
        assert Q == 0.0

    def test_proportional_to_mass(self):
        params = KineticParams()
        Q1 = heat_of_reaction(0.001, 50.0, params)
        Q2 = heat_of_reaction(0.001, 100.0, params)
        assert pytest.approx(Q2, rel=1e-10) == 2.0 * Q1


class TestHeatTransfer:
    def test_heating(self):
        thermal = ThermalParams()
        Q = heat_transfer(300.0, 400.0, thermal)
        assert Q > 0.0  # jacket hotter -> heat in

    def test_cooling(self):
        thermal = ThermalParams()
        Q = heat_transfer(400.0, 300.0, thermal)
        assert Q < 0.0  # jacket cooler -> heat out

    def test_equilibrium(self):
        thermal = ThermalParams()
        Q = heat_transfer(350.0, 350.0, thermal)
        assert Q == 0.0


class TestViscosity:
    def test_initial_viscosity(self):
        params = ViscosityParams()
        eta = viscosity(0.0, 298.15, params)
        # At alpha=0, power-law factor is 1.0, so eta == eta_0
        assert pytest.approx(eta) == params.eta_0

    def test_viscosity_increases_with_conversion(self):
        params = ViscosityParams()
        eta_low = viscosity(0.1, 298.15, params)
        eta_high = viscosity(0.4, 298.15, params)
        assert eta_high > eta_low

    def test_gel_point_returns_eta_gel(self):
        params = ViscosityParams()
        eta_at_gel = viscosity(0.6, 298.15, params)
        assert eta_at_gel == params.eta_gel

    def test_above_gel_returns_eta_gel(self):
        params = ViscosityParams()
        eta = viscosity(0.7, 298.15, params)
        assert eta == params.eta_gel

    def test_near_gel_capped_at_eta_gel(self):
        params = ViscosityParams()
        eta = viscosity(0.59, 298.15, params)
        # Near gel point: should be high but capped at eta_gel
        assert eta > params.eta_0
        assert np.isfinite(eta)
        assert eta <= params.eta_gel

    def test_capped_at_eta_gel(self):
        """Viscosity should never exceed eta_gel, even near gel point."""
        params = ViscosityParams(
            eta_0=0.5, C_visc=2.0, alpha_gel=0.8, eta_gel=100.0,
        )
        eta_mid = viscosity(0.4, 350.0, params)
        # Should be moderate and within eta_gel cap
        assert eta_mid < params.eta_gel

    def test_species_mixing_rule(self):
        """Log-mixing rule blends species viscosities by mass fraction."""
        params = ViscosityParams(
            eta_0=0.5, C_visc=2.0, alpha_gel=0.8, eta_gel=100.0,
            species_viscosities={"component_a": 8.0, "component_b": 0.02},
        )
        masses = {"component_a": 60.0, "component_b": 18.0, "product": 0.0}
        eta = viscosity(0.0, 298.15, params, species_masses=masses)
        # Log-mixing: ln(eta_mix) = (60/78)*ln(8) + (18/78)*ln(0.02)
        # eta_mix ≈ exp(0.769*2.08 + 0.231*(-3.91)) ≈ exp(0.70) ≈ 2.0
        assert 1.0 < eta < 5.0

    def test_species_mixing_ignores_product(self):
        """Product species without declared viscosity is excluded."""
        params = ViscosityParams(
            eta_0=0.5, C_visc=2.0, alpha_gel=0.8, eta_gel=100.0,
            species_viscosities={"component_a": 8.0, "component_b": 0.02},
        )
        # All mass is product (no declared viscosity) → falls back to eta_0
        masses = {"component_a": 0.0, "component_b": 0.0, "product": 78.0}
        eta = viscosity(0.0, 298.15, params, species_masses=masses)
        assert pytest.approx(eta) == params.eta_0
