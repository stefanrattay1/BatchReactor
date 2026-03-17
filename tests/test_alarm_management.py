"""Tests for formal alarm management lifecycle and suppression."""

from __future__ import annotations

from reactor.alarm_management import AlarmManager


def _equipment_cfg_with_flow_and_temp() -> dict:
    return {
        "control_modules": [
            {
                "tag": "FT-301",
                "type": "sensor",
                "name": "Outlet Flow",
                "alarms": {"L": 0.05, "LL": 0.01},
            },
            {
                "tag": "TT-101",
                "type": "sensor",
                "name": "Reactor Temp",
                "alarms": {"HH": 473.15},
            },
        ]
    }


def test_alarm_lifecycle_onset_ack_clear_with_operator_history() -> None:
    manager = AlarmManager.from_equipment_config(_equipment_cfg_with_flow_and_temp())

    manager.evaluate(
        elapsed_s=10.0,
        signals={"TT-101.HH": True},
        snapshot={"temperature_K": 480.0, "phase": "CURING"},
        context={},
    )

    active = manager.get_active_alarms()
    assert len(active) == 1
    assert active[0]["alarm_id"] == "TT-101.HH"
    assert active[0]["acknowledged"] is False

    assert manager.acknowledge("TT-101.HH", operator_id="op-42", elapsed_s=12.0)

    active_after_ack = manager.get_active_alarms()
    assert len(active_after_ack) == 1
    assert active_after_ack[0]["acknowledged"] is True

    manager.evaluate(
        elapsed_s=20.0,
        signals={"TT-101.HH": False},
        snapshot={"temperature_K": 450.0, "phase": "COOLING"},
        context={},
    )

    assert manager.get_active_alarms() == []

    history = manager.get_history()
    assert [event["event"] for event in history[:3]] == ["onset", "acknowledge", "clear"]
    assert history[1]["operator_id"] == "op-42"
    assert history[0]["snapshot"]["temperature_K"] == 480.0
    assert history[2]["snapshot"]["temperature_K"] == 450.0


def test_flow_low_alarm_is_suppressed_during_venting_context() -> None:
    manager = AlarmManager.from_equipment_config(_equipment_cfg_with_flow_and_temp())

    manager.evaluate(
        elapsed_s=5.0,
        signals={"FT-301.L": True},
        snapshot={"phase": "DISCHARGING"},
        context={
            "phase": "DISCHARGING",
            "operation_name": "Vent line",
            "em_status": {"EM-DRAIN": {"mode": "entleeren", "state": "RUNNING"}},
        },
    )

    assert manager.get_active_alarms() == []
    assert manager.get_history() == []

    manager.evaluate(
        elapsed_s=8.0,
        signals={"FT-301.L": True},
        snapshot={"phase": "REACTION"},
        context={"phase": "REACTION", "operation_name": "Main hold"},
    )

    active = manager.get_active_alarms()
    assert len(active) == 1
    assert active[0]["alarm_id"] == "FT-301.L"


def test_manual_suppression_blocks_alarm_until_unsuppressed() -> None:
    manager = AlarmManager.from_equipment_config(_equipment_cfg_with_flow_and_temp())

    assert manager.set_manual_suppression(
        "TT-101.HH",
        suppressed=True,
        operator_id="lead-operator",
        elapsed_s=1.0,
        reason="commissioning",
    )

    manager.evaluate(
        elapsed_s=2.0,
        signals={"TT-101.HH": True},
        snapshot={"temperature_K": 479.0},
        context={},
    )
    assert manager.get_active_alarms() == []

    assert manager.set_manual_suppression(
        "TT-101.HH",
        suppressed=False,
        operator_id="lead-operator",
        elapsed_s=3.0,
    )

    manager.evaluate(
        elapsed_s=4.0,
        signals={"TT-101.HH": True},
        snapshot={"temperature_K": 479.5},
        context={},
    )
    active = manager.get_active_alarms()
    assert len(active) == 1
    assert active[0]["alarm_id"] == "TT-101.HH"
