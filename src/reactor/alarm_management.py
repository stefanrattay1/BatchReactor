"""Formal alarm management (ISA-18.2 / ISA-101 inspired).

This module adds a structured alarm lifecycle around existing threshold checks:

- alarm classes (priority/category)
- onset/acknowledge/clear transitions
- suppression rules for expected transients
- operator-attributed history with evidence snapshots
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AlarmPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AlarmCategory(str, Enum):
    INSTRUMENT = "INSTRUMENT"
    SAFETY = "SAFETY"
    PROCESS = "PROCESS"


@dataclass(frozen=True)
class AlarmDefinition:
    alarm_id: str
    name: str
    source: str
    level: str
    priority: AlarmPriority
    category: AlarmCategory
    description: str = ""


@dataclass
class AlarmRuntimeState:
    active: bool = False
    acknowledged: bool = False
    suppressed: bool = False
    onset_at_s: float | None = None
    acknowledged_at_s: float | None = None
    cleared_at_s: float | None = None
    onset_snapshot: dict[str, Any] = field(default_factory=dict)
    clear_snapshot: dict[str, Any] = field(default_factory=dict)


class AlarmManager:
    """Manages formal alarm definitions, lifecycle, suppression and history."""

    def __init__(
        self,
        definitions: list[AlarmDefinition],
        *,
        suppression_rules: list[dict[str, Any]] | None = None,
    ):
        self._defs: dict[str, AlarmDefinition] = {d.alarm_id: d for d in definitions}
        self._state: dict[str, AlarmRuntimeState] = {
            alarm_id: AlarmRuntimeState()
            for alarm_id in self._defs
        }
        self._history: list[dict[str, Any]] = []
        self._manual_suppression: dict[str, dict[str, Any]] = {}
        self._suppression_rules = suppression_rules or []

    @classmethod
    def from_equipment_config(cls, equipment_cfg: dict[str, Any] | None = None) -> "AlarmManager":
        equipment_cfg = equipment_cfg or {}
        definitions: list[AlarmDefinition] = []
        control_modules = equipment_cfg.get("control_modules", []) if isinstance(equipment_cfg, dict) else []

        for cm in control_modules:
            if not isinstance(cm, dict):
                continue
            if str(cm.get("type", "")).strip().lower() != "sensor":
                continue

            tag = str(cm.get("tag", "")).strip()
            name = str(cm.get("name", tag)).strip() or tag
            alarms = cm.get("alarms", {})
            if not tag or not isinstance(alarms, dict):
                continue

            for level in alarms:
                norm_level = str(level).upper().strip()
                if norm_level not in {"HH", "H", "L", "LL"}:
                    continue
                definitions.append(
                    AlarmDefinition(
                        alarm_id=f"{tag}.{norm_level}",
                        name=f"{name} {norm_level}",
                        source=tag,
                        level=norm_level,
                        priority=_priority_for_level(norm_level),
                        category=AlarmCategory.INSTRUMENT,
                        description=f"{name} crossed {norm_level} threshold",
                    )
                )

        definitions.append(
            AlarmDefinition(
                alarm_id="controller.runaway",
                name="Thermal runaway",
                source="controller",
                level="RUNAWAY",
                priority=AlarmPriority.CRITICAL,
                category=AlarmCategory.SAFETY,
                description="Controller entered runaway alarm phase",
            )
        )

        suppression_rules = [
            {
                "rule_id": "mute_flow_low_during_vent_or_discharge",
                "description": "Mute low flow alarms while venting/discharging transitions are expected",
                "enabled": True,
            },
        ]
        return cls(definitions, suppression_rules=suppression_rules)

    def evaluate(
        self,
        *,
        elapsed_s: float,
        signals: dict[str, bool],
        snapshot: dict[str, Any],
        context: dict[str, Any] | None = None,
        operator_id: str = "system",
    ) -> None:
        context = context or {}

        for alarm_id, alarm_def in self._defs.items():
            state = self._state[alarm_id]
            active_now = bool(signals.get(alarm_id, False))
            suppressed_now = self._is_suppressed(alarm_def, context)
            state.suppressed = suppressed_now

            if suppressed_now:
                active_now = False

            if active_now and not state.active:
                state.active = True
                state.acknowledged = False
                state.onset_at_s = elapsed_s
                state.cleared_at_s = None
                state.acknowledged_at_s = None
                state.onset_snapshot = dict(snapshot)
                state.clear_snapshot = {}
                self._append_history(
                    event="onset",
                    alarm=alarm_def,
                    elapsed_s=elapsed_s,
                    operator_id=operator_id,
                    acknowledged=False,
                    snapshot=snapshot,
                )
            elif (not active_now) and state.active:
                state.active = False
                state.cleared_at_s = elapsed_s
                state.clear_snapshot = dict(snapshot)
                self._append_history(
                    event="clear",
                    alarm=alarm_def,
                    elapsed_s=elapsed_s,
                    operator_id=operator_id,
                    acknowledged=state.acknowledged,
                    snapshot=snapshot,
                )

    def acknowledge(self, alarm_id: str, *, operator_id: str, elapsed_s: float) -> bool:
        state = self._state.get(alarm_id)
        alarm_def = self._defs.get(alarm_id)
        if state is None or alarm_def is None:
            return False
        if not state.active or state.acknowledged:
            return False

        state.acknowledged = True
        state.acknowledged_at_s = elapsed_s
        self._append_history(
            event="acknowledge",
            alarm=alarm_def,
            elapsed_s=elapsed_s,
            operator_id=operator_id,
            acknowledged=True,
            snapshot={},
        )
        return True

    def set_manual_suppression(
        self,
        alarm_id: str,
        *,
        suppressed: bool,
        operator_id: str,
        elapsed_s: float,
        reason: str = "",
    ) -> bool:
        if alarm_id not in self._defs:
            return False
        if suppressed:
            self._manual_suppression[alarm_id] = {
                "operator_id": operator_id,
                "at_s": elapsed_s,
                "reason": reason,
            }
            event = "suppress"
        else:
            self._manual_suppression.pop(alarm_id, None)
            event = "unsuppress"

        self._history.append(
            {
                "event": event,
                "alarm_id": alarm_id,
                "operator_id": operator_id,
                "at_s": round(float(elapsed_s), 3),
                "reason": reason,
            }
        )
        return True

    def get_active_alarms(self) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for alarm_id, state in self._state.items():
            if not state.active:
                continue
            alarm_def = self._defs[alarm_id]
            active.append(
                {
                    "alarm_id": alarm_id,
                    "name": alarm_def.name,
                    "source": alarm_def.source,
                    "level": alarm_def.level,
                    "priority": alarm_def.priority.value,
                    "category": alarm_def.category.value,
                    "acknowledged": state.acknowledged,
                    "suppressed": state.suppressed,
                    "onset_at_s": state.onset_at_s,
                }
            )
        return sorted(active, key=lambda a: (a["acknowledged"], a["priority"], a["alarm_id"]))

    def get_history(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is None or limit <= 0:
            return list(self._history)
        return self._history[-limit:]

    def get_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "alarm_id": d.alarm_id,
                "name": d.name,
                "source": d.source,
                "level": d.level,
                "priority": d.priority.value,
                "category": d.category.value,
                "description": d.description,
            }
            for d in self._defs.values()
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.get_active_alarms(),
            "active_count": len([s for s in self._state.values() if s.active]),
            "unacknowledged_count": len([s for s in self._state.values() if s.active and not s.acknowledged]),
            "history_count": len(self._history),
            "definitions": self.get_definitions(),
        }

    def _is_suppressed(self, alarm_def: AlarmDefinition, context: dict[str, Any]) -> bool:
        if alarm_def.alarm_id in self._manual_suppression:
            return True

        for rule in self._suppression_rules:
            if not bool(rule.get("enabled", True)):
                continue
            rule_id = str(rule.get("rule_id", ""))
            if rule_id == "mute_flow_low_during_vent_or_discharge":
                if alarm_def.level not in {"L", "LL"}:
                    continue
                if not alarm_def.source.upper().startswith("FT-"):
                    continue
                if _context_has_vent_or_discharge(context):
                    return True
        return False

    def _append_history(
        self,
        *,
        event: str,
        alarm: AlarmDefinition,
        elapsed_s: float,
        operator_id: str,
        acknowledged: bool,
        snapshot: dict[str, Any],
    ) -> None:
        self._history.append(
            {
                "event": event,
                "alarm_id": alarm.alarm_id,
                "name": alarm.name,
                "source": alarm.source,
                "level": alarm.level,
                "priority": alarm.priority.value,
                "category": alarm.category.value,
                "at_s": round(float(elapsed_s), 3),
                "operator_id": operator_id,
                "acknowledged": acknowledged,
                "snapshot": dict(snapshot),
            }
        )


def _priority_for_level(level: str) -> AlarmPriority:
    if level in {"HH", "LL"}:
        return AlarmPriority.CRITICAL
    if level in {"H", "L"}:
        return AlarmPriority.HIGH
    return AlarmPriority.MEDIUM


def _context_has_vent_or_discharge(context: dict[str, Any]) -> bool:
    phase_name = str(context.get("phase", "")).lower()
    op_name = str(context.get("operation_name", "")).lower()
    if any(token in phase_name for token in ("vent", "entlueft", "entleer", "discharg")):
        return True
    if any(token in op_name for token in ("vent", "entlueft", "entleer", "discharg")):
        return True

    em_status = context.get("em_status", {})
    if not isinstance(em_status, dict):
        return False
    for data in em_status.values():
        mode = ""
        if isinstance(data, dict):
            mode = str(data.get("mode", "")).lower()
        else:
            mode = str(data).lower()
        if any(token in mode for token in ("vent", "entlueft", "entleer", "discharg")):
            return True
    return False
