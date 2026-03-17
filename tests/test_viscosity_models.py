"""Unit tests for pluggable viscosity models."""

import math

import numpy as np
import pytest

from reactor.chemistry import ViscosityParams, viscosity as legacy_viscosity
from reactor.viscosity_models import (
    ArrheniusViscosity,
    ConstantViscosity,
    ConversionViscosity,
    FullViscosity,
    ViscosityModel,
    VISCOSITY_REGISTRY,
    build_viscosity_model,
    register_viscosity_model,
)


# Common test parameters
DEFAULT_PARAMS = ViscosityParams()
FULL_PARAMS = ViscosityParams(
    eta_0=0.5,
    eta_ref=0.5,
    T_ref_K=298.15,
    E_eta_J_mol=45000.0,
    C_visc=2.0,
    alpha_gel=0.8,
    eta_gel=100.0,
)
MIXING_PARAMS = ViscosityParams(
    eta_0=0.5,
    C_visc=2.0,
    alpha_gel=0.8,
    eta_gel=100.0,
    species_viscosities={"component_a": 8.0, "component_b": 0.02},
)


class TestConstantViscosity:
    def test_returns_eta_0(self):
        model = ConstantViscosity()
        params = ViscosityParams(eta_0=0.5)
        assert model.evaluate(300, {}, {}, params) == 0.5

    def test_ignores_temperature(self):
        model = ConstantViscosity()
        params = ViscosityParams(eta_0=1.0)
        assert model.evaluate(200, {}, {}, params) == model.evaluate(500, {}, {}, params)

    def test_ignores_conversion(self):
        model = ConstantViscosity()
        params = ViscosityParams(eta_0=1.0)
        assert model.evaluate(300, {"alpha": 0.5}, {}, params) == 1.0

    def test_ignores_composition(self):
        model = ConstantViscosity()
        params = ViscosityParams(eta_0=1.0)
        masses = {"component_a": 60.0, "component_b": 18.0}
        assert model.evaluate(300, {}, masses, params) == 1.0


class TestArrheniusViscosity:
    def test_at_reference_temperature(self):
        model = ArrheniusViscosity()
        params = ViscosityParams(eta_ref=0.5, T_ref_K=298.15, E_eta_J_mol=45000.0)
        eta = model.evaluate(298.15, {}, {}, params)
        assert pytest.approx(eta) == 0.5

    def test_decreases_with_temperature(self):
        model = ArrheniusViscosity()
        params = ViscosityParams(eta_ref=0.5, T_ref_K=298.15, E_eta_J_mol=45000.0)
        eta_cold = model.evaluate(280.0, {}, {}, params)
        eta_hot = model.evaluate(350.0, {}, {}, params)
        assert eta_hot < eta_cold

    def test_ignores_conversion(self):
        model = ArrheniusViscosity()
        params = ViscosityParams(eta_ref=0.5, T_ref_K=298.15, E_eta_J_mol=45000.0)
        eta_a = model.evaluate(320, {"alpha": 0.0}, {}, params)
        eta_b = model.evaluate(320, {"alpha": 0.5}, {}, params)
        assert pytest.approx(eta_a) == eta_b

    def test_zero_activation_returns_eta_ref(self):
        model = ArrheniusViscosity()
        params = ViscosityParams(eta_ref=0.5, E_eta_J_mol=0.0)
        assert model.evaluate(350.0, {}, {}, params) == 0.5

    def test_falls_back_to_eta_0(self):
        model = ArrheniusViscosity()
        params = ViscosityParams(eta_0=1.5, eta_ref=None, E_eta_J_mol=0.0)
        assert model.evaluate(300, {}, {}, params) == 1.5


class TestConversionViscosity:
    def test_zero_conversion_returns_base(self):
        model = ConversionViscosity()
        params = ViscosityParams(eta_ref=0.5, E_eta_J_mol=0.0, C_visc=2.0, alpha_gel=0.8)
        eta = model.evaluate(298.15, {"alpha": 0.0}, {}, params)
        assert pytest.approx(eta) == 0.5

    def test_increases_with_conversion(self):
        model = ConversionViscosity()
        params = ViscosityParams(eta_ref=0.5, E_eta_J_mol=0.0, C_visc=2.0, alpha_gel=0.8)
        eta_low = model.evaluate(298.15, {"alpha": 0.1}, {}, params)
        eta_high = model.evaluate(298.15, {"alpha": 0.5}, {}, params)
        assert eta_high > eta_low

    def test_gel_point_returns_eta_gel(self):
        model = ConversionViscosity()
        params = ViscosityParams(eta_0=0.5, C_visc=2.0, alpha_gel=0.6, eta_gel=100.0)
        eta = model.evaluate(298.15, {"alpha": 0.6}, {}, params)
        assert eta == 100.0

    def test_above_gel_returns_eta_gel(self):
        model = ConversionViscosity()
        params = ViscosityParams(eta_0=0.5, C_visc=2.0, alpha_gel=0.6, eta_gel=100.0)
        eta = model.evaluate(298.15, {"alpha": 0.8}, {}, params)
        assert eta == 100.0

    def test_capped_at_eta_gel(self):
        model = ConversionViscosity()
        params = ViscosityParams(eta_0=0.5, C_visc=4.0, alpha_gel=0.8, eta_gel=100.0)
        eta = model.evaluate(298.15, {"alpha": 0.79}, {}, params)
        assert np.isfinite(eta)
        assert eta <= params.eta_gel

    def test_temperature_effect(self):
        model = ConversionViscosity()
        params = ViscosityParams(eta_ref=0.5, T_ref_K=298.15, E_eta_J_mol=45000.0,
                                 C_visc=2.0, alpha_gel=0.8)
        eta_cold = model.evaluate(280.0, {"alpha": 0.3}, {}, params)
        eta_hot = model.evaluate(350.0, {"alpha": 0.3}, {}, params)
        assert eta_hot < eta_cold  # Higher T -> lower base viscosity


