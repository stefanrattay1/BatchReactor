"""Tests for OPC Tool client pool (migrated from reactor.opc_client)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opc_tool.client import OPCClientPool, OPCConnection
from opc_tool.node_manager import NodeManager


@pytest.mark.asyncio
async def test_add_connection_does_not_persist_password(tmp_path: Path):
    node_mgr = NodeManager(data_dir=tmp_path / "nodes")
    config_path = tmp_path / "opc_connections.json"
    pool = OPCClientPool(node_manager=node_mgr, config_path=config_path)

    await pool.add_connection({
        "id": "conn-1",
        "endpoint": "opc.tcp://localhost:4840",
        "username": "operator",
        "password": "super-secret",
        "enabled": False,
    })

    with open(config_path) as f:
        saved = json.load(f)

    assert saved["connections"][0]["username"] == "operator"
    assert "password" not in saved["connections"][0]


def test_load_config_ignores_legacy_password_and_flags_credentials_needed(tmp_path: Path):
    config_path = tmp_path / "opc_connections.json"
    config_path.write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "id": "conn-legacy",
                        "endpoint": "opc.tcp://localhost:4840",
                        "username": "operator",
                        "password": "legacy-secret",
                        "enabled": False,
                    }
                ],
                "subscriptions": [],
            }
        )
    )

    node_mgr = NodeManager(data_dir=tmp_path / "nodes")
    pool = OPCClientPool(node_manager=node_mgr, config_path=config_path)
    status = pool.get_connection_status()

    assert len(status) == 1
    assert status[0]["needs_credentials"] is True


@pytest.mark.asyncio
async def test_secure_mode_without_cert_material_fails_closed():
    conn = OPCConnection.from_dict(
        {
            "id": "secure-1",
            "endpoint": "opc.tcp://localhost:4840",
            "security_mode": "Sign",
            "enabled": True,
        }
    )

    ok = await conn.connect()

    assert ok is False
