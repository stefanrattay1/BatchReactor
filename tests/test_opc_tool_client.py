"""Tests for reactor's OPC Tool REST client (opc_tool_client.py).

Uses httpx MockTransport to simulate OPC Tool API responses.
"""

from __future__ import annotations

import json

import httpx
import pytest

from reactor.opc_tool_client import OPCToolClient


def _mock_transport(handler):
    """Create an httpx.MockTransport from a handler function."""
    return httpx.MockTransport(handler)


def _make_client(handler) -> OPCToolClient:
    """Create an OPCToolClient with mocked transport."""
    client = OPCToolClient(base_url="http://test:8001")
    client._client = httpx.AsyncClient(
        transport=_mock_transport(handler), base_url="http://test:8001",
    )
    return client


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"status": "ok"})

        client = _make_client(handler)
        assert await client.check_health() is True
        assert client.available is True
        await client.close()

    @pytest.mark.asyncio
    async def test_unreachable(self):
        def handler(request: httpx.Request):
            raise httpx.ConnectError("refused")

        client = _make_client(handler)
        assert await client.check_health() is False
        assert client.available is False
        await client.close()

    @pytest.mark.asyncio
    async def test_server_error(self):
        def handler(request: httpx.Request):
            return httpx.Response(500)

        client = _make_client(handler)
        assert await client.check_health() is False
        await client.close()


class TestListNodes:
    @pytest.mark.asyncio
    async def test_list_all(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={
                "nodes": [
                    {"id": "n1", "name": "Temperature"},
                    {"id": "n2", "name": "Pressure"},
                ]
            })

        client = _make_client(handler)
        nodes = await client.list_nodes()
        assert len(nodes) == 2
        assert nodes[0]["id"] == "n1"
        await client.close()

    @pytest.mark.asyncio
    async def test_list_with_category(self):
        def handler(request: httpx.Request):
            assert "category=sensor" in str(request.url)
            return httpx.Response(200, json={"nodes": [{"id": "s1"}]})

        client = _make_client(handler)
        nodes = await client.list_nodes(category="sensor")
        assert len(nodes) == 1
        await client.close()


class TestGetValue:
    @pytest.mark.asyncio
    async def test_get_single_value(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"value": 42.5})

        client = _make_client(handler)
        val = await client.get_value("temp-1")
        assert val == 42.5
        await client.close()


class TestBulkOperations:
    @pytest.mark.asyncio
    async def test_bulk_read(self):
        def handler(request: httpx.Request):
            body = json.loads(request.content)
            assert body["node_ids"] == ["n1", "n2"]
            return httpx.Response(200, json={"values": {"n1": 1.0, "n2": 2.0}})

        client = _make_client(handler)
        values = await client.get_values_bulk(["n1", "n2"])
        assert values == {"n1": 1.0, "n2": 2.0}
        await client.close()

    @pytest.mark.asyncio
    async def test_bulk_write(self):
        def handler(request: httpx.Request):
            body = json.loads(request.content)
            assert len(body["updates"]) == 2
            return httpx.Response(200, json={"status": "ok"})

        client = _make_client(handler)
        await client.write_values_bulk({"n1": 1.0, "n2": 2.0})
        await client.close()


class TestMaybeReconnect:
    @pytest.mark.asyncio
    async def test_already_available(self):
        def handler(request: httpx.Request):
            return httpx.Response(200, json={"status": "ok"})

        client = _make_client(handler)
        client._available = True
        result = await client.maybe_reconnect()
        assert result is True
        await client.close()

    @pytest.mark.asyncio
    async def test_retry_respects_interval(self):
        call_count = 0

        def handler(request: httpx.Request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"status": "ok"})

        client = _make_client(handler)
        client._available = False
        import time
        client._last_health_check = time.monotonic()  # just checked
        result = await client.maybe_reconnect()
        assert result is False  # should not retry yet
        assert call_count == 0
        await client.close()
