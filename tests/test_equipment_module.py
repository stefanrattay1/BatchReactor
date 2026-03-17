"""Tests for Equipment Modules and EMManager (ISA-88 EM/CM layer)."""

from __future__ import annotations

import pytest

from reactor.control_module import OnOffValve, Pump, Sensor, Motor, Heater, ControlValve, CMState
from reactor.equipment_module import (
    EMState,
    EquipmentConfigError,
    EquipmentModule,
    EquipmentStateRecipe,
    ModeStep,
    OperatingMode,
    ValidationIssue,
    _evaluate_check,
    build_equipment_module,
    validate_equipment_config,
    validate_equipment_state_recipe,
)
from reactor.em_manager import EMManager
from reactor.sensor_buffer import SensorBuffer
from reactor.execution_adapters import SimulationCMAdapter, CMAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valve(tag, flow_rate=1.0):
    return OnOffValve(tag, tag, config={"flow_rate": flow_rate})


def _make_pump(tag):
    return Pump(tag, tag, config={"max_speed": 1500})


def _make_sensor(tag, pv=0.0):
    class _M:
        pass
    model = _M()
    cm = Sensor(tag, tag)
    return cm, model


def _make_em_drain():
    """Build a minimal Entleeren EM with XV-301, P-301, FT-301."""
    em = EquipmentModule("EM-DRAIN", "Entleeren", ["XV-301", "P-301", "FT-301"])
    em.register_mode(OperatingMode(
        name="aus",
        display_name="Aus",
        steps=[
            ModeStep("Pumpe stoppen", "command:P-301:stop"),
            ModeStep("Ventil schliessen", "command:XV-301:close"),
        ],
    ))
    em.register_mode(OperatingMode(
        name="entleeren",
        display_name="Entleeren",
        steps=[
            ModeStep("Auslass oeffnen", "command:XV-301:open", check="cm_state:XV-301:running", timeout_s=5),
            ModeStep("Pumpe starten", "command:P-301:start", check="cm_state:P-301:running", timeout_s=5),
        ],
    ))
    return em


def _cm_lookup():
    """Build a minimal CM lookup dict for EM-DRAIN tests."""
    valve = _make_valve("XV-301")
    pump = _make_pump("P-301")
    sensor = Sensor("FT-301", "FT-301")
    return {"XV-301": valve, "P-301": pump, "FT-301": sensor}


# ---------------------------------------------------------------------------
# EquipmentModule: mode registration and request
# ---------------------------------------------------------------------------

class TestEquipmentModuleBasics:
    def test_available_modes(self):
        em = _make_em_drain()
        assert "aus" in em.available_modes
        assert "entleeren" in em.available_modes

    def test_initial_mode(self):
        em = _make_em_drain()
        assert em.current_mode == "aus"

    def test_initial_state_idle(self):
        em = _make_em_drain()
        assert em.em_state == EMState.IDLE

    def test_request_unknown_mode_returns_false(self):
        em = _make_em_drain()
        assert em.request_mode("unknown_mode") is False

    def test_request_known_mode_transitions_to_transitioning(self):
        em = _make_em_drain()
        assert em.request_mode("entleeren") is True
        assert em.em_state == EMState.TRANSITIONING

    def test_request_current_mode_while_transitioning_cancels_transition(self):
        em = _make_em_drain()
        em.request_mode("entleeren")
        assert em.request_mode("aus") is True
        assert em.requested_mode is None
        assert em.em_state == EMState.IDLE

    def test_same_mode_while_idle_returns_true(self):
        em = _make_em_drain()
        assert em.em_state == EMState.IDLE
        assert em.current_mode == "aus"
        assert em.request_mode("aus") is True
        assert em.em_state == EMState.IDLE

    def test_same_mode_while_active_returns_true(self):
        em = _make_em_drain()
        # Complete transition to a non-default mode first
        em.request_mode("entleeren")
        cms = _cm_lookup()
        # Tick enough to complete the steps
        for _ in range(5):
            em.tick(0.5, cms)
        assert em.em_state == EMState.ACTIVE
        assert em.current_mode == "entleeren"
        assert em.request_mode("entleeren") is True  # already in requested mode

    def test_reset_fault_clears_state(self):
        em = _make_em_drain()
        em._state = EMState.FAULT
        em.reset_fault()
        assert em.em_state == EMState.IDLE


