"""Integration tests: run a full simulated batch and verify physics + FSM behaviour."""

from pathlib import Path

import pytest

from reactor.chemistry import KineticParams, ThermalParams
from reactor.config import ModelConfig
from reactor.controller import BatchController, Phase
from reactor.physics import ReactorModel, ReactorState
from reactor.recipe import RecipePlayer, load_recipe

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def default_recipe():
    return load_recipe(PROJECT_ROOT / "recipes" / "default.yaml")


@pytest.fixture
def default_model_config():
    return ModelConfig.from_yaml(PROJECT_ROOT / "configs" / "default.yaml")


def run_batch(model: ReactorModel, controller: BatchController, player: RecipePlayer,
              dt: float = 0.5, max_steps: int = 10000) -> list[dict]:
    """Run a complete batch and return a log of states."""
    controller.recipe_player = player
    controller._dt = dt
    controller.start_recipe()
    log = []

    for step in range(max_steps):
        # Apply recipe
        if not player.finished:
            setpoints = player.tick(dt)
            if "jacket_temp" in setpoints:
                model.state.jacket_temperature = setpoints["jacket_temp"]
            model.set_feed_rate("component_a", setpoints.get("feed_component_a", 0.0))
            model.set_feed_rate("component_b", setpoints.get("feed_component_b", 0.0))
        else:
            model.set_feed_rate("component_a", 0.0)
            model.set_feed_rate("component_b", 0.0)

        model.step(dt)
        controller.evaluate()

        log.append({
            "t": step * dt,
            "T": model.state.temperature,
            "alpha": model.state.conversion,
            "phase": controller.phase,
            "mass_total": model.state.mass_total,
            "viscosity": model.viscosity,
        })

        # Stop if recipe is done and we're discharging or cooled
        if player.finished and controller.phase in (Phase.DISCHARGING, Phase.RUNAWAY_ALARM):
            break

    return log


class TestFullBatch:
    def test_normal_batch_completes(self, default_recipe, default_model_config):
        """A normal batch should proceed through all phases without runaway."""
        state = ReactorState(temperature=298.15, jacket_temperature=298.15, volume=0.1)
        model = ReactorModel(model_config=default_model_config, initial_state=state)
        controller = BatchController(model)
        player = RecipePlayer(default_recipe)

        log = run_batch(model, controller, player, dt=1.0, max_steps=5000)

        phases_seen = {entry["phase"] for entry in log}
        assert Phase.CHARGING in phases_seen
        assert Phase.HEATING in phases_seen
        assert Phase.RUNAWAY_ALARM not in phases_seen

    def test_temperature_rises_during_heating(self, default_recipe, default_model_config):
        state = ReactorState(temperature=298.15, jacket_temperature=298.15, volume=0.1)
        model = ReactorModel(model_config=default_model_config, initial_state=state)
        controller = BatchController(model)
        player = RecipePlayer(default_recipe)

        log = run_batch(model, controller, player, dt=1.0, max_steps=5000)

        max_temp = max(entry["T"] for entry in log)
        assert max_temp > 340.0  # should heat significantly

    def test_conversion_increases(self, default_recipe, default_model_config):
        state = ReactorState(temperature=298.15, jacket_temperature=298.15, volume=0.1)
        model = ReactorModel(model_config=default_model_config, initial_state=state)
        controller = BatchController(model)
        player = RecipePlayer(default_recipe)

        log = run_batch(model, controller, player, dt=1.0, max_steps=5000)

        final_alpha = log[-1]["alpha"]
        assert final_alpha > 0.5  # should have significant conversion

    def test_mass_increases_during_charging(self, default_recipe, default_model_config):
        state = ReactorState(temperature=298.15, jacket_temperature=298.15, volume=0.1)
        model = ReactorModel(model_config=default_model_config, initial_state=state)
        controller = BatchController(model)
        player = RecipePlayer(default_recipe)

        log = run_batch(model, controller, player, dt=1.0, max_steps=5000)

        # Mass should increase during charging (first ~180 seconds)
        mass_at_start = log[0]["mass_total"]
        mass_after_charging = log[200]["mass_total"]  # ~200 seconds in
        assert mass_after_charging > mass_at_start

    def test_viscosity_increases_with_conversion(self, default_recipe, default_model_config):
        state = ReactorState(temperature=298.15, jacket_temperature=298.15, volume=0.1)
        model = ReactorModel(model_config=default_model_config, initial_state=state)
        controller = BatchController(model)
        player = RecipePlayer(default_recipe)

        log = run_batch(model, controller, player, dt=1.0, max_steps=5000)

        # Find an early point with low conversion and a later point with higher
        visc_at_charge = log[50]["viscosity"]  # during charging, no reaction yet
        # Compare against higher conversion region (near gel) where viscosity must increase
        late_entries = [e for e in log if e["alpha"] > 0.7]
        if late_entries:
            assert late_entries[-1]["viscosity"] > visc_at_charge
        else:
            # If conversion never reached 0.7, check peak viscosity exceeds initial
            assert max(e["viscosity"] for e in log) > visc_at_charge


class TestRunawayScenario:
    def test_adiabatic_runaway(self):
        """Pre-charged reactor at elevated temp with no cooling should run away."""
        state = ReactorState(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.1},
            temperature=393.15,  # 120 C — above cure temp, fast kinetics
            jacket_temperature=393.15,
            volume=0.1,
        )
        model = ReactorModel(
            thermal=ThermalParams(Cp=1.8, UA=0.0),  # no cooling at all
            initial_state=state,
        )
        controller = BatchController(model)
        controller._dt = 1.0
        controller.start_recipe()

        max_temp = state.temperature
        for _ in range(3000):
            model.step(1.0)
            controller.evaluate()
            max_temp = max(max_temp, model.state.temperature)
            if controller.phase == Phase.RUNAWAY_ALARM:
                break

        # With no cooling and fast kinetics, temperature should rise substantially
        assert max_temp > state.temperature + 20.0
