"""Central node catalog for the OPC Tool.

Every OPC UA node — whether locally created or discovered from an external
server — is registered here.  The NodeManager is the single source of truth
for node metadata, current values, and persistence.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger("opc_tool.node_manager")


@dataclass
class OPCNode:
    """A single OPC UA node in the catalog."""

    id: str
    name: str
    node_id: str  # OPC UA NodeId string (e.g., "ns=2;s=Temperature_K")
    source: str  # "local" or a connection_id
    category: str  # "sensor" | "actuator" | "status" | "custom"
    data_type: str = "Double"  # "Double" | "String" | "Int32" | "Boolean"
    writable: bool = False
    current_value: Any = None
    last_updated: float = 0.0
    metadata: dict = field(default_factory=dict)  # units, description, etc.

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OPCNode:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class NodeManager:
    """CRUD manager for the OPC node catalog with JSON persistence."""

    def __init__(self, data_dir: str | Path = "opc_tool_data") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._nodes: dict[str, OPCNode] = {}
        self._load()

    # -- Persistence ----------------------------------------------------------

    @property
    def _config_path(self) -> Path:
        return self.data_dir / "nodes.json"

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        try:
            with open(self._config_path) as f:
                data = json.load(f)
            for node_dict in data.get("nodes", []):
                node = OPCNode.from_dict(node_dict)
                self._nodes[node.id] = node
            logger.info("Loaded %d nodes from %s", len(self._nodes), self._config_path)
        except Exception:
            logger.exception("Failed to load node catalog from %s", self._config_path)

    def _save(self) -> None:
        try:
            payload = {"nodes": [n.to_dict() for n in self._nodes.values()]}
            with open(self._config_path, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            logger.exception("Failed to save node catalog")

    # -- CRUD -----------------------------------------------------------------

    def add_node(self, node: OPCNode) -> OPCNode:
        self._nodes[node.id] = node
        self._save()
        logger.info("Added node: %s (%s)", node.id, node.name)
        return node

    def remove_node(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        self._save()
        logger.info("Removed node: %s", node_id)
        return True

    def update_node(self, node_id: str, updates: dict[str, Any]) -> OPCNode | None:
        node = self._nodes.get(node_id)
        if node is None:
            return None
        for key, value in updates.items():
            if hasattr(node, key) and key != "id":
                setattr(node, key, value)
        self._save()
        return node

    def get_node(self, node_id: str) -> OPCNode | None:
        return self._nodes.get(node_id)

    def list_nodes(self, category: str | None = None) -> list[OPCNode]:
        nodes = list(self._nodes.values())
        if category:
            nodes = [n for n in nodes if n.category == category]
        return nodes

    # -- Value operations -----------------------------------------------------

    def get_value(self, node_id: str) -> tuple[Any, float]:
        """Return (current_value, last_updated) for a node."""
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(f"Node not found: {node_id}")
        return node.current_value, node.last_updated

    def set_value(self, node_id: str, value: Any) -> None:
        """Update the cached value for a node (does NOT persist to disk)."""
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(f"Node not found: {node_id}")
        node.current_value = value
        node.last_updated = time.time()

    def get_values_bulk(self, node_ids: list[str]) -> dict[str, Any]:
        """Return current values for multiple nodes."""
        result: dict[str, Any] = {}
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node is not None:
                result[nid] = node.current_value
        return result

    def set_values_bulk(self, updates: list[dict[str, Any]]) -> None:
        """Batch update values: [{"node_id": ..., "value": ...}, ...]."""
        now = time.time()
        for item in updates:
            node = self._nodes.get(item["node_id"])
            if node is not None:
                node.current_value = item["value"]
                node.last_updated = now
