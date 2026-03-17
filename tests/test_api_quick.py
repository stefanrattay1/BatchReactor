#!/usr/bin/env python3
"""Quick dashboard test - simpler version.

Requires a running reactor web server on localhost:8000.
"""
import requests
import time

import pytest

BASE_URL = "http://localhost:8000"


def _server_reachable() -> bool:
    try:
        requests.get(f"{BASE_URL}/api/state", timeout=1)
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False


pytestmark = pytest.mark.skipif(
    not _server_reachable(), reason="Reactor web server not running on localhost:8000"
)


def test():
    print("Testing dashboard API...")

    # Test 1: State API
    r = requests.get(f"{BASE_URL}/api/state")
    assert r.status_code == 200
    d = r.json()
    print(f"✓ State API: temp={d['temperature_C']}°C, phase={d['phase']}")
    
    # Test 2: Recipe API
    r = requests.get(f"{BASE_URL}/api/recipe/current")
    assert r.status_code == 200
    recipe = r.json()
    print(f"✓ Recipe API: {recipe['name']}, {len(recipe['steps'])} steps")
    
    # Test 3: Dashboard HTML
    r = requests.get(f"{BASE_URL}/")
    assert r.status_code == 200
    assert "chart-temp" in r.text
    assert "nowMarkerPlugin" in r.text
    print(f"✓ Dashboard HTML: {len(r.text)} bytes, has chart and plugin")
    
    # Test 4: Start simulation
    r = requests.post(f"{BASE_URL}/api/command", json={"command": "START"})
    assert r.status_code == 200
    print("✓ Started simulation")
    
    # Test 5: Wait and check progress
    time.sleep(3)
    r = requests.get(f"{BASE_URL}/api/state")
    d = r.json()
    print(f"✓ After 3s: time={d['recipe_elapsed_s']:.1f}s, running={d['simulation_running']}")
    assert d['simulation_running'] == True
    assert d['recipe_elapsed_s'] >= 2
    
    # Test 6: Stop
    r = requests.post(f"{BASE_URL}/api/command", json={"command": "STOP"})
    print("✓ Stopped simulation")
    
    print("\n✅ All API tests passed!")

def test_list_batch_records():
    """GET /api/batch/records returns a list (possibly empty)."""
    r = requests.get(f"{BASE_URL}/api/batch/records")
    assert r.status_code == 200
    data = r.json()
    assert "records" in data
    assert isinstance(data["records"], list)


def test_get_batch_record_invalid_id():
    """GET /api/batch/records/{bad_id} returns 400 for invalid format."""
    r = requests.get(f"{BASE_URL}/api/batch/records/../../etc/passwd")
    assert r.status_code == 400
    assert "error" in r.json()


def test_get_batch_record_not_found():
    """GET /api/batch/records/{id} returns 404 for missing record."""
    r = requests.get(f"{BASE_URL}/api/batch/records/99991231_235959")
    assert r.status_code == 404
    assert "error" in r.json()


if __name__ == "__main__":
    test()
