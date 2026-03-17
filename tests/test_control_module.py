"""Tests for Control Modules (ISA-88 CM layer)."""

from __future__ import annotations

import pytest

from reactor.control_module import (
    CMState,
    ControlModule,
    Heater,
    Motor,
    OnOffValve,
    ControlValve,
    Pump,
    Sensor,
    build_control_module,
    CM_REGISTRY,
)
from reactor.execution_adapters import SimulationCMAdapter
from reactor.sensor_buffer import SensorBuffer


class _DummyState:
    temperature: float = 320.0
    jacket_temperature: float = 310.0
    volume: float = 0.1
    pressure_bar: float = 0.5
    conversion: float = 0.3
    agitator_speed_rpm: float = 800.0


class _DummyModel:
    """Minimal ReactorModel stand-in."""

    def __init__(self):
        self.state = _DummyState()


def _make_valve(tag="XV-101", maps_to="feed_component_a", flow_rate=0.5):
    cm = OnOffValve(tag, "Test Valve", maps_to=maps_to, config={"flow_rate": flow_rate})
    buf = SensorBuffer()
    cm.bind(SimulationCMAdapter(_DummyModel(), buf, "em:EM-TEST"))
    return cm, buf


# ---------------------------------------------------------------------------
# OnOffValve
# ---------------------------------------------------------------------------

class TestOnOffValve:
    def test_initial_state_idle(self):
        cm, _ = _make_valve()
        assert cm.state == CMState.IDLE

    def test_open_sets_running(self):
        cm, _ = _make_valve()
        assert cm.command("open") is True
        assert cm.state == CMState.RUNNING

    def test_close_sets_idle(self):
        cm, _ = _make_valve()
        cm.command("open")
        assert cm.command("close") is True
        assert cm.state == CMState.IDLE

    def test_open_writes_flow_to_buffer(self):
        cm, buf = _make_valve(flow_rate=0.5)
        cm.command("open")
        winners = buf.resolve()
        assert "feed_component_a" in winners
        assert winners["feed_component_a"].value == pytest.approx(0.5)

    def test_close_writes_zero_to_buffer(self):
        cm, buf = _make_valve(flow_rate=0.5)
        cm.command("open")
        buf.resolve()
        cm.command("close")
        winners = buf.resolve()
        assert "feed_component_a" in winners
        assert winners["feed_component_a"].value == pytest.approx(0.0)

    def test_read_pv_position(self):
        cm, _ = _make_valve()
        assert cm.read_pv() == pytest.approx(0.0)
        cm.command("open")
        assert cm.read_pv() == pytest.approx(1.0)

    def test_unknown_command_returns_false(self):
        cm, _ = _make_valve()
        assert cm.command("rotate") is False

    def test_fault_rejects_commands(self):
        cm, _ = _make_valve()
        cm.set_fault("test fault")
        assert cm.command("open") is False

    def test_clear_fault(self):
        cm, _ = _make_valve()
        cm.set_fault("test")
        cm.clear_fault()
        assert cm.state == CMState.IDLE
        assert cm.command("open") is True

    def test_get_status_includes_pv(self):
        cm, _ = _make_valve()
        s = cm.get_status()
        assert s.tag == "XV-101"
        assert s.cm_type == "valve_onoff"
        assert s.value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# ControlValve
# ---------------------------------------------------------------------------

class TestControlValve:
    def _make(self):
        cm = ControlValve("FCV-101", "Flow Control Valve", maps_to="flow_sp", config={"max_flow": 2.0})
        cm.bind(SimulationCMAdapter(_DummyModel(), SensorBuffer(), "em:EM-X"))
        return cm

    def test_set_position_clamps(self):
        cm = self._make()
        cm.command("set_position", 150.0)
        assert cm.read_pv() == pytest.approx(100.0)

    def test_set_position_zero_is_idle(self):
        cm = self._make()
        cm.command("set_position", 50.0)
        cm.command("set_position", 0.0)
        assert cm.state == CMState.IDLE

    def test_close_sets_position_zero(self):
        cm = self._make()
        cm.command("set_position", 60.0)
        cm.command("close")
        assert cm.read_pv() == pytest.approx(0.0)
        assert cm.state == CMState.IDLE


# ---------------------------------------------------------------------------
# Pump
# ---------------------------------------------------------------------------

class TestPump:
    def _make(self, max_speed=1500):
        cm = Pump("P-101", "Test Pump", config={"max_speed": max_speed})
        cm.bind(SimulationCMAdapter(_DummyModel(), SensorBuffer(), "em:EM-X"))
        return cm

    def test_start_sets_running(self):
        cm = self._make()
        assert cm.command("start") is True
        assert cm.state == CMState.RUNNING

    def test_stop_sets_idle(self):
        cm = self._make()
        cm.command("start")
        cm.command("stop")
        assert cm.state == CMState.IDLE
        assert cm.read_pv() == pytest.approx(0.0)

    def test_start_with_speed(self):
        cm = self._make(max_speed=3000)
        cm.command("start", 1200.0)
        assert cm.read_pv() == pytest.approx(1200.0)

    def test_speed_clamped_to_max(self):
        cm = self._make(max_speed=1500)
        cm.command("set_speed", 9999.0)
        assert cm.read_pv() == pytest.approx(1500.0)

    def test_set_speed_zero_is_idle(self):
        cm = self._make()
        cm.command("start")
        cm.command("set_speed", 0.0)
        assert cm.state == CMState.IDLE


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------

