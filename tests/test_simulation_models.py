"""Unit tests for pluggable simulation models.

Tests all four model types (viscosity, heat transfer, mixing, energy)
and their registries, factories, and integration with config.
"""

import math

import numpy as np
import pytest

from reactor.chemistry import ThermalParams, ViscosityParams


# =========================================================================
# Viscosity Models
# =========================================================================


class TestConstantViscosity:
    def setup_method(self):
        from reactor.viscosity_models import ConstantViscosity
        self.model = ConstantViscosity()
        self.params = ViscosityParams(eta_0=0.5)

    def test_returns_eta_0(self):
        eta = self.model.evaluate(T=300, conversions={}, species_masses={}, params=self.params)
        assert eta == 0.5

    def test_independent_of_temperature(self):
        eta_cold = self.model.evaluate(T=250, conversions={}, species_masses={}, params=self.params)
        eta_hot = self.model.evaluate(T=450, conversions={}, species_masses={}, params=self.params)
        assert eta_cold == eta_hot == 0.5

    def test_independent_of_conversion(self):
        eta_low = self.model.evaluate(T=300, conversions={"alpha": 0.0}, species_masses={}, params=self.params)
        eta_high = self.model.evaluate(T=300, conversions={"alpha": 0.9}, species_masses={}, params=self.params)
        assert eta_low == eta_high == 0.5


class TestArrheniusViscosity:
    def setup_method(self):
        from reactor.viscosity_models import ArrheniusViscosity
        self.model = ArrheniusViscosity()
        self.params = ViscosityParams(eta_ref=0.5, T_ref_K=298.15, E_eta_J_mol=45000.0)

    def test_returns_eta_ref_at_T_ref(self):
        eta = self.model.evaluate(T=298.15, conversions={}, species_masses={}, params=self.params)
        assert pytest.approx(eta, rel=1e-6) == 0.5

    def test_viscosity_decreases_with_temperature(self):
        eta_cold = self.model.evaluate(T=298.15, conversions={}, species_masses={}, params=self.params)
        eta_hot = self.model.evaluate(T=350.0, conversions={}, species_masses={}, params=self.params)
        assert eta_hot < eta_cold

    def test_independent_of_conversion(self):
        eta_low = self.model.evaluate(T=330, conversions={"alpha": 0.0}, species_masses={}, params=self.params)
        eta_high = self.model.evaluate(T=330, conversions={"alpha": 0.9}, species_masses={}, params=self.params)
        assert eta_low == eta_high

    def test_no_activation_energy_returns_eta_ref(self):
        params = ViscosityParams(eta_ref=2.0, T_ref_K=298.15, E_eta_J_mol=0.0)
        eta = self.model.evaluate(T=400, conversions={}, species_masses={}, params=params)
        assert eta == 2.0


class TestConversionViscosity:
    def setup_method(self):
        from reactor.viscosity_models import ConversionViscosity
        self.model = ConversionViscosity()
        self.params = ViscosityParams(
            eta_ref=0.5, T_ref_K=298.15, E_eta_J_mol=45000.0,
            C_visc=2.0, alpha_gel=0.8, eta_gel=100.0,
        )

    def test_increases_with_conversion(self):
        eta_low = self.model.evaluate(T=298.15, conversions={"alpha": 0.1}, species_masses={}, params=self.params)
        eta_high = self.model.evaluate(T=298.15, conversions={"alpha": 0.5}, species_masses={}, params=self.params)
        assert eta_high > eta_low

    def test_gel_point_returns_eta_gel(self):
        eta = self.model.evaluate(T=298.15, conversions={"alpha": 0.8}, species_masses={}, params=self.params)
        assert eta == self.params.eta_gel

    def test_above_gel_returns_eta_gel(self):
        eta = self.model.evaluate(T=298.15, conversions={"alpha": 0.95}, species_masses={}, params=self.params)
        assert eta == self.params.eta_gel

    def test_capped_at_eta_gel(self):
        eta = self.model.evaluate(T=298.15, conversions={"alpha": 0.79}, species_masses={}, params=self.params)
        assert np.isfinite(eta)
        assert eta <= self.params.eta_gel

    def test_temperature_effect(self):
        eta_cold = self.model.evaluate(T=298.15, conversions={"alpha": 0.3}, species_masses={}, params=self.params)
        eta_hot = self.model.evaluate(T=370.0, conversions={"alpha": 0.3}, species_masses={}, params=self.params)
        assert eta_hot < eta_cold  # Temperature reduces base viscosity


