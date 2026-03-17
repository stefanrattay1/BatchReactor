"""OPC UA client pool for connecting to external servers.

Migrated from reactor.opc_client with reactor-specific logic removed.
The polling loop updates NodeManager instead of a reactor SensorBuffer.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
import logging
import operator
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from asyncua import Client, ua

from .node_manager import NodeManager

logger = logging.getLogger("opc_tool.client")

# ---------------------------------------------------------------------------
# Safe math expression evaluator
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


def _safe_eval_math_expr(expression: str, value: Any) -> float:
    """Safely evaluate a simple numeric expression using only arithmetic ops."""

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
# Connection and subscription dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OPCConnection:
    """A single OPC UA client connection."""

    id: str
    endpoint: str
    security_mode: str = "None"
    security_policy: str | None = None
    certificate_path: str | None = None
    private_key_path: str | None = None
    username: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        self.client: Client | None = None
        self.connected: bool = False
        self._runtime_password: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OPCConnection:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def set_runtime_credentials(self, username: str | None, password: str) -> None:
        if username is not None:
            self.username = username
        self._runtime_password = password

    @property
    def has_runtime_password(self) -> bool:
        return bool(self._runtime_password)

    async def connect(self) -> bool:
        if self.connected:
            return True
        try:
            self.client = Client(url=self.endpoint)

            if self.security_mode and self.security_mode != "None":
                if not (self.security_policy and self.certificate_path and self.private_key_path):
                    logger.error(
                        "Connection %s: security_mode=%s but missing policy/cert/key",
                        self.id, self.security_mode,
                    )
                    return False

                cert_path = Path(self.certificate_path)
                key_path = Path(self.private_key_path)
                if not cert_path.is_file():
                    logger.error("Connection %s: certificate not found: %s", self.id, cert_path)
                    return False
                if not key_path.is_file():
                    logger.error("Connection %s: private key not found: %s", self.id, key_path)
                    return False

                security_string = (
                    f"{self.security_policy},{self.security_mode},"
                    f"{self.certificate_path},{self.private_key_path}"
                )
                self.client.set_security_string(security_string)

            if self.username:
                if not self._runtime_password:
                    logger.warning(
                        "Connection %s: username set but runtime password missing", self.id,
                    )
                    return False
                self.client.set_user(self.username)
                self.client.set_password(self._runtime_password)

            await self.client.connect()
            self.connected = True
            logger.info("Connected to OPC UA server: %s", self.endpoint)
            return True
        except Exception as e:
            logger.error("Failed to connect to %s: %s", self.endpoint, e)
            self.connected = False
            return False

    async def disconnect(self) -> None:
        if self.client and self.connected:
            try:
                await self.client.disconnect()
                self.connected = False
                logger.info("Disconnected from %s", self.endpoint)
            except Exception as e:
                logger.error("Error disconnecting from %s: %s", self.endpoint, e)

    async def read_node(self, node_id: str) -> Any | None:
        if not self.connected or not self.client:
            return None
        try:
            node = self.client.get_node(node_id)
            return await node.read_value()
        except Exception as e:
            logger.error("Failed to read node %s: %s", node_id, e)
            return None

    async def browse_node(self, node_id: str | None = None) -> list[dict[str, Any]]:
        if not self.connected or not self.client:
            return []
        try:
            node = (
                self.client.get_objects_node()
                if node_id is None
                else self.client.get_node(node_id)
            )
            children = await node.get_children()
            results: list[dict[str, Any]] = []

            for child in children:
                try:
                    browse_name = await child.read_browse_name()
                    node_class = await child.read_node_class()
                    node_id_str = child.nodeid.to_string()

                    data_type = None
                    if node_class == ua.NodeClass.Variable:
                        try:
                            data_type_node = await child.read_data_type()
                            data_type = data_type_node.to_string()
                        except Exception:
                            data_type = "Unknown"

                    results.append({
                        "node_id": node_id_str,
                        "browse_name": browse_name.Name,
                        "node_class": node_class.name,
                        "data_type": data_type,
                    })
                except Exception as e:
                    logger.warning("Error browsing child node: %s", e)
                    continue

            return results
        except Exception as e:
            logger.error("Failed to browse node %s: %s", node_id, e)
            return []


@dataclass
class NodeSubscription:
    """A subscription to poll a single external OPC UA node."""

    id: str
    connection_id: str
    node_id: str
    catalog_node_id: str  # The OPC Tool node_manager node ID to update
    polling_rate_ms: int = 1000
    transform: str = "value"
    enabled: bool = True

    def __post_init__(self) -> None:
        self.last_value: Any = None

    @property
    def interval_s(self) -> float:
        return max(self.polling_rate_ms, 10) / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeSubscription:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def apply_transform(self, value: Any) -> Any:
        if self.transform == "value":
            return value
        try:
            return _safe_eval_math_expr(self.transform, value)
        except Exception as e:
            logger.error("Transform failed for subscription %s: %s", self.id, e)
            return value


# ---------------------------------------------------------------------------
# Client pool
# ---------------------------------------------------------------------------

_POLL_TICK_S = 0.10


class OPCClientPool:
    """Manages connections to external OPC UA servers.

    Polled subscription values are written to NodeManager instead of
    reactor-specific SensorBuffer.
    """

    def __init__(self, node_manager: NodeManager, config_path: Path) -> None:
        self.node_manager = node_manager
        self.config_path = config_path
        self.connections: dict[str, OPCConnection] = {}
        self.subscriptions: dict[str, NodeSubscription] = {}
        self.discovery_url = "opc.tcp://localhost:4840"
        self.running = False
        self._polling_task: asyncio.Task | None = None
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.info("No OPC client config found, creating default at %s", self.config_path)
            self._save_config({
                "discovery_url": self.discovery_url,
                "connections": [],
                "subscriptions": [],
            })
            return

        try:
            with open(self.config_path) as f:
                config = json.load(f)

            self.discovery_url = config.get("discovery_url", self.discovery_url)

            for conn_cfg in config.get("connections", []):
                if "password" in conn_cfg:
                    logger.warning(
                        "Ignoring legacy persisted password for connection '%s'",
                        conn_cfg.get("id", "unknown"),
                    )
                conn = OPCConnection.from_dict(conn_cfg)
                self.connections[conn.id] = conn

            for sub_cfg in config.get("subscriptions", []):
                sub = NodeSubscription.from_dict(sub_cfg)
                self.subscriptions[sub.id] = sub

            logger.info(
                "Loaded %d connections, %d subscriptions",
                len(self.connections), len(self.subscriptions),
            )
        except Exception:
            logger.exception("Failed to load OPC client config from %s", self.config_path)

    def _save_config(self, config: dict[str, Any] | None = None) -> None:
        if config is None:
            config = {
                "discovery_url": self.discovery_url,
                "connections": [c.to_dict() for c in self.connections.values()],
                "subscriptions": [s.to_dict() for s in self.subscriptions.values()],
            }
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)
        except Exception:
            logger.exception("Failed to save OPC client config to %s", self.config_path)

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        logger.info("Starting OPC client pool")

        for conn in self.connections.values():
            if conn.enabled:
                await conn.connect()

        self._polling_task = asyncio.create_task(self._polling_loop())

    async def stop(self) -> None:
        if not self.running and self._polling_task is None:
            return

        self.running = False
        logger.info("Stopping OPC client pool")

        if self._polling_task is not None:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            finally:
                self._polling_task = None

        for conn in self.connections.values():
            await conn.disconnect()

    async def _polling_loop(self) -> None:
        next_poll: dict[str, float] = {}
        try:
            while self.running:
                now = time.monotonic()

                for sub in list(self.subscriptions.values()):
                    if not sub.enabled:
                        continue
                    if now < next_poll.get(sub.id, 0.0):
                        continue

                    conn = self.connections.get(sub.connection_id)
                    if not conn or not conn.connected:
                        next_poll[sub.id] = now + sub.interval_s
                        continue

                    try:
                        value = await conn.read_node(sub.node_id)
                        if value is not None:
                            transformed = sub.apply_transform(value)
                            sub.last_value = transformed
                            # Write to NodeManager instead of SensorBuffer
                            try:
                                self.node_manager.set_value(sub.catalog_node_id, transformed)
                            except KeyError:
                                logger.warning(
                                    "Subscription %s: catalog node '%s' not found",
                                    sub.id, sub.catalog_node_id,
                                )
                    except Exception as e:
                        logger.error("Error polling subscription %s: %s", sub.id, e)

                    next_poll[sub.id] = time.monotonic() + sub.interval_s

                await asyncio.sleep(_POLL_TICK_S)
        except asyncio.CancelledError:
            logger.debug("OPC polling task cancelled")
            raise

    # -- Connection management -----------------------------------------------

    async def add_connection(self, config: dict[str, Any]) -> OPCConnection:
        conn = OPCConnection.from_dict(config)
        password = config.get("password")
        if isinstance(password, str) and password:
            conn.set_runtime_credentials(config.get("username"), password)
        self.connections[conn.id] = conn

        if conn.enabled:
            await conn.connect()

        self._save_config()
        return conn

    async def set_connection_credentials(
        self, conn_id: str, *, username: str | None, password: str,
    ) -> OPCConnection:
        if not password:
            raise ValueError("Password is required")

        conn = self.connections.get(conn_id)
        if conn is None:
            raise KeyError(f"Connection not found: {conn_id}")

        conn.set_runtime_credentials(username, password)

        if conn.enabled:
            if conn.connected:
                await conn.disconnect()
            await conn.connect()

        self._save_config()
        return conn

    async def remove_connection(self, conn_id: str) -> None:
        conn = self.connections.get(conn_id)
        if conn is None:
            return

        await conn.disconnect()
        del self.connections[conn_id]

        to_remove = [sid for sid, sub in self.subscriptions.items() if sub.connection_id == conn_id]
        for sid in to_remove:
            del self.subscriptions[sid]

        self._save_config()

    # -- Subscription management ---------------------------------------------

    def add_subscription(self, config: dict[str, Any]) -> NodeSubscription:
        sub = NodeSubscription.from_dict(config)
        self.subscriptions[sub.id] = sub
        self._save_config()
        return sub

    def remove_subscription(self, sub_id: str) -> None:
        if sub_id in self.subscriptions:
            del self.subscriptions[sub_id]
            self._save_config()

    # -- Status --------------------------------------------------------------

    def get_connection_status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": conn.id,
                "endpoint": conn.endpoint,
                "connected": conn.connected,
                "enabled": conn.enabled,
                "username": conn.username,
                "needs_credentials": bool(conn.username and not conn.has_runtime_password),
                "subscription_count": sum(
                    1 for s in self.subscriptions.values() if s.connection_id == conn.id
                ),
            }
            for conn in self.connections.values()
        ]

    def get_subscription_status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": sub.id,
                "connection_id": sub.connection_id,
                "node_id": sub.node_id,
                "catalog_node_id": sub.catalog_node_id,
                "enabled": sub.enabled,
                "last_value": sub.last_value,
            }
            for sub in self.subscriptions.values()
        ]

    # -- Discovery -----------------------------------------------------------

    @staticmethod
    async def discover_servers(discovery_url: str = "opc.tcp://localhost:4840") -> list[str]:
        try:
            client = Client(url=discovery_url)
            servers = await client.connect_and_find_servers()
            return [
                url
                for server in servers
                for url in (server.DiscoveryUrls or [])
            ]
        except Exception as e:
            logger.error("Server discovery failed for %s: %s", discovery_url, e)
            return []