# ---------------------------------------------------------------------------
# EquipmentModule: step sequencing
# ---------------------------------------------------------------------------

class TestModeTransitionSequencing:
    def test_instant_transition_for_empty_steps(self):
        em = EquipmentModule("EM-X", "Test", [])
        em.register_mode(OperatingMode("on", "On", steps=[]))
        em.request_mode("on")
        cms = {}
        em.tick(0.5, cms)
        assert em.em_state == EMState.ACTIVE
        assert em.current_mode == "on"

    def test_steps_executed_in_order(self):
        executed = []

        valve = _make_valve("XV-301")
        pump = _make_pump("P-301")

        em = EquipmentModule("EM-T", "Test", ["XV-301", "P-301"])
        em.register_mode(OperatingMode(
            name="start",
            display_name="Start",
            steps=[
                ModeStep("Open valve", "command:XV-301:open"),
                ModeStep("Start pump", "command:P-301:start"),
            ],
        ))
        em.request_mode("start")
        cms = {"XV-301": valve, "P-301": pump}

        # First tick: executes step 0 action (open valve), check is None → advance
        em.tick(0.5, cms)
        # After step 0 completes: valve should be open
        assert valve.state == CMState.RUNNING

        # Second tick: executes step 1 action (start pump)
        em.tick(0.5, cms)
        assert pump.state == CMState.RUNNING

        # Third tick: no more steps → transition complete
        em.tick(0.5, cms)
        assert em.em_state == EMState.ACTIVE
        assert em.current_mode == "start"

    def test_check_condition_waits(self):
        valve = _make_valve("XV-301")
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(OperatingMode(
            name="open",
            display_name="Open",
            steps=[
                ModeStep("Open valve", "command:XV-301:open",
                         check="cm_state:XV-301:running", timeout_s=5),
            ],
        ))
        em.request_mode("open")
        cms = {"XV-301": valve}

        # First tick: execute action (open) + check → valve just opened → RUNNING → check passes
        em.tick(0.5, cms)
        # step check passes (valve just opened to RUNNING state)
        em.tick(0.5, cms)
        assert em.em_state == EMState.ACTIVE

    def test_timeout_causes_fault(self):
        valve = _make_valve("XV-301")
        # Never open the valve → check will never pass
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(OperatingMode(
            name="wait",
            display_name="Wait",
            steps=[
                ModeStep("Wait for sensor", "noop",
                         check="cm_state:XV-301:running", timeout_s=2.0, on_timeout="fault"),
            ],
        ))
        em.request_mode("wait")
        cms = {"XV-301": valve}

        # Tick beyond timeout
        for _ in range(10):
            em.tick(0.5, cms)

        assert em.em_state == EMState.FAULT

    def test_timeout_skip_advances(self):
        valve = _make_valve("XV-301")
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(OperatingMode(
            name="skip",
            display_name="Skip",
            steps=[
                ModeStep("Skip step", "noop",
                         check="cm_state:XV-301:running", timeout_s=1.0, on_timeout="skip"),
            ],
        ))
        em.request_mode("skip")
        cms = {"XV-301": valve}

        for _ in range(10):
            em.tick(0.5, cms)

        assert em.em_state == EMState.ACTIVE

    def test_get_status_includes_transition_info(self):
        valve = _make_valve("XV-301")
        em = _make_em_drain()
        em.request_mode("entleeren")
        status = em.get_status()
        assert status["state"] == "transitioning"
        assert status["transitioning_to"] == "entleeren"
        assert "transition_step" in status


# ---------------------------------------------------------------------------
# Check evaluator
# ---------------------------------------------------------------------------