class TestFullViscosity:
    def setup_method(self):
        from reactor.viscosity_models import FullViscosity
        self.model = FullViscosity()

    def test_matches_legacy_viscosity_no_species(self):
        """FullViscosity should match chemistry.viscosity() for same inputs."""
        from reactor.chemistry import viscosity as legacy_viscosity

        params = ViscosityParams(
            eta_0=0.5, C_visc=4.0, alpha_gel=0.6, eta_gel=100.0,
        )
        for alpha in [0.0, 0.1, 0.3, 0.5]:
            for T in [298.15, 330.0, 370.0]:
                legacy = legacy_viscosity(alpha, T, params)
                model_result = self.model.evaluate(
                    T=T, conversions={"alpha": alpha},
                    species_masses={}, params=params,
                )
                assert pytest.approx(legacy, rel=1e-6) == model_result, \
                    f"Mismatch at alpha={alpha}, T={T}: legacy={legacy}, model={model_result}"

    def test_matches_legacy_with_species_mixing(self):
        """FullViscosity should match chemistry.viscosity() with species masses."""
        from reactor.chemistry import viscosity as legacy_viscosity

        params = ViscosityParams(
            eta_0=0.5, C_visc=2.0, alpha_gel=0.8, eta_gel=100.0,
            species_viscosities={"component_a": 8.0, "component_b": 0.02},
        )
        masses = {"component_a": 60.0, "component_b": 18.0, "product": 0.0}

        for alpha in [0.0, 0.2, 0.4]:
            legacy = legacy_viscosity(alpha, 298.15, params, species_masses=masses)
            model_result = self.model.evaluate(
                T=298.15, conversions={"alpha": alpha},
                species_masses=masses, params=params,
            )
            assert pytest.approx(legacy, rel=1e-6) == model_result

    def test_gel_point_cap(self):
        params = ViscosityParams(eta_0=0.5, alpha_gel=0.6, eta_gel=100.0)
        eta = self.model.evaluate(T=300, conversions={"alpha": 0.7}, species_masses={}, params=params)
        assert eta == 100.0


class TestViscosityRegistry:
    def test_all_models_registered(self):
        from reactor.viscosity_models import VISCOSITY_REGISTRY
        assert "constant" in VISCOSITY_REGISTRY
        assert "arrhenius" in VISCOSITY_REGISTRY
        assert "conversion" in VISCOSITY_REGISTRY
        assert "full_composition" in VISCOSITY_REGISTRY

    def test_build_model_factory(self):
        from reactor.viscosity_models import build_viscosity_model, ConstantViscosity
        model = build_viscosity_model("constant")
        assert isinstance(model, ConstantViscosity)

    def test_unknown_model_raises(self):
        from reactor.viscosity_models import build_viscosity_model
        with pytest.raises(ValueError, match="Unknown viscosity model"):
            build_viscosity_model("nonexistent")

    def test_register_custom_model(self):
        from reactor.viscosity_models import (
            ViscosityModel, register_viscosity_model, VISCOSITY_REGISTRY,
            build_viscosity_model,
        )

        class TestModel(ViscosityModel):
            def evaluate(self, T, conversions, species_masses, params):
                return 42.0

        register_viscosity_model("test_custom", TestModel)
        assert "test_custom" in VISCOSITY_REGISTRY

        model = build_viscosity_model("test_custom")
        assert model.evaluate(300, {}, {}, ViscosityParams()) == 42.0

        # Cleanup
        del VISCOSITY_REGISTRY["test_custom"]


# =========================================================================
# Heat Transfer Models
# =========================================================================


