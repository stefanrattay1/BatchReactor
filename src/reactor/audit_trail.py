"""Centralized audit trail for state-transition event logging.

Provides structured, append-only JSON Lines (JSONL) logging for all
state-changing events in the reactor system:

- Batch state transitions (START, HOLD, RESTART, STOP, ABORT, RESET)
- Recipe phase transitions (CHARGE_COMPONENT_A → HEAT_TO_SOAK, etc.)
- Controller thermal phase transitions (IDLE → CHARGING → HEATING, etc.)
- Equipment module mode requests (accepted and rejected)
- Web API commands and actuator overrides
- Alarm lifecycle (onset, acknowledge, clear)

Each event carries an optional cryptographic hash chain for tamper
evidence: ``event_hash = SHA-256(prev_hash ‖ canonical_json(event))``.

Usage::

    trail = AuditTrail(log_path=Path("logs/audit.jsonl"))
    trail.emit(
        event_type="batch_state_transition",
        source="batch_state",
        actor="web_api",
        action="dispatch",
        subject="batch_state",
        details={"from": "IDLE", "to": "RUNNING", "command": "START"},
        elapsed_s=0.0,
    )
    trail.close()
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger("reactor.audit_trail")


@dataclass
class AuditEvent:
    """A single audit trail entry."""

    sequence: int
    timestamp: str  # ISO-8601 UTC
    elapsed_s: float
    event_type: str
    source: str
    actor: str
    action: str
    subject: str
    details: dict[str, Any] = field(default_factory=dict)
    state_snapshot: dict[str, Any] | None = None
    prev_hash: str = ""
    event_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d["state_snapshot"] is None:
            del d["state_snapshot"]
        return d


# Genesis hash for the first event in the chain.
_GENESIS_HASH = "0" * 64


def _compute_event_hash(prev_hash: str, event_dict: dict[str, Any]) -> str:
    """Compute SHA-256 over prev_hash + canonical JSON of event (excluding hashes)."""
    canonical = {k: v for k, v in event_dict.items()
                 if k not in ("prev_hash", "event_hash")}
    payload = prev_hash + json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditTrail:
    """Append-only event log with optional hash chain integrity.

    Parameters
    ----------
    log_path
        Path to the JSONL output file.  ``None`` disables file persistence
        (events are still kept in memory).
    enable_hash_chain
        When True, each event includes ``prev_hash`` and ``event_hash``
        forming a tamper-evident chain.
    """

    def __init__(
        self,
        log_path: Path | None = None,
        *,
        enable_hash_chain: bool = True,
    ) -> None:
        self._events: list[AuditEvent] = []
        self._sequence: int = 0
        self._last_hash: str = _GENESIS_HASH
        self._log_path = log_path
        self._log_file: IO[str] | None = None
        self._enable_hash_chain = enable_hash_chain

        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = open(log_path, "a", encoding="utf-8")
            logger.info("Audit trail: %s (hash_chain=%s)", log_path, enable_hash_chain)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def emit(
        self,
        *,
        event_type: str,
        source: str,
        actor: str = "system",
        action: str = "",
        subject: str = "",
        details: dict[str, Any] | None = None,
        elapsed_s: float = 0.0,
        state_snapshot: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Record a new audit event.

        Returns the created :class:`AuditEvent`.
        """
        self._sequence += 1
        event = AuditEvent(
            sequence=self._sequence,
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_s=round(elapsed_s, 3),
            event_type=event_type,
            source=source,
            actor=actor,
            action=action,
            subject=subject,
            details=details or {},
            state_snapshot=state_snapshot,
        )

        if self._enable_hash_chain:
            event.prev_hash = self._last_hash
            event.event_hash = _compute_event_hash(self._last_hash, event.to_dict())
            self._last_hash = event.event_hash

        self._events.append(event)
        self._persist(event)
        return event

    def close(self) -> None:
        """Flush and close the JSONL file."""
        if self._log_file is not None:
            self._log_file.flush()
            self._log_file.close()
            self._log_file = None

    # ------------------------------------------------------------------
    # Read-only access
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[AuditEvent]:
        """All events recorded so far (in-memory copy)."""
        return list(self._events)

    @property
    def event_count(self) -> int:
        return len(self._events)

    def recent(self, n: int = 50) -> list[dict[str, Any]]:
        """Return the last *n* events as dicts (for API responses)."""
        return [e.to_dict() for e in self._events[-n:]]

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    def verify_chain(self) -> tuple[bool, int]:
        """Verify the in-memory hash chain.

        Returns ``(valid, last_valid_sequence)``.  If the chain is empty,
        returns ``(True, 0)``.
        """
        if not self._enable_hash_chain:
            return True, self._sequence

        prev = _GENESIS_HASH
        for event in self._events:
            expected = _compute_event_hash(prev, event.to_dict())
            if event.event_hash != expected:
                return False, event.sequence - 1
            prev = event.event_hash
        return True, self._sequence

    @staticmethod
    def load_and_verify(path: Path) -> tuple[list[AuditEvent], bool, int]:
        """Load events from a JSONL file and verify the hash chain.

        Returns ``(events, chain_valid, last_valid_sequence)``.
        """
        events: list[AuditEvent] = []
        prev = _GENESIS_HASH
        last_valid = 0

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                event = AuditEvent(
                    sequence=d["sequence"],
                    timestamp=d["timestamp"],
                    elapsed_s=d["elapsed_s"],
                    event_type=d["event_type"],
                    source=d["source"],
                    actor=d["actor"],
                    action=d["action"],
                    subject=d["subject"],
                    details=d.get("details", {}),
                    state_snapshot=d.get("state_snapshot"),
                    prev_hash=d.get("prev_hash", ""),
                    event_hash=d.get("event_hash", ""),
                )
                events.append(event)

                if event.event_hash:
                    expected = _compute_event_hash(prev, event.to_dict())
                    if event.event_hash != expected:
                        return events, False, last_valid
                    prev = event.event_hash
                    last_valid = event.sequence

        return events, True, last_valid

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _persist(self, event: AuditEvent) -> None:
        if self._log_file is not None:
            line = json.dumps(event.to_dict(), default=str)
            self._log_file.write(line + "\n")
            self._log_file.flush()


