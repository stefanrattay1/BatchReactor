"""Generate a data package by running the simulation headlessly with perturbations.

Usage:
    python scripts/generate_data_package.py
    python scripts/generate_data_package.py --recipe recipes/test_fast.yaml --name my_test
    python scripts/generate_data_package.py --jacket-noise 2.0 --feed-noise 1.0 --seed 42
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

# Ensure the src package is importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from reactor.config import ModelConfig, Settings
from reactor.controller import BatchController
from reactor.physics import ReactorModel, ReactorState
from reactor.recipe import RecipePlayer, load_recipe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("generate_data_package")


def generate(
    recipe_file: str = "recipes/default.yaml",
    config_file: str = "configs/default.yaml",
    output_name: str | None = None,
    jacket_noise_K: float = 1.5,
    feed_noise_pct: float = 0.5,
    seed: int | None = None,
) -> Path:
    rng = np.random.default_rng(seed)

    # Load config and recipe
    cfg_path = PROJECT_ROOT / config_file
    model_cfg = ModelConfig.from_yaml(cfg_path)

    settings = Settings()
    ic = model_cfg.initial_conditions
    initial_state = ReactorState(
        temperature=ic.get("temperature", settings.initial_temp_k),
        jacket_temperature=ic.get("jacket_temperature", settings.initial_temp_k),
        volume=ic.get("volume", 0.1),
    )
    model = ReactorModel(model_config=model_cfg, initial_state=initial_state)

    recipe_path = PROJECT_ROOT / recipe_file
    recipe = load_recipe(recipe_path)
    player = RecipePlayer(recipe)

    controller = BatchController(model, controller_cfg=model_cfg.controller)
    controller.recipe_player = player
    controller._dt = settings.tick_interval

    dt = settings.tick_interval
    elapsed = 0.0
    started = False
    snapshots: list[dict] = []
    recipe_jacket_K = settings.initial_temp_k

    logger.info("Generating data package for recipe: %s", recipe.name)
    logger.info("Total recipe duration: %.0fs (%.1f min)", recipe.total_duration, recipe.total_duration / 60)

    tick_count = 0
    # Record a few IDLE snapshots before starting (simulates ~1s delay)
    idle_ticks = int(1.0 / dt)

    while True:
        # Auto-start after idle ticks
        if not started and tick_count >= idle_ticks:
            controller.start_recipe()
            started = True

        if started:
            if not player.finished:
                setpoints = player.tick(dt)

                # Apply jacket setpoint (add noise only after material is loaded)
                if "jacket_temp" in setpoints:
                    base_jacket = setpoints["jacket_temp"]
                    recipe_jacket_K = base_jacket
                    if s.mass_total > 1.0 and jacket_noise_K > 0:
                        base_jacket += rng.normal(0, jacket_noise_K)
                    model.state.jacket_temperature = base_jacket

                # Apply feed rates (add noise only when flow is significant)
                for feed_key, species in [
                    ("feed_component_a", "component_a"),
                    ("feed_component_b", "component_b"),
                    ("feed_solvent", "solvent"),
                ]:
                    base_rate = setpoints.get(feed_key, 0.0)
                    if base_rate > 0:
                        if feed_noise_pct > 0:
                            base_rate *= (1 + rng.normal(0, feed_noise_pct / 100))
                        model.set_feed_rate(species, max(0.0, base_rate))
                    else:
                        model.set_feed_rate(species, 0.0)
            else:
                model.set_feed_rate("component_a", 0.0)
                model.set_feed_rate("component_b", 0.0)
                model.set_feed_rate("solvent", 0.0)

            model.step(dt)
            controller.evaluate()

        # Build snapshot matching /api/state response shape
        s = model.state
        snapshot = {
            "temperature_K": round(s.temperature, 2),
            "temperature_C": round(s.temperature - 273.15, 2),
            "jacket_temperature_K": round(s.jacket_temperature, 2),
            "conversion": round(s.conversion, 4),
            "viscosity_Pas": round(min(model.viscosity, 1e6), 1),
            "pressure_bar": round(model.pressure_bar, 3),
            "mass_component_a_kg": round(s.species_masses.get("component_a", 0.0), 2),
            "mass_component_b_kg": round(s.species_masses.get("component_b", 0.0), 2),
            "mass_product_kg": round(s.species_masses.get("product", 0.0), 2),
            "mass_solvent_kg": round(s.species_masses.get("solvent", 0.0), 2),
            "mass_total_kg": round(s.mass_total, 2),
            "phase": controller.phase.name,
            "phase_id": int(controller.phase),
            "dt_dt": round(controller.dt_dt, 3),
            "recipe_step": player.current_step.name if player.current_step else "DONE",
            "recipe_step_idx": player.current_step_idx,
            "recipe_elapsed_s": round(player.total_elapsed if started else 0.0, 1),
            "recipe_finished": player.finished,
            "simulation_running": controller._recipe_started,
            "feed_rate_component_a": round(model.get_feed_rate("component_a"), 3),
            "feed_rate_component_b": round(model.get_feed_rate("component_b"), 3),
            "feed_rate_solvent": round(model.get_feed_rate("solvent"), 3),
            "recipe_jacket_setpoint_K": round(recipe_jacket_K, 2),
            "override_active": False,
            "override_source": "none",
            "test_input_active": False,
            "test_input_name": None,
            "actuator_overrides": {},
            "test_scenario": None,
        }
        snapshots.append(snapshot)

        if started:
            elapsed += dt

        tick_count += 1
        if tick_count % 200 == 0:
            logger.info(
                "  t=%.0fs  phase=%s  T=%.1fK  conv=%.3f  (%d snapshots)",
                elapsed, controller.phase.name, s.temperature, s.conversion, len(snapshots),
            )

        # Stop when recipe is done and we've had enough buffer
        if player.finished and elapsed > player.total_elapsed + 60:
            break
        # Safety: don't run forever
        if elapsed > recipe.total_duration + 600:
            break

    # Write output
    output_dir = PROJECT_ROOT / "data_packages"
    output_dir.mkdir(exist_ok=True)

    name = output_name or f"{recipe.name.replace(' ', '_').replace('(', '').replace(')', '')}_{datetime.now():%Y%m%d_%H%M%S}"
    output_path = output_dir / f"{name}.json"

    package = {
        "metadata": {
            "name": name,
            "recipe_name": recipe.name,
            "recipe_file": recipe_file,
            "config_file": config_file,
            "tick_interval": dt,
            "total_duration": round(elapsed, 2),
            "total_snapshots": len(snapshots),
            "generated_at": datetime.now().isoformat(),
            "perturbations": {
                "jacket_noise_K": jacket_noise_K,
                "feed_noise_pct": feed_noise_pct,
                "seed": seed,
            },
        },
        "snapshots": snapshots,
    }

    with open(output_path, "w") as f:
        json.dump(package, f)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Generated %d snapshots (%.1f MB) -> %s", len(snapshots), size_mb, output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate a reactor data package")
    parser.add_argument("--recipe", default="recipes/default.yaml", help="Recipe YAML file")
    parser.add_argument("--config", default="configs/default.yaml", help="Model config YAML file")
    parser.add_argument("--name", default=None, help="Output package name")
    parser.add_argument("--jacket-noise", type=float, default=1.5, help="Jacket temperature noise (K)")
    parser.add_argument("--feed-noise", type=float, default=0.5, help="Feed rate noise (%%)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    generate(
        recipe_file=args.recipe,
        config_file=args.config,
        output_name=args.name,
        jacket_noise_K=args.jacket_noise,
        feed_noise_pct=args.feed_noise,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