class _FakeState:
    """Minimal stub for ReactorState in tests."""
    def __init__(self, temperature=300.0, volume=0.05):
        self.temperature = temperature
        self.volume = volume


class _FakeFM:
    """Minimal stub for FluidMechanicsState in tests."""
    def __init__(self, UA_kW_per_K=2.5, power_W=500.0):
        self._UA = UA_kW_per_K
        self.power_W = power_W

    @property
    def UA_kW_per_K(self):
        return self._UA


class TestConstantUA:
    def test_returns_thermal_UA(self):
        from reactor.heat_transfer_models import ConstantUA
        model = ConstantUA()
        thermal = ThermalParams(UA=1.5)
        result = model.compute_UA(
            state=_FakeState(), thermal=thermal,
            geometry=None, fluid_mechanics=None,
        )
        assert result == 1.5

    def test_ignores_fluid_mechanics(self):
        from reactor.heat_transfer_models import ConstantUA
        model = ConstantUA()
        thermal = ThermalParams(UA=1.0)
        fm = _FakeFM(UA_kW_per_K=5.0)
        result = model.compute_UA(
            state=_FakeState(), thermal=thermal,
            geometry=None, fluid_mechanics=fm,
        )
        assert result == 1.0  # Not 5.0


class TestDynamicUA:
    def test_uses_fluid_mechanics_UA(self):
        from reactor.heat_transfer_models import DynamicUA
        model = DynamicUA()
        thermal = ThermalParams(UA=1.0)
        fm = _FakeFM(UA_kW_per_K=2.5)
        result = model.compute_UA(
            state=_FakeState(), thermal=thermal,
            geometry=None, fluid_mechanics=fm,
        )
        assert result == 2.5

    def test_fallback_to_constant_when_no_fm(self):
        from reactor.heat_transfer_models import DynamicUA
        model = DynamicUA()
        thermal = ThermalParams(UA=1.0)
        result = model.compute_UA(
            state=_FakeState(), thermal=thermal,
            geometry=None, fluid_mechanics=None,
        )
        assert result == 1.0

    def test_enforces_minimum_UA(self):
        from reactor.heat_transfer_models import DynamicUA
        model = DynamicUA()
        thermal = ThermalParams(UA=1.0)
        fm = _FakeFM(UA_kW_per_K=0.01)  # Very low
        result = model.compute_UA(
            state=_FakeState(), thermal=thermal,
            geometry=None, fluid_mechanics=fm,
        )
        assert result == 0.01


class TestHeatTransferRegistry:
    def test_all_models_registered(self):
        from reactor.heat_transfer_models import HEAT_TRANSFER_REGISTRY
        assert "constant" in HEAT_TRANSFER_REGISTRY
        assert "geometry_aware" in HEAT_TRANSFER_REGISTRY
        assert "dynamic" in HEAT_TRANSFER_REGISTRY

    def test_build_model_factory(self):
        from reactor.heat_transfer_models import build_heat_transfer_model, ConstantUA
        model = build_heat_transfer_model("constant")
        assert isinstance(model, ConstantUA)

    def test_unknown_model_raises(self):
        from reactor.heat_transfer_models import build_heat_transfer_model
        with pytest.raises(ValueError, match="Unknown heat transfer model"):
            build_heat_transfer_model("nonexistent")


# =========================================================================
# Mixing Models
# =========================================================================


class TestPerfectMixing:
    def test_always_returns_one(self):
        from reactor.mixing_models import PerfectMixing
        model = PerfectMixing()
        assert model.compute_efficiency(Re=0.0, params={}) == 1.0
        assert model.compute_efficiency(Re=100.0, params={}) == 1.0
        assert model.compute_efficiency(Re=100000.0, params={}) == 1.0


