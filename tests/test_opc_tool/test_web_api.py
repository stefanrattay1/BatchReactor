"""Tests for the OPC Tool REST API (FastAPI TestClient)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opc_tool.node_manager import NodeManager, OPCNode
from opc_tool.client import OPCClientPool
from opc_tool.web import create_app


@pytest.fixture
def node_mgr(tmp_path: Path) -> NodeManager:
    return NodeManager(data_dir=tmp_path / "nodes")


@pytest.fixture
def client_pool(tmp_path: Path, node_mgr: NodeManager) -> OPCClientPool:
    return OPCClientPool(
        node_manager=node_mgr,
        config_path=tmp_path / "opc_connections.json",
    )


@pytest.fixture
def api(node_mgr: NodeManager, client_pool: OPCClientPool) -> TestClient:
    app = create_app(node_manager=node_mgr, client_pool=client_pool, servers={})
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, api: TestClient):
        r = api.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert "version" in r.json()


class TestNodeCRUD:
    def test_create_and_list_nodes(self, api: TestClient):
        r = api.post("/api/nodes", json={
            "id": "temp-1", "name": "Temperature", "category": "sensor",
        })
        assert r.status_code == 200

        r = api.get("/api/nodes")
        assert r.status_code == 200
        nodes = r.json()["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["id"] == "temp-1"

    def test_get_single_node(self, api: TestClient):
        api.post("/api/nodes", json={"id": "n1", "name": "N1"})
        r = api.get("/api/nodes/n1")
        assert r.status_code == 200
        assert r.json()["id"] == "n1"

    def test_get_nonexistent_node(self, api: TestClient):
        r = api.get("/api/nodes/nope")
        assert r.status_code == 404

    def test_update_node(self, api: TestClient):
        api.post("/api/nodes", json={"id": "n1", "name": "N1"})
        r = api.put("/api/nodes/n1", json={"name": "Updated"})
        assert r.status_code == 200
        assert r.json()["node"]["name"] == "Updated"

    def test_delete_node(self, api: TestClient):
        api.post("/api/nodes", json={"id": "n1", "name": "N1"})
        r = api.delete("/api/nodes/n1")
        assert r.status_code == 200
        r = api.get("/api/nodes/n1")
        assert r.status_code == 404

    def test_filter_by_category(self, api: TestClient):
        api.post("/api/nodes", json={"id": "s1", "name": "S1", "category": "sensor"})
        api.post("/api/nodes", json={"id": "a1", "name": "A1", "category": "actuator"})
        r = api.get("/api/nodes?category=sensor")
        assert len(r.json()["nodes"]) == 1
        assert r.json()["nodes"][0]["id"] == "s1"


class TestValueReadWrite:
    def test_write_and_read_value(self, api: TestClient):
        api.post("/api/nodes", json={"id": "n1", "name": "N1"})
        r = api.post("/api/nodes/n1/value", json={"value": 42.5})
        assert r.status_code == 200

        r = api.get("/api/nodes/n1/value")
        assert r.status_code == 200
        assert r.json()["value"] == 42.5

    def test_read_value_nonexistent(self, api: TestClient):
        r = api.get("/api/nodes/nope/value")
        assert r.status_code == 404

    def test_bulk_read(self, api: TestClient):
        api.post("/api/nodes", json={"id": "n1", "name": "N1"})
        api.post("/api/nodes", json={"id": "n2", "name": "N2"})
        api.post("/api/nodes/n1/value", json={"value": 1.0})
        api.post("/api/nodes/n2/value", json={"value": 2.0})

        r = api.post("/api/values/bulk", json={"node_ids": ["n1", "n2"]})
        assert r.status_code == 200
        assert r.json()["values"] == {"n1": 1.0, "n2": 2.0}

    def test_bulk_write(self, api: TestClient):
        api.post("/api/nodes", json={"id": "n1", "name": "N1"})
        api.post("/api/nodes", json={"id": "n2", "name": "N2"})

        r = api.post("/api/values/write-bulk", json={
            "updates": [
                {"node_id": "n1", "value": 10.0},
                {"node_id": "n2", "value": 20.0},
            ]
        })
        assert r.status_code == 200

        r = api.post("/api/values/bulk", json={"node_ids": ["n1", "n2"]})
        assert r.json()["values"] == {"n1": 10.0, "n2": 20.0}


class TestServerManagement:
    def test_list_servers_empty(self, api: TestClient):
        r = api.get("/api/servers")
        assert r.status_code == 200
        assert r.json()["servers"] == []


class TestConnectionManagement:
    def test_list_connections_empty(self, api: TestClient):
        r = api.get("/api/connections")
        assert r.status_code == 200
        assert r.json()["connections"] == []
        assert r.json()["subscriptions"] == []
