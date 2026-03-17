"""Unit tests for pluggable mixing efficiency models."""

import math

import pytest

from reactor.mixing_models import (
    MixingModel,
    PerfectMixing,
    PowerLawMixing,
    ReynoldsMixing,
    MIXING_REGISTRY,
    build_mixing_model,
    register_mixing_model,
)


DEFAULT_PARAMS = {"eta_min": 0.20, "Re_turb": 10000.0, "steepness": 2.5}


class TestPerfectMixing:
    def test_always_one(self):
        model = PerfectMixing()
        assert model.compute_efficiency(0.0, {}) == 1.0
        assert model.compute_efficiency(100.0, {}) == 1.0
        assert model.compute_efficiency(1e6, {}) == 1.0

    def test_ignores_params(self):
        model = PerfectMixing()
        assert model.compute_efficiency(500, DEFAULT_PARAMS) == 1.0


class TestReynoldsMixing:
    def test_zero_Re_returns_eta_min(self):
        model = ReynoldsMixing()
        eta = model.compute_efficiency(0.0, DEFAULT_PARAMS)
        assert eta == DEFAULT_PARAMS["eta_min"]

    def test_high_Re_approaches_one(self):
        model = ReynoldsMixing()
        eta = model.compute_efficiency(1e6, DEFAULT_PARAMS)
        assert eta > 0.98

    def test_monotonically_increases(self):
        model = ReynoldsMixing()
        Re_values = [1.0, 10.0, 100.0, 1000.0, 10000.0, 100000.0]
        etas = [model.compute_efficiency(Re, DEFAULT_PARAMS) for Re in Re_values]
        for i in range(len(etas) - 1):
            assert etas[i + 1] >= etas[i]

    def test_between_eta_min_and_one(self):
        model = ReynoldsMixing()
        for Re in [0.1, 1.0, 10, 100, 1000, 10000, 100000]:
            eta = model.compute_efficiency(Re, DEFAULT_PARAMS)
            assert DEFAULT_PARAMS["eta_min"] <= eta <= 1.0

    def test_transition_around_Re_turb(self):
        model = ReynoldsMixing()
        # Well below turbulent threshold -> close to eta_min
        eta_low = model.compute_efficiency(10.0, DEFAULT_PARAMS)
        # Well above turbulent threshold -> close to 1.0
        eta_high = model.compute_efficiency(100000.0, DEFAULT_PARAMS)
        # At threshold -> roughly midpoint
        eta_mid = model.compute_efficiency(1000.0, DEFAULT_PARAMS)

        assert eta_low < eta_mid < eta_high

    def test_matches_fluid_mechanics_function(self):
        """Verify ReynoldsMixing matches fluid_mechanics.mixing_efficiency()."""
        from reactor.fluid_mechanics import mixing_efficiency as fm_mixing

        model = ReynoldsMixing()
        params = {"eta_min": 0.20, "Re_turb": 10000.0, "steepness": 2.5}

        for Re in [1.0, 50, 500, 5000, 50000, 500000]:
            expected = fm_mixing(Re, Re_turb=10000.0)
            actual = model.compute_efficiency(Re, params)
            assert pytest.approx(expected, rel=1e-10) == actual

    def test_negative_Re_returns_eta_min(self):
        model = ReynoldsMixing()
        eta = model.compute_efficiency(-100, DEFAULT_PARAMS)
        assert eta == DEFAULT_PARAMS["eta_min"]


class TestPowerLawMixing:
    def test_zero_Re_returns_eta_min(self):
        model = PowerLawMixing()
        params = {"Re_crit": 1000, "exponent": 0.7, "eta_min": 0.1}
        assert model.compute_efficiency(0.0, params) == 0.1

    def test_high_Re_returns_one(self):
        model = PowerLawMixing()
        params = {"Re_crit": 1000, "exponent": 0.7, "eta_min": 0.1}
        eta = model.compute_efficiency(1e6, params)
        assert eta == 1.0

    def test_at_Re_crit_returns_one(self):
        model = PowerLawMixing()
        params = {"Re_crit": 1000, "exponent": 1.0, "eta_min": 0.1}
        # At Re_crit with exponent=1: (1000/1000)^1 = 1.0
        assert model.compute_efficiency(1000, params) == 1.0

    def test_monotonically_increases(self):
        model = PowerLawMixing()
        params = {"Re_crit": 1000, "exponent": 0.7, "eta_min": 0.1}
        Re_values = [1.0, 10, 100, 1000, 10000]
        etas = [model.compute_efficiency(Re, params) for Re in Re_values]
        for i in range(len(etas) - 1):
            assert etas[i + 1] >= etas[i]

    def test_capped_at_one(self):
        model = PowerLawMixing()
        params = {"Re_crit": 100, "exponent": 0.5, "eta_min": 0.1}
        # Re >> Re_crit should be capped at 1.0
        eta = model.compute_efficiency(1e8, params)
        assert eta == 1.0


class TestRegistry:
    def test_all_models_registered(self):
        assert "perfect" in MIXING_REGISTRY
        assert "reynolds" in MIXING_REGISTRY
        assert "power_law" in MIXING_REGISTRY

    def test_build_known_model(self):
        model = build_mixing_model("reynolds")
        assert isinstance(model, ReynoldsMixing)

    def test_build_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown mixing model"):
            build_mixing_model("nonexistent")

    def test_register_custom_model(self):
        class Custom(MixingModel):
            def compute_efficiency(self, Re, params):
                return 0.42

        register_mixing_model("test_custom", Custom)
        assert "test_custom" in MIXING_REGISTRY
        model = build_mixing_model("test_custom")
        assert model.compute_efficiency(100, {}) == 0.42
        del MIXING_REGISTRY["test_custom"]
