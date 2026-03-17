"""Tests for the SensorBuffer class."""

from __future__ import annotations

import pytest

from reactor.sensor_buffer import SensorBuffer, BufferedValue


class _DummyState:
    """Minimal ReactorState stand-in for testing."""

    temperature: float = 298.15
    jacket_temperature: float = 298.15
    volume: float = 0.1


# ---------------------------------------------------------------------------
# Priority resolution
# ---------------------------------------------------------------------------


class TestPriorityResolution:
    def test_highest_priority_wins(self):
        buf = SensorBuffer()
        buf.write("jacket_temperature", 330.0, source="recipe", priority=10)
        buf.write("jacket_temperature", 350.0, source="opc_subscription", priority=50)
        buf.write("jacket_temperature", 340.0, source="web_api", priority=30)

        winners = buf.resolve()

        assert "jacket_temperature" in winners
        assert winners["jacket_temperature"].value == 350.0
        assert winners["jacket_temperature"].source == "opc_subscription"

    def test_single_source_resolves(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)

        winners = buf.resolve()
        assert winners["temperature"].value == 310.0

    def test_same_source_overwrites(self):
        """Multiple writes from same source should keep the latest."""
        buf = SensorBuffer()
        buf.write("temperature", 300.0, source="opc_subscription", priority=50)
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)

        winners = buf.resolve()
        assert winners["temperature"].value == 310.0

    def test_empty_buffer_resolves_empty(self):
        buf = SensorBuffer()
        winners = buf.resolve()
        assert winners == {}

    def test_multiple_keys_resolved_independently(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)
        buf.write("jacket_temperature", 350.0, source="recipe", priority=10)

        winners = buf.resolve()

        assert winners["temperature"].value == 310.0
        assert winners["jacket_temperature"].value == 350.0


# ---------------------------------------------------------------------------
# Sticky behavior
# ---------------------------------------------------------------------------


class TestStickyBehavior:
    def test_temperature_is_auto_sticky(self):
        """temperature is solver-overwritten, so should auto-detect as sticky."""
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)

        # First resolve
        w1 = buf.resolve()
        assert w1["temperature"].value == 310.0

        # Second resolve (no new writes) — sticky should persist
        w2 = buf.resolve()
        assert w2["temperature"].value == 310.0

    def test_jacket_temperature_is_not_sticky(self):
        """jacket_temperature is preserved by step(), so should be non-sticky."""
        buf = SensorBuffer()
        buf.write("jacket_temperature", 350.0, source="recipe", priority=10)

        # First resolve consumes the entry
        w1 = buf.resolve()
        assert w1["jacket_temperature"].value == 350.0

        # Second resolve (no new writes) — non-sticky should be gone
        w2 = buf.resolve()
        assert "jacket_temperature" not in w2

    def test_sticky_survives_multiple_resolves(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)

        for _ in range(5):
            winners = buf.resolve()
            assert winners["temperature"].value == 310.0

    def test_sticky_replaced_by_new_write(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)
        buf.resolve()

        # New write from same source with updated value
        buf.write("temperature", 320.0, source="opc_subscription", priority=50)
        winners = buf.resolve()
        assert winners["temperature"].value == 320.0

    def test_explicit_sticky_override(self):
        """Manual sticky=True on a normally non-sticky key."""
        buf = SensorBuffer()
        buf.write("jacket_temperature", 350.0, source="test", priority=10, sticky=True)

        buf.resolve()
        w2 = buf.resolve()
        assert w2["jacket_temperature"].value == 350.0


# ---------------------------------------------------------------------------
# apply_to_state
# ---------------------------------------------------------------------------


class TestApplyToState:
    def test_apply_sets_attributes(self):
        buf = SensorBuffer()
        state = _DummyState()

        buf.write("temperature", 310.0, source="opc_subscription", priority=50)
        buf.write("jacket_temperature", 350.0, source="recipe", priority=10)

        sources = buf.apply_to_state(state)

        assert state.temperature == 310.0
        assert state.jacket_temperature == 350.0
        assert sources["temperature"] == "opc_subscription"
        assert sources["jacket_temperature"] == "recipe"

    def test_apply_unknown_key_warns(self, caplog):
        buf = SensorBuffer()
        state = _DummyState()

        buf.write("nonexistent_key", 42.0, source="test", priority=10, sticky=False)
        sources = buf.apply_to_state(state)

        assert "nonexistent_key" not in sources
        assert "unknown state_key" in caplog.text

    def test_apply_empty_buffer(self):
        buf = SensorBuffer()
        state = _DummyState()
        state.temperature = 300.0

        sources = buf.apply_to_state(state)

        assert sources == {}
        assert state.temperature == 300.0  # Unchanged


# ---------------------------------------------------------------------------
# clear_source
# ---------------------------------------------------------------------------


class TestClearSource:
    def test_clear_removes_source_from_buffer(self):
        buf = SensorBuffer()
        buf.write("jacket_temperature", 350.0, source="web_api", priority=30)
        buf.write("jacket_temperature", 330.0, source="recipe", priority=10)

        buf.clear_source("web_api")
        winners = buf.resolve()

        assert winners["jacket_temperature"].source == "recipe"

    def test_clear_removes_sticky_entries(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)
        buf.resolve()  # Install sticky

        buf.clear_source("opc_subscription")
        winners = buf.resolve()

        assert "temperature" not in winners

    def test_clear_nonexistent_source_is_safe(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)
        buf.clear_source("nonexistent")  # Should not raise

        winners = buf.resolve()
        assert winners["temperature"].value == 310.0


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_includes_all_sections(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)
        buf.resolve()

        status = buf.get_status()

        assert "buffered" in status
        assert "sticky" in status
        assert "last_resolved" in status

    def test_status_shows_last_resolved(self):
        buf = SensorBuffer()
        buf.write("jacket_temperature", 350.0, source="recipe", priority=10)
        buf.resolve()

        status = buf.get_status()
        assert "jacket_temperature" in status["last_resolved"]
        assert status["last_resolved"]["jacket_temperature"]["source"] == "recipe"

    def test_status_shows_sticky_entries(self):
        buf = SensorBuffer()
        buf.write("temperature", 310.0, source="opc_subscription", priority=50)
        buf.resolve()

        status = buf.get_status()
        assert "temperature" in status["sticky"]
        assert status["sticky"]["temperature"]["source"] == "opc_subscription"


# ---------------------------------------------------------------------------
# Key alias behavior (temperature_K -> temperature)
# ---------------------------------------------------------------------------


class TestKeyAliases:
    def test_temperature_k_alias_is_sticky(self):
        """temperature_K should be treated as solver-overwritten (sticky)."""
        buf = SensorBuffer()
        buf.write("temperature_K", 310.0, source="opc_subscription", priority=50)

        buf.resolve()
        w2 = buf.resolve()
        assert "temperature_K" in w2

    def test_jacket_temperature_k_alias_applies(self):
        buf = SensorBuffer()
        state = _DummyState()
        buf.write("jacket_temperature_K", 350.0, source="test", priority=10)

        sources = buf.apply_to_state(state)
        assert state.jacket_temperature == 350.0
