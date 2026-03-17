"""Performance tests for reactor modeling.

Run with:  pytest -m performance -v
These are excluded from the default test suite via addopts in pyproject.toml.
"""

import statistics
import time
from pathlib import Path

import pytest

from reactor.chemistry import KineticParams, ThermalParams
from reactor.config import ModelConfig
from reactor.controller import BatchController, Phase
from reactor.physics import ReactorModel, ReactorState
from reactor.recipe import RecipePlayer, load_recipe

PROJECT_ROOT = Path(__file__).parent.parent

pytestmark = pytest.mark.performance


@pytest.fixture
def default_model_config():
    return ModelConfig.from_yaml(PROJECT_ROOT / "configs" / "default.yaml")


@pytest.fixture
def default_recipe():
    return load_recipe(PROJECT_ROOT / "recipes" / "default.yaml")


def _run_full_batch(model, controller, player, dt=1.0, max_steps=5000):
    """Run a complete batch, returning (log, wall_time_s)."""
    controller.recipe_player = player
    controller._dt = dt
    controller.start_recipe()
    log = []

    t0 = time.monotonic()
    for step in range(max_steps):
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
            "solve_method": model.last_solve_method,
        })

        if player.finished and controller.phase in (Phase.DISCHARGING, Phase.RUNAWAY_ALARM):
            break

    wall_time = time.monotonic() - t0
    return log, wall_time


class TestFullBatchPerformance:
    """Benchmark a complete batch run."""

    WALL_TIME_LIMIT_S = 300.0  # generous — typical is ~100-120s for ~5000 steps

    def test_full_batch_wall_time(self, default_model_config, default_recipe, capsys):
        state = ReactorState(temperature=298.15, jacket_temperature=298.15, volume=0.1)
        model = ReactorModel(model_config=default_model_config, initial_state=state)
        controller = BatchController(model)
        player = RecipePlayer(default_recipe)

        log, wall_time = _run_full_batch(model, controller, player)

        sim_time = log[-1]["t"] if log else 0.0
        speedup = sim_time / wall_time if wall_time > 0 else float("inf")

        with capsys.disabled():
            print(f"\n{'─' * 50}")
            print(f"  Full batch performance")
            print(f"{'─' * 50}")
            print(f"  Simulated time : {sim_time:>8.1f} s  ({sim_time / 60:.1f} min)")
            print(f"  Wall time      : {wall_time:>8.2f} s")
            print(f"  Total steps    : {len(log):>8d}")
            print(f"  Speedup        : {speedup:>8.0f}x real-time")
            print(f"  Final phase    : {log[-1]['phase'].name if log else 'N/A'}")
            print(f"  Final conv.    : {log[-1]['alpha']:.3f}" if log else "")
            print(f"{'─' * 50}")

        assert wall_time < self.WALL_TIME_LIMIT_S, (
            f"Full batch took {wall_time:.1f}s, exceeds {self.WALL_TIME_LIMIT_S}s limit"
        )


class TestStepPerformance:
    """Benchmark individual physics steps."""

    MEDIAN_STEP_LIMIT_MS = 200.0  # generous — typical is ~10-50ms
    NUM_STEPS = 100

    def test_single_step_timing(self, default_model_config, capsys):
        """Time individual model.step() calls with active reaction kinetics."""
        state = ReactorState(
            species_masses={"component_a": 60.0, "component_b": 18.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.1},
            temperature=353.15,  # cure temperature — kinetics active
            jacket_temperature=353.15,
            volume=0.1,
        )
        model = ReactorModel(model_config=default_model_config, initial_state=state)

        timings_ms = []
        for _ in range(self.NUM_STEPS):
            t0 = time.monotonic()
            model.step(1.0)
            elapsed_ms = (time.monotonic() - t0) * 1000
            timings_ms.append(elapsed_ms)

        median = statistics.median(timings_ms)
        p95 = sorted(timings_ms)[int(0.95 * len(timings_ms))]

        with capsys.disabled():
            print(f"\n{'─' * 50}")
            print(f"  Single step timing ({self.NUM_STEPS} steps)")
            print(f"{'─' * 50}")
            print(f"  Min    : {min(timings_ms):>8.1f} ms")
            print(f"  Median : {median:>8.1f} ms")
            print(f"  P95    : {p95:>8.1f} ms")
            print(f"  Max    : {max(timings_ms):>8.1f} ms")
            print(f"  Total  : {sum(timings_ms):>8.0f} ms")
            print(f"{'─' * 50}")

        assert median < self.MEDIAN_STEP_LIMIT_MS, (
            f"Median step time {median:.1f}ms exceeds {self.MEDIAN_STEP_LIMIT_MS}ms limit"
        )