class TestFullViscosity:
    def test_zero_conversion_returns_base(self):
        model = FullViscosity()
        eta = model.evaluate(298.15, {"alpha": 0.0}, {}, DEFAULT_PARAMS)
        assert pytest.approx(eta) == DEFAULT_PARAMS.eta_0

    def test_increases_with_conversion(self):
        model = FullViscosity()
        eta_low = model.evaluate(298.15, {"alpha": 0.1}, {}, DEFAULT_PARAMS)
        eta_high = model.evaluate(298.15, {"alpha": 0.4}, {}, DEFAULT_PARAMS)
        assert eta_high > eta_low

    def test_gel_point_returns_eta_gel(self):
        model = FullViscosity()
        eta = model.evaluate(298.15, {"alpha": 0.6}, {}, DEFAULT_PARAMS)
        assert eta == DEFAULT_PARAMS.eta_gel

    def test_species_mixing_rule(self):
        model = FullViscosity()
        masses = {"component_a": 60.0, "component_b": 18.0, "product": 0.0}
        eta = model.evaluate(298.15, {"alpha": 0.0}, masses, MIXING_PARAMS)
        assert 1.0 < eta < 5.0

    def test_species_mixing_no_known_species_fallback(self):
        model = FullViscosity()
        masses = {"component_a": 0.0, "component_b": 0.0, "product": 78.0}
        eta = model.evaluate(298.15, {"alpha": 0.0}, masses, MIXING_PARAMS)
        assert pytest.approx(eta) == MIXING_PARAMS.eta_0


class TestFullViscosityMatchesLegacy:
    """Verify FullViscosity produces identical results to chemistry.viscosity()."""

    def test_match_at_zero_conversion(self):
        model = FullViscosity()
        T = 298.15
        params = DEFAULT_PARAMS

        legacy = legacy_viscosity(0.0, T, params)
        new = model.evaluate(T, {"alpha": 0.0}, {}, params)
        assert pytest.approx(legacy) == new

    def test_match_at_mid_conversion(self):
        model = FullViscosity()
        T = 340.0
        params = FULL_PARAMS

        legacy = legacy_viscosity(0.4, T, params)
        new = model.evaluate(T, {"alpha": 0.4}, {}, params)
        assert pytest.approx(legacy) == new

    def test_match_at_gel_point(self):
        model = FullViscosity()
        T = 353.15
        params = FULL_PARAMS

        legacy = legacy_viscosity(0.8, T, params)
        new = model.evaluate(T, {"alpha": 0.8}, {}, params)
        assert pytest.approx(legacy) == new

    def test_match_with_species_mixing(self):
        model = FullViscosity()
        T = 298.15
        masses = {"component_a": 60.0, "component_b": 18.0, "product": 0.0}

        legacy = legacy_viscosity(0.0, T, MIXING_PARAMS, species_masses=masses)
        new = model.evaluate(T, {"alpha": 0.0}, masses, MIXING_PARAMS)
        assert pytest.approx(legacy) == new

    @pytest.mark.parametrize("alpha", [0.0, 0.1, 0.3, 0.5, 0.7, 0.79])
    @pytest.mark.parametrize("T", [280.0, 298.15, 330.0, 370.0])
    def test_match_sweep(self, alpha, T):
        model = FullViscosity()
        params = FULL_PARAMS

        legacy = legacy_viscosity(alpha, T, params)
        new = model.evaluate(T, {"alpha": alpha}, {}, params)
        assert pytest.approx(legacy, rel=1e-10) == new


class TestRegistry:
    def test_all_models_registered(self):
        assert "constant" in VISCOSITY_REGISTRY
        assert "arrhenius" in VISCOSITY_REGISTRY
        assert "conversion" in VISCOSITY_REGISTRY
        assert "full_composition" in VISCOSITY_REGISTRY

    def test_build_known_model(self):
        model = build_viscosity_model("constant")
        assert isinstance(model, ConstantViscosity)

    def test_build_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown viscosity model"):
            build_viscosity_model("nonexistent")

    def test_register_custom_model(self):
        class Custom(ViscosityModel):
            def evaluate(self, T, conversions, species_masses, params):
                return 42.0

        register_viscosity_model("test_custom", Custom)
        assert "test_custom" in VISCOSITY_REGISTRY
        model = build_viscosity_model("test_custom")
        assert model.evaluate(300, {}, {}, DEFAULT_PARAMS) == 42.0
        # Cleanup
        del VISCOSITY_REGISTRY["test_custom"]

    def test_register_non_subclass_raises(self):
        with pytest.raises(TypeError):
            register_viscosity_model("bad", object)