class TestSensor:
    def _make(self, maps_to="temperature", alarms=None):
        cfg = {"alarms": alarms} if alarms else {}
        cm = Sensor("TT-101", "Reaktortemperatur", maps_to=maps_to, config=cfg)
        cm.bind(SimulationCMAdapter(_DummyModel(), SensorBuffer(), "em:EM-X"))
        return cm

    def test_always_running(self):
        cm = self._make()
        assert cm.state == CMState.RUNNING

    def test_reads_model_temperature(self):
        cm = self._make(maps_to="temperature")
        assert cm.read_pv() == pytest.approx(320.0)

    def test_alarm_high_triggered(self):
        cm = self._make(maps_to="temperature", alarms={"HH": 450.0, "H": 350.0})
        active = cm.check_alarms()
        # 320 K > 350? No → H should be False
        assert active.get("H") is False
        assert active.get("HH") is False

    def test_alarm_high_triggered_above_limit(self):
        cm = self._make(maps_to="temperature", alarms={"H": 300.0})
        # Model temp is 320K which is > 300K
        active = cm.check_alarms()
        assert active.get("H") is True

    def test_disable_alarm(self):
        cm = self._make(maps_to="temperature", alarms={"H": 300.0})
        cm.command("disable_alarm")
        assert cm.check_alarms() == {}

    def test_enable_alarm_after_disable(self):
        cm = self._make(maps_to="temperature", alarms={"H": 300.0})
        cm.command("disable_alarm")
        cm.command("enable_alarm")
        active = cm.check_alarms()
        assert active.get("H") is True


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------

class TestMotor:
    def _make(self):
        buf = SensorBuffer()
        cm = Motor("M-101", "Ruehrer", maps_to="agitator_speed_rpm", config={"max_speed_rpm": 1500})
        cm.bind(SimulationCMAdapter(_DummyModel(), buf, "em:EM-X"))
        return cm, buf

    def test_start_sets_running(self):
        cm, _ = self._make()
        assert cm.command("start") is True
        assert cm.state == CMState.RUNNING

    def test_stop_sets_idle(self):
        cm, _ = self._make()
        cm.command("start")
        cm.command("stop")
        assert cm.state == CMState.IDLE

    def test_set_speed_within_bounds(self):
        cm, _ = self._make()
        cm.command("set_speed", 800.0)
        assert cm.read_pv() == pytest.approx(800.0)

    def test_speed_clamped(self):
        cm, _ = self._make()
        cm.command("set_speed", 9999.0)
        assert cm.read_pv() == pytest.approx(1500.0)


# ---------------------------------------------------------------------------
# Heater
# ---------------------------------------------------------------------------

class TestHeater:
    def _make(self):
        buf = SensorBuffer()
        cm = Heater("HE-101", "Heizung", maps_to="jacket_temperature",
                    config={"min_temp": 263.15, "max_temp": 473.15})
        cm.bind(SimulationCMAdapter(_DummyModel(), buf, "em:EM-X"))
        return cm, buf

    def test_initial_state_idle(self):
        cm, _ = self._make()
        assert cm.state == CMState.IDLE

    def test_set_temperature_sets_running(self):
        cm, _ = self._make()
        cm.command("set_temperature", 353.15)
        assert cm.state == CMState.RUNNING

    def test_setpoint_clamped_to_max(self):
        cm, _ = self._make()
        cm.command("set_temperature", 999.0)
        assert cm.get_status().setpoint == pytest.approx(473.15)

    def test_setpoint_clamped_to_min(self):
        cm, _ = self._make()
        cm.command("set_temperature", 10.0)
        assert cm.get_status().setpoint == pytest.approx(263.15)

    def test_off_sets_idle(self):
        cm, _ = self._make()
        cm.command("set_temperature", 353.0)
        cm.command("off")
        assert cm.state == CMState.IDLE
        assert cm.get_status().setpoint is None

    def test_set_temperature_writes_to_buffer(self):
        cm, buf = self._make()
        cm.command("set_temperature", 353.0)
        winners = buf.resolve()
        assert "jacket_temperature" in winners
        assert winners["jacket_temperature"].value == pytest.approx(353.0)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_build_onoff_valve(self):
        cfg = {"tag": "XV-201", "type": "valve_onoff", "name": "Test", "maps_to": "feed_component_a", "flow_rate": 1.0}
        cm = build_control_module(cfg)
        assert isinstance(cm, OnOffValve)
        assert cm.tag == "XV-201"

    def test_build_pump(self):
        cfg = {"tag": "P-201", "type": "pump", "name": "Pump", "max_speed": 3000}
        cm = build_control_module(cfg)
        assert isinstance(cm, Pump)

    def test_build_sensor(self):
        cfg = {"tag": "TT-201", "type": "sensor", "name": "Temp", "maps_to": "temperature"}
        cm = build_control_module(cfg)
        assert isinstance(cm, Sensor)

    def test_build_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown CM type"):
            build_control_module({"tag": "X", "type": "turbocharger"})

    def test_all_registry_types_constructable(self):
        for name in CM_REGISTRY:
            cfg = {"tag": f"T-{name}", "type": name, "name": name}
            cm = build_control_module(cfg)
            assert cm.tag == f"T-{name}"