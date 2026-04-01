"""Tests for PID canvas sensor-to-node coverage and layout reset API.

Two problems validated here:

1. DELETE /api/pid/layout — allows the user to reset stale saved positions.
2. Equipment sensors not appearing on the 2D canvas — every sensor in the
   node catalog that has a ``tag`` field (i.e. comes from a control module)
   must either have a hard-coded entry in DEFAULT_NODES or be handled by
   buildDynamicNodes() in the frontend.  The Python side of this test
   validates that the catalog produces well-formed tag entries so the
   frontend logic can act on them.
"""
from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import pytest
try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - optional test dependency
    requests = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
PID_LAYOUT_JS = PROJECT_ROOT / "frontend" / "src" / "config" / "pidLayout.js"
CONFIG_YAML = PROJECT_ROOT / "configs" / "default.yaml"
BASE_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _server_reachable() -> bool:
    if requests is None:
        return False
    try:
        requests.get(f"{BASE_URL}/api/state", timeout=1)
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False


def _extract_default_tags() -> set[str]:
    """Parse DEFAULT_NODES from pidLayout.js and return the set of data.tag values."""
    src = PID_LAYOUT_JS.read_text()
    # Match tag: 'XX-NNN' inside DEFAULT_NODES (before DEFAULT_EDGES)
    edges_start = src.find("export const DEFAULT_EDGES")
    nodes_src = src[:edges_start] if edges_start != -1 else src
    return set(re.findall(r"tag:\s*['\"]([A-Z0-9]+-\d+)['\"]", nodes_src))


def _extract_cm_tags_from_yaml() -> list[str]:
    """Return all control_module tags defined in the default equipment config."""
    import yaml  # only needed here
    with open(CONFIG_YAML) as f:
        cfg = yaml.safe_load(f)
    equipment = cfg.get("equipment", {})
    cms = equipment.get("control_modules", [])
    return [cm["tag"] for cm in cms if isinstance(cm, dict) and "tag" in cm]


def _extract_pid_roles_from_yaml() -> dict:
    import yaml
    with open(CONFIG_YAML) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("equipment", {}).get("pid", {}).get("em_roles", {})


# ---------------------------------------------------------------------------
# Static tests — no server needed
# ---------------------------------------------------------------------------

class TestPIDLayoutJS:
    """Validate the static pidLayout.js file."""

    def test_pid_layout_js_exists(self):
        assert PID_LAYOUT_JS.exists(), f"pidLayout.js not found at {PID_LAYOUT_JS}"

    def test_core_instrument_tags_present(self):
        """Core sensor and actuator tags must have DEFAULT_NODES entries."""
        expected = {
            "TT-101", "PT-101", "LT-101",           # sensors
            "FT-101", "FT-102", "FT-103",           # flow transmitters
            "XV-101", "XV-102", "XV-103",           # feed valves
            "P-101", "P-102", "P-103",              # feed pumps
            "XV-301", "P-301", "FT-301",            # drain train
        }
        tags = _extract_default_tags()
        missing = expected - tags
        assert not missing, (
            f"These tags are expected in DEFAULT_NODES but are absent: {sorted(missing)}"
        )

    def test_no_duplicate_tags_in_default_nodes(self):
        src = PID_LAYOUT_JS.read_text()
        edges_start = src.find("export const DEFAULT_EDGES")
        nodes_src = src[:edges_start] if edges_start != -1 else src
        tags = re.findall(r"tag:\s*['\"]([A-Z0-9]+-\d+)['\"]", nodes_src)
        dupes = [t for t in set(tags) if tags.count(t) > 1]
        assert not dupes, f"Duplicate tags in DEFAULT_NODES: {dupes}"

    def test_dynamic_node_id_prefix_never_collides_with_default_ids(self):
        """All dynamic node IDs start with 'sensor_'; no DEFAULT_NODES id may do so."""
        src = PID_LAYOUT_JS.read_text()
        ids = re.findall(r"id:\s*['\"]([^'\"]+)['\"]", src)
        # Filter to DEFAULT_NODES section
        edges_start = src.find("export const DEFAULT_EDGES")
        nodes_src = src[:edges_start] if edges_start != -1 else src
        node_ids = re.findall(r"\bid:\s*['\"]([^'\"]+)['\"]", nodes_src)
        collisions = [i for i in node_ids if i.startswith("sensor_")]
        assert not collisions, (
            f"DEFAULT_NODES ids must not start with 'sensor_' (reserved for dynamic nodes): {collisions}"
        )