class TestCheckEvaluator:
    def test_always_true(self):
        assert _evaluate_check("always", {}) is True

    def test_cm_state_running(self):
        pump = _make_pump("P-101")
        pump.command("start")
        assert _evaluate_check("cm_state:P-101:running", {"P-101": pump}) is True

    def test_cm_state_idle(self):
        pump = _make_pump("P-101")
        assert _evaluate_check("cm_state:P-101:idle", {"P-101": pump}) is True
        assert _evaluate_check("cm_state:P-101:running", {"P-101": pump}) is False

    def test_pv_gt(self):
        pump = _make_pump("P-101")
        pump.command("set_speed", 900.0)
        assert _evaluate_check("pv_gt:P-101:500.0", {"P-101": pump}) is True
        assert _evaluate_check("pv_gt:P-101:1200.0", {"P-101": pump}) is False

    def test_pv_lt(self):
        pump = _make_pump("P-101")
        pump.command("set_speed", 200.0)
        assert _evaluate_check("pv_lt:P-101:500.0", {"P-101": pump}) is True
        assert _evaluate_check("pv_lt:P-101:100.0", {"P-101": pump}) is False

    def test_unknown_cm_returns_false(self):
        assert _evaluate_check("cm_state:MISSING:running", {}) is False

    def test_unknown_check_type_returns_false(self):
        pump = _make_pump("P-101")
        assert _evaluate_check("magic:P-101:test", {"P-101": pump}) is False

    def test_compound_check_and_or_not(self):
        pump = _make_pump("P-101")
        pump.command("set_speed", 900.0)
        assert _evaluate_check(
            "(pv_gt:P-101:800 AND pv_lt:P-101:1200) OR NOT cm_state:P-101:running",
            {"P-101": pump},
        ) is True

    def test_compound_check_case_insensitive_operators(self):
        pump = _make_pump("P-101")
        assert _evaluate_check("cm_state:P-101:idle aNd nOt cm_state:P-101:running", {"P-101": pump}) is True

    def test_invalid_compound_check_warns_and_fails_closed(self, caplog):
        pump = _make_pump("P-101")
        assert _evaluate_check("cm_state:P-101:idle AND (pv_gt:P-101:100", {"P-101": pump}) is False
        assert "Invalid check expression" in caplog.text

    def test_missing_pv_value_warns_and_fails_closed(self, caplog):
        sensor = Sensor("FT-301", "Flow")
        assert _evaluate_check("pv_gt:FT-301:0.1", {"FT-301": sensor}) is False
        assert "PV unavailable" in caplog.text


# ---------------------------------------------------------------------------
# build_equipment_module factory
# ---------------------------------------------------------------------------

class TestBuildEquipmentModule:
    def test_build_from_config(self):
        cfg = {
            "tag": "EM-X",
            "name": "Test EM",
            "cms": ["XV-101", "P-101"],
            "modes": [
                {
                    "name": "aus",
                    "display_name": "Aus",
                    "steps": [
                        {"name": "Stop pump", "action": "command:P-101:stop"},
                    ],
                },
            ],
        }
        em = build_equipment_module(cfg)
        assert em.tag == "EM-X"
        assert "aus" in em.available_modes
        assert em.cm_tags == ["XV-101", "P-101"]

    def test_empty_modes_list(self):
        cfg = {"tag": "EM-EMPTY", "name": "Empty", "cms": []}
        em = build_equipment_module(cfg)
        assert em.available_modes == []


# ---------------------------------------------------------------------------
# EMManager
# ---------------------------------------------------------------------------

class _DummyState:
    temperature: float = 320.0
    jacket_temperature: float = 310.0
    volume: float = 0.1
    pressure_bar: float = 0.5


class _DummyModel:
    def __init__(self):
        self.state = _DummyState()


