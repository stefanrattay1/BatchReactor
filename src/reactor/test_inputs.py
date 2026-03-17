"""Test input player: loads timed events from YAML and fires them during the simulation.

A test input file defines a sequence of timed actions (commands, actuator
overrides) that are automatically applied during the simulation loop, exactly
as a DCS operator would do manually.

Usage in the simulation:
    player = TestInputPlayer.from_yaml("test_inputs/normal_batch.yaml")
    ...
    # Each tick:
    for event in player.due_events(elapsed):
        # apply event
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("reactor.test_inputs")


@dataclass
class TestEvent:
    """A single timed test input event."""

    at: float  # simulation time in seconds when this event fires
    action: str  # "command", "set_jacket", "clear_jacket"
    value: Any = None  # action-specific value
    log: str = ""  # human-readable description
    fired: bool = field(default=False, repr=False)


@dataclass
class TestInputPlan:
    """A complete test input plan loaded from YAML."""

    name: str
    description: str
    events: list[TestEvent] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> TestInputPlan:
        path = Path(path)
        with open(path) as f:
            raw = yaml.safe_load(f)

        events = []
        for ev in raw.get("events", []):
            events.append(TestEvent(
                at=float(ev["at"]),
                action=ev["action"],
                value=ev.get("value"),
                log=ev.get("log", ""),
            ))
        # Sort by time
        events.sort(key=lambda e: e.at)

        return cls(
            name=raw.get("name", path.stem),
            description=raw.get("description", ""),
            events=events,
        )


class TestInputPlayer:
    """Plays test events at the correct simulation time.

    Call ``due_events(elapsed)`` each tick to get events that should fire.
    Events only fire once.
    """

    def __init__(self, plan: TestInputPlan):
        self.plan = plan
        self._next_idx = 0

    @classmethod
    def from_yaml(cls, path: str | Path) -> TestInputPlayer:
        return cls(TestInputPlan.from_yaml(path))

    @property
    def finished(self) -> bool:
        return self._next_idx >= len(self.plan.events)

    @property
    def active_name(self) -> str:
        return self.plan.name

    def due_events(self, elapsed: float) -> list[TestEvent]:
        """Return events whose ``at`` time has been reached, in order."""
        fired: list[TestEvent] = []
        while self._next_idx < len(self.plan.events):
            ev = self.plan.events[self._next_idx]
            if ev.at <= elapsed:
                ev.fired = True
                self._next_idx += 1
                fired.append(ev)
                if ev.log:
                    logger.info("[TEST t=%.1fs] %s", elapsed, ev.log)
            else:
                break
        return fired

    def summary(self) -> dict:
        """Return a JSON-serialisable summary of the plan and progress."""
        return {
            "name": self.plan.name,
            "description": self.plan.description,
            "total_events": len(self.plan.events),
            "fired_events": self._next_idx,
            "finished": self.finished,
            "events": [
                {
                    "at": ev.at,
                    "action": ev.action,
                    "value": ev.value,
                    "log": ev.log,
                    "fired": ev.fired,
                }
                for ev in self.plan.events
            ],
        }
