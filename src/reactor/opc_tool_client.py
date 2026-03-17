"""REST client for communicating with the OPC Tool.

The reactor uses this to discover OPC Tool nodes and read/write values
via the OPC Tool's REST API instead of directly managing OPC UA servers.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("reactor.opc_tool_client")

# Retry interval when OPC Tool is not reachable
_HEALTH_RETRY_INTERVAL_S = 30.0


class OPCToolClient:
    """Async HTTP client for the OPC Tool REST API."""

    def __init__(self, base_url: str = "http://localhost:8001") -> None:
        self.base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=5.0)
        self._available = False
        self._last_health_check = 0.0

    @property
    def available(self) -> bool:
        return self._available

    async def check_health(self) -> bool:
        """Check if the OPC Tool is reachable."""
        try:
            r = await self._client.get("/api/health")
            self._available = r.status_code == 200
            self._last_health_check = time.monotonic()
            return self._available
        except Exception:
            self._available = False
            self._last_health_check = time.monotonic()
            return False

    async def maybe_reconnect(self) -> bool:
        """Retry health check if enough time has passed since last attempt."""
        if self._available:
            return True
        now = time.monotonic()
        if now - self._last_health_check < _HEALTH_RETRY_INTERVAL_S:
            return False
        return await self.check_health()

    async def list_nodes(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all nodes from the OPC Tool catalog."""
        params = {"category": category} if category else {}
        r = await self._client.get("/api/nodes", params=params)
        r.raise_for_status()
        return r.json().get("nodes", [])

    async def get_value(self, node_id: str) -> Any:
        """Read a single node value."""
        r = await self._client.get(f"/api/nodes/{node_id}/value")
        r.raise_for_status()
        return r.json().get("value")

    async def get_values_bulk(self, node_ids: list[str]) -> dict[str, Any]:
        """Read multiple node values in one request."""
        r = await self._client.post("/api/values/bulk", json={"node_ids": node_ids})
        r.raise_for_status()
        return r.json().get("values", {})

    async def write_value(self, node_id: str, value: Any) -> None:
        """Write a value to a single node."""
        await self._client.post(
            f"/api/nodes/{node_id}/value", json={"value": value}
        )

    async def write_values_bulk(self, updates: dict[str, Any]) -> None:
        """Write values to multiple nodes in one request."""
        payload = [{"node_id": k, "value": v} for k, v in updates.items()]
        await self._client.post("/api/values/write-bulk", json={"updates": payload})

    async def close(self) -> None:
        await self._client.aclose()