def _make_em_manager_from_cfg():
    model = _DummyModel()
    buf = SensorBuffer()
    cfg = {
        "control_modules": [
            {"tag": "XV-301", "type": "valve_onoff", "name": "Auslass", "flow_rate": 1.0},
            {"tag": "P-301", "type": "pump", "name": "Entleerpumpe"},
            {"tag": "FT-301", "type": "sensor", "name": "Durchfluss"},
        ],
        "equipment_modules": [
            {
                "tag": "EM-DRAIN",
                "name": "Entleeren",
                "cms": ["XV-301", "P-301", "FT-301"],
                "modes": [
                    {
                        "name": "aus",
                        "display_name": "Aus",
                        "steps": [
                            {"name": "Stop pump", "action": "command:P-301:stop"},
                        ],
                    },
                    {
                        "name": "entleeren",
                        "display_name": "Entleeren",
                        "steps": [
                            {"name": "Open valve", "action": "command:XV-301:open",
                             "check": "cm_state:XV-301:running", "timeout_s": 5},
                        ],
                    },
                ],
            },
        ],
    }
    def _sim_adapter_factory(cm_tag: str, em_tag: str) -> CMAdapter:
        src = f"em:{em_tag}" if em_tag else f"cm:{cm_tag}"
        return SimulationCMAdapter(model, buf, src)

    mgr = EMManager(equipment_cfg=cfg, adapter_factory=_sim_adapter_factory)
    return mgr, model, buf


def _make_interlocked_manager():
    model = _DummyModel()
    buf = SensorBuffer()
    cfg = {
        "control_modules": [
            {"tag": "XV-101", "type": "valve_onoff", "name": "Component A", "flow_rate": 1.0},
            {"tag": "P-101", "type": "pump", "name": "Fill Pump"},
            {"tag": "XV-301", "type": "valve_onoff", "name": "Drain", "flow_rate": 1.0},
            {"tag": "P-301", "type": "pump", "name": "Drain Pump"},
        ],
        "interlocks": {
            "mode_conflicts": [
                {"left": "EM-FILL:dose_component_a", "right": "EM-DRAIN:entleeren"},
            ],
            "mode_preconditions": [
                {"selector": "EM-DRAIN:entleeren", "requires": ["EM-FILL:aus"]},
            ],
        },
        "equipment_modules": [
            {
                "tag": "EM-FILL",
                "name": "Fill",
                "cms": ["XV-101", "P-101"],
                "modes": [
                    {"name": "aus", "display_name": "Aus", "steps": []},
                    {"name": "dose_component_a", "display_name": "Component A", "steps": []},
                ],
            },
            {
                "tag": "EM-DRAIN",
                "name": "Drain",
                "cms": ["XV-301", "P-301"],
                "modes": [
                    {"name": "aus", "display_name": "Aus", "steps": []},
                    {"name": "entleeren", "display_name": "Drain", "steps": []},
                ],
            },
        ],
    }
    def _sim_adapter_factory(cm_tag: str, em_tag: str) -> CMAdapter:
        src = f"em:{em_tag}" if em_tag else f"cm:{cm_tag}"
        return SimulationCMAdapter(model, buf, src)

    mgr = EMManager(equipment_cfg=cfg, adapter_factory=_sim_adapter_factory)
    return mgr