class TestSolverReliability:
    """Track solver method usage and fallback rates."""

    MAX_FALLBACK_RATE = 0.20  # allow up to 20% fallback

    def test_solver_fallback_rate(self, default_model_config, default_recipe, capsys):
        """Count how often IPOPT succeeds vs falls back to scipy BDF."""
        state = ReactorState(temperature=298.15, jacket_temperature=298.15, volume=0.1)
        model = ReactorModel(model_config=default_model_config, initial_state=state)
        controller = BatchController(model)
        player = RecipePlayer(default_recipe)

        log, wall_time = _run_full_batch(model, controller, player)

        method_counts = {}
        for entry in log:
            m = entry["solve_method"]
            method_counts[m] = method_counts.get(m, 0) + 1

        total = len(log)
        fallback_count = method_counts.get("fallback", 0)
        pyomo_count = method_counts.get("pyomo", 0)
        fallback_rate = fallback_count / total if total > 0 else 0.0

        with capsys.disabled():
            print(f"\n{'─' * 50}")
            print(f"  Solver reliability ({total} steps)")
            print(f"{'─' * 50}")
            for method, count in sorted(method_counts.items()):
                pct = count / total * 100 if total else 0
                print(f"  {method:<12s}: {count:>5d}  ({pct:5.1f}%)")
            print(f"  Fallback rate: {fallback_rate:.1%}")
            print(f"{'─' * 50}")

        assert fallback_rate <= self.MAX_FALLBACK_RATE, (
            f"Fallback rate {fallback_rate:.1%} exceeds {self.MAX_FALLBACK_RATE:.0%} limit"
        )

    def test_substep_overhead(self, default_model_config, capsys):
        """Measure overhead from adaptive sub-stepping by comparing step times
        across a range of conversion states (low vs high, where IPOPT may struggle)."""
        scenarios = [
            ("low conversion", 0.05, 330.0),
            ("mid conversion", 0.40, 353.0),
            ("high conversion", 0.80, 370.0),
        ]

        results = []
        for label, alpha, temp_k in scenarios:
            state = ReactorState(
                species_masses={"component_a": 60.0, "component_b": 18.0, "product": 0.0, "solvent": 0.0},
                conversions={"alpha": alpha},
                temperature=temp_k,
                jacket_temperature=temp_k,
                volume=0.1,
            )
            model = ReactorModel(model_config=default_model_config, initial_state=state)

            timings_ms = []
            methods = []
            for _ in range(20):
                t0 = time.monotonic()
                model.step(1.0)
                elapsed_ms = (time.monotonic() - t0) * 1000
                timings_ms.append(elapsed_ms)
                methods.append(model.last_solve_method)

            results.append({
                "label": label,
                "median_ms": statistics.median(timings_ms),
                "max_ms": max(timings_ms),
                "fallbacks": methods.count("fallback"),
                "total": len(methods),
            })

        with capsys.disabled():
            print(f"\n{'─' * 60}")
            print(f"  Sub-step overhead across conversion states (20 steps each)")
            print(f"{'─' * 60}")
            print(f"  {'Scenario':<18s} {'Median':>8s} {'Max':>8s} {'Fallbacks':>10s}")
            for r in results:
                print(
                    f"  {r['label']:<18s} {r['median_ms']:>7.1f}ms"
                    f" {r['max_ms']:>7.1f}ms"
                    f" {r['fallbacks']:>5d}/{r['total']}"
                )
            print(f"{'─' * 60}")

        # No hard assertion — this is primarily diagnostic
        # But flag if high-conversion steps are >10x slower than low-conversion
        if results[0]["median_ms"] > 0:
            ratio = results[-1]["median_ms"] / results[0]["median_ms"]
            with capsys.disabled():
                print(f"  High/low conversion speed ratio: {ratio:.1f}x")
            assert ratio < 50, (
                f"High-conversion steps are {ratio:.0f}x slower than low-conversion"
            )
