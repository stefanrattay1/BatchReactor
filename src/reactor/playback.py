"""Data package playback: replays recorded state snapshots through the dashboard."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("reactor.playback")


@dataclass
class DataPackage:
    """A complete recorded simulation run."""

    name: str
    recipe_name: str
    tick_interval: float
    total_duration: float
    total_snapshots: int
    generated_at: str
    perturbations: dict
    snapshots: list[dict[str, Any]]

    @classmethod
    def from_json(cls, path: str | Path) -> DataPackage:
        path = Path(path)
        with open(path) as f:
            raw = json.load(f)
        meta = raw["metadata"]
        return cls(
            name=meta["name"],
            recipe_name=meta["recipe_name"],
            tick_interval=meta["tick_interval"],
            total_duration=meta["total_duration"],
            total_snapshots=meta["total_snapshots"],
            generated_at=meta["generated_at"],
            perturbations=meta.get("perturbations", {}),
            snapshots=raw["snapshots"],
        )


class DataPackagePlayer:
    """Steps through a recorded data package one snapshot at a time."""

    def __init__(self, package: DataPackage):
        self.package = package
        self._index: int = 0
        self._playing: bool = False

    @classmethod
    def from_json(cls, path: str | Path) -> DataPackagePlayer:
        return cls(DataPackage.from_json(path))

    @property
    def current_snapshot(self) -> dict[str, Any] | None:
        if self._index < len(self.package.snapshots):
            return self.package.snapshots[self._index]
        return None

    @property
    def finished(self) -> bool:
        return self._index >= len(self.package.snapshots)

    @property
    def playing(self) -> bool:
        return self._playing

    def start(self) -> None:
        self._playing = True

    def stop(self) -> None:
        self._playing = False

    def reset(self) -> None:
        self._playing = False
        self._index = 0

    def tick(self) -> dict[str, Any] | None:
        """Advance one snapshot. Returns the snapshot dict or None if done."""
        if not self._playing or self.finished:
            return self.current_snapshot
        snapshot = self.package.snapshots[self._index]
        self._index += 1
        if self._index >= len(self.package.snapshots):
            self._playing = False
        return snapshot
