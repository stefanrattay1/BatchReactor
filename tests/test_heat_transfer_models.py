"""Unit tests for pluggable heat transfer models."""

from dataclasses import dataclass

import pytest

from reactor.chemistry import ThermalParams
from reactor.heat_transfer_models import (
    ConstantUA,
    DynamicUA,
    GeometryAwareUA,
    HeatTransferModel,
    HEAT_TRANSFER_REGISTRY,
    build_heat_transfer_model,
    register_heat_transfer_model,
)


# Lightweight mock for ReactorState
@dataclass
class MockReactorState:
    temperature: float = 350.0
    volume: float = 0.08  # m³


# Lightweight mock for ReactorGeometry
class MockGeometry:
    def __init__(self, vessel_volume=0.1, wetted_area_full=0.8):
        self._vessel_volume = vessel_volume
        self._wetted_area_full = wetted_area_full

    @property
    def vessel_volume(self):
        return self._vessel_volume

    def wetted_area(self, V_liquid):
        # Linear scaling for simplicity
        return self._wetted_area_full * (V_liquid / self._vessel_volume)


# Lightweight mock for FluidMechanicsState
@dataclass
class MockFluidMechanicsState:
    UA_dynamic: float = 800.0  # W/K

    @property
    def UA_kW_per_K(self):
        return self.UA_dynamic / 1000.0


class TestConstantUA:
    def test_returns_thermal_UA(self):
        model = ConstantUA()
        thermal = ThermalParams(UA=1.5)
        UA = model.compute_UA(MockReactorState(), thermal, None, None)
        assert UA == 1.5

    def test_ignores_geometry(self):
        model = ConstantUA()
        thermal = ThermalParams(UA=1.5)
        geo = MockGeometry()
        UA = model.compute_UA(MockReactorState(), thermal, geo, None)
        assert UA == 1.5

    def test_ignores_fluid_mechanics(self):
        model = ConstantUA()
        thermal = ThermalParams(UA=1.5)
        fm = MockFluidMechanicsState()
        UA = model.compute_UA(MockReactorState(), thermal, None, fm)
        assert UA == 1.5


class TestGeometryAwareUA:
    def test_at_full_fill(self):
        model = GeometryAwareUA()
        thermal = ThermalParams(UA=1.0)
        state = MockReactorState(volume=0.1)
        geo = MockGeometry(vessel_volume=0.1, wetted_area_full=0.8)
        UA = model.compute_UA(state, thermal, geo, None)
        # At full fill, area ratio = 1.0
        assert pytest.approx(UA) == 1.0

    def test_at_half_fill(self):
        model = GeometryAwareUA()
        thermal = ThermalParams(UA=1.0)
        state = MockReactorState(volume=0.05)
        geo = MockGeometry(vessel_volume=0.1, wetted_area_full=0.8)
        UA = model.compute_UA(state, thermal, geo, None)
        # At half fill, area ratio = 0.5
        assert pytest.approx(UA) == 0.5

    def test_fallback_to_constant_without_geometry(self):
        model = GeometryAwareUA()
        thermal = ThermalParams(UA=1.0)
        UA = model.compute_UA(MockReactorState(), thermal, None, None)
        assert UA == 1.0

    def test_scales_proportionally(self):
        model = GeometryAwareUA()
        thermal = ThermalParams(UA=2.0)
        geo = MockGeometry(vessel_volume=0.1)
        state_quarter = MockReactorState(volume=0.025)
        state_full = MockReactorState(volume=0.1)

        UA_quarter = model.compute_UA(state_quarter, thermal, geo, None)
        UA_full = model.compute_UA(state_full, thermal, geo, None)

        assert pytest.approx(UA_quarter) == 0.5  # 2.0 * 0.25
        assert pytest.approx(UA_full) == 2.0


class TestDynamicUA:
    def test_uses_fluid_mechanics(self):
        model = DynamicUA()
        thermal = ThermalParams(UA=1.0)
        fm = MockFluidMechanicsState(UA_dynamic=1500.0)  # 1.5 kW/K
        UA = model.compute_UA(MockReactorState(), thermal, None, fm)
        assert pytest.approx(UA) == 1.5

    def test_returns_dynamic_UA_without_flooring(self):
        model = DynamicUA()
        thermal = ThermalParams(UA=1.0)
        fm = MockFluidMechanicsState(UA_dynamic=50.0)  # 0.05 kW/K
        UA = model.compute_UA(MockReactorState(), thermal, None, fm)
        assert pytest.approx(UA) == 0.05

    def test_fallback_without_fluid_mechanics(self):
        model = DynamicUA()
        thermal = ThermalParams(UA=1.0)
        UA = model.compute_UA(MockReactorState(), thermal, None, None)
        assert UA == 1.0


class TestRegistry:
    def test_all_models_registered(self):
        assert "constant" in HEAT_TRANSFER_REGISTRY
        assert "geometry_aware" in HEAT_TRANSFER_REGISTRY
        assert "dynamic" in HEAT_TRANSFER_REGISTRY

    def test_build_known_model(self):
        model = build_heat_transfer_model("constant")
        assert isinstance(model, ConstantUA)

    def test_build_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown heat transfer model"):
            build_heat_transfer_model("nonexistent")

    def test_register_custom_model(self):
        class Custom(HeatTransferModel):
            def compute_UA(self, state, thermal, geometry, fluid_mechanics):
                return 42.0

        register_heat_transfer_model("test_custom", Custom)
        assert "test_custom" in HEAT_TRANSFER_REGISTRY
        model = build_heat_transfer_model("test_custom")
        assert model.compute_UA(None, None, None, None) == 42.0
        del HEAT_TRANSFER_REGISTRY["test_custom"]
