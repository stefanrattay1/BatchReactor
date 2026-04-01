"""Equipment Module Manager: orchestrates all EMs and CMs.

The EMManager builds Equipment Modules and Control Modules from config,
wires their dependencies (ReactorModel, SensorBuffer, OPCToolClient),
and dispatches ``tick()`` calls each simulation step.

Integration with the main loop::

    em_manager = EMManager(model, sensor_buffer, equipment_cfg)

    # In simulation tick, between recipe collection and sensor_buffer.apply_to_state():
    em_manager.dispatch_recipe_modes(recipe_values)  # em_mode:* channels
    em_manager.tick(dt)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from .control_module import ControlModule, build_control_module
from .equipment_module import EquipmentModule, build_equipment_module, validate_equipment_config

if TYPE_CHECKING:
    from .execution_adapters import CMAdapter
    from .opc_tool_client import OPCToolClient

logger = logging.getLogger("reactor.em_manager")

EM_MODE_PREFIX = "em_mode:"


class EMManager:
    """Orchestrates all Equipment Modules and Control Modules."""

    def __init__(
        self,
        equipment_cfg: dict[str, Any],
        adapter_factory: Callable[[str, str], "CMAdapter"],
        opc_client: "OPCToolClient | None" = None,
    ):
        self._adapter_factory = adapter_factory
        self._equipment_cfg = equipment_cfg
        self._opc_client = opc_client
        self._cms: dict[str, ControlModule] = {}
        self._ems: dict[str, EquipmentModule] = {}
        self._last_recipe_modes: dict[str, str] = {}  # tracks step changes
        self._mode_conflicts: list[tuple[str, str, str, str]] = []
        self._mode_preconditions: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self._events: list[dict[str, Any]] = []

        self._build_from_config(equipment_cfg)
        self._load_interlocks(equipment_cfg)

    def _build_from_config(self, cfg: dict[str, Any]) -> None:
        """Instantiate CMs and EMs from config dict."""
        # Build control modules
        for cm_cfg in cfg.get("control_modules", []):
            try:
                cm = build_control_module(cm_cfg)
                self._cms[cm.tag] = cm
                logger.info("CM created: %s (%s)", cm.tag, cm.cm_type)
            except (ValueError, KeyError) as e:
                logger.error("Failed to create CM from config: %s", e)

        # Build equipment modules
        for em_cfg in cfg.get("equipment_modules", []):
            try:
                em = build_equipment_module(em_cfg)
                self._ems[em.tag] = em
                logger.info("EM created: %s (%s)", em.tag, em.name)
            except (ValueError, KeyError) as e:
                logger.error("Failed to create EM from config: %s", e)

        # Bind CMs to their dependencies and owning EMs
        self._bind_cms()

        # Validate all mode recipes against the CM registry
        issues = validate_equipment_config(self._ems, self._cms)
        for issue in issues:
            if issue.severity == "error":
                logger.error(
                    "Config validation: %s/%s [%s]: %s",
                    issue.em_tag, issue.mode_name, issue.step_name, issue.message,
                )
            else:
                logger.warning(
                    "Config validation: %s/%s [%s]: %s",
                    issue.em_tag, issue.mode_name, issue.step_name, issue.message,
                )

    def _bind_cms(self) -> None:
        """Wire CMs to model, sensor buffer, and OPC client."""
        # Build CM → EM ownership map
        cm_to_em: dict[str, str] = {}
        for em in self._ems.values():
            for cm_tag in em.cm_tags:
                cm_to_em[cm_tag] = em.tag

        for tag, cm in self._cms.items():
            em_tag = cm_to_em.get(tag, "")
            cm.bind(self._adapter_factory(tag, em_tag))

    def tick(self, dt: float) -> None:
        """Called once per simulation tick, before sensor_buffer.apply_to_state()."""
        for em in self._ems.values():
            em.tick(dt, self._cms)

    def _load_interlocks(self, cfg: dict[str, Any]) -> None:
        """Load config-driven interlocks and transition preconditions."""
        interlocks = cfg.get("interlocks", {}) if isinstance(cfg, dict) else {}
        for rule in interlocks.get("mode_conflicts", []):
            if not isinstance(rule, dict):
                continue
            left = str(rule.get("left", "")).strip()
            right = str(rule.get("right", "")).strip()
            l_parsed = self._parse_selector(left)
            r_parsed = self._parse_selector(right)
            if l_parsed is None or r_parsed is None:
                continue
            self._mode_conflicts.append((l_parsed[0], l_parsed[1], r_parsed[0], r_parsed[1]))

        for rule in interlocks.get("mode_preconditions", []):
            if not isinstance(rule, dict):
                continue
            selector = self._parse_selector(str(rule.get("selector", "")).strip())
            if selector is None:
                continue
            requires: list[tuple[str, str]] = []
            for req in rule.get("requires", []):
                req_sel = self._parse_selector(str(req).strip())
                if req_sel is None:
                    continue
                requires.append(req_sel)
            if requires:
                self._mode_preconditions[(selector[0], selector[1])] = requires

    def reinitialize(self, equipment_cfg: dict[str, Any]) -> None:
        """Rebuild all EM/CM state from a fresh equipment config in place."""
        self._equipment_cfg = equipment_cfg
        self._cms.clear()
        self._ems.clear()
        self._last_recipe_modes.clear()
        self._mode_conflicts.clear()
        self._mode_preconditions.clear()
        self._events.clear()

        self._build_from_config(equipment_cfg)
        self._load_interlocks(equipment_cfg)

    def _parse_selector(self, selector: str) -> tuple[str, str] | None:
        parts = selector.split(":", 1)
        if len(parts) != 2:
            logger.warning("Invalid mode selector '%s' (expected EM:mode)", selector)
            return None
        em_tag = parts[0].strip()
        mode_name = parts[1].strip()
        if not em_tag or not mode_name:
            return None
        return em_tag, mode_name

    def _selector_matches(self, selector: tuple[str, str], em_tag: str, mode_name: str) -> bool:
        sel_em, sel_mode = selector
        if sel_em != em_tag:
            return False
        return sel_mode == "*" or sel_mode == mode_name

    def _effective_mode_snapshot(self) -> dict[str, str]:
        return {tag: em.effective_mode for tag, em in self._ems.items()}

    def _emit_event(self, event_type: str, details: dict[str, Any]) -> None:
        payload = {
            "type": event_type,
            **details,
        }
        self._events.append(payload)

    def consume_events(self) -> list[dict[str, Any]]:
        events = list(self._events)
        self._events.clear()
        return events

    def get_mode_snapshot(self) -> dict[str, dict[str, str]]:
        return {
            tag: {
                "mode": em.effective_mode,
                "state": em.em_state.value,
            }
            for tag, em in self._ems.items()
        }

    def _check_mode_request(self, em_tag: str, mode_name: str) -> tuple[bool, str | None]:
        snapshot = self._effective_mode_snapshot()

        for (sel_em, sel_mode), requires in self._mode_preconditions.items():
            if not self._selector_matches((sel_em, sel_mode), em_tag, mode_name):
                continue
            for req_em, req_mode in requires:
                current = snapshot.get(req_em, "")
                if req_mode != "*" and current != req_mode:
                    return False, (
                        f"precondition_failed:{em_tag}:{mode_name}:requires:{req_em}:{req_mode}:actual:{current}"
                    )

        for l_em, l_mode, r_em, r_mode in self._mode_conflicts:
            left_matches = self._selector_matches((l_em, l_mode), em_tag, mode_name)
            right_matches = self._selector_matches((r_em, r_mode), em_tag, mode_name)

            if left_matches:
                other = snapshot.get(r_em, "")
                if other and self._selector_matches((r_em, r_mode), r_em, other):
                    return False, f"interlock_conflict:{l_em}:{l_mode}:{r_em}:{other}"
            if right_matches:
                other = snapshot.get(l_em, "")
                if other and self._selector_matches((l_em, l_mode), l_em, other):
                    return False, f"interlock_conflict:{r_em}:{r_mode}:{l_em}:{other}"

        return True, None

    def dispatch_recipe_modes(self, recipe_values: dict[str, Any]) -> None:
        """Extract em_mode:* channels from recipe tick output and request mode changes.

        Only dispatches when the mode value changes (step transitions),
        not every tick.
        """
        for channel, value in recipe_values.items():
            if not channel.startswith(EM_MODE_PREFIX):
                continue
            em_tag = channel[len(EM_MODE_PREFIX):]
            mode_name = str(value)

            # Only dispatch on change
            if self._last_recipe_modes.get(em_tag) == mode_name:
                continue

            self._last_recipe_modes[em_tag] = mode_name
            ok = self.request_mode(em_tag, mode_name)
            if ok:
                logger.info(
                    "Recipe dispatched: %s → mode '%s'", em_tag, mode_name,
                )

    def request_mode(self, em_tag: str, mode_name: str) -> bool:
        """Request a mode change on an EM."""
        em = self._ems.get(em_tag)
        if em is None:
            logger.warning("Unknown EM tag: '%s'", em_tag)
            self._emit_event(
                "mode_request_rejected",
                {
                    "reason": "unknown_em",
                    "em_tag": em_tag,
                    "mode_name": mode_name,
                },
            )
            return False

        allowed, reason = self._check_mode_request(em_tag, mode_name)
        if not allowed:
            logger.warning("EM request blocked (%s -> %s): %s", em_tag, mode_name, reason)
            self._emit_event(
                "mode_request_rejected",
                {
                    "reason": reason or "interlock_failed",
                    "em_tag": em_tag,
                    "mode_name": mode_name,
                },
            )
            return False

        return em.request_mode(mode_name, cm_lookup=self._cms)

    def reset_recipe_modes(self) -> None:
        """Clear tracked recipe modes (call on recipe reset/start)."""
        self._last_recipe_modes.clear()

    # ------------------------------------------------------------------
    # Status / web API
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Full status for GET /api/equipment/status."""
        return {
            "equipment_modules": {
                tag: em.get_status() for tag, em in self._ems.items()
            },
            "control_modules": {
                tag: cm.get_status().__dict__ for tag, cm in self._cms.items()
            },
        }

    def get_em_list(self) -> list[dict[str, Any]]:
        """Summary list for frontend dropdown rendering."""
        result = []
        for em in self._ems.values():
            status = em.get_status()
            entry: dict[str, Any] = {
                "tag": em.tag,
                "name": em.name,
                "current_mode": em.current_mode,
                "modes": em.available_modes,
                "state": em.em_state.value,
            }
            # Include live transition progress so the frontend can show the Vorgang
            if "transitioning_to" in status:
                entry["transitioning_to"] = status["transitioning_to"]
                entry["transition_step"] = status["transition_step"]
                entry["transition_total_steps"] = status["transition_total_steps"]
                entry["transition_steps"] = status.get("transition_steps", [])
            if "fault_message" in status:
                entry["fault_message"] = status["fault_message"]
            result.append(entry)
        return result

    def get_em_status(self, em_tag: str) -> dict[str, Any] | None:
        em = self._ems.get(em_tag)
        return em.get_status() if em else None

    def get_cm_status(self, cm_tag: str) -> dict[str, Any] | None:
        cm = self._cms.get(cm_tag)
        return cm.get_status().__dict__ if cm else None

    def get_sensor_alarm_statuses(self) -> list[dict[str, Any]]:
        """Return evaluated alarm snapshots for sensor CMs.

        Each item includes sensor tag/name, active alarm booleans, configured
        limits and current PV.
        """
        results: list[dict[str, Any]] = []
        for cm in self._cms.values():
            if cm.cm_type != "sensor":
                continue
            checker = getattr(cm, "check_alarms", None)
            if callable(checker):
                checker()
            status = cm.get_status()
            metadata = status.metadata if isinstance(status.metadata, dict) else {}
            raw_active = metadata.get("alarm_active", {})
            active = raw_active if isinstance(raw_active, dict) else {}
            raw_limits = metadata.get("alarms", {})
            limits = raw_limits if isinstance(raw_limits, dict) else {}
            results.append(
                {
                    "tag": cm.tag,
                    "name": cm.name,
                    "maps_to": cm.maps_to,
                    "pv": status.value,
                    "active": {k: bool(v) for k, v in active.items()},
                    "limits": dict(limits),
                }
            )
        return results

    @property
    def has_modules(self) -> bool:
        return bool(self._ems)
