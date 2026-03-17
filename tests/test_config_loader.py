"""Tests for YAML model config loading."""

from pathlib import Path

import pytest

from reactor.config import ModelConfig

CONFIG_PATH = Path(__file__).parent.parent / "configs" / "default.yaml"


@pytest.fixture
def model_cfg() -> ModelConfig:
    return ModelConfig.from_yaml(CONFIG_PATH)


class TestYAMLLoading:
    def test_loads_without_error(self, model_cfg):
        assert model_cfg.raw is not None

    def test_kinetics_section(self, model_cfg):
        k = model_cfg.kinetics
        assert k["A1"] == 5.0e4
        assert k["Ea1"] == 60000.0
        assert k["A2"] == 5.0e8
        assert k["Ea2"] == 75000.0
        assert k["m"] == 0.5
        assert k["n"] == 1.5
        assert k["delta_H"] == 350.0
        assert k["alpha_gel"] == 0.8

    def test_thermal_section(self, model_cfg):
        t = model_cfg.thermal
        assert t["Cp"] == 1.8
        assert t["UA"] == 1.0

    def test_viscosity_section(self, model_cfg):
        v = model_cfg.viscosity
        assert v["eta_0"] == 0.5
        assert v["C_visc"] == 2.0
        assert v["alpha_gel"] == 0.8
        assert v["eta_gel"] == 100.0
        assert "component_a" in v["species_viscosities"]

    def test_physics_section(self, model_cfg):
        p = model_cfg.physics
        assert p["stoich_ratio"] == 0.3
        assert p["max_temp"] == 500.0
        assert p["R_gas"] == 8.314

    def test_controller_section(self, model_cfg):
        c = model_cfg.controller
        assert c["cure_temp_K"] == 350.0
        assert c["runaway_temp_K"] == 473.15
        assert c["conversion_done"] == 0.95

    def test_solver_section(self, model_cfg):
        s = model_cfg.solver
        assert s["solver_name"] == "ipopt"
        assert s["n_finite_elements"] == 8
        assert s["solver_options"]["max_iter"] == 2000

    def test_initial_conditions(self, model_cfg):
        ic = model_cfg.initial_conditions
        assert ic["temperature"] == 298.15
        assert ic["volume"] == 0.1


class TestFromDict:
    def test_from_dict_round_trip(self, model_cfg):
        cfg2 = ModelConfig.from_dict(model_cfg.raw)
        assert cfg2.kinetics == model_cfg.kinetics
        assert cfg2.thermal == model_cfg.thermal
        assert cfg2.solver == model_cfg.solver

    def test_from_dict_custom_values(self):
        data = {
            "kinetics": {"A1": 99.0, "Ea1": 1000.0, "A2": 0.0, "Ea2": 0.0,
                         "m": 0.5, "n": 1.5, "delta_H": 100.0, "alpha_gel": 0.6},
            "thermal": {"Cp": 2.0, "UA": 1.0},
            "viscosity": {"eta_0": 1.0, "C_visc": 2.0, "alpha_gel": 0.5},
            "physics": {"stoich_ratio": 0.5, "max_temp": 400.0, "R_gas": 8.314},
            "controller": {"cure_temp_K": 340.0, "cool_done_temp_K": 310.0,
                           "runaway_temp_K": 450.0, "runaway_dT_dt": 3.0,
                           "conversion_done": 0.9, "dt_window": 5},
            "initial_conditions": {"temperature": 300.0, "jacket_temperature": 300.0,
                                   "volume": 0.2},
            "solver": {"horizon": 1.0, "n_finite_elements": 3, "collocation_points": 2,
                       "solver_name": "ipopt", "solver_options": {"max_iter": 100}},
        }
        cfg = ModelConfig.from_dict(data)
        assert cfg.kinetics["A1"] == 99.0
        assert cfg.thermal["UA"] == 1.0
        assert cfg.controller["runaway_temp_K"] == 450.0

    def test_from_dict_rejects_missing_legacy_kinetics(self):
        data = {
            "reactor": {"volume_m3": 0.1},
            "physics": {"stoich_ratio": 0.3},
            "thermal": {"Cp": 1.8, "UA": 1.0},
        }
        with pytest.raises(ValueError, match="Invalid kinetics config"):
            ModelConfig.from_dict(data)