# ---------------------------------------------------------------------------
# Convenience: build a state snapshot from common reactor objects
# ---------------------------------------------------------------------------

def build_state_snapshot(
    *,
    elapsed: float,
    model: Any,
    controller: Any,
    batch_sm: Any,
    player: Any,
    em_manager: Any | None = None,
) -> dict[str, Any]:
    """Build a reactor state snapshot for embedding in audit events.

    All parameters are optional-ish (passed as keyword args) so the caller
    can provide what's available.
    """
    snapshot: dict[str, Any] = {
        "elapsed_s": round(float(elapsed), 3),
    }

    if model is not None:
        s = model.state
        snapshot["temperature_K"] = round(float(s.temperature), 4)
        snapshot["jacket_temperature_K"] = round(float(s.jacket_temperature), 4)
        snapshot["conversion"] = round(float(s.conversion), 6)
        snapshot["mass_total_kg"] = round(float(s.mass_total), 4)
        snapshot["viscosity_Pas"] = round(float(model.viscosity), 4)

    if controller is not None:
        snapshot["controller_phase"] = controller.phase.name

    if batch_sm is not None:
        snapshot["batch_state"] = batch_sm.state.value

    if player is not None:
        snapshot["recipe_step"] = player.current_step.name if player.current_step else "DONE"
        snapshot["operation_name"] = player.current_operation_name or "DONE"

    if em_manager is not None:
        snapshot["em_modes"] = em_manager.get_mode_snapshot()

    return snapshot
