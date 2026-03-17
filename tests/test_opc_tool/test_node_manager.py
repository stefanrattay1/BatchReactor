"""Tests for opc_tool.node_manager — node catalog CRUD and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opc_tool.node_manager import NodeManager, OPCNode


@pytest.fixture
def node_mgr(tmp_path: Path) -> NodeManager:
    return NodeManager(data_dir=tmp_path / "nodes")


def _make_node(**overrides) -> OPCNode:
    defaults = dict(
        id="temp-1", name="Temperature", node_id="ns=2;s=Temperature",
        source="local", category="sensor", data_type="Double",
    )
    defaults.update(overrides)
    return OPCNode(**defaults)


class TestNodeCRUD:
    def test_add_and_get(self, node_mgr: NodeManager):
        node = _make_node()
        node_mgr.add_node(node)
        fetched = node_mgr.get_node("temp-1")
        assert fetched is not None
        assert fetched.name == "Temperature"

    def test_remove(self, node_mgr: NodeManager):
        node_mgr.add_node(_make_node())
        assert node_mgr.remove_node("temp-1") is True
        assert node_mgr.get_node("temp-1") is None

    def test_remove_nonexistent(self, node_mgr: NodeManager):
        assert node_mgr.remove_node("nope") is False

    def test_update(self, node_mgr: NodeManager):
        node_mgr.add_node(_make_node())
        updated = node_mgr.update_node("temp-1", {"name": "Reactor Temp"})
        assert updated is not None
        assert updated.name == "Reactor Temp"

    def test_update_nonexistent(self, node_mgr: NodeManager):
        assert node_mgr.update_node("nope", {"name": "x"}) is None

    def test_list_nodes(self, node_mgr: NodeManager):
        node_mgr.add_node(_make_node(id="s1", category="sensor"))
        node_mgr.add_node(_make_node(id="a1", category="actuator"))
        assert len(node_mgr.list_nodes()) == 2
        assert len(node_mgr.list_nodes(category="sensor")) == 1
        assert len(node_mgr.list_nodes(category="actuator")) == 1

    def test_add_overwrites_same_id(self, node_mgr: NodeManager):
        node_mgr.add_node(_make_node(name="V1"))
        node_mgr.add_node(_make_node(name="V2"))
        assert len(node_mgr.list_nodes()) == 1
        assert node_mgr.get_node("temp-1").name == "V2"


class TestNodeValues:
    def test_set_and_get_value(self, node_mgr: NodeManager):
        node_mgr.add_node(_make_node())
        node_mgr.set_value("temp-1", 42.5)
        value, ts = node_mgr.get_value("temp-1")
        assert value == 42.5
        assert ts > 0

    def test_set_value_nonexistent_raises(self, node_mgr: NodeManager):
        with pytest.raises(KeyError):
            node_mgr.set_value("nope", 1.0)

    def test_get_value_nonexistent_raises(self, node_mgr: NodeManager):
        with pytest.raises(KeyError):
            node_mgr.get_value("nope")

    def test_bulk_values(self, node_mgr: NodeManager):
        node_mgr.add_node(_make_node(id="n1"))
        node_mgr.add_node(_make_node(id="n2"))
        node_mgr.set_values_bulk([
            {"node_id": "n1", "value": 10.0},
            {"node_id": "n2", "value": 20.0},
        ])
        values = node_mgr.get_values_bulk(["n1", "n2", "missing"])
        assert values == {"n1": 10.0, "n2": 20.0}


class TestPersistence:
    def test_save_and_reload(self, tmp_path: Path):
        mgr1 = NodeManager(data_dir=tmp_path / "data")
        mgr1.add_node(_make_node(id="p1", name="Pressure"))
        mgr1.add_node(_make_node(id="t1", name="Temperature"))

        # Reload from same directory
        mgr2 = NodeManager(data_dir=tmp_path / "data")
        assert len(mgr2.list_nodes()) == 2
        assert mgr2.get_node("p1").name == "Pressure"

    def test_empty_data_dir(self, tmp_path: Path):
        mgr = NodeManager(data_dir=tmp_path / "empty")
        assert len(mgr.list_nodes()) == 0

    def test_corrupt_file_handled(self, tmp_path: Path):
        data_dir = tmp_path / "corrupt"
        data_dir.mkdir()
        (data_dir / "nodes.json").write_text("not json")
        mgr = NodeManager(data_dir=data_dir)
        assert len(mgr.list_nodes()) == 0


class TestOPCNodeSerialization:
    def test_to_dict_roundtrip(self):
        node = _make_node(writable=True, current_value=3.14)
        d = node.to_dict()
        restored = OPCNode.from_dict(d)
        assert restored.id == node.id
        assert restored.writable == node.writable
        assert restored.current_value == node.current_value

    def test_from_dict_ignores_unknown_keys(self):
        d = {"id": "x", "name": "X", "node_id": "n", "source": "local",
             "category": "sensor", "unknown_key": "ignored"}
        node = OPCNode.from_dict(d)
        assert node.id == "x"