class TestEMManager:
    def test_builds_cms_and_ems(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        assert "XV-301" in mgr._cms
        assert "EM-DRAIN" in mgr._ems

    def test_request_mode_succeeds(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        assert mgr.request_mode("EM-DRAIN", "entleeren") is True

    def test_request_mode_unknown_em_fails(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        assert mgr.request_mode("EM-DOES-NOT-EXIST", "aus") is False

    def test_tick_advances_em(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        mgr.request_mode("EM-DRAIN", "entleeren")
        em = mgr._ems["EM-DRAIN"]
        assert em.em_state == EMState.TRANSITIONING
        for _ in range(5):
            mgr.tick(0.5)
        assert em.em_state == EMState.ACTIVE

    def test_dispatch_recipe_modes(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        recipe_values = {"em_mode:EM-DRAIN": "entleeren", "jacket_temp": 338.15}
        mgr.dispatch_recipe_modes(recipe_values)
        em = mgr._ems["EM-DRAIN"]
        assert em.em_state == EMState.TRANSITIONING

    def test_dispatch_no_change_skipped(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        recipe_values = {"em_mode:EM-DRAIN": "entleeren"}
        mgr.dispatch_recipe_modes(recipe_values)
        em = mgr._ems["EM-DRAIN"]
        for _ in range(5):
            mgr.tick(0.5)
        assert em.current_mode == "entleeren"
        # Same mode again — should be no-op (no double dispatch)
        mgr.dispatch_recipe_modes(recipe_values)
        assert em.em_state == EMState.ACTIVE  # still active, not transitioning again

    def test_reset_recipe_modes_clears_cache(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        recipe_values = {"em_mode:EM-DRAIN": "entleeren"}
        mgr.dispatch_recipe_modes(recipe_values)
        mgr.reset_recipe_modes()
        # After reset, same value should dispatch again
        em = mgr._ems["EM-DRAIN"]
        em._state = EMState.IDLE
        em._current_mode = "aus"
        mgr.dispatch_recipe_modes(recipe_values)
        assert em.em_state == EMState.TRANSITIONING

    def test_get_status_structure(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        status = mgr.get_status()
        assert "equipment_modules" in status
        assert "control_modules" in status
        assert "EM-DRAIN" in status["equipment_modules"]
        assert "XV-301" in status["control_modules"]

    def test_get_em_list(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        lst = mgr.get_em_list()
        assert len(lst) == 1
        em_info = lst[0]
        assert em_info["tag"] == "EM-DRAIN"
        assert "aus" in em_info["modes"]

    def test_has_modules(self):
        mgr, _, _ = _make_em_manager_from_cfg()
        assert mgr.has_modules is True

    def test_empty_config_has_no_modules(self):
        model = _DummyModel()
        buf = SensorBuffer()
        def _sim_adapter_factory(cm_tag: str, em_tag: str) -> CMAdapter:
            return SimulationCMAdapter(model, buf, "em:X")

        mgr = EMManager(equipment_cfg={}, adapter_factory=_sim_adapter_factory)
        assert mgr.has_modules is False

    def test_interlock_conflict_rejects_request(self):
        mgr = _make_interlocked_manager()
        assert mgr.request_mode("EM-FILL", "dose_component_a") is True
        mgr.tick(0.1)

        assert mgr.request_mode("EM-DRAIN", "entleeren") is False
        events = mgr.consume_events()
        assert any(e.get("type") == "mode_request_rejected" for e in events)
        assert any(str(e.get("reason", "")) for e in events)

    def test_precondition_rejects_request(self):
        mgr = _make_interlocked_manager()
        assert mgr.request_mode("EM-FILL", "dose_component_a") is True
        mgr.tick(0.1)

        assert mgr.request_mode("EM-DRAIN", "entleeren") is False
        reasons = [str(e.get("reason", "")) for e in mgr.consume_events()]
        assert any("precondition_failed" in r or "interlock_conflict" in r for r in reasons)


# ---------------------------------------------------------------------------
# EquipmentStateRecipe validation
# ---------------------------------------------------------------------------


def _cm_registry_full():
    """Build a CM registry with all types for validation tests."""
    return {
        "XV-301": OnOffValve("XV-301", "Drain Valve", config={"flow_rate": 1.0}),
        "P-301": Pump("P-301", "Drain Pump", config={"max_speed": 1500}),
        "FT-301": Sensor("FT-301", "Flow Sensor"),
        "M-101": Motor("M-101", "Agitator"),
        "HE-101": Heater("HE-101", "Heater"),
        "PCV-101": ControlValve("PCV-101", "Pressure Valve"),
    }


class TestEquipmentStateRecipeValidation:
    def test_valid_recipe_no_issues(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="entleeren", display_name="Drain",
            steps=[
                ModeStep("Open valve", "command:XV-301:open", check="cm_state:XV-301:running"),
                ModeStep("Start pump", "command:P-301:start", check="cm_state:P-301:running"),
            ],
            preconditions=["cm_state:XV-301:idle"],
            postconditions=["cm_state:P-301:running"],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-DRAIN", ["XV-301", "P-301", "FT-301"], registry)
        assert len(issues) == 0

    def test_unknown_cm_in_action_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Open", "command:NONEXISTENT:open")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", [], registry)
        assert any(i.severity == "error" and "NONEXISTENT" in i.message for i in issues)

    def test_invalid_command_for_cm_type_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Fly", "command:XV-301:fly")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", ["XV-301"], registry)
        assert any(i.severity == "error" and "fly" in i.message for i in issues)

    def test_unknown_cm_in_check_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Wait", "noop", check="cm_state:MISSING:running")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", [], registry)
        assert any(i.severity == "error" and "MISSING" in i.message for i in issues)

    def test_invalid_check_format_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Wait", "noop", check="bad_format")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", [], registry)
        assert any(i.severity == "error" for i in issues)

    def test_unknown_check_type_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Wait", "noop", check="magic:XV-301:test")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", ["XV-301"], registry)
        assert any(i.severity == "error" and "magic" in i.message for i in issues)

    def test_compound_check_is_valid(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="good", display_name="Good",
            steps=[ModeStep("Wait", "noop", check="cm_state:XV-301:idle AND pv_lt:FT-301:1.0")],
            preconditions=["NOT cm_state:P-301:running"],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-DRAIN", ["XV-301", "P-301", "FT-301"], registry)
        assert not any(i.severity == "error" for i in issues)

    def test_invalid_compound_check_syntax_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Wait", "noop", check="cm_state:XV-301:idle AND (pv_lt:FT-301:1.0")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", ["XV-301", "FT-301"], registry)
        assert any(i.severity == "error" and "Invalid check expression" in i.message for i in issues)

    def test_pv_threshold_not_numeric_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Check", "noop", check="pv_gt:FT-301:abc")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", ["FT-301"], registry)
        assert any(i.severity == "error" and "not a valid number" in i.message for i in issues)

    def test_invalid_on_timeout_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Wait", "noop", on_timeout="explode")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", [], registry)
        assert any(i.severity == "error" and "on_timeout" in i.message for i in issues)

    def test_duplicate_step_name_is_warning(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="dup", display_name="Dup",
            steps=[
                ModeStep("Same Name", "command:XV-301:open"),
                ModeStep("Same Name", "command:XV-301:close"),
            ],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", ["XV-301"], registry)
        assert any(i.severity == "warning" and "Duplicate" in i.message for i in issues)

    def test_cm_not_owned_by_em_is_warning(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="cross", display_name="Cross",
            steps=[ModeStep("Open", "command:XV-301:open")],
        )
        # XV-301 exists in registry but not in em_cm_tags
        issues = validate_equipment_state_recipe(recipe, "EM-OTHER", ["P-301"], registry)
        assert any(i.severity == "warning" and "not owned" in i.message for i in issues)

    def test_precondition_with_unknown_cm_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="pre", display_name="Pre",
            steps=[],
            preconditions=["cm_state:GHOST:idle"],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", [], registry)
        assert any(i.severity == "error" and "GHOST" in i.message for i in issues)

    def test_postcondition_with_bad_format_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="post", display_name="Post",
            steps=[],
            postconditions=["bad"],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", [], registry)
        assert any(i.severity == "error" for i in issues)

    def test_noop_action_not_validated(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="noop", display_name="Noop",
            steps=[ModeStep("Wait", "noop")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", [], registry)
        assert len(issues) == 0

    def test_action_missing_verb_is_error(self):
        registry = _cm_registry_full()
        recipe = EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Bad", "command:XV-301")],
        )
        issues = validate_equipment_state_recipe(recipe, "EM-X", ["XV-301"], registry)
        assert any(i.severity == "error" and "at least" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Precondition enforcement
# ---------------------------------------------------------------------------


class TestPreconditionEnforcement:
    def test_precondition_met_allows_transition(self):
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(EquipmentStateRecipe(
            name="open", display_name="Open",
            steps=[ModeStep("Open", "command:XV-301:open")],
            preconditions=["cm_state:XV-301:idle"],
        ))
        cms = {"XV-301": _make_valve("XV-301")}
        assert em.request_mode("open", cm_lookup=cms) is True
        assert em.em_state == EMState.TRANSITIONING

    def test_precondition_not_met_rejects_transition(self):
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(EquipmentStateRecipe(
            name="open", display_name="Open",
            steps=[ModeStep("Open", "command:XV-301:open")],
            preconditions=["cm_state:XV-301:running"],  # valve is idle, not running
        ))
        cms = {"XV-301": _make_valve("XV-301")}
        assert em.request_mode("open", cm_lookup=cms) is False

    def test_no_preconditions_always_allows(self):
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(EquipmentStateRecipe(
            name="open", display_name="Open",
            steps=[ModeStep("Open", "command:XV-301:open")],
        ))
        cms = {"XV-301": _make_valve("XV-301")}
        assert em.request_mode("open", cm_lookup=cms) is True

    def test_no_cm_lookup_skips_precondition_check(self):
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(EquipmentStateRecipe(
            name="open", display_name="Open",
            steps=[ModeStep("Open", "command:XV-301:open")],
            preconditions=["cm_state:XV-301:running"],
        ))
        # Without cm_lookup, preconditions are not checked (backward compat)
        assert em.request_mode("open") is True

    def test_multiple_preconditions_all_must_pass(self):
        em = EquipmentModule("EM-T", "Test", ["XV-301", "P-301"])
        em.register_mode(EquipmentStateRecipe(
            name="drain", display_name="Drain",
            steps=[],
            preconditions=["cm_state:XV-301:idle", "cm_state:P-301:idle"],
        ))
        valve = _make_valve("XV-301")
        pump = _make_pump("P-301")
        cms = {"XV-301": valve, "P-301": pump}

        # Both idle → should pass
        assert em.request_mode("drain", cm_lookup=cms) is True

    def test_multiple_preconditions_one_fails(self):
        em = EquipmentModule("EM-T", "Test", ["XV-301", "P-301"])
        em.register_mode(EquipmentStateRecipe(
            name="drain", display_name="Drain",
            steps=[],
            preconditions=["cm_state:XV-301:idle", "cm_state:P-301:running"],
        ))
        valve = _make_valve("XV-301")
        pump = _make_pump("P-301")  # idle, not running
        cms = {"XV-301": valve, "P-301": pump}
        assert em.request_mode("drain", cm_lookup=cms) is False


# ---------------------------------------------------------------------------
# Postcondition assertion
# ---------------------------------------------------------------------------


class TestPostconditionAssertion:
    def test_postcondition_met_completes_normally(self):
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(EquipmentStateRecipe(
            name="open", display_name="Open",
            steps=[ModeStep("Open", "command:XV-301:open")],
            postconditions=["cm_state:XV-301:running"],
        ))
        cms = {"XV-301": _make_valve("XV-301")}
        em.request_mode("open")
        # Tick to execute action (opens valve → running) and advance
        em.tick(0.5, cms)
        em.tick(0.5, cms)
        assert em.em_state == EMState.ACTIVE
        assert em.current_mode == "open"

    def test_postcondition_not_met_still_completes_with_warning(self, caplog):
        em = EquipmentModule("EM-T", "Test", ["XV-301"])
        em.register_mode(EquipmentStateRecipe(
            name="nothing", display_name="Nothing",
            steps=[],  # no steps → instant completion
            postconditions=["cm_state:XV-301:running"],  # won't be satisfied
        ))
        cms = {"XV-301": _make_valve("XV-301")}  # valve is idle
        em.request_mode("nothing")
        em.tick(0.5, cms)
        assert em.em_state == EMState.ACTIVE  # completes despite failed postcondition
        assert "postcondition NOT met" in caplog.text

    def test_no_postconditions_completes_normally(self):
        em = EquipmentModule("EM-T", "Test", [])
        em.register_mode(EquipmentStateRecipe(
            name="on", display_name="On", steps=[],
        ))
        em.request_mode("on")
        em.tick(0.5, {})
        assert em.em_state == EMState.ACTIVE


# ---------------------------------------------------------------------------
# validate_equipment_config (full config)
# ---------------------------------------------------------------------------


class TestValidateEquipmentConfig:
    def test_valid_config_no_errors(self):
        registry = _cm_registry_full()
        em = EquipmentModule("EM-DRAIN", "Drain", ["XV-301", "P-301", "FT-301"])
        em.register_mode(EquipmentStateRecipe(
            name="entleeren", display_name="Drain",
            steps=[
                ModeStep("Open", "command:XV-301:open", check="cm_state:XV-301:running"),
                ModeStep("Start", "command:P-301:start"),
            ],
        ))
        ems = {"EM-DRAIN": em}
        issues = validate_equipment_config(ems, registry)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_strict_mode_raises_on_error(self):
        registry = _cm_registry_full()
        em = EquipmentModule("EM-X", "Test", [])
        em.register_mode(EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Fly", "command:XV-301:fly")],
        ))
        ems = {"EM-X": em}
        with pytest.raises(EquipmentConfigError, match="validation failed"):
            validate_equipment_config(ems, registry, strict=True)

    def test_non_strict_returns_issues(self):
        registry = _cm_registry_full()
        em = EquipmentModule("EM-X", "Test", [])
        em.register_mode(EquipmentStateRecipe(
            name="bad", display_name="Bad",
            steps=[ModeStep("Fly", "command:XV-301:fly")],
        ))
        ems = {"EM-X": em}
        issues = validate_equipment_config(ems, registry, strict=False)
        assert len(issues) > 0


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_operating_mode_alias_works(self):
        mode = OperatingMode(name="test", display_name="Test")
        assert isinstance(mode, EquipmentStateRecipe)
        assert mode.preconditions == []
        assert mode.postconditions == []

    def test_old_yaml_without_pre_post_parses_fine(self):
        cfg = {
            "tag": "EM-X",
            "name": "Test",
            "cms": ["XV-101"],
            "modes": [
                {
                    "name": "aus",
                    "display_name": "Aus",
                    "steps": [
                        {"name": "Stop", "action": "command:XV-101:close"},
                    ],
                },
            ],
        }
        em = build_equipment_module(cfg)
        mode = em.modes["aus"]
        assert mode.preconditions == []
        assert mode.postconditions == []

    def test_modes_property_returns_copy(self):
        em = _make_em_drain()
        modes = em.modes
        assert "aus" in modes
        assert "entleeren" in modes
        # Modifying the copy should not affect the EM
        modes.pop("aus")
        assert "aus" in em.modes


# ---------------------------------------------------------------------------
# VALID_COMMANDS on CM types
# ---------------------------------------------------------------------------


class TestCMValidCommands:
    def test_onoff_valve_commands(self):
        assert OnOffValve.VALID_COMMANDS == frozenset({"open", "close"})

    def test_control_valve_commands(self):
        assert ControlValve.VALID_COMMANDS == frozenset({"set_position", "close"})

    def test_pump_commands(self):
        assert Pump.VALID_COMMANDS == frozenset({"start", "stop", "set_speed"})

    def test_sensor_commands(self):
        assert Sensor.VALID_COMMANDS == frozenset({"enable_alarm", "disable_alarm"})

    def test_motor_commands(self):
        assert Motor.VALID_COMMANDS == frozenset({"start", "stop", "set_speed"})

    def test_heater_commands(self):
        assert Heater.VALID_COMMANDS == frozenset({"set_temperature", "off"})
