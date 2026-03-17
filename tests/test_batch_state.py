"""Tests for ISA-88 Batch State Machine (IEC 61512, Section 5.2)."""

from __future__ import annotations

import pytest

from reactor.batch_state import (
    BatchCommand,
    BatchState,
    BatchStateMachine,
    PHYSICS_ACTIVE_STATES,
    PROCEDURE_ACTIVE_STATES,
    TERMINAL_STATES,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _sm() -> BatchStateMachine:
    return BatchStateMachine()


def _start(sm: BatchStateMachine, t: float = 0.0) -> None:
    assert sm.dispatch(BatchCommand.START, t)


# ------------------------------------------------------------------
# Happy path
# ------------------------------------------------------------------

class TestHappyPath:
    def test_idle_start_running(self):
        sm = _sm()
        assert sm.state == BatchState.IDLE
        _start(sm)
        assert sm.state == BatchState.RUNNING

    def test_running_complete_reset(self):
        sm = _sm()
        _start(sm, 0.0)
        sm.complete(elapsed=100.0)
        assert sm.state == BatchState.COMPLETE
        assert sm.dispatch(BatchCommand.RESET, 101.0)
        assert sm.state == BatchState.IDLE

    def test_full_cycle(self):
        sm = _sm()
        _start(sm, 0.0)
        sm.complete(60.0)
        sm.dispatch(BatchCommand.RESET, 61.0)
        # Second run
        _start(sm, 100.0)
        sm.complete(200.0)
        assert sm.state == BatchState.COMPLETE


# ------------------------------------------------------------------
# Hold / Restart
# ------------------------------------------------------------------

class TestHoldRestart:
    def test_hold_and_restart(self):
        sm = _sm()
        _start(sm)
        assert sm.dispatch(BatchCommand.HOLD, 10.0)
        assert sm.state == BatchState.HELD
        assert sm.dispatch(BatchCommand.RESTART, 20.0)
        assert sm.state == BatchState.RUNNING

    def test_hold_then_stop(self):
        sm = _sm()
        _start(sm)
        sm.dispatch(BatchCommand.HOLD, 10.0)
        assert sm.dispatch(BatchCommand.STOP, 15.0)
        assert sm.state == BatchState.STOPPED

    def test_hold_then_abort(self):
        sm = _sm()
        _start(sm)
        sm.dispatch(BatchCommand.HOLD, 10.0)
        assert sm.dispatch(BatchCommand.ABORT, 15.0)
        assert sm.state == BatchState.ABORTED


# ------------------------------------------------------------------
# Stop / Abort
# ------------------------------------------------------------------

class TestStopAbort:
    def test_stop_from_running(self):
        sm = _sm()
        _start(sm)
        assert sm.dispatch(BatchCommand.STOP, 5.0)
        assert sm.state == BatchState.STOPPED
        assert sm.is_terminal

    def test_abort_from_running(self):
        sm = _sm()
        _start(sm)
        assert sm.dispatch(BatchCommand.ABORT, 5.0)
        assert sm.state == BatchState.ABORTED
        assert sm.is_terminal

    def test_reset_from_stopped(self):
        sm = _sm()
        _start(sm)
        sm.dispatch(BatchCommand.STOP, 5.0)
        assert sm.dispatch(BatchCommand.RESET, 10.0)
        assert sm.state == BatchState.IDLE

    def test_reset_from_aborted(self):
        sm = _sm()
        _start(sm)
        sm.dispatch(BatchCommand.ABORT, 5.0)
        assert sm.dispatch(BatchCommand.RESET, 10.0)
        assert sm.state == BatchState.IDLE


# ------------------------------------------------------------------
# Invalid transitions
# ------------------------------------------------------------------

class TestInvalidTransitions:
    def test_start_when_running(self):
        sm = _sm()
        _start(sm)
        assert not sm.dispatch(BatchCommand.START, 1.0)
        assert sm.state == BatchState.RUNNING

    def test_hold_when_idle(self):
        sm = _sm()
        assert not sm.dispatch(BatchCommand.HOLD, 0.0)
        assert sm.state == BatchState.IDLE

    def test_restart_when_running(self):
        sm = _sm()
        _start(sm)
        assert not sm.dispatch(BatchCommand.RESTART, 1.0)

    def test_restart_when_idle(self):
        sm = _sm()
        assert not sm.dispatch(BatchCommand.RESTART, 0.0)

    def test_reset_when_running(self):
        sm = _sm()
        _start(sm)
        assert not sm.dispatch(BatchCommand.RESET, 1.0)

    def test_stop_when_idle(self):
        sm = _sm()
        assert not sm.dispatch(BatchCommand.STOP, 0.0)


# ------------------------------------------------------------------
# Properties
# ------------------------------------------------------------------

class TestProperties:
    def test_idle_properties(self):
        sm = _sm()
        assert not sm.is_physics_active
        assert not sm.is_procedure_active
        assert not sm.is_terminal

    def test_running_properties(self):
        sm = _sm()
        _start(sm)
        assert sm.is_physics_active
        assert sm.is_procedure_active
        assert not sm.is_terminal

    def test_held_properties(self):
        sm = _sm()
        _start(sm)
        sm.dispatch(BatchCommand.HOLD, 1.0)
        assert sm.is_physics_active
        assert not sm.is_procedure_active
        assert not sm.is_terminal

    def test_complete_properties(self):
        sm = _sm()
        _start(sm)
        sm.complete(10.0)
        assert not sm.is_physics_active
        assert not sm.is_procedure_active
        assert sm.is_terminal

    def test_stopped_properties(self):
        sm = _sm()
        _start(sm)
        sm.dispatch(BatchCommand.STOP, 1.0)
        assert not sm.is_physics_active
        assert not sm.is_procedure_active
        assert sm.is_terminal


# ------------------------------------------------------------------
# complete() edge cases
# ------------------------------------------------------------------

class TestComplete:
    def test_complete_only_from_running(self):
        sm = _sm()
        _start(sm)
        sm.dispatch(BatchCommand.HOLD, 5.0)
        sm.complete(10.0)  # should be a no-op in HELD
        assert sm.state == BatchState.HELD

    def test_complete_noop_when_idle(self):
        sm = _sm()
        sm.complete(0.0)
        assert sm.state == BatchState.IDLE


# ------------------------------------------------------------------
# History tracking
# ------------------------------------------------------------------

class TestHistory:
    def test_history_records_transitions(self):
        sm = _sm()
        _start(sm, 0.0)
        sm.dispatch(BatchCommand.HOLD, 10.0)
        sm.dispatch(BatchCommand.RESTART, 20.0)
        sm.complete(60.0)

        h = sm.history
        assert len(h) == 4
        assert h[0] == {"at_s": 0.0, "from": "IDLE", "to": "RUNNING", "command": "START"}
        assert h[1] == {"at_s": 10.0, "from": "RUNNING", "to": "HELD", "command": "HOLD"}
        assert h[2] == {"at_s": 20.0, "from": "HELD", "to": "RUNNING", "command": "RESTART"}
        assert h[3] == {"at_s": 60.0, "from": "RUNNING", "to": "COMPLETE", "command": "AUTO_COMPLETE"}

    def test_invalid_command_not_in_history(self):
        sm = _sm()
        sm.dispatch(BatchCommand.HOLD, 0.0)  # invalid
        assert len(sm.history) == 0

    def test_hard_reset_clears_history(self):
        sm = _sm()
        _start(sm)
        sm.complete(10.0)
        assert len(sm.history) == 2
        sm.reset()
        assert len(sm.history) == 0
        assert sm.state == BatchState.IDLE


# ------------------------------------------------------------------
# Serialisation
# ------------------------------------------------------------------

class TestSerialisation:
    def test_to_dict(self):
        sm = _sm()
        _start(sm, 5.0)
        d = sm.to_dict()
        assert d["state"] == "RUNNING"
        assert d["state_entered_at_s"] == 5.0
        assert len(d["history"]) == 1


# ------------------------------------------------------------------
# Frozenset constants
# ------------------------------------------------------------------

class TestConstants:
    def test_physics_active_states(self):
        assert PHYSICS_ACTIVE_STATES == {BatchState.RUNNING, BatchState.HELD}

    def test_procedure_active_states(self):
        assert PROCEDURE_ACTIVE_STATES == {BatchState.RUNNING}

    def test_terminal_states(self):
        assert TERMINAL_STATES == {BatchState.COMPLETE, BatchState.STOPPED, BatchState.ABORTED}
