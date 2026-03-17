"""Tests for reactor OPC mapping (opc_mapping.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reactor.opc_mapping import (
    NodeMapping,
    OPCMappingManager,
    safe_eval_math_expr,
    ALLOWED_READ_KEYS,
    ALLOWED_WRITE_KEYS,
)


class TestSafeEvalMathExpr:
    def test_identity(self):
        assert safe_eval_math_expr("value", 42.0) == 42.0

    def test_addition(self):
        assert safe_eval_math_expr("value + 273.15", 25.0) == pytest.approx(298.15)

    def test_multiplication(self):
        assert safe_eval_math_expr("value * 2", 5.0) == pytest.approx(10.0)

    def test_complex_expression(self):
        assert safe_eval_math_expr("(value - 32) * 5 / 9", 212.0) == pytest.approx(100.0)

    def test_unary_negation(self):
        assert safe_eval_math_expr("-value", 5.0) == pytest.approx(-5.0)

    def test_power(self):
        assert safe_eval_math_expr("value ** 2", 3.0) == pytest.approx(9.0)

    def test_rejects_unknown_variable(self):
        with pytest.raises(ValueError, match="Unsupported variable"):
            safe_eval_math_expr("x + 1", 5.0)

    def test_rejects_function_calls(self):
        with pytest.raises(ValueError):
            safe_eval_math_expr("abs(value)", -5.0)


class TestNodeMapping:
    def test_to_dict_roundtrip(self):
        m = NodeMapping(
            opc_node_id="temp-1", reactor_var="temperature",
            direction="read", transform="value + 273.15", priority=80,
        )
        d = m.to_dict()
        restored = NodeMapping.from_dict(d)
        assert restored.opc_node_id == "temp-1"
        assert restored.transform == "value + 273.15"
        assert restored.priority == 80

    def test_apply_transform_identity(self):
        m = NodeMapping(opc_node_id="x", reactor_var="temperature", direction="read")
        assert m.apply_transform(42.0) == 42.0

    def test_apply_transform_expression(self):
        m = NodeMapping(
            opc_node_id="x", reactor_var="temperature",
            direction="read", transform="value + 273.15",
        )
        assert m.apply_transform(25.0) == pytest.approx(298.15)

    def test_from_dict_ignores_unknown(self):
        d = {"opc_node_id": "x", "reactor_var": "temperature",
             "direction": "read", "unknown": 123}
        m = NodeMapping.from_dict(d)
        assert m.opc_node_id == "x"


class TestOPCMappingManager:
    @pytest.fixture
    def mgr(self, tmp_path: Path) -> OPCMappingManager:
        return OPCMappingManager(config_path=tmp_path / "mappings.json")

    def test_add_and_list(self, mgr: OPCMappingManager):
        m = NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="read")
        mgr.add_mapping(m)
        assert len(mgr.list_mappings()) == 1

    def test_add_replaces_same_node_direction(self, mgr: OPCMappingManager):
        m1 = NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="read")
        m2 = NodeMapping(opc_node_id="n1", reactor_var="pressure_bar", direction="read")
        mgr.add_mapping(m1)
        mgr.add_mapping(m2)
        mappings = mgr.list_mappings()
        assert len(mappings) == 1
        assert mappings[0].reactor_var == "pressure_bar"

    def test_same_node_different_direction_kept(self, mgr: OPCMappingManager):
        m1 = NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="read")
        m2 = NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="write")
        mgr.add_mapping(m1)
        mgr.add_mapping(m2)
        assert len(mgr.list_mappings()) == 2

    def test_remove_by_node_and_direction(self, mgr: OPCMappingManager):
        mgr.add_mapping(NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="read"))
        mgr.add_mapping(NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="write"))
        assert mgr.remove_mapping("n1", direction="read") is True
        assert len(mgr.list_mappings()) == 1

    def test_remove_all_directions(self, mgr: OPCMappingManager):
        mgr.add_mapping(NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="read"))
        mgr.add_mapping(NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="write"))
        assert mgr.remove_mapping("n1") is True
        assert len(mgr.list_mappings()) == 0

    def test_remove_nonexistent(self, mgr: OPCMappingManager):
        assert mgr.remove_mapping("nope") is False

    def test_get_read_mappings(self, mgr: OPCMappingManager):
        mgr.add_mapping(NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="read"))
        mgr.add_mapping(NodeMapping(opc_node_id="n2", reactor_var="temperature", direction="write"))
        mgr.add_mapping(NodeMapping(opc_node_id="n3", reactor_var="pressure_bar", direction="read", enabled=False))
        reads = mgr.get_read_mappings()
        assert len(reads) == 1
        assert reads[0].opc_node_id == "n1"

    def test_get_write_mappings(self, mgr: OPCMappingManager):
        mgr.add_mapping(NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="write"))
        mgr.add_mapping(NodeMapping(opc_node_id="n2", reactor_var="temperature", direction="read"))
        writes = mgr.get_write_mappings()
        assert len(writes) == 1
        assert writes[0].opc_node_id == "n1"

    def test_persistence(self, tmp_path: Path):
        path = tmp_path / "m.json"
        mgr1 = OPCMappingManager(config_path=path)
        mgr1.add_mapping(NodeMapping(opc_node_id="n1", reactor_var="temperature", direction="read"))

        mgr2 = OPCMappingManager(config_path=path)
        assert len(mgr2.list_mappings()) == 1
        assert mgr2.list_mappings()[0].opc_node_id == "n1"

    def test_empty_config(self, tmp_path: Path):
        mgr = OPCMappingManager(config_path=tmp_path / "nonexistent.json")
        assert len(mgr.list_mappings()) == 0


class TestAllowedKeys:
    def test_read_keys_include_temperature(self):
        assert "temperature" in ALLOWED_READ_KEYS
        assert "temperature_K" in ALLOWED_READ_KEYS

    def test_write_keys_include_conversion(self):
        assert "conversion" in ALLOWED_WRITE_KEYS
        assert "fsm_state_name" in ALLOWED_WRITE_KEYS
