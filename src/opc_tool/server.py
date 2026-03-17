"""Managed OPC UA server instances.

Wraps asyncua.Server to create OPC UA servers whose node trees are driven
by the NodeManager catalog — no reactor-specific types.
"""

from __future__ import annotations

import logging
from typing import Any

from asyncua import Server, ua

from .node_manager import NodeManager, OPCNode

logger = logging.getLogger("opc_tool.server")

# Map our data_type strings to asyncua VariantType
_VARIANT_MAP: dict[str, ua.VariantType] = {
    "Double": ua.VariantType.Double,
    "Float": ua.VariantType.Float,
    "Int32": ua.VariantType.Int32,
    "Int16": ua.VariantType.Int16,
    "UInt32": ua.VariantType.UInt32,
    "UInt16": ua.VariantType.UInt16,
    "Boolean": ua.VariantType.Boolean,
    "String": ua.VariantType.String,
}

_DEFAULT_VALUES: dict[str, Any] = {
    "Double": 0.0,
    "Float": 0.0,
    "Int32": 0,
    "Int16": 0,
    "UInt32": 0,
    "UInt16": 0,
    "Boolean": False,
    "String": "",
}


class ManagedOPCServer:
    """A managed OPC UA server whose nodes come from the NodeManager."""

    def __init__(
        self,
        server_id: str,
        endpoint: str = "opc.tcp://0.0.0.0:4840",
        name: str = "OPC Tool Server",
        namespace_uri: str = "urn:opctool:server",
    ) -> None:
        self.server_id = server_id
        self.endpoint = endpoint
        self.name = name
        self.namespace_uri = namespace_uri
        self._server = Server()
        self._ua_nodes: dict[str, object] = {}  # node_id -> asyncua Node
        self._variant_types: dict[str, ua.VariantType] = {}  # node_id -> VariantType
        self._idx: int = 0
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def init(self, node_manager: NodeManager) -> None:
        """Initialize the OPC UA server and create nodes from the catalog."""
        await self._server.init()
        self._server.set_endpoint(self.endpoint)
        self._server.set_server_name(self.name)
        self._idx = await self._server.register_namespace(self.namespace_uri)
        objects = self._server.nodes.objects

        # Group nodes by category for folder structure
        categories: dict[str, list[OPCNode]] = {}
        for node in node_manager.list_nodes():
            if node.source != "local":
                continue  # Only expose locally defined nodes
            categories.setdefault(node.category, []).append(node)

        for category, nodes in categories.items():
            # Simple pluralization: "sensor" → "Sensors", "status" → "Status"
            if category.endswith("s"):
                folder_name = category.capitalize()
            else:
                folder_name = category.capitalize() + "s"
            folder = await objects.add_folder(self._idx, folder_name)

            for node in nodes:
                variant_type = _VARIANT_MAP.get(node.data_type, ua.VariantType.Double)
                default_val = node.current_value
                if default_val is None:
                    default_val = _DEFAULT_VALUES.get(node.data_type, 0.0)

                ua_node = await folder.add_variable(
                    self._idx, node.name, default_val, variant_type
                )
                if node.writable:
                    await ua_node.set_writable()

                self._ua_nodes[node.id] = ua_node
                self._variant_types[node.id] = variant_type
                logger.debug("Created OPC node: %s/%s", folder_name, node.name)

        logger.info(
            "Server '%s' initialized with %d nodes at %s",
            self.server_id, len(self._ua_nodes), self.endpoint,
        )

    async def start(self) -> None:
        await self._server.start()
        self._running = True
        logger.info("Server '%s' started on %s", self.server_id, self.endpoint)

    async def stop(self) -> None:
        if self._running:
            await self._server.stop()
            self._running = False
            logger.info("Server '%s' stopped", self.server_id)

    def _coerce(self, node_id: str, value: Any) -> ua.Variant:
        """Wrap a Python value in a ua.Variant with the correct type."""
        vtype = self._variant_types.get(node_id, ua.VariantType.Double)
        # Coerce Python type to match declared OPC UA type
        if vtype in (ua.VariantType.Int32, ua.VariantType.Int16,
                     ua.VariantType.UInt32, ua.VariantType.UInt16):
            value = int(value)
        elif vtype in (ua.VariantType.Double, ua.VariantType.Float):
            value = float(value)
        elif vtype == ua.VariantType.Boolean:
            value = bool(value)
        elif vtype == ua.VariantType.String:
            value = str(value)
        return ua.Variant(value, vtype)

    async def update_node(self, node_id: str, value: Any) -> None:
        """Write a value to an OPC UA node by catalog node_id."""
        ua_node = self._ua_nodes.get(node_id)
        if ua_node is None:
            return
        await ua_node.write_value(self._coerce(node_id, value))

    async def read_node(self, node_id: str) -> Any:
        """Read the current value from an OPC UA node."""
        ua_node = self._ua_nodes.get(node_id)
        if ua_node is None:
            return None
        return await ua_node.read_value()

    async def sync_from_catalog(self, node_manager: NodeManager) -> None:
        """Push all current catalog values to OPC UA nodes."""
        for node_id, ua_node in self._ua_nodes.items():
            catalog_node = node_manager.get_node(node_id)
            if catalog_node is not None and catalog_node.current_value is not None:
                try:
                    await ua_node.write_value(self._coerce(node_id, catalog_node.current_value))
                except Exception as e:
                    logger.warning("Failed to sync node %s: %s", node_id, e)

    async def sync_to_catalog(self, node_manager: NodeManager) -> None:
        """Read all writable OPC UA node values back into the catalog."""
        for node_id, ua_node in self._ua_nodes.items():
            catalog_node = node_manager.get_node(node_id)
            if catalog_node is not None and catalog_node.writable:
                try:
                    value = await ua_node.read_value()
                    node_manager.set_value(node_id, value)
                except Exception as e:
                    logger.warning("Failed to read back node %s: %s", node_id, e)
