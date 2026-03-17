"""ISA-88 Batch State Model (IEC 61512, Section 5.2).

Provides a single source-of-truth state machine for batch execution.
The thermal Phase FSM (controller.py) and ProcedurePlayer (procedure.py)
are subordinate/informational -- they report into this state but do not
control it.

State diagram::

    IDLE ──START──▶ RUNNING ──(complete)──▶ COMPLETE ──RESET──▶ IDLE
                      │  ▲
                    HOLD RESTART
                      │  │
                      ▼  │
                     HELD
                      │
                    STOP / ABORT
                      ▼
                   STOPPED / ABORTED ──RESET──▶ IDLE
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("reactor.batch_state")


class BatchState(Enum):
    """ISA-88 batch states."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    HELD = "HELD"
    STOPPED = "STOPPED"
    ABORTED = "ABORTED"


class BatchCommand(Enum):
    """ISA-88 batch commands."""

    START = "START"
    HOLD = "HOLD"
    RESTART = "RESTART"
    STOP = "STOP"
    ABORT = "ABORT"
    RESET = "RESET"


# Valid transitions: (current_state, command) -> next_state
_TRANSITIONS: dict[tuple[BatchState, BatchCommand], BatchState] = {
    (BatchState.IDLE, BatchCommand.START): BatchState.RUNNING,
    (BatchState.RUNNING, BatchCommand.HOLD): BatchState.HELD,
    (BatchState.RUNNING, BatchCommand.STOP): BatchState.STOPPED,
    (BatchState.RUNNING, BatchCommand.ABORT): BatchState.ABORTED,
    (BatchState.HELD, BatchCommand.RESTART): BatchState.RUNNING,
    (BatchState.HELD, BatchCommand.STOP): BatchState.STOPPED,
    (BatchState.HELD, BatchCommand.ABORT): BatchState.ABORTED,
    (BatchState.COMPLETE, BatchCommand.RESET): BatchState.IDLE,
    (BatchState.STOPPED, BatchCommand.RESET): BatchState.IDLE,
    (BatchState.ABORTED, BatchCommand.RESET): BatchState.IDLE,
}

# States where the physics model should be stepped.
PHYSICS_ACTIVE_STATES = frozenset({BatchState.RUNNING, BatchState.HELD})

# States where the procedure player should be ticked.
PROCEDURE_ACTIVE_STATES = frozenset({BatchState.RUNNING})

# Terminal states — batch loop should exit in batch mode.
TERMINAL_STATES = frozenset({BatchState.COMPLETE, BatchState.STOPPED, BatchState.ABORTED})


class BatchStateMachine:
    """ISA-88 batch state machine.

    Single source of truth for batch execution state.  Dispatches
    commands, enforces the transition table, and tracks state history
    for the batch record.
    """

    def __init__(
        self,
        *,
        on_transition: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._state = BatchState.IDLE
        self._history: list[dict[str, Any]] = []
        self._state_entered_at: float = 0.0  # simulation time (s)
        self._on_transition = on_transition

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> BatchState:
        return self._state

    @property
    def is_physics_active(self) -> bool:
        """Should ``model.step(dt)`` be called?"""
        return self._state in PHYSICS_ACTIVE_STATES

    @property
    def is_procedure_active(self) -> bool:
        """Should ``player.tick(dt)`` be called?"""
        return self._state in PROCEDURE_ACTIVE_STATES

    @property
    def is_terminal(self) -> bool:
        """Has the batch reached a final state?"""
        return self._state in TERMINAL_STATES

    @property
    def history(self) -> list[dict[str, Any]]:
        """Copy of the state-transition history."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def dispatch(self, command: BatchCommand, elapsed: float = 0.0) -> bool:
        """Attempt a state transition.  Returns *True* if the transition occurred."""
        key = (self._state, command)
        next_state = _TRANSITIONS.get(key)
        if next_state is None:
            logger.warning(
                "Invalid batch command %s in state %s",
                command.value,
                self._state.value,
            )
            return False

        prev = self._state
        self._state = next_state
        self._record(prev, next_state, command.value, elapsed)
        logger.info(
            "Batch state: %s -> %s (command=%s, t=%.1fs)",
            prev.value,
            next_state.value,
            command.value,
            elapsed,
        )
        return True

    def complete(self, elapsed: float = 0.0) -> None:
        """Auto-transition RUNNING -> COMPLETE when the recipe finishes."""
        if self._state != BatchState.RUNNING:
            return
        prev = self._state
        self._state = BatchState.COMPLETE
        self._record(prev, BatchState.COMPLETE, "AUTO_COMPLETE", elapsed)
        logger.info("Batch state: RUNNING -> COMPLETE (auto, t=%.1fs)", elapsed)

    def reset(self) -> None:
        """Hard reset to IDLE (for re-initialisation, not the RESET command)."""
        self._state = BatchState.IDLE
        self._history.clear()
        self._state_entered_at = 0.0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "state_entered_at_s": round(self._state_entered_at, 2),
            "history": self._history,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record(
        self,
        prev: BatchState,
        next_state: BatchState,
        trigger: str,
        elapsed: float,
    ) -> None:
        record = {
            "at_s": round(elapsed, 2),
            "from": prev.value,
            "to": next_state.value,
            "command": trigger,
        }
        self._history.append(record)
        self._state_entered_at = elapsed
        if self._on_transition is not None:
            self._on_transition(record)
