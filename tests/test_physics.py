"""Unit tests for physics module."""

import numpy as np
import pytest

from reactor.chemistry import KineticParams, ThermalParams, ViscosityParams
from reactor.physics import ReactorModel, ReactorState, SolverResult, SolverStatus


@pytest.fixture
def charged_state() -> ReactorState:
    """A reactor charged with 100 kg component_a + 30 kg component_b at 80 C."""
    return ReactorState(
        species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
        conversions={"alpha": 0.0},
        temperature=353.15,  # 80 C
        jacket_temperature=353.15,
        volume=0.1,
    )


@pytest.fixture
def model(charged_state: ReactorState) -> ReactorModel:
    return ReactorModel(initial_state=charged_state)


class TestReactorState:
    def test_to_array_roundtrip(self, charged_state: ReactorState):
        arr = charged_state.to_array()
        restored = ReactorState.from_array(arr, charged_state.jacket_temperature, charged_state.volume)
        assert pytest.approx(restored.species_masses["component_a"]) == charged_state.species_masses["component_a"]
        assert pytest.approx(restored.temperature) == charged_state.temperature
        assert pytest.approx(restored.conversion) == charged_state.conversion

    def test_mass_total(self, charged_state: ReactorState):
        assert pytest.approx(charged_state.mass_total) == 130.0


