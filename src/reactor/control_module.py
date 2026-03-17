"""ISA-88 Control Modules: low-level hardware abstractions.

Control Modules (CMs) wrap individual physical devices (valves, pumps,
sensors, motors, heaters) and provide a uniform interface for commanding
and reading state.  Each CM can operate in **simulated** mode (reads from
ReactorModel, writes to SensorBuffer) or **OPC-mapped** mode (reads/writes
via OPCToolClient).

Pattern follows the existing ABC + Registry used for physics models.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .execution_adapters import CMAdapter

logger = logging.getLogger("reactor.control_module")


class CMState(Enum):
    """Standard control module states."""

    OFF = "off"
    IDLE = "idle"
    RUNNING = "running"
    FAULT = "fault"


@dataclass
class CMStatus:
    """Snapshot of a CM's current state for display / logging."""

    tag: str
    name: str
    cm_type: str
    state: str
    value: float | None = None
    setpoint: float | None = None
    unit: str = ""
    fault_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ControlModule(ABC):
    """Abstract base for all control modules."""

    VALID_COMMANDS: frozenset[str] = frozenset()

    def __init__(
        self,
        tag: str,
        name: str,
        cm_type: str,
        *,
        maps_to: str = "",
        opc_node_id: str | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.tag = tag
        self.name = name
        self.cm_type = cm_type
        self.maps_to = maps_to
        self.opc_node_id = opc_node_id
        self._config = config or {}
        self._state = CMState.IDLE
        self._fault_msg = ""

        # Injected Execution Context
        self._adapter: CMAdapter | None = None

    @property
    def state(self) -> CMState:
        return self._state

    def bind(self, adapter: CMAdapter) -> None:
        """Inject execution environment adapter."""
        self._adapter = adapter

    @abstractmethod
    def command(self, action: str, value: Any = None) -> bool:
        """Execute a command. Returns True if accepted."""

    @abstractmethod
    def read_pv(self) -> float | None:
        """Read the current process value."""

    def get_status(self) -> CMStatus:
        return CMStatus(
            tag=self.tag,
            name=self.name,
            cm_type=self.cm_type,
            state=self._state.value,
            value=self.read_pv(),
            unit=self._config.get("unit", ""),
            fault_message=self._fault_msg,
        )

    def set_fault(self, message: str) -> None:
        self._state = CMState.FAULT
        self._fault_msg = message
        logger.warning("CM %s FAULT: %s", self.tag, message)

    def clear_fault(self) -> None:
        if self._state == CMState.FAULT:
            self._state = CMState.IDLE
            self._fault_msg = ""

    def _write_output(self, key: str, value: float, priority: int = 40) -> None:
        """Write value to the execution environment."""
        if self._adapter is not None:
            self._adapter.write_output(key, value, priority)

    def _read_input(self, key: str) -> Any | None:
        """Read value from the execution environment."""
        if self._adapter is not None:
            return self._adapter.read_input(key)
        return None


# ---------------------------------------------------------------------------
# Concrete CM types
# ---------------------------------------------------------------------------


class OnOffValve(ControlModule):
    """Binary valve: open / close.

    Config keys:
        flow_rate: float  — flow in kg/s when open (used when maps_to is a feed)
    """

    VALID_COMMANDS: frozenset[str] = frozenset({"open", "close"})

    def __init__(self, tag: str, name: str, **kwargs: Any):
        super().__init__(tag, name, "valve_onoff", **kwargs)
        self._position = 0.0  # 0 = closed, 1 = open
        self._flow_rate = self._config.get("flow_rate", 0.0)

    def command(self, action: str, value: Any = None) -> bool:
        if self._state == CMState.FAULT:
            return False
        if action == "open":
            self._position = 1.0
            self._state = CMState.RUNNING
            if self.maps_to and self._flow_rate > 0:
                self._write_output(self.maps_to, self._flow_rate)
            return True
        if action == "close":
            self._position = 0.0
            self._state = CMState.IDLE
            if self.maps_to and self._flow_rate > 0:
                self._write_output(self.maps_to, 0.0)
            return True
        return False

    def read_pv(self) -> float | None:
        return self._position

    def get_status(self) -> CMStatus:
        s = super().get_status()
        s.value = self._position
        s.metadata["flow_rate"] = self._flow_rate
        return s


class ControlValve(ControlModule):
    """Proportional valve: 0–100 % position.

    Config keys:
        max_flow: float  — flow at 100% position
    """

    VALID_COMMANDS: frozenset[str] = frozenset({"set_position", "close"})

    def __init__(self, tag: str, name: str, **kwargs: Any):
        super().__init__(tag, name, "valve_control", **kwargs)
        self._position = 0.0  # 0..100 %
        self._max_flow = self._config.get("max_flow", 1.0)

    def command(self, action: str, value: Any = None) -> bool:
        if self._state == CMState.FAULT:
            return False
        if action == "set_position":
            pos = float(value) if value is not None else 0.0
            self._position = max(0.0, min(100.0, pos))
            self._state = CMState.RUNNING if self._position > 0 else CMState.IDLE
            if self.maps_to:
                flow = self._max_flow * self._position / 100.0
                self._write_output(self.maps_to, flow)
            return True
        if action == "close":
            return self.command("set_position", 0.0)
        return False

    def read_pv(self) -> float | None:
        return self._position


class Pump(ControlModule):
    """Pump with on/off + optional speed.

    Config keys:
        max_speed: float  — max RPM (default 1500)
        flow_rate: float  — flow in kg/s when running at max speed
    """

    VALID_COMMANDS: frozenset[str] = frozenset({"start", "stop", "set_speed"})

    def __init__(self, tag: str, name: str, **kwargs: Any):
        super().__init__(tag, name, "pump", **kwargs)
        self._speed = 0.0
        self._max_speed = self._config.get("max_speed", 1500.0)
        self._flow_rate = self._config.get("flow_rate", 0.0)

    def command(self, action: str, value: Any = None) -> bool:
        if self._state == CMState.FAULT:
            return False
        if action == "start":
            speed = float(value) if value is not None else self._max_speed
            self._speed = max(0.0, min(self._max_speed, speed))
            self._state = CMState.RUNNING
            return True
        if action == "stop":
            self._speed = 0.0
            self._state = CMState.IDLE
            return True
        if action == "set_speed":
            speed = float(value) if value is not None else 0.0
            self._speed = max(0.0, min(self._max_speed, speed))
            self._state = CMState.RUNNING if self._speed > 0 else CMState.IDLE
            return True
        return False

    def read_pv(self) -> float | None:
        return self._speed


class Sensor(ControlModule):
    """Read-only measurement CM.

    Config keys:
        alarms: dict  — {HH: float, H: float, L: float, LL: float}
    """

    VALID_COMMANDS: frozenset[str] = frozenset({"enable_alarm", "disable_alarm"})

    def __init__(self, tag: str, name: str, **kwargs: Any):
        super().__init__(tag, name, "sensor", **kwargs)
        self._alarms = self._config.get("alarms", {})
        self._alarm_active: dict[str, bool] = {}
        self._alarm_enabled = True
        self._state = CMState.RUNNING  # sensors are always "running"

    def command(self, action: str, value: Any = None) -> bool:
        if action == "enable_alarm":
            self._alarm_enabled = True
            return True
        if action == "disable_alarm":
            self._alarm_enabled = False
            self._alarm_active.clear()
            return True
        return False

    def read_pv(self) -> float | None:
        if self.maps_to:
            return self._read_input(self.maps_to)
        return None

    def check_alarms(self) -> dict[str, bool]:
        """Evaluate alarm limits against current PV."""
        if not self._alarm_enabled:
            return {}
        pv = self.read_pv()
        if pv is None:
            return {}
        active: dict[str, bool] = {}
        for level, limit in self._alarms.items():
            if level in ("HH", "H"):
                active[level] = pv >= limit
            elif level in ("LL", "L"):
                active[level] = pv <= limit
        self._alarm_active = active
        return active

    def get_status(self) -> CMStatus:
        s = super().get_status()
        s.metadata["alarms"] = self._alarms
        s.metadata["alarm_active"] = self._alarm_active
        return s


class Motor(ControlModule):
    """Variable-speed motor (agitator).

    Config keys:
        max_speed_rpm: float  — maximum RPM
    """

    VALID_COMMANDS: frozenset[str] = frozenset({"start", "stop", "set_speed"})

    def __init__(self, tag: str, name: str, **kwargs: Any):
        super().__init__(tag, name, "motor", **kwargs)
        self._speed = 0.0
        self._max_speed = self._config.get("max_speed_rpm", 1500.0)

    def command(self, action: str, value: Any = None) -> bool:
        if self._state == CMState.FAULT:
            return False
        if action == "start":
            speed = float(value) if value is not None else self._max_speed
            self._speed = max(0.0, min(self._max_speed, speed))
            self._state = CMState.RUNNING
            if self.maps_to:
                self._write_output(self.maps_to, self._speed)
            return True
        if action == "stop":
            self._speed = 0.0
            self._state = CMState.IDLE
            if self.maps_to:
                self._write_output(self.maps_to, 0.0)
            return True
        if action == "set_speed":
            speed = float(value) if value is not None else 0.0
            self._speed = max(0.0, min(self._max_speed, speed))
            self._state = CMState.RUNNING if self._speed > 0 else CMState.IDLE
            if self.maps_to:
                self._write_output(self.maps_to, self._speed)
            return True
        return False

    def read_pv(self) -> float | None:
        return self._speed


class Heater(ControlModule):
    """Heating / cooling element — writes to jacket temperature.

    Config keys:
        min_temp: float  — minimum setpoint (K)
        max_temp: float  — maximum setpoint (K)
    """

    VALID_COMMANDS: frozenset[str] = frozenset({"set_temperature", "off"})

    def __init__(self, tag: str, name: str, **kwargs: Any):
        super().__init__(tag, name, "heater", **kwargs)
        self._setpoint: float | None = None
        self._min_temp = self._config.get("min_temp", 263.15)
        self._max_temp = self._config.get("max_temp", 473.15)

    def command(self, action: str, value: Any = None) -> bool:
        if self._state == CMState.FAULT:
            return False
        if action == "set_temperature":
            temp = float(value) if value is not None else 298.15
            self._setpoint = max(self._min_temp, min(self._max_temp, temp))
            self._state = CMState.RUNNING
            if self.maps_to:
                self._write_output(self.maps_to, self._setpoint)
            return True
        if action == "off":
            self._setpoint = None
            self._state = CMState.IDLE
            return True
        return False

    def read_pv(self) -> float | None:
        if self.maps_to:
            return self._read_input(self.maps_to)
        return self._setpoint

    def get_status(self) -> CMStatus:
        s = super().get_status()
        s.setpoint = self._setpoint
        return s


# ---------------------------------------------------------------------------
# Registry + Factory
# ---------------------------------------------------------------------------

CM_REGISTRY: dict[str, type[ControlModule]] = {
    "valve_onoff": OnOffValve,
    "valve_control": ControlValve,
    "pump": Pump,
    "sensor": Sensor,
    "motor": Motor,
    "heater": Heater,
}


def build_control_module(cm_config: dict[str, Any]) -> ControlModule:
    """Factory: build a CM from a config dict.

    Expected keys: tag, type, name, maps_to (optional), opc_node_id (optional).
    All other keys are passed as ``config`` to the CM constructor.
    """
    cm_type = cm_config["type"]
    cls = CM_REGISTRY.get(cm_type)
    if cls is None:
        available = ", ".join(CM_REGISTRY.keys())
        raise ValueError(
            f"Unknown CM type: '{cm_type}'. Available: {available}"
        )

    # Separate known keys from extra config
    known = {"tag", "type", "name", "maps_to", "opc_node_id"}
    extra = {k: v for k, v in cm_config.items() if k not in known}

    return cls(
        tag=cm_config["tag"],
        name=cm_config.get("name", cm_config["tag"]),
        maps_to=cm_config.get("maps_to", ""),
        opc_node_id=cm_config.get("opc_node_id"),
        config=extra,
    )