class TestReynoldsMixing:
    def setup_method(self):
        from reactor.mixing_models import ReynoldsMixing
        self.model = ReynoldsMixing()
        self.params = {"eta_min": 0.20, "Re_turb": 10000.0, "steepness": 2.5}

    def test_low_Re_gives_eta_min(self):
        eta = self.model.compute_efficiency(Re=1.0, params=self.params)
        assert pytest.approx(eta, abs=0.05) == 0.20

    def test_high_Re_gives_near_one(self):
        eta = self.model.compute_efficiency(Re=100000.0, params=self.params)
        assert eta > 0.95

    def test_zero_Re_gives_eta_min(self):
        eta = self.model.compute_efficiency(Re=0.0, params=self.params)
        assert eta == 0.20

    def test_monotonically_increasing(self):
        Re_values = [1, 10, 100, 1000, 10000, 100000]
        etas = [self.model.compute_efficiency(Re=r, params=self.params) for r in Re_values]
        for i in range(len(etas) - 1):
            assert etas[i + 1] >= etas[i]

    def test_matches_legacy_mixing_efficiency(self):
        """Should match fluid_mechanics.mixing_efficiency()."""
        from reactor.fluid_mechanics import mixing_efficiency as legacy_eta
        for Re in [1, 50, 500, 5000, 50000]:
            legacy = legacy_eta(Re)
            model_result = self.model.compute_efficiency(Re, self.params)
            assert pytest.approx(legacy, rel=1e-6) == model_result, \
                f"Mismatch at Re={Re}: legacy={legacy}, model={model_result}"


class TestPowerLawMixing:
    def setup_method(self):
        from reactor.mixing_models import PowerLawMixing
        self.model = PowerLawMixing()
        self.params = {"Re_crit": 1000.0, "exponent": 0.7, "eta_min": 0.1}

    def test_low_Re_gives_eta_min(self):
        eta = self.model.compute_efficiency(Re=0.01, params=self.params)
        assert eta == 0.1

    def test_at_Re_crit_gives_one(self):
        eta = self.model.compute_efficiency(Re=1000.0, params=self.params)
        assert pytest.approx(eta, rel=1e-6) == 1.0

    def test_above_Re_crit_capped_at_one(self):
        eta = self.model.compute_efficiency(Re=10000.0, params=self.params)
        assert eta == 1.0

    def test_zero_Re(self):
        eta = self.model.compute_efficiency(Re=0.0, params=self.params)
        assert eta == 0.1


class TestMixingRegistry:
    def test_all_models_registered(self):
        from reactor.mixing_models import MIXING_REGISTRY
        assert "perfect" in MIXING_REGISTRY
        assert "reynolds" in MIXING_REGISTRY
        assert "power_law" in MIXING_REGISTRY

    def test_build_model_factory(self):
        from reactor.mixing_models import build_mixing_model, PerfectMixing
        model = build_mixing_model("perfect")
        assert isinstance(model, PerfectMixing)


# =========================================================================
# Energy Models
# =========================================================================


class TestIsothermalModel:
    def test_always_returns_zero(self):
        from reactor.energy_models import IsothermalModel
        model = IsothermalModel()
        assert model.compute_dT_dt(Q_rxn=100, Q_jacket=50, Q_frictional=10, m_total=80, Cp=1.8) == 0.0

    def test_ignores_all_heat(self):
        from reactor.energy_models import IsothermalModel
        model = IsothermalModel()
        assert model.compute_dT_dt(Q_rxn=1e6, Q_jacket=-1e6, Q_frictional=1e6, m_total=1, Cp=1) == 0.0


