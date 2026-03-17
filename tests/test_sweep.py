"""Tests for parametric sweep functionality."""

from unittest.mock import patch, MagicMock

import pytest

from reactor.batch import (
    SweepConfig,
    SweepResult,
    SweepRunner,
    BatchResult,
    _apply_config_override,
    run_sweep,
)
from reactor.config import Settings


class TestApplyConfigOverride:
    def test_top_level_key(self):
        raw = {"a": 1, "b": 2}
        result = _apply_config_override(raw, "a", 99)
        assert result["a"] == 99
        assert raw["a"] == 1  # original unchanged

    def test_nested_key(self):
        raw = {"kinetics": {"A2": 5e8, "Ea2": 75000}}
        result = _apply_config_override(raw, "kinetics.A2", 1e9)
        assert result["kinetics"]["A2"] == 1e9
        assert result["kinetics"]["Ea2"] == 75000  # sibling untouched
        assert raw["kinetics"]["A2"] == 5e8  # original unchanged

    def test_creates_missing_parent(self):
        raw = {"thermal": {"Cp": 1.8}}
        result = _apply_config_override(raw, "new_section.param", 42.0)
        assert result["new_section"]["param"] == 42.0

    def test_deep_copy_isolation(self):
        raw = {"x": {"y": {"z": 1}}}
        r1 = _apply_config_override(raw, "x.y.z", 10)
        r2 = _apply_config_override(raw, "x.y.z", 20)
        assert r1["x"]["y"]["z"] == 10
        assert r2["x"]["y"]["z"] == 20
        assert raw["x"]["y"]["z"] == 1  # original unchanged


class TestSweepConfig:
    def test_construction(self):
        cfg = SweepConfig(param_path="kinetics.A2", values=[1e8, 5e8, 1e9])
        assert cfg.param_path == "kinetics.A2"
        assert cfg.values == [1e8, 5e8, 1e9]


class TestSweepResult:
    def test_to_dict_with_error(self):
        sr = SweepResult(param_value=1e9, error="IPOPT failed")
        d = sr.to_dict()
        assert d["param_value"] == 1e9
        assert d["error"] == "IPOPT failed"
        assert "result" not in d

    def test_to_dict_with_result(self):
        mock_result = MagicMock(spec=BatchResult)
        mock_result.to_dict.return_value = {
            "final_temperature_K": 353.0,
            "peak_temperature_K": 436.0,
            "total_time_s": 4740.0,
        }
        sr = SweepResult(param_value=5e8, result=mock_result)
        d = sr.to_dict()
        assert d["param_value"] == 5e8
        assert d["final_temperature_K"] == 353.0
        assert "error" not in d


class TestRunSweep:
    def _make_fake_batch_result(self, value: float) -> BatchResult:
        return BatchResult(
            csv_path="",
            total_time_s=100.0 + value,
            wall_time_s=1.0,
            final_temperature_K=353.0,
            final_conversions={"alpha": 0.99},
            final_phase="DONE",
            total_ticks=200,
            final_masses={"component_a": 1.0},
            peak_temperature_K=400.0,
        )

    def test_sweep_calls_batch_per_value(self):
        values = [1e8, 5e8, 1e9]
        sweep_cfg = SweepConfig(param_path="kinetics.A2", values=values)

        call_log: list[float] = []

        def fake_run_batch_impl(settings, progress, cancel_flag, *, model_cfg=None):
            a2 = model_cfg.raw.get("kinetics", {}).get("A2", None)
            call_log.append(a2)
            return self._make_fake_batch_result(a2 or 0.0)

        settings = Settings()
        settings.model_config_file = str(
            __import__("pathlib").Path(__file__).parent.parent / "configs" / "default.yaml"
        )

        with patch("reactor.batch._run_batch_impl", side_effect=fake_run_batch_impl):
            results = run_sweep(settings, sweep_cfg, max_workers=2)

        assert len(results) == 3
        assert set(call_log) == {1e8, 5e8, 1e9}
        for r in results:
            assert r.result is not None
            assert r.error == ""

    def test_sweep_preserves_order(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        sweep_cfg = SweepConfig(param_path="thermal.Cp", values=values)

        def fake_impl(settings, progress, cancel_flag, *, model_cfg=None):
            cp = model_cfg.raw.get("thermal", {}).get("Cp", 0.0)
            return self._make_fake_batch_result(cp)

        settings = Settings()
        settings.model_config_file = str(
            __import__("pathlib").Path(__file__).parent.parent / "configs" / "default.yaml"
        )

        with patch("reactor.batch._run_batch_impl", side_effect=fake_impl):
            results = run_sweep(settings, sweep_cfg, max_workers=3)

        # Order must match input values
        for i, v in enumerate(values):
            assert results[i].param_value == v

    def test_sweep_handles_failed_run(self):
        values = [1e8, 5e8]
        sweep_cfg = SweepConfig(param_path="kinetics.A2", values=values)

        def fake_impl(settings, progress, cancel_flag, *, model_cfg=None):
            a2 = model_cfg.raw.get("kinetics", {}).get("A2", 0)
            if a2 == 1e8:
                raise RuntimeError("Solver diverged")
            return self._make_fake_batch_result(a2)

        settings = Settings()
        settings.model_config_file = str(
            __import__("pathlib").Path(__file__).parent.parent / "configs" / "default.yaml"
        )

        with patch("reactor.batch._run_batch_impl", side_effect=fake_impl):
            results = run_sweep(settings, sweep_cfg, max_workers=2)

        assert len(results) == 2
        # Find the failed and successful results
        failed = next(r for r in results if r.param_value == 1e8)
        ok = next(r for r in results if r.param_value == 5e8)
        assert failed.error != ""
        assert ok.result is not None


class TestSweepRunner:
    def test_initial_state(self):
        runner = SweepRunner()
        assert runner.status == "idle"
        assert not runner.is_running

    def test_get_status_dict_idle(self):
        runner = SweepRunner()
        d = runner.get_status_dict()
        assert d["status"] == "idle"
