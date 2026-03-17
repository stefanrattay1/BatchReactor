"""Unit tests for the batch controller FSM."""

import pytest

from reactor.chemistry import ThermalParams
from reactor.controller import (
    _DEFAULT_CONTROLLER_CFG,
    BatchController,
    Phase,
)
from reactor.physics import ReactorModel, ReactorState

# Pull thresholds from default config for test assertions
CURE_TEMP_K = _DEFAULT_CONTROLLER_CFG["cure_temp_K"]
COOL_DONE_TEMP_K = _DEFAULT_CONTROLLER_CFG["cool_done_temp_K"]
RUNAWAY_TEMP_K = _DEFAULT_CONTROLLER_CFG["runaway_temp_K"]
CONVERSION_DONE = _DEFAULT_CONTROLLER_CFG["conversion_done"]


def make_controller(
    temperature: float = 298.15,
    conversion: float = 0.0,
    mass_component_a: float = 100.0,
    mass_component_b: float = 30.0,
) -> BatchController:
    state = ReactorState(
        species_masses={"component_a": mass_component_a, "component_b": mass_component_b, "product": 0.0, "solvent": 0.0},
        conversions={"alpha": conversion},
        temperature=temperature,
        jacket_temperature=temperature,
        volume=0.1,
    )
    model = ReactorModel(initial_state=state)
    return BatchController(model)


class TestFSMTransitions:
    def test_starts_idle(self):
        ctrl = make_controller()
        assert ctrl.phase == Phase.IDLE

    def test_idle_to_charging(self):
        ctrl = make_controller()
        ctrl.start_recipe()
        ctrl.evaluate()
        assert ctrl.phase == Phase.CHARGING

    def test_charging_to_heating(self):
        ctrl = make_controller()
        ctrl.start_recipe()
        ctrl.evaluate()  # -> CHARGING
        # Simulate no recipe player -> charging completes immediately
        ctrl.recipe_player = None  # no player means _charging_complete returns False
        # Need to set a recipe player that's past charging
        from reactor.recipe import BatchStep, Recipe, RecipePlayer, ProfileSegment, ProfileType

        recipe = Recipe("test", [
            BatchStep("HEAT", 100.0, {
                "jacket_temp": ProfileSegment(ProfileType.CONSTANT, 353.15, 353.15, 100.0),
            }),
        ])
        ctrl.recipe_player = RecipePlayer(recipe)
        ctrl.evaluate()
        assert ctrl.phase == Phase.HEATING

    def test_heating_to_exotherm(self):
        ctrl = make_controller(temperature=CURE_TEMP_K + 1.0)
        ctrl.phase = Phase.HEATING
        ctrl.evaluate()
        assert ctrl.phase == Phase.EXOTHERM

    def test_exotherm_to_cooling(self):
        ctrl = make_controller(temperature=353.15, conversion=CONVERSION_DONE + 0.01)
        ctrl.phase = Phase.EXOTHERM
        ctrl.evaluate()
        assert ctrl.phase == Phase.COOLING

    def test_cooling_to_discharging(self):
        ctrl = make_controller(temperature=COOL_DONE_TEMP_K - 1.0, conversion=0.99)
        ctrl.phase = Phase.COOLING
        ctrl.evaluate()
        assert ctrl.phase == Phase.DISCHARGING

    def test_discharging_stays(self):
        ctrl = make_controller()
        ctrl.phase = Phase.DISCHARGING
        ctrl.evaluate()
        assert ctrl.phase == Phase.DISCHARGING


class TestRunawayDetection:
    def test_high_temperature_triggers_alarm(self):
        ctrl = make_controller(temperature=RUNAWAY_TEMP_K + 10.0)
        ctrl.phase = Phase.EXOTHERM
        ctrl.evaluate()
        assert ctrl.phase == Phase.RUNAWAY_ALARM

    def test_high_dt_dt_triggers_alarm(self):
        ctrl = make_controller(temperature=353.15)
        ctrl._dt = 1.0
        ctrl.phase = Phase.HEATING
        # Simulate rapid temperature rise
        for T in range(350, 380, 3):  # 3 K/s rise
            ctrl.model.state.temperature = float(T)
            ctrl._temp_history.append(float(T))
        ctrl.evaluate()
        assert ctrl.phase == Phase.RUNAWAY_ALARM

    def test_alarm_is_sticky(self):
        ctrl = make_controller(temperature=300.0)
        ctrl.phase = Phase.RUNAWAY_ALARM
        ctrl.evaluate()
        assert ctrl.phase == Phase.RUNAWAY_ALARM

    def test_alarm_manual_reset(self):
        ctrl = make_controller()
        ctrl.phase = Phase.RUNAWAY_ALARM
        ctrl.reset_alarm()
        assert ctrl.phase == Phase.IDLE

    def test_idle_does_not_trigger_runaway(self):
        ctrl = make_controller(temperature=RUNAWAY_TEMP_K + 10.0)
        ctrl.phase = Phase.IDLE
        ctrl.evaluate()
        # Still idle (not recipe started), runaway check skipped
        assert ctrl.phase == Phase.IDLE


class TestDtDt:
    def test_no_history_returns_zero(self):
        ctrl = make_controller()
        assert ctrl.dt_dt == 0.0

    def test_steady_temperature(self):
        ctrl = make_controller()
        for _ in range(10):
            ctrl._temp_history.append(353.15)
        assert pytest.approx(ctrl.dt_dt, abs=0.01) == 0.0

    def test_rising_temperature(self):
        ctrl = make_controller()
        ctrl._dt = 1.0
        for i in range(10):
            ctrl._temp_history.append(350.0 + i * 1.0)  # 1 K/s
        # 9 K rise over 10 samples * 1s = 0.9 K/s (window spans n*dt, not (n-1)*dt)
        assert pytest.approx(ctrl.dt_dt, rel=0.01) == 0.9