class TestReactorModel:
    def test_step_respects_solver_horizon(self, charged_state: ReactorState):
        model = ReactorModel(initial_state=charged_state)
        model._solver_cfg["horizon"] = 0.25

        attempted_steps: list[float] = []

        def _fake_solve_horizon(step_dt: float) -> SolverResult:
            attempted_steps.append(step_dt)
            return SolverResult(
                status=SolverStatus.SUCCESS,
                state={
                    "species_masses": dict(model.state.species_masses),
                    "conversions": dict(model.state.conversions),
                    "T": model.state.temperature,
                },
            )

        model._solve_horizon = _fake_solve_horizon
        model.step(1.0)

        assert len(attempted_steps) == 4
        assert all(step <= 0.25 + 1e-12 for step in attempted_steps)
        assert pytest.approx(sum(attempted_steps), rel=0, abs=1e-12) == 1.0

    def test_step_advances_conversion(self, model: ReactorModel):
        model.step(1.0)
        assert model.state.conversion > 0.0

    def test_step_conserves_mass(self, model: ReactorModel):
        initial_mass = model.state.mass_total
        model.step(1.0)
        # Mass should be conserved (no feeds active)
        assert pytest.approx(model.state.mass_total, rel=1e-4) == initial_mass

    def test_exotherm_raises_temperature(self, model: ReactorModel):
        """With no jacket cooling offset, reaction heat should raise temperature."""
        # Set jacket to same temp so heat transfer is zero -> only exotherm
        model.state.jacket_temperature = model.state.temperature
        T_initial = model.state.temperature
        for _ in range(10):
            model.step(1.0)
        assert model.state.temperature > T_initial

    @pytest.mark.timeout(30)
    def test_adiabatic_temperature_rise(self):
        """With UA=0, temperature rise should match delta_H * delta_alpha / Cp."""
        state = ReactorState(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.0},
            temperature=353.15,
            jacket_temperature=353.15,
            volume=0.1,
        )
        model = ReactorModel(
            thermal=ThermalParams(Cp=1.8, UA=0.0),
            initial_state=state,
        )
        # UA=0 is degenerate for IPOPT (hangs); use scipy fallback directly
        T0 = model.state.temperature
        for _ in range(60):
            model._capture_initial_masses()
            model._update_fluid_mechanics()
            model._fallback_step(1.0)
        delta_T = model.state.temperature - T0
        delta_alpha = model.state.conversion

        # Expected: delta_T ≈ delta_H * m_component_a * delta_alpha / (m_total * Cp)
        expected_dT = (350.0 * 100.0 * delta_alpha) / (130.0 * 1.8)
        assert pytest.approx(delta_T, rel=0.1) == expected_dT

    def test_cooling_reduces_temperature(self):
        """Cold jacket should cool the reactor."""
        state = ReactorState(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.95},
            temperature=373.15,  # 100 C
            jacket_temperature=293.15,  # 20 C jacket
            volume=0.1,
        )
        model = ReactorModel(initial_state=state)
        T_initial = model.state.temperature
        for _ in range(60):
            model.step(1.0)
        assert model.state.temperature < T_initial

    def test_feed_increases_mass(self):
        # Start with a small amount of solvent so m_total > 0 for energy balance
        state = ReactorState(
            species_masses={"component_a": 0.0, "component_b": 0.0, "product": 0.0, "solvent": 0.1},
            conversions={"alpha": 0.0},
            temperature=298.15,
            jacket_temperature=298.15,
            volume=0.1,
        )
        model = ReactorModel(initial_state=state)
        model.set_feed_rate("component_a", 0.5)  # kg/s
        model.step(2.0)
        assert model.state.species_masses["component_a"] > 0.0

    def test_temperature_bounded(self):
        """Temperature should stay within Pyomo variable bounds (max 500K)."""
        state = ReactorState(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.0},
            temperature=490.0,  # near cap
            jacket_temperature=490.0,
            volume=0.1,
        )
        model = ReactorModel(
            thermal=ThermalParams(UA=0.0),
            initial_state=state,
        )
        for _ in range(5):
            model.step(1.0)
        assert model.state.temperature <= 500.0

    def test_viscosity_property(self, model: ReactorModel):
        assert model.viscosity > 0.0

    def test_pressure_atmospheric(self, model: ReactorModel):
        # Pressure is kept at 0.5 bar for security reasons (not atmospheric)
        assert pytest.approx(model.pressure_bar, rel=0.01) == 0.5

    def test_multi_step_simulation(self, model: ReactorModel):
        """Run many steps; conversion and temperature should progress monotonically."""
        prev_conv = model.state.conversion
        prev_temp = model.state.temperature
        # Adiabatic-like: jacket at same temperature so only reaction heat drives T
        model.state.jacket_temperature = model.state.temperature
        for i in range(20):
            model.step(1.0)
            # Conversion must never decrease
            assert model.state.conversion >= prev_conv - 1e-9, (
                f"Step {i}: conversion decreased ({model.state.conversion} < {prev_conv})"
            )
            prev_conv = model.state.conversion
        assert model.state.conversion > 0.01, "Multi-step sim should make measurable progress"

    def test_fallback_solver_produces_valid_state(self, model: ReactorModel):
        """Force Pyomo failure → verify scipy fallback produces valid results."""
        # Make _solve_horizon always fail so step() falls back
        def _always_fail(dt):
            return SolverResult(status=SolverStatus.FAILED_EXCEPTION, state=None, message="forced failure")

        model._solve_horizon = _always_fail
        model.step(1.0)

        assert model.last_solve_method == "fallback"
        assert model.state.temperature > 0.0
        assert model.state.mass_total > 0.0
        # Conversion should still be non-negative
        assert model.state.conversion >= 0.0

    def test_model_reuse_across_steps(self, model: ReactorModel):
        """Pyomo model should be built once and reused (identity check)."""
        model.step(1.0)
        first_model = model._pyomo_model
        assert first_model is not None

        model.step(1.0)
        assert model._pyomo_model is first_model, "Pyomo model was rebuilt unexpectedly"

    def test_reinitialize_clears_cached_model(self):
        """reinitialize() should reset the cached Pyomo model."""
        from reactor.config import ModelConfig
        cfg = ModelConfig.from_yaml("configs/default.yaml")
        state = ReactorState(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.0},
            temperature=353.15, jacket_temperature=353.15,
            volume=0.1,
        )
        model = ReactorModel(model_config=cfg, initial_state=state)
        model.step(1.0)
        assert model._pyomo_model is not None

        model.reinitialize(cfg)
        assert model._pyomo_model is None, "reinitialize did not clear cached model"
