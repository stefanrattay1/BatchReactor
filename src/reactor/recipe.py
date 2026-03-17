"""Recipe player: profile generators, sequencer, YAML/XML loader, and noise injection."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
import warnings

import numpy as np
import yaml

from .condition_expression import ConditionParseError, parse_condition_expression


class ProfileType(Enum):
    CONSTANT = "constant"
    LINEAR_RAMP = "linear_ramp"
    EXPONENTIAL = "exponential"


@dataclass
class ProfileSegment:
    """A single output profile over a time interval."""

    profile_type: ProfileType
    start_value: float
    end_value: float
    duration: float  # seconds

    def evaluate(self, t: float) -> float:
        """Return value at time t (0 <= t <= duration)."""
        if self.duration <= 0:
            return self.end_value
        frac = np.clip(t / self.duration, 0.0, 1.0)
        if self.profile_type == ProfileType.CONSTANT:
            return self.start_value
        elif self.profile_type == ProfileType.LINEAR_RAMP:
            return self.start_value + (self.end_value - self.start_value) * frac
        elif self.profile_type == ProfileType.EXPONENTIAL:
            if self.start_value <= 0 or self.end_value <= 0:
                return self.start_value + (self.end_value - self.start_value) * frac
            return self.start_value * (self.end_value / self.start_value) ** frac
        return self.start_value


@dataclass
class BatchStep:
    """A single step in the batch recipe."""

    name: str
    duration: float  # seconds
    profiles: dict[str, ProfileSegment] = field(default_factory=dict)
    em_modes: dict[str, str] = field(default_factory=dict)  # em_mode:TAG -> mode_name
    transitions: list[dict[str, Any]] = field(default_factory=list)
    completion_guards: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Recipe:
    """A complete batch recipe."""

    name: str
    steps: list[BatchStep] = field(default_factory=list)

    @property
    def total_duration(self) -> float:
        return sum(s.duration for s in self.steps)

    @property
    def channels(self) -> set[str]:
        channels: set[str] = set()
        for step in self.steps:
            channels.update(step.profiles.keys())
        return channels


class RecipePlayer:
    """Plays a recipe by tracking elapsed time and returning current setpoints."""

    def __init__(self, recipe: Recipe):
        self.recipe = recipe
        self.current_step_idx: int = 0
        self.step_elapsed: float = 0.0
        self.finished: bool = False

    @property
    def current_step(self) -> BatchStep | None:
        if self.finished or self.current_step_idx >= len(self.recipe.steps):
            return None
        return self.recipe.steps[self.current_step_idx]

    @property
    def total_elapsed(self) -> float:
        elapsed = sum(s.duration for s in self.recipe.steps[: self.current_step_idx])
        return elapsed + self.step_elapsed

    def tick(self, dt: float) -> dict[str, float | str]:
        """Advance by dt seconds and return current channel values.

        Returns a dict of channel -> value.  Most channels return floats;
        ``em_mode:*`` channels return string mode names.
        """
        if self.finished:
            return {}

        step = self.current_step
        if step is None:
            self.finished = True
            return {}

        values: dict[str, float | str] = {}
        for channel, profile in step.profiles.items():
            values[channel] = profile.evaluate(self.step_elapsed)
        # Include EM mode channels as string values
        for channel, mode_name in step.em_modes.items():
            values[channel] = mode_name

        self.step_elapsed += dt
        while self.step_elapsed >= step.duration:
            self.step_elapsed -= step.duration
            self.current_step_idx += 1
            if self.current_step_idx >= len(self.recipe.steps):
                self.finished = True
                break
            step = self.recipe.steps[self.current_step_idx]

        return values

    def reset(self) -> None:
        self.current_step_idx = 0
        self.step_elapsed = 0.0
        self.finished = False


def add_sensor_noise(value: float, noise_pct: float = 0.5) -> float:
    """Add Gaussian noise as a percentage of the reading."""
    if value == 0.0:
        return value
    sigma = abs(value) * noise_pct / 100.0
    return value + np.random.normal(0, sigma)


def _parse_profile(data: dict[str, Any]) -> ProfileSegment:
    """Parse a profile segment from YAML data."""
    ptype = ProfileType(data["type"])
    if ptype == ProfileType.CONSTANT:
        value = float(data["value"])
        return ProfileSegment(ptype, value, value, 0.0)
    start = float(data["start"])
    end = float(data["end"])
    return ProfileSegment(ptype, start, end, 0.0)  # duration set by parent step


_EM_MODE_PREFIX = "em_mode:"


class ConditionSyntaxWarning(UserWarning):
    """Issued when a condition expression is syntactically invalid at load time."""


def _parse_batch_step(step_data: dict[str, Any]) -> BatchStep:
    """Parse a single phase/step dict into a BatchStep.

    Used by both the flat YAML loader and the nested procedure loader.
    """
    duration = float(step_data["duration"])
    profiles: dict[str, ProfileSegment] = {}
    em_modes: dict[str, str] = {}
    for channel, prof_data in step_data.get("profiles", {}).items():
        if channel.startswith(_EM_MODE_PREFIX):
            em_modes[channel] = str(
                prof_data.get("value", prof_data) if isinstance(prof_data, dict) else prof_data
            )
            continue
        profile = _parse_profile(prof_data)
        profiles[channel] = ProfileSegment(
            profile.profile_type, profile.start_value, profile.end_value, duration
        )
    transitions = list(step_data.get("transitions", []))
    for idx, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            continue
        cond = str(transition.get("if", "")).strip()
        if not cond:
            continue
        try:
            parse_condition_expression(cond)
        except ConditionParseError as exc:
            step_name = str(step_data.get("name", ""))
            warnings.warn(
                (
                    "Invalid transition condition syntax in step "
                    f"'{step_name}' transition[{idx}] '{cond}': {exc}"
                ),
                ConditionSyntaxWarning,
                stacklevel=3,
            )

    return BatchStep(
        name=step_data["name"],
        duration=duration,
        profiles=profiles,
        em_modes=em_modes,
        transitions=transitions,
        completion_guards=list(step_data.get("completion_guards", [])),
    )


def _load_recipe_xml(path: Path):  # -> tuple[Recipe, RecipeMetadata | None]
    """Parse a recipe from an XML file.

    Returns ``(Recipe, RecipeMetadata | None)``.  The caller is responsible for
    HMAC verification (via the helpers in ``procedure.py``) before calling this.
    """
    # Import lazily to avoid circular imports at module level
    from .procedure import (
        RecipeMetadata,
        _parse_xml_metadata,
        _verify_xml_signature,
    )

    tree = ET.parse(path)
    root = tree.getroot()

    _verify_xml_signature(root, path)
    xml_meta = _parse_xml_metadata(root)

    name = root.get("name", path.stem)
    steps: list[BatchStep] = []
    for step_el in root.findall("step"):
        step_name = step_el.get("name", "")
        duration = float(step_el.get("duration", 0))
        profiles: dict[str, ProfileSegment] = {}
        em_modes: dict[str, str] = {}
        for prof_el in step_el.findall("profile"):
            channel = prof_el.get("channel", "")
            # EM mode channels carry string values, not numeric profiles
            if channel.startswith(_EM_MODE_PREFIX):
                em_modes[channel] = prof_el.get("value", "")
                continue
            prof_data = {k: v for k, v in prof_el.attrib.items() if k != "channel"}
            profile = _parse_profile(prof_data)
            profiles[channel] = ProfileSegment(
                profile.profile_type, profile.start_value, profile.end_value, duration
            )
        steps.append(BatchStep(
            name=step_name,
            duration=duration,
            profiles=profiles,
            em_modes=em_modes,
            transitions=[],
            completion_guards=[],
        ))
    return Recipe(name=name, steps=steps), xml_meta


def _load_recipe_from_raw(raw: dict[str, Any], path: Path) -> Recipe:
    """Parse the flat ``steps:`` YAML format into a Recipe."""
    steps = [_parse_batch_step(s) for s in raw["steps"]]
    return Recipe(name=raw.get("name", path.stem), steps=steps)


def load_recipe(path: str | Path) -> Recipe:
    """Load a recipe from a YAML or XML file.

    Supports both flat (``steps:``) and nested (``unit_procedures:``) YAML
    formats, as well as XML.  Always returns a flat Recipe for backward
    compatibility; use ``load_procedure()`` from procedure.py to access the
    full ISA-88 hierarchy.
    """
    from .procedure import load_procedure
    proc = load_procedure(path)
    return Recipe(name=proc.name, steps=proc.phases_flat)
