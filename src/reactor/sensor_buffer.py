"""Synchronized sensor buffer for external input sources.

All external inputs (recipe, OPC subscriptions, web API, test inputs) write to
the buffer with a source tag and priority.  The main simulation loop resolves
the buffer once per tick — highest priority wins per state key — then applies
the winners to ``ReactorState`` before calling ``model.step(dt)``.

Sticky values (for solver-overwritten variables like temperature) are
automatically re-applied each tick until a new write replaces them.
Non-sticky values (for preserved variables like jacket_temperature) are
cleared after one application.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .physics import ReactorState

logger = logging.getLogger("reactor.sensor_buffer")

# State keys whose values are overwritten by the Pyomo solver each step().
# These need sticky buffering so the external value is re-applied next tick.
_SOLVER_OVERWRITTEN_KEYS = frozenset({"temperature", "temperature_K"})

# Map user-facing state_key names to ReactorState attribute names.
_STATE_KEY_MAP: dict[str, str] = {
    "temperature": "temperature",
    "temperature_K": "temperature",
    "jacket_temperature": "jacket_temperature",
    "jacket_temperature_K": "jacket_temperature",
    "volume": "volume",
}

# Keys written by CMs that are informational only (not ReactorState attributes).
# These are tracked in the buffer for status/debugging but not applied to state.
_INFORMATIONAL_KEYS = frozenset({
    "agitator_speed_rpm",
    "pressure_setpoint",
})


@dataclass
class BufferedValue:
    """A single value written to the buffer by one source."""

    value: float
    source: str
    priority: int
    timestamp: float = field(default_factory=time.monotonic)
    sticky: bool = False


class SensorBuffer:
    """Thread-safe buffer mediating all external writes to ReactorState.

    Usage::

        buf = SensorBuffer()

        # Sources write independently (possibly from async polling loops)
        buf.write("jacket_temperature", 330.0, source="recipe", priority=10)
        buf.write("jacket_temperature", 350.0, source="opc_subscription", priority=50)

        # Main loop resolves once per tick
        winners = buf.resolve()
        # -> {"jacket_temperature": BufferedValue(value=350.0, ...)}

        buf.apply_to_state(state)  # sets state.jacket_temperature = 350.0
    """

    def __init__(self) -> None:
        # state_key -> list of competing BufferedValues (from different sources)
        self._buffer: dict[str, list[BufferedValue]] = {}
        # Sticky values that persist across resolve() calls
        self._sticky: dict[str, BufferedValue] = {}
        # Last resolved winners (for status/debugging)
        self._last_resolved: dict[str, BufferedValue] = {}

    def write(
        self,
        state_key: str,
        value: float,
        source: str,
        priority: int,
        sticky: bool | None = None,
    ) -> None:
        """Write a value from a source.

        Parameters
        ----------
        state_key:
            Target state variable (e.g. ``"temperature"``, ``"jacket_temperature"``).
        value:
            The numeric value to write.
        source:
            Tag identifying the source (e.g. ``"recipe"``, ``"opc_subscription"``).
        priority:
            Numeric priority; higher wins when multiple sources write the same key.
        sticky:
            If ``None`` (default), auto-detect from ``_SOLVER_OVERWRITTEN_KEYS``.
            If ``True``, the value is re-applied every tick until replaced.
            If ``False``, the value is cleared after one resolution.
        """
        if sticky is None:
            sticky = state_key in _SOLVER_OVERWRITTEN_KEYS

        entry = BufferedValue(
            value=value,
            source=source,
            priority=priority,
            sticky=sticky,
        )

        if state_key not in self._buffer:
            self._buffer[state_key] = []

        # Replace existing entry from the same source, or append
        entries = self._buffer[state_key]
        for i, existing in enumerate(entries):
            if existing.source == source:
                entries[i] = entry
                break
        else:
            entries.append(entry)

        # Also update sticky store if this is a sticky write
        if sticky:
            existing_sticky = self._sticky.get(state_key)
            if existing_sticky is None or priority >= existing_sticky.priority:
                self._sticky[state_key] = entry

    def resolve(self) -> dict[str, BufferedValue]:
        """Resolve all buffered values: highest priority wins per key.

        Non-sticky entries are cleared after resolution.
        Sticky entries persist in a separate store and participate in future
        resolutions until replaced by a new ``write()``.

        Returns a dict of state_key -> winning ``BufferedValue``.
        """
        winners: dict[str, BufferedValue] = {}

        # Merge current buffer entries with sticky entries
        all_keys = set(self._buffer.keys()) | set(self._sticky.keys())

        for key in all_keys:
            candidates: list[BufferedValue] = []

            # Current tick's writes
            if key in self._buffer:
                candidates.extend(self._buffer[key])

            # Sticky entries (re-applied automatically)
            if key in self._sticky:
                sticky_entry = self._sticky[key]
                # Only add if not already present from current writes
                if not any(c.source == sticky_entry.source for c in candidates):
                    candidates.append(sticky_entry)

            if candidates:
                # Highest priority wins; break ties by most recent timestamp
                winner = max(candidates, key=lambda c: (c.priority, c.timestamp))
                winners[key] = winner

                # Update sticky store: if the winner is sticky, keep it;
                # if a non-sticky source won, it overrides sticky for this tick
                if winner.sticky:
                    self._sticky[key] = winner
                # If a non-sticky entry won over a sticky one, don't clear sticky —
                # it will come back next tick when the non-sticky one is gone

        # Clear non-sticky entries from the buffer
        self._buffer.clear()

        self._last_resolved = winners
        return winners

    def apply_to_state(self, state: ReactorState) -> dict[str, str]:
        """Resolve the buffer and apply winners to the given state.

        Returns a dict of state_key -> winning source name (for tracking).
        """
        winners = self.resolve()
        sources: dict[str, str] = {}

        for key, entry in winners.items():
            if key in _INFORMATIONAL_KEYS:
                sources[key] = entry.source
                continue
            attr = _STATE_KEY_MAP.get(key)
            if attr is None:
                logger.warning(
                    "SensorBuffer: unknown state_key '%s'; allowed: %s",
                    key,
                    sorted(_STATE_KEY_MAP),
                )
                continue

            setattr(state, attr, entry.value)
            sources[key] = entry.source

        return sources

    def clear_source(self, source: str) -> None:
        """Remove all entries from a specific source.

        Useful when an override is cleared (e.g. web API deactivates scenario).
        """
        for key in list(self._buffer.keys()):
            self._buffer[key] = [
                e for e in self._buffer[key] if e.source != source
            ]
            if not self._buffer[key]:
                del self._buffer[key]

        for key in list(self._sticky.keys()):
            if self._sticky[key].source == source:
                del self._sticky[key]

    def get_status(self) -> dict[str, Any]:
        """Return current buffer state for debugging / web API."""
        buffered: dict[str, list[dict]] = {}
        for key, entries in self._buffer.items():
            buffered[key] = [
                {
                    "value": e.value,
                    "source": e.source,
                    "priority": e.priority,
                    "sticky": e.sticky,
                }
                for e in entries
            ]

        sticky: dict[str, dict] = {}
        for key, entry in self._sticky.items():
            sticky[key] = {
                "value": entry.value,
                "source": entry.source,
                "priority": entry.priority,
            }

        last_winners: dict[str, dict] = {}
        for key, entry in self._last_resolved.items():
            last_winners[key] = {
                "value": round(entry.value, 4),
                "source": entry.source,
                "priority": entry.priority,
                "sticky": entry.sticky,
            }

        return {
            "buffered": buffered,
            "sticky": sticky,
            "last_resolved": last_winners,
        }