class TestNodeCatalogTagCoverage:
    """Validate that equipment sensor tags are well-formed for dynamic node creation."""

    def test_cm_tags_are_valid_pid_format(self):
        """Every control-module tag must match the XX-NNN P&ID naming convention."""
        tags = _extract_cm_tags_from_yaml()
        pattern = re.compile(r"^[A-Z]+-\d+$")
        bad = [t for t in tags if not pattern.match(t)]
        assert not bad, f"Control module tags with invalid P&ID format: {bad}"

    def test_cm_tags_not_empty(self):
        tags = _extract_cm_tags_from_yaml()
        assert len(tags) > 0, "No control module tags found in default.yaml"

    def test_sensors_not_in_default_nodes_are_candidates_for_dynamic_creation(self):
        """Tags from CMs that are absent from DEFAULT_NODES must be non-empty strings
        so the frontend can create a dynamic node for them when enabled."""
        cm_tags = set(_extract_cm_tags_from_yaml())
        default_tags = _extract_default_tags()
        dynamic_candidates = cm_tags - default_tags
        # Each candidate must be a non-empty string in XX-NNN format
        pattern = re.compile(r"^[A-Z]+-\d+$")
        for tag in dynamic_candidates:
            assert isinstance(tag, str) and tag, f"Dynamic candidate tag is not a string: {tag!r}"
            assert pattern.match(tag), f"Dynamic candidate tag has bad format: {tag}"

    def test_reactor_sensor_instruments_use_explicit_sensor_port(self):
        roles = _extract_pid_roles_from_yaml()

        fill_side = roles["EM-FILL"]["side_instruments"]
        pressure_side = roles["EM-PRESS"]["instruments"]

        expected = {
            "LT-101": fill_side[0],
            "TT-101": fill_side[1],
            "PT-101": pressure_side[0],
        }

        for tag, item in expected.items():
            assert item.get("attach_to") == "reactor", f"{tag} must attach to the reactor"
            assert item.get("attach_handle") == "sensor", f"{tag} must use the reactor sensor port"


# ---------------------------------------------------------------------------
# API tests — require a running server
# ---------------------------------------------------------------------------

pytestmark_server = pytest.mark.skipif(
    not _server_reachable(), reason="Reactor web server not running on localhost:8000"
)


@pytestmark_server
class TestPIDLayoutAPI:
    """Tests for GET / POST / DELETE /api/pid/layout."""

    def test_get_returns_dict(self):
        r = requests.get(f"{BASE_URL}/api/pid/layout")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_post_saves_positions(self):
        positions = {"reactor": {"x": 123, "y": 456}}
        r = requests.post(f"{BASE_URL}/api/pid/layout", json=positions)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Verify it was persisted
        r2 = requests.get(f"{BASE_URL}/api/pid/layout")
        assert r2.json()["reactor"]["x"] == 123

    def test_delete_clears_saved_layout(self):
        # Ensure something is saved first
        requests.post(f"{BASE_URL}/api/pid/layout", json={"reactor": {"x": 999, "y": 999}})

        r = requests.delete(f"{BASE_URL}/api/pid/layout")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # After delete, GET must return an empty dict (defaults used by frontend)
        r2 = requests.get(f"{BASE_URL}/api/pid/layout")
        assert r2.json() == {}

    def test_delete_is_idempotent(self):
        """Calling DELETE twice should not error even if no file exists."""
        requests.delete(f"{BASE_URL}/api/pid/layout")
        r = requests.delete(f"{BASE_URL}/api/pid/layout")
        assert r.status_code == 200


@pytestmark_server
class TestNodeCatalogAPI:
    """Validate /api/connections returns equipment sensors with proper tag fields."""

    def _catalog(self):
        r = requests.get(f"{BASE_URL}/api/connections")
        assert r.status_code == 200
        return r.json()["opc_ua"]["node_catalog"]

    def test_equipment_nodes_have_tag_field(self):
        """Every valve/pump/actuator node must expose a 'tag' for the frontend."""
        catalog = self._catalog()
        equipment = [n for n in catalog if n.get("category") in ("valve", "pump", "actuator")]
        assert len(equipment) > 0, "No equipment nodes in catalog"
        for node in equipment:
            assert "tag" in node, f"Equipment node '{node['id']}' is missing 'tag' field"
            assert node["tag"], f"Equipment node '{node['id']}' has empty 'tag'"

    def test_equipment_tags_match_pid_format(self):
        catalog = self._catalog()
        equipment = [n for n in catalog if n.get("category") in ("valve", "pump", "actuator")]
        pattern = re.compile(r"^[A-Z]+-\d+$")
        for node in equipment:
            tag = node.get("tag", "")
            assert pattern.match(tag), (
                f"Equipment node '{node['id']}' has malformed tag: '{tag}'"
            )

    def test_core_sensors_have_no_tag_field(self):
        """Core sensors (temperature, pressure …) should NOT have a tag — they are
        matched to DEFAULT_NODES via state_key, not tag."""
        catalog = self._catalog()
        core = [n for n in catalog if n["id"] in ("temperature", "pressure", "conversion",
                                                    "viscosity", "fill_level", "mass_total")]
        for node in core:
            assert "tag" not in node, (
                f"Core sensor '{node['id']}' unexpectedly has a 'tag' field; "
                "this would prevent it from showing on the PID canvas"
            )
