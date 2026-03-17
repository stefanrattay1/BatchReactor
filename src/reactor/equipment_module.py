"""ISA-88 Equipment Modules: functional units with operating modes.

An Equipment Module (EM) coordinates a group of Control Modules (CMs)
to achieve a process goal (e.g. draining, filling, heating).  Each EM
has a set of **operating modes** selectable via dropdown in the UI.
Mode transitions execute step sequences that command CMs in order,
with optional completion checks and timeout handling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .condition_expression import (
    ConditionParseError,
    evaluate_condition_ast,
    iter_condition_atoms,
    parse_condition_expression,
)
from .control_module import CMState, ControlModule

logger = logging.getLogger("reactor.equipment_module")


@dataclass
class ModeStep:
    """A single step in a mode transition sequence.

    Actions use a simple DSL:
        "command:XV-301:open"         — call CM XV-301.command("open")
        "command:HE-101:set_temperature:353.15" — with value
        "noop"                        — do nothing (just wait for check)

    Checks use a simple DSL:
        "cm_state:XV-301:running"     — CM is in the specified state
        "pv_gt:FT-301:0.1"           — process value > threshold
        "pv_lt:TT-101:373.15"        — process value < threshold
        "always"                      — immediately satisfied
        None                          — no check (instant advance)
    """

    name: str
    action: str
    check: str | None = None
    timeout_s: float = 10.0
    on_timeout: str = "fault"  # "fault" | "skip"


@dataclass
class EquipmentStateRecipe:
    """A first-class equipment state recipe: named mode with step sequence,
    preconditions (checked before starting), and postconditions (asserted
    after completion).

    Preconditions and postconditions use the same check DSL as ModeStep.check.
    """

    name: str
    display_name: str
    steps: list[ModeStep] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)


# Backward compat alias
OperatingMode = EquipmentStateRecipe


class EMState(Enum):
    """Equipment module state."""

    IDLE = "idle"
    TRANSITIONING = "transitioning"
    ACTIVE = "active"
    FAULT = "fault"


class EquipmentModule:
    """ISA-88 Equipment Module.

    Controls a group of CMs and operates in discrete modes.
    Mode changes trigger step sequences that command CMs in order.
    """

    def __init__(self, tag: str, name: str, cm_tags: list[str]):
        self.tag = tag
        self.name = name
        self._cm_tags = list(cm_tags)
        self._modes: dict[str, EquipmentStateRecipe] = {}
        self._current_mode: str = "aus"
        self._requested_mode: str | None = None
        self._state = EMState.IDLE
        self._step_idx: int = 0
        self._step_timer: float = 0.0
        self._fault_msg: str = ""
        self._step_action_executed: bool = False

    def register_mode(self, mode: EquipmentStateRecipe) -> None:
        self._modes[mode.name] = mode

    @property
    def modes(self) -> dict[str, EquipmentStateRecipe]:
        """Read-only view of registered modes."""
        return dict(self._modes)

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def available_modes(self) -> list[str]:
        return list(self._modes.keys())

    @property
    def em_state(self) -> EMState:
        return self._state

    @property
    def requested_mode(self) -> str | None:
        return self._requested_mode

    @property
    def effective_mode(self) -> str:
        if self._state == EMState.TRANSITIONING and self._requested_mode:
            return self._requested_mode
        return self._current_mode

    @property
    def cm_tags(self) -> list[str]:
        return list(self._cm_tags)

    def request_mode(
        self, mode_name: str, cm_lookup: dict[str, ControlModule] | None = None,
    ) -> bool:
        """Request a mode change.

        Returns False for unknown modes or failed preconditions.
        If a transition is already in progress, a new request overrides the
        in-flight transition and restarts from step 0.
        """
        if mode_name not in self._modes:
            logger.warning(
                "EM %s: unknown mode '%s', available: %s",
                self.tag, mode_name, list(self._modes.keys()),
            )
            return False
        # Check preconditions if cm_lookup is available
        mode = self._modes[mode_name]
        if cm_lookup and mode.preconditions:
            for cond in mode.preconditions:
                if not _evaluate_check(cond, cm_lookup):
                    logger.warning(
                        "EM %s: precondition failed for mode '%s': %s",
                        self.tag, mode_name, cond,
                    )
                    return False

        if mode_name == self._current_mode and self._state != EMState.TRANSITIONING:
            return True  # already in requested mode
        if self._state == EMState.TRANSITIONING:
            if mode_name == self._current_mode:
                logger.info(
                    "EM %s: cancelling transition to '%s' and keeping current mode '%s'",
                    self.tag, self._requested_mode, self._current_mode,
                )
                self._requested_mode = None
                self._state = EMState.IDLE
                self._step_idx = 0
                self._step_timer = 0.0
                self._step_action_executed = False
                return True
            if mode_name == self._requested_mode:
                logger.info(
                    "EM %s: already transitioning to '%s'",
                    self.tag, mode_name,
                )
                return True
            logger.info(
                "EM %s: overriding transition '%s' -> '%s'",
                self.tag, self._requested_mode, mode_name,
            )
        self._requested_mode = mode_name
        self._state = EMState.TRANSITIONING
        self._step_idx = 0
        self._step_timer = 0.0
        self._step_action_executed = False
        logger.info("EM %s: transitioning to mode '%s'", self.tag, mode_name)
        return True

    def reset_fault(self) -> None:
        """Clear fault state and return to idle."""
        if self._state == EMState.FAULT:
            self._state = EMState.IDLE
            self._fault_msg = ""
            self._requested_mode = None

    def tick(self, dt: float, cm_lookup: dict[str, ControlModule]) -> None:
        """Advance by one simulation tick.  Called by EMManager."""
        if self._state != EMState.TRANSITIONING or self._requested_mode is None:
            return

        mode = self._modes[self._requested_mode]

        # No steps → instant transition
        if not mode.steps:
            self._complete_transition(cm_lookup)
            return

        # All steps completed
        if self._step_idx >= len(mode.steps):
            self._complete_transition(cm_lookup)
            return

        step = mode.steps[self._step_idx]

        # Execute action on first tick of this step
        if not self._step_action_executed:
            self._execute_action(step, cm_lookup)
            self._step_action_executed = True

        self._step_timer += dt

        # Evaluate check condition
        if step.check is None or _evaluate_check(step.check, cm_lookup):
            self._advance_step()
        elif self._step_timer > step.timeout_s:
            if step.on_timeout == "skip":
                logger.warning(
                    "EM %s: timeout on step '%s', skipping", self.tag, step.name,
                )
                self._advance_step()
            else:
                self._state = EMState.FAULT
                self._fault_msg = f"Timeout on step '{step.name}' in mode '{self._requested_mode}'"
                self._requested_mode = None
                logger.error("EM %s FAULT: %s", self.tag, self._fault_msg)

    def _advance_step(self) -> None:
        self._step_idx += 1
        self._step_timer = 0.0
        self._step_action_executed = False

    def _complete_transition(
        self, cm_lookup: dict[str, ControlModule] | None = None,
    ) -> None:
        mode = self._modes[self._requested_mode]  # type: ignore[arg-type]
        # Assert postconditions (warnings only, does not block completion)
        if cm_lookup and mode.postconditions:
            for cond in mode.postconditions:
                if not _evaluate_check(cond, cm_lookup):
                    logger.warning(
                        "EM %s: postcondition NOT met after mode '%s': %s",
                        self.tag, self._requested_mode, cond,
                    )
        logger.info(
            "EM %s: transition complete → mode '%s'",
            self.tag, self._requested_mode,
        )
        self._current_mode = self._requested_mode  # type: ignore[assignment]
        self._requested_mode = None
        self._state = EMState.ACTIVE

    def _execute_action(
        self, step: ModeStep, cm_lookup: dict[str, ControlModule],
    ) -> None:
        """Parse and execute a step action string."""
        if step.action == "noop":
            return
        parts = step.action.split(":")
        if parts[0] == "command" and len(parts) >= 3:
            cm_tag = parts[1]
            cmd = parts[2]
            value = parts[3] if len(parts) > 3 else None
            cm = cm_lookup.get(cm_tag)
            if cm is None:
                logger.warning(
                    "EM %s step '%s': CM '%s' not found", self.tag, step.name, cm_tag,
                )
                return
            ok = cm.command(cmd, value)
            if not ok:
                logger.warning(
                    "EM %s step '%s': CM '%s' rejected command '%s'",
                    self.tag, step.name, cm_tag, cmd,
                )

    def get_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tag": self.tag,
            "name": self.name,
            "current_mode": self._current_mode,
            "available_modes": self.available_modes,
            "state": self._state.value,
            "cm_tags": self._cm_tags,
        }
        if self._state == EMState.TRANSITIONING and self._requested_mode:
            mode = self._modes[self._requested_mode]
            result["transitioning_to"] = self._requested_mode
            result["transition_step"] = self._step_idx
            result["transition_total_steps"] = len(mode.steps)
            result["transition_steps"] = [s.name for s in mode.steps]
            if self._step_idx < len(mode.steps):
                result["transition_step_name"] = mode.steps[self._step_idx].name
        if self._fault_msg:
            result["fault_message"] = self._fault_msg
        return result


# ---------------------------------------------------------------------------
# Check evaluator (shared utility)
# ---------------------------------------------------------------------------


def _evaluate_check(check: str, cm_lookup: dict[str, ControlModule]) -> bool:
    """Evaluate a check condition string.

    Formats:
        "cm_state:XV-301:running"    — CM is in specified state
        "pv_gt:FT-301:0.1"          — process value > threshold
        "pv_lt:TT-101:373.15"       — process value < threshold
        "always"                      — always true
    """
    check = check.strip()
    if check.lower() == "always":
        return True

    try:
        ast = parse_condition_expression(check)
    except ConditionParseError as exc:
        logger.warning("Invalid check expression '%s': %s", check, exc)
        return False

    return evaluate_condition_ast(ast, lambda atom: _evaluate_check_atom(atom, cm_lookup))


def _evaluate_check_atom(check: str, cm_lookup: dict[str, ControlModule]) -> bool:
    check = check.strip()
    if check.lower() == "always":
        return True

    parts = check.split(":")
    if len(parts) < 3:
        logger.warning("Invalid check format: '%s'", check)
        return False

    check_type, cm_tag = parts[0], parts[1]

    cm = cm_lookup.get(cm_tag)
    if cm is None:
        logger.warning("Check references unknown CM '%s'", cm_tag)
        return False

    if check_type == "cm_state":
        expected = parts[2].lower()
        return cm.state.value == expected

    if check_type in ("pv_gt", "pv_lt"):
        pv = cm.read_pv()
        if pv is None:
            logger.warning("PV unavailable for check '%s'", check)
            return False
        try:
            threshold = float(parts[2])
        except (ValueError, IndexError):
            logger.warning("Invalid numeric threshold in check '%s'", check)
            return False
        return pv > threshold if check_type == "pv_gt" else pv < threshold

    logger.warning("Unknown check type: '%s'", check_type)
    return False


# ---------------------------------------------------------------------------
# Config-driven factory
# ---------------------------------------------------------------------------


def build_equipment_module(em_config: dict[str, Any]) -> EquipmentModule:
    """Build an EquipmentModule from a config dict.

    Expected keys:
        tag: str
        name: str
        cms: list[str]  — tags of owned CMs
        modes: list[dict]  — each with name, display_name, steps
    """
    em = EquipmentModule(
        tag=em_config["tag"],
        name=em_config.get("name", em_config["tag"]),
        cm_tags=em_config.get("cms", []),
    )

    for mode_cfg in em_config.get("modes", []):
        steps = []
        for step_cfg in mode_cfg.get("steps", []):
            steps.append(ModeStep(
                name=step_cfg["name"],
                action=step_cfg.get("action", "noop"),
                check=step_cfg.get("check"),
                timeout_s=float(step_cfg.get("timeout_s", 10.0)),
                on_timeout=step_cfg.get("on_timeout", "fault"),
            ))
        mode = EquipmentStateRecipe(
            name=mode_cfg["name"],
            display_name=mode_cfg.get("display_name", mode_cfg["name"]),
            steps=steps,
            preconditions=list(mode_cfg.get("preconditions", [])),
            postconditions=list(mode_cfg.get("postconditions", [])),
        )
        em.register_mode(mode)

    return em


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_VALID_CHECK_TYPES = frozenset({"cm_state", "pv_gt", "pv_lt"})


@dataclass
class ValidationIssue:
    """A single validation finding."""

    em_tag: str
    mode_name: str
    step_name: str  # "" for mode-level issues
    severity: str  # "error" | "warning"
    message: str


class EquipmentConfigError(Exception):
    """Raised when equipment config validation fails in strict mode."""


def _validate_action(
    action: str,
    step_name: str,
    em_tag: str,
    em_cm_tags: list[str],
    cm_registry: dict[str, ControlModule],
    add_issue: Any,
) -> None:
    """Validate a single action DSL string."""
    parts = action.split(":")
    if parts[0] != "command":
        add_issue(step_name, "error", f"Unknown action type '{parts[0]}' (expected 'command' or 'noop')")
        return
    if len(parts) < 3:
        add_issue(step_name, "error", f"Action '{action}' needs at least command:TAG:verb")
        return
    cm_tag = parts[1]
    verb = parts[2]
    cm = cm_registry.get(cm_tag)
    if cm is None:
        add_issue(step_name, "error", f"CM '{cm_tag}' not found")
        return
    if cm_tag not in em_cm_tags:
        add_issue(step_name, "warning", f"CM '{cm_tag}' not owned by EM '{em_tag}'")
    if cm.VALID_COMMANDS and verb not in cm.VALID_COMMANDS:
        add_issue(
            step_name, "error",
            f"CM '{cm_tag}' ({cm.cm_type}) does not support command '{verb}' "
            f"(valid: {sorted(cm.VALID_COMMANDS)})",
        )


def _validate_check_str(
    check: str,
    step_name: str,
    em_tag: str,
    em_cm_tags: list[str],
    cm_registry: dict[str, ControlModule],
    add_issue: Any,
) -> None:
    """Validate a single check DSL string."""
    check = check.strip()
    if check.lower() == "always":
        return
    try:
        ast = parse_condition_expression(check)
    except ConditionParseError as exc:
        add_issue(step_name, "error", f"Invalid check expression '{check}': {exc}")
        return

    for atom in iter_condition_atoms(ast):
        _validate_check_atom(atom, step_name, em_tag, em_cm_tags, cm_registry, add_issue)


def _validate_check_atom(
    check: str,
    step_name: str,
    em_tag: str,
    em_cm_tags: list[str],
    cm_registry: dict[str, ControlModule],
    add_issue: Any,
) -> None:
    check = check.strip()
    if not check:
        add_issue(step_name, "error", "Empty check atom")
        return
    if check.lower() == "always":
        return

    parts = check.split(":")
    if len(parts) < 3:
        add_issue(step_name, "error", f"Check '{check}' needs at least type:TAG:value")
        return
    check_type, cm_tag = parts[0], parts[1]
    if check_type not in _VALID_CHECK_TYPES:
        add_issue(step_name, "error", f"Unknown check type '{check_type}' (valid: {sorted(_VALID_CHECK_TYPES)})")
        return
    cm = cm_registry.get(cm_tag)
    if cm is None:
        add_issue(step_name, "error", f"Check references unknown CM '{cm_tag}'")
        return
    if cm_tag not in em_cm_tags:
        add_issue(step_name, "warning", f"Check references CM '{cm_tag}' not owned by EM '{em_tag}'")
    if check_type in ("pv_gt", "pv_lt"):
        try:
            float(parts[2])
        except (ValueError, IndexError):
            add_issue(step_name, "error", f"Threshold in '{check}' is not a valid number")


def validate_equipment_state_recipe(
    recipe: EquipmentStateRecipe,
    em_tag: str,
    em_cm_tags: list[str],
    cm_registry: dict[str, ControlModule],
) -> list[ValidationIssue]:
    """Validate a single EquipmentStateRecipe against the known CM set."""
    issues: list[ValidationIssue] = []

    def add_issue(step_name: str, severity: str, msg: str) -> None:
        issues.append(ValidationIssue(em_tag, recipe.name, step_name, severity, msg))

    seen_step_names: set[str] = set()

    for step in recipe.steps:
        if step.name in seen_step_names:
            add_issue(step.name, "warning", f"Duplicate step name '{step.name}'")
        seen_step_names.add(step.name)

        if step.on_timeout not in ("fault", "skip"):
            add_issue(step.name, "error", f"Invalid on_timeout: '{step.on_timeout}'")

        if step.action != "noop":
            _validate_action(step.action, step.name, em_tag, em_cm_tags, cm_registry, add_issue)

        if step.check is not None:
            _validate_check_str(step.check, step.name, em_tag, em_cm_tags, cm_registry, add_issue)

    for label, conditions in [("precondition", recipe.preconditions), ("postcondition", recipe.postconditions)]:
        for cond in conditions:
            _validate_check_str(cond, f"[{label}]", em_tag, em_cm_tags, cm_registry, add_issue)

    return issues


def validate_equipment_config(
    ems: dict[str, EquipmentModule],
    cms: dict[str, ControlModule],
    *,
    strict: bool = False,
) -> list[ValidationIssue]:
    """Validate all EMs and their mode recipes against the CM registry.

    If strict=True, raises EquipmentConfigError on any error-severity issue.
    Otherwise returns the full list for logging.
    """
    all_issues: list[ValidationIssue] = []
    for em in ems.values():
        for mode in em._modes.values():
            issues = validate_equipment_state_recipe(mode, em.tag, em.cm_tags, cms)
            all_issues.extend(issues)

    errors = [i for i in all_issues if i.severity == "error"]
    if strict and errors:
        msg = "; ".join(f"{i.em_tag}/{i.mode_name}/{i.step_name}: {i.message}" for i in errors)
        raise EquipmentConfigError(f"Equipment config validation failed: {msg}")

    return all_issues