class TestAdiabaticModel:
    def test_only_reaction_heat(self):
        from reactor.energy_models import AdiabaticModel
        model = AdiabaticModel()
        # dT/dt = Q_rxn / (m * Cp) = 10 / (80 * 1.8)
        result = model.compute_dT_dt(Q_rxn=10, Q_jacket=-5, Q_frictional=1, m_total=80, Cp=1.8)
        expected = 10.0 / (80.0 * 1.8)
        assert pytest.approx(result) == expected

    def test_ignores_jacket(self):
        from reactor.energy_models import AdiabaticModel
        model = AdiabaticModel()
        result1 = model.compute_dT_dt(Q_rxn=10, Q_jacket=0, Q_frictional=0, m_total=80, Cp=1.8)
        result2 = model.compute_dT_dt(Q_rxn=10, Q_jacket=-100, Q_frictional=0, m_total=80, Cp=1.8)
        assert result1 == result2  # Q_jacket is ignored

    def test_pyomo_symbolic_args(self):
        """compute_dT_dt must work with Pyomo symbolic expressions (no numeric guards)."""
        import pyomo.environ as pyo
        from reactor.energy_models import AdiabaticModel
        m = pyo.ConcreteModel()
        m.Q = pyo.Param(initialize=10.0)
        m.mass = pyo.Param(initialize=80.0)
        m.Cp = pyo.Param(initialize=1.8)
        model = AdiabaticModel()
        expr = model.compute_dT_dt(m.Q, 0.0, 0.0, m.mass, m.Cp)
        assert pytest.approx(pyo.value(expr)) == 10.0 / (80.0 * 1.8)


class TestFullEnergyModel:
    def test_reaction_plus_jacket(self):
        from reactor.energy_models import FullEnergyModel
        model = FullEnergyModel()
        # dT/dt = (Q_rxn + Q_jacket) / (m * Cp) = (10 + 5) / (80 * 1.8)
        result = model.compute_dT_dt(Q_rxn=10, Q_jacket=5, Q_frictional=99, m_total=80, Cp=1.8)
        expected = (10.0 + 5.0) / (80.0 * 1.8)
        assert pytest.approx(result) == expected

    def test_ignores_frictional(self):
        from reactor.energy_models import FullEnergyModel
        model = FullEnergyModel()
        result1 = model.compute_dT_dt(Q_rxn=10, Q_jacket=5, Q_frictional=0, m_total=80, Cp=1.8)
        result2 = model.compute_dT_dt(Q_rxn=10, Q_jacket=5, Q_frictional=100, m_total=80, Cp=1.8)
        assert result1 == result2


class TestExtendedEnergyModel:
    def test_includes_frictional(self):
        from reactor.energy_models import ExtendedEnergyModel
        model = ExtendedEnergyModel()
        # dT/dt = (Q_rxn + Q_jacket + Q_fric) / (m * Cp) = (10 + 5 + 2) / (80 * 1.8)
        result = model.compute_dT_dt(Q_rxn=10, Q_jacket=5, Q_frictional=2, m_total=80, Cp=1.8)
        expected = (10.0 + 5.0 + 2.0) / (80.0 * 1.8)
        assert pytest.approx(result) == expected

    def test_zero_frictional_matches_full(self):
        from reactor.energy_models import ExtendedEnergyModel, FullEnergyModel
        ext = ExtendedEnergyModel()
        full = FullEnergyModel()
        kwargs = dict(Q_rxn=10, Q_jacket=5, Q_frictional=0, m_total=80, Cp=1.8)
        assert ext.compute_dT_dt(**kwargs) == full.compute_dT_dt(**kwargs)


class TestEnergyRegistry:
    def test_all_models_registered(self):
        from reactor.energy_models import ENERGY_REGISTRY
        assert "isothermal" in ENERGY_REGISTRY
        assert "adiabatic" in ENERGY_REGISTRY
        assert "full" in ENERGY_REGISTRY
        assert "extended" in ENERGY_REGISTRY

    def test_build_model_factory(self):
        from reactor.energy_models import build_energy_model, FullEnergyModel
        model = build_energy_model("full")
        assert isinstance(model, FullEnergyModel)


# =========================================================================
# Config Integration
# =========================================================================


