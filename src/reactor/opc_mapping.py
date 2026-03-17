"""Mapping between OPC Tool nodes and reactor state variables.

Users configure these mappings through the reactor GUI to specify
which OPC Tool nodes correspond to which reactor variables.
"""

from __future__ import annotations

import ast
import json
import logging
import operator
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger("reactor.opc_mapping")

# ---------------------------------------------------------------------------
# Safe math expression evaluator (duplicated from opc_tool.client for
# independence — the reactor does not import from opc_tool at runtime)
# ---------------------------------------------------------------------------

_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval_math_expr(expression: str, value: Any) -> float:
    """Safely evaluate a simple numeric expression."""

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Name):
            if node.id != "value":
                raise ValueError(f"Unsupported variable: {node.id}")
            return float(value)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numeric constants are allowed")
        if isinstance(node, ast.BinOp):
            op_fn = _BIN_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            return float(op_fn(_eval(node.left), _eval(node.right)))
        if isinstance(node, ast.UnaryOp):
            op_fn = _UNARY_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
            return float(op_fn(_eval(node.operand)))
        raise ValueError(f"Unsupported expression element: {type(node).__name__}")

    parsed = ast.parse(expression, mode="eval")
    return _eval(parsed)


# ---------------------------------------------------------------------------
# Node mapping dataclass
# ---------------------------------------------------------------------------

@dataclass
class NodeMapping:
    """Maps an OPC Tool node to a reactor state variable."""

    opc_node_id: str  # Node ID in the OPC Tool catalog
    reactor_var: str  # Reactor state key (e.g., "temperature", "jacket_temperature")
    direction: str  # "read" (OPC -> reactor) | "write" (reactor -> OPC)
    transform: str = "value"  # Math expression, e.g., "value + 273.15"
    priority: int = 50  # For SensorBuffer (reads only)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeMapping:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def apply_transform(self, value: Any) -> float:
        if self.transform == "value":
            return float(value)
        return safe_eval_math_expr(self.transform, value)


# ---------------------------------------------------------------------------
# Mapping manager
# ---------------------------------------------------------------------------

# Allowed reactor state keys for read mappings
ALLOWED_READ_KEYS = {
    "temperature", "temperature_K",
    "jacket_temperature", "jacket_temperature_K",
    "volume", "pressure_bar", "command",
    "cm_feedback", "cm_fault",
}

# Allowed reactor state keys for write mappings
ALLOWED_WRITE_KEYS = {
    "temperature", "conversion", "viscosity",
    "pressure_bar", "mass_total",
    "jacket_temperature", "fsm_state", "fsm_state_name",
    "batch_elapsed",
    "cm_command", "cm_setpoint",
}


class OPCMappingManager:
    """Manages the mapping between OPC Tool nodes and reactor state variables."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._mappings: list[NodeMapping] = []
        self.load()

    def load(self) -> None:
        """Load mappings from JSON file."""
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path) as f:
                data = json.load(f)
            self._mappings = [NodeMapping.from_dict(m) for m in data.get("mappings", [])]
            logger.info("Loaded %d OPC mappings from %s", len(self._mappings), self.config_path)
        except Exception:
            logger.exception("Failed to load OPC mappings from %s", self.config_path)

    def save(self) -> None:
        """Persist mappings to JSON file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"mappings": [m.to_dict() for m in self._mappings]}
            with open(self.config_path, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            logger.exception("Failed to save OPC mappings")

    def add_mapping(self, mapping: NodeMapping) -> NodeMapping:
        # Remove any existing mapping for the same opc_node_id + direction
        self._mappings = [
            m for m in self._mappings
            if not (m.opc_node_id == mapping.opc_node_id and m.direction == mapping.direction)
        ]
        self._mappings.append(mapping)
        self.save()
        return mapping

    def remove_mapping(self, opc_node_id: str, direction: str | None = None) -> bool:
        before = len(self._mappings)
        if direction:
            self._mappings = [
                m for m in self._mappings
                if not (m.opc_node_id == opc_node_id and m.direction == direction)
            ]
        else:
            self._mappings = [m for m in self._mappings if m.opc_node_id != opc_node_id]
        removed = len(self._mappings) < before
        if removed:
            self.save()
        return removed

    def get_read_mappings(self) -> list[NodeMapping]:
        """Get all enabled read (OPC -> reactor) mappings."""
        return [m for m in self._mappings if m.direction == "read" and m.enabled]

    def get_write_mappings(self) -> list[NodeMapping]:
        """Get all enabled write (reactor -> OPC) mappings."""
        return [m for m in self._mappings if m.direction == "write" and m.enabled]

    def list_mappings(self) -> list[NodeMapping]:
        return list(self._mappings)
