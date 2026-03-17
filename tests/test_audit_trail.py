"""Tests for the audit trail module (state-transition event log)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from reactor.audit_trail import AuditEvent, AuditTrail, _compute_event_hash, _GENESIS_HASH


class TestAuditEvent:
    """Tests for the AuditEvent dataclass."""

    def test_to_dict_includes_all_fields(self):
        event = AuditEvent(
            sequence=1,
            timestamp="2026-03-17T12:00:00+00:00",
            elapsed_s=10.5,
            event_type="batch_state_transition",
            source="batch_state",
            actor="web_api",
            action="dispatch",
            subject="batch_state",
            details={"from": "IDLE", "to": "RUNNING", "command": "START"},
            state_snapshot={"temperature_K": 298.15},
            prev_hash="abc",
            event_hash="def",
        )
        d = event.to_dict()
        assert d["sequence"] == 1
        assert d["event_type"] == "batch_state_transition"
        assert d["actor"] == "web_api"
        assert d["details"]["from"] == "IDLE"
        assert d["state_snapshot"]["temperature_K"] == 298.15
        assert d["prev_hash"] == "abc"
        assert d["event_hash"] == "def"

    def test_to_dict_omits_none_snapshot(self):
        event = AuditEvent(
            sequence=1, timestamp="t", elapsed_s=0.0,
            event_type="test", source="test", actor="system",
            action="", subject="",
        )
        d = event.to_dict()
        assert "state_snapshot" not in d


class TestAuditTrailInMemory:
    """Tests for AuditTrail without file persistence."""

    def test_emit_increments_sequence(self):
        trail = AuditTrail()
        e1 = trail.emit(event_type="a", source="s", elapsed_s=0.0)
        e2 = trail.emit(event_type="b", source="s", elapsed_s=1.0)
        assert e1.sequence == 1
        assert e2.sequence == 2

    def test_emit_sets_hash_chain(self):
        trail = AuditTrail()
        e1 = trail.emit(event_type="a", source="s", elapsed_s=0.0)
        assert e1.prev_hash == _GENESIS_HASH
        assert e1.event_hash != ""

        e2 = trail.emit(event_type="b", source="s", elapsed_s=1.0)
        assert e2.prev_hash == e1.event_hash

    def test_emit_without_hash_chain(self):
        trail = AuditTrail(enable_hash_chain=False)
        e = trail.emit(event_type="a", source="s", elapsed_s=0.0)
        assert e.prev_hash == ""
        assert e.event_hash == ""

    def test_events_returns_copy(self):
        trail = AuditTrail()
        trail.emit(event_type="a", source="s", elapsed_s=0.0)
        events = trail.events
        events.clear()
        assert trail.event_count == 1

    def test_recent_returns_last_n(self):
        trail = AuditTrail()
        for i in range(10):
            trail.emit(event_type=f"e{i}", source="s", elapsed_s=float(i))
        recent = trail.recent(3)
        assert len(recent) == 3
        assert recent[0]["event_type"] == "e7"
        assert recent[2]["event_type"] == "e9"

    def test_verify_chain_valid(self):
        trail = AuditTrail()
        trail.emit(event_type="a", source="s", elapsed_s=0.0)
        trail.emit(event_type="b", source="s", elapsed_s=1.0)
        trail.emit(event_type="c", source="s", elapsed_s=2.0)
        valid, last = trail.verify_chain()
        assert valid is True
        assert last == 3

    def test_verify_chain_detects_tampering(self):
        trail = AuditTrail()
        trail.emit(event_type="a", source="s", elapsed_s=0.0)
        trail.emit(event_type="b", source="s", elapsed_s=1.0)
        # Tamper with event 1
        trail._events[0].details["tampered"] = True
        valid, last = trail.verify_chain()
        assert valid is False
        assert last == 0

    def test_verify_chain_empty(self):
        trail = AuditTrail()
        valid, last = trail.verify_chain()
        assert valid is True
        assert last == 0

    def test_verify_chain_without_hash_chain(self):
        trail = AuditTrail(enable_hash_chain=False)
        trail.emit(event_type="a", source="s", elapsed_s=0.0)
        valid, last = trail.verify_chain()
        assert valid is True

    def test_emit_stores_details_and_snapshot(self):
        trail = AuditTrail()
        e = trail.emit(
            event_type="test",
            source="s",
            actor="operator",
            action="do_thing",
            subject="target",
            details={"key": "val"},
            elapsed_s=5.0,
            state_snapshot={"temperature_K": 350.0},
        )
        assert e.details == {"key": "val"}
        assert e.state_snapshot == {"temperature_K": 350.0}
        assert e.actor == "operator"
        assert e.action == "do_thing"
        assert e.subject == "target"


class TestAuditTrailPersistence:
    """Tests for JSONL file persistence and reload."""

    def test_persists_to_jsonl(self, tmp_path):
        log_path = tmp_path / "audit.jsonl"
        trail = AuditTrail(log_path=log_path)
        trail.emit(event_type="a", source="s", elapsed_s=0.0)
        trail.emit(event_type="b", source="s", elapsed_s=1.0, details={"x": 42})
        trail.close()

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert first["event_type"] == "a"
        assert first["sequence"] == 1

        second = json.loads(lines[1])
        assert second["event_type"] == "b"
        assert second["details"]["x"] == 42

    def test_load_and_verify_valid_chain(self, tmp_path):
        log_path = tmp_path / "audit.jsonl"
        trail = AuditTrail(log_path=log_path)
        trail.emit(event_type="a", source="s", elapsed_s=0.0)
        trail.emit(event_type="b", source="s", elapsed_s=1.0)
        trail.emit(event_type="c", source="s", elapsed_s=2.0)
        trail.close()

        events, valid, last = AuditTrail.load_and_verify(log_path)
        assert len(events) == 3
        assert valid is True
        assert last == 3

    def test_load_and_verify_detects_file_tampering(self, tmp_path):
        log_path = tmp_path / "audit.jsonl"
        trail = AuditTrail(log_path=log_path)
        trail.emit(event_type="a", source="s", elapsed_s=0.0)
        trail.emit(event_type="b", source="s", elapsed_s=1.0)
        trail.close()

        # Tamper with the file: change event_type in first line
        lines = log_path.read_text().strip().split("\n")
        first = json.loads(lines[0])
        first["event_type"] = "tampered"
        lines[0] = json.dumps(first)
        log_path.write_text("\n".join(lines) + "\n")

        events, valid, last = AuditTrail.load_and_verify(log_path)
        assert valid is False
        assert last == 0

    def test_append_mode(self, tmp_path):
        log_path = tmp_path / "audit.jsonl"

        trail1 = AuditTrail(log_path=log_path)
        trail1.emit(event_type="a", source="s", elapsed_s=0.0)
        trail1.close()

        trail2 = AuditTrail(log_path=log_path)
        trail2.emit(event_type="b", source="s", elapsed_s=1.0)
        trail2.close()

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2


class TestHashChainIntegrity:
    """Tests for the cryptographic hash chain."""

    def test_compute_event_hash_deterministic(self):
        event_dict = {
            "sequence": 1,
            "timestamp": "2026-03-17T12:00:00",
            "elapsed_s": 0.0,
            "event_type": "test",
            "source": "test",
            "actor": "system",
            "action": "",
            "subject": "",
            "details": {},
        }
        h1 = _compute_event_hash(_GENESIS_HASH, event_dict)
        h2 = _compute_event_hash(_GENESIS_HASH, event_dict)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_different_prev_hash_gives_different_result(self):
        event_dict = {
            "sequence": 1, "timestamp": "t", "elapsed_s": 0.0,
            "event_type": "test", "source": "s", "actor": "a",
            "action": "", "subject": "", "details": {},
        }
        h1 = _compute_event_hash("a" * 64, event_dict)
        h2 = _compute_event_hash("b" * 64, event_dict)
        assert h1 != h2

    def test_hash_excludes_hash_fields(self):
        event_dict = {
            "sequence": 1, "timestamp": "t", "elapsed_s": 0.0,
            "event_type": "test", "source": "s", "actor": "a",
            "action": "", "subject": "", "details": {},
            "prev_hash": "should_be_ignored",
            "event_hash": "should_be_ignored",
        }
        event_without = {k: v for k, v in event_dict.items()
                         if k not in ("prev_hash", "event_hash")}
        h1 = _compute_event_hash(_GENESIS_HASH, event_dict)
        h2 = _compute_event_hash(_GENESIS_HASH, event_without)
        assert h1 == h2


class TestBatchStateMachineCallback:
    """Test the on_transition callback integration."""

    def test_callback_fires_on_dispatch(self):
        records = []
        from reactor.batch_state import BatchStateMachine, BatchCommand
        sm = BatchStateMachine(on_transition=lambda r: records.append(r))
        sm.dispatch(BatchCommand.START, elapsed=0.0)
        assert len(records) == 1
        assert records[0]["from"] == "IDLE"
        assert records[0]["to"] == "RUNNING"
        assert records[0]["command"] == "START"

    def test_callback_fires_on_complete(self):
        records = []
        from reactor.batch_state import BatchStateMachine, BatchCommand
        sm = BatchStateMachine(on_transition=lambda r: records.append(r))
        sm.dispatch(BatchCommand.START, elapsed=0.0)
        sm.complete(elapsed=100.0)
        assert len(records) == 2
        assert records[1]["from"] == "RUNNING"
        assert records[1]["to"] == "COMPLETE"
        assert records[1]["command"] == "AUTO_COMPLETE"

    def test_no_callback_no_error(self):
        from reactor.batch_state import BatchStateMachine, BatchCommand
        sm = BatchStateMachine()  # no callback
        sm.dispatch(BatchCommand.START, elapsed=0.0)
        assert sm.state.value == "RUNNING"

    def test_invalid_command_no_callback(self):
        records = []
        from reactor.batch_state import BatchStateMachine, BatchCommand
        sm = BatchStateMachine(on_transition=lambda r: records.append(r))
        # HOLD from IDLE is invalid
        sm.dispatch(BatchCommand.HOLD, elapsed=0.0)
        assert len(records) == 0


class TestAuditTrailIntegrationWithBatch:
    """Integration tests: audit trail wired into batch state machine."""

    def test_batch_transitions_produce_audit_events(self, tmp_path):
        from reactor.batch_state import BatchStateMachine, BatchCommand

        log_path = tmp_path / "audit.jsonl"
        trail = AuditTrail(log_path=log_path)

        def on_transition(record):
            trail.emit(
                event_type="batch_state_transition",
                source="batch_state",
                actor="system",
                action="dispatch",
                subject="batch_state",
                details=record,
                elapsed_s=record.get("at_s", 0.0),
            )

        sm = BatchStateMachine(on_transition=on_transition)
        sm.dispatch(BatchCommand.START, elapsed=0.0)
        sm.dispatch(BatchCommand.HOLD, elapsed=10.0)
        sm.dispatch(BatchCommand.RESTART, elapsed=20.0)
        sm.complete(elapsed=100.0)
        trail.close()

        assert trail.event_count == 4
        events, valid, last = AuditTrail.load_and_verify(log_path)
        assert valid is True
        assert last == 4
        assert events[0].event_type == "batch_state_transition"
        assert events[0].details["from"] == "IDLE"
        assert events[0].details["to"] == "RUNNING"
        assert events[3].details["command"] == "AUTO_COMPLETE"


class TestBuildStateSnapshot:
    """Test the build_state_snapshot helper."""

    def test_with_none_arguments(self):
        from reactor.audit_trail import build_state_snapshot
        snap = build_state_snapshot(
            elapsed=5.0, model=None, controller=None,
            batch_sm=None, player=None,
        )
        assert snap["elapsed_s"] == 5.0
        assert "temperature_K" not in snap

    def test_with_mock_objects(self):
        from reactor.audit_trail import build_state_snapshot

        class MockState:
            temperature = 350.0
            jacket_temperature = 340.0
            conversion = 0.5
            mass_total = 80.0

        class MockModel:
            state = MockState()
            viscosity = 12.5

        class MockPhase:
            name = "HEATING"

        class MockController:
            phase = MockPhase()

        class MockBatchSM:
            class state:
                value = "RUNNING"

        class MockStep:
            name = "HEAT_TO_CURE"

        class MockPlayer:
            def __init__(self):
                self.current_step = MockStep()

            @property
            def current_operation_name(self):
                return "REACTION"

        snap = build_state_snapshot(
            elapsed=50.0,
            model=MockModel(),
            controller=MockController(),
            batch_sm=MockBatchSM(),
            player=MockPlayer(),
        )
        assert snap["temperature_K"] == 350.0
        assert snap["conversion"] == 0.5
        assert snap["controller_phase"] == "HEATING"
        assert snap["batch_state"] == "RUNNING"
        assert snap["recipe_step"] == "HEAT_TO_CURE"
        assert snap["operation_name"] == "REACTION"