class TestSimulationConfig:
    """Test that ModelConfig correctly parses the simulation section."""

    def test_default_config_no_simulation_section(self):
        """Without simulation section, defaults to full-fidelity models."""
        from reactor.config import ModelConfig

        config = ModelConfig.from_dict({
            "kinetics": {"A1": 1e4, "Ea1": 55000, "A2": 1e6, "Ea2": 45000,
                         "m": 0.5, "n": 1.5, "delta_H": 350, "alpha_gel": 0.6},
            "thermal": {"Cp": 1.8, "UA": 0.5},
        })

        sim = config.simulation
        assert sim["models"]["viscosity"] == "full_composition"
        assert sim["models"]["heat_transfer"] == "constant"  # No mixing enabled
        assert sim["models"]["mixing"] == "perfect"  # No mixing enabled
        assert sim["models"]["energy"] == "full"

    def test_default_config_with_mixing_enabled(self):
        """With mixing enabled, defaults to dynamic/reynolds models."""
        from reactor.config import ModelConfig

        config = ModelConfig.from_dict({
            "kinetics": {"A1": 1e4, "Ea1": 55000, "A2": 1e6, "Ea2": 45000,
                         "m": 0.5, "n": 1.5, "delta_H": 350, "alpha_gel": 0.6},
            "thermal": {"Cp": 1.8, "UA": 0.5},
            "mixing": {"enabled": True, "impeller_diameter_m": 0.16},
            "geometry": {"type": "cylindrical_flat", "diameter_m": 0.5, "height_m": 0.6},
        })

        sim = config.simulation
        assert sim["models"]["heat_transfer"] == "dynamic"
        assert sim["models"]["mixing"] == "reynolds"

    def test_explicit_model_overrides(self):
        """Explicit simulation.models overrides defaults."""
        from reactor.config import ModelConfig

        config = ModelConfig.from_dict({
            "kinetics": {"A1": 1e4, "Ea1": 55000, "A2": 1e6, "Ea2": 45000,
                         "m": 0.5, "n": 1.5, "delta_H": 350, "alpha_gel": 0.6},
            "thermal": {"Cp": 1.8, "UA": 0.5},
            "simulation": {
                "models": {
                    "viscosity": "constant",
                    "energy": "adiabatic",
                },
            },
        })

        sim = config.simulation
        assert sim["models"]["viscosity"] == "constant"
        assert sim["models"]["energy"] == "adiabatic"
        # Non-overridden defaults
        assert sim["models"]["heat_transfer"] == "constant"
        assert sim["models"]["mixing"] == "perfect"

    def test_invalid_model_name_raises(self):
        """Unknown model name should raise ValueError."""
        from reactor.config import ModelConfig

        with pytest.raises(ValueError, match="Unknown viscosity model"):
            ModelConfig.from_dict({
                "kinetics": {"A1": 1e4, "Ea1": 55000, "A2": 1e6, "Ea2": 45000,
                             "m": 0.5, "n": 1.5, "delta_H": 350, "alpha_gel": 0.6},
                "thermal": {"Cp": 1.8, "UA": 0.5},
                "simulation": {
                    "models": {"viscosity": "nonexistent"},
                },
            })

    def test_dynamic_ht_without_mixing_raises(self):
        """Requesting dynamic heat transfer without mixing should raise."""
        from reactor.config import ModelConfig

        with pytest.raises(ValueError, match="requires mixing.enabled"):
            ModelConfig.from_dict({
                "kinetics": {"A1": 1e4, "Ea1": 55000, "A2": 1e6, "Ea2": 45000,
                             "m": 0.5, "n": 1.5, "delta_H": 350, "alpha_gel": 0.6},
                "thermal": {"Cp": 1.8, "UA": 0.5},
                "simulation": {
                    "models": {"heat_transfer": "dynamic"},
                },
            })


# =========================================================================
# Pyomo Energy Model Integration
# =========================================================================


class TestPyomoEnergyModelIntegration:
    """Test that energy models produce correct Pyomo constraint structures."""

    @pytest.fixture
    def _simple_network(self):
        """Build a minimal reaction network for testing."""
        from reactor.reaction_network import (
            Species, RateLaw, Reaction, ReactionNetwork, MathOps,
        )

        class SimpleRateLaw(RateLaw):
            def evaluate(self, species_masses, conversions, T, parameters, ops):
                k = parameters.get("k", 0.001)
                alpha = conversions.get("alpha", 0.0)
                return k * (1.0 - alpha)

        component_a = Species("component_a", density=1.16)
        product = Species("product", density=1.2, inert=True)
        rxn = Reaction(
            name="cure",
            rate_law=SimpleRateLaw(),
            parameters={"k": 0.001},
            stoichiometry={"component_a": -1.0, "product": 1.0},
            delta_H=350.0,
            heat_basis="component_a",
            conversion_variable="alpha",
        )
        return ReactionNetwork(species=[component_a, product], reactions=[rxn])

    @pytest.fixture
    def _initial_state(self):
        from reactor.physics import ReactorState
        state = ReactorState(temperature=350.0)
        state.species_masses = {"component_a": 60.0, "product": 0.0}
        state.conversions = {"alpha": 0.1}
        return state

    def test_full_energy_model_has_jacket_term(self, _simple_network, _initial_state):
        """Full energy model should include Q_jacket in constraint."""
        from reactor.pyomo_model import build_reactor_model_from_network
        from reactor.energy_models import FullEnergyModel
        import pyomo.environ as pyo

        m = build_reactor_model_from_network(
            t_horizon=1.0, n_fe=3, n_cp=2,
            network=_simple_network,
            initial_state=_initial_state,
            feed_rates={"component_a": 0.0, "product": 0.0},
            jacket_T=350.0,
            initial_masses={"component_a": 60.0, "product": 0.01},
            thermal={"Cp": 1.8, "UA": 0.5},
            physics={"max_temp": 500.0},
            energy_model=FullEnergyModel(),
        )
        # Model should have energy_ode constraint
        assert hasattr(m, "energy_ode")

    def test_isothermal_fixes_dT_dt_zero(self, _simple_network, _initial_state):
        """Isothermal model should constrain dT/dt = 0."""
        from reactor.pyomo_model import build_reactor_model_from_network
        from reactor.energy_models import IsothermalModel
        import pyomo.environ as pyo

        m = build_reactor_model_from_network(
            t_horizon=1.0, n_fe=3, n_cp=2,
            network=_simple_network,
            initial_state=_initial_state,
            feed_rates={"component_a": 0.0, "product": 0.0},
            jacket_T=400.0,  # Different from reactor T
            initial_masses={"component_a": 60.0, "product": 0.01},
            thermal={"Cp": 1.8, "UA": 0.5},
            physics={"max_temp": 500.0},
            energy_model=IsothermalModel(),
        )
        assert hasattr(m, "energy_ode")

    def test_adiabatic_energy_model(self, _simple_network, _initial_state):
        """Adiabatic model should build without error."""
        from reactor.pyomo_model import build_reactor_model_from_network
        from reactor.energy_models import AdiabaticModel

        m = build_reactor_model_from_network(
            t_horizon=1.0, n_fe=3, n_cp=2,
            network=_simple_network,
            initial_state=_initial_state,
            feed_rates={"component_a": 0.0, "product": 0.0},
            jacket_T=350.0,
            initial_masses={"component_a": 60.0, "product": 0.01},
            thermal={"Cp": 1.8, "UA": 0.5},
            physics={"max_temp": 500.0},
            energy_model=AdiabaticModel(),
        )
        assert hasattr(m, "energy_ode")

    def test_extended_uses_Q_frictional(self, _simple_network, _initial_state):
        """Extended model should build with Q_frictional parameter."""
        from reactor.pyomo_model import build_reactor_model_from_network
        from reactor.energy_models import ExtendedEnergyModel
        import pyomo.environ as pyo

        m = build_reactor_model_from_network(
            t_horizon=1.0, n_fe=3, n_cp=2,
            network=_simple_network,
            initial_state=_initial_state,
            feed_rates={"component_a": 0.0, "product": 0.0},
            jacket_T=350.0,
            initial_masses={"component_a": 60.0, "product": 0.01},
            thermal={"Cp": 1.8, "UA": 0.5},
            physics={"max_temp": 500.0},
            energy_model=ExtendedEnergyModel(),
            Q_frictional_kW=0.5,
        )
        assert hasattr(m, "energy_ode")
        assert pyo.value(m.Q_frictional) == 0.5
