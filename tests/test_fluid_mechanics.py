"""Unit tests for the fluid_mechanics module."""

import math
import pytest

from reactor.fluid_mechanics import (
    AgitatorParams,
    FluidMechanicsState,
    FluidProps,
    compute_fluid_mechanics,
    flow_regime,
    impeller_reynolds,
    jacket_htc,
    jacket_nusselt,
    mixing_efficiency,
    overall_htc,
    power_draw,
    prandtl_number,
)


@pytest.fixture
def rushton() -> AgitatorParams:
    """Standard Rushton turbine in a 0.50 m vessel."""
    return AgitatorParams(
        diameter_m=0.16,
        speed_rpm=120.0,
        power_number=5.0,
        impeller_type="rushton",
    )


@pytest.fixture
def thin_fluid() -> FluidProps:
    """Low-viscosity fluid (like water)."""
    return FluidProps(
        density=1000.0,
        viscosity=0.001,   # 1 mPa·s (water)
        thermal_conductivity=0.60,
        specific_heat=4180.0,
    )


@pytest.fixture
def thick_fluid() -> FluidProps:
    """High-viscosity fluid (gelling reactive mixture)."""
    return FluidProps(
        density=1150.0,
        viscosity=100.0,   # 100 Pa·s (very thick)
        thermal_conductivity=0.17,
        specific_heat=1800.0,
    )


class TestReynoldsNumber:
    def test_water_is_turbulent(self, rushton, thin_fluid):
        Re = impeller_reynolds(rushton, thin_fluid)
        assert Re > 10_000
        assert flow_regime(Re) == "turbulent"

    def test_thick_fluid_is_laminar(self, rushton, thick_fluid):
        Re = impeller_reynolds(rushton, thick_fluid)
        assert Re < 10
        assert flow_regime(Re) == "laminar"

    def test_scales_with_rpm(self, thin_fluid):
        a1 = AgitatorParams(diameter_m=0.16, speed_rpm=60.0)
        a2 = AgitatorParams(diameter_m=0.16, speed_rpm=120.0)
        Re1 = impeller_reynolds(a1, thin_fluid)
        Re2 = impeller_reynolds(a2, thin_fluid)
        assert pytest.approx(Re2 / Re1, rel=0.01) == 2.0

    def test_zero_viscosity(self, rushton):
        fluid = FluidProps(density=1000.0, viscosity=0.0)
        assert impeller_reynolds(rushton, fluid) == 0.0


class TestNusselt:
    def test_turbulent_nusselt_is_large(self):
        # Re=50000, Pr=7 (water-like)
        Nu = jacket_nusselt(50_000, 7.0)
        assert Nu > 100

    def test_zero_re_fallback(self):
        Nu = jacket_nusselt(0.0, 7.0)
        assert Nu == 1.0

    def test_prandtl_number(self, thin_fluid):
        Pr = prandtl_number(thin_fluid)
        # Water: Pr ≈ 4180 * 0.001 / 0.60 ≈ 6.97
        assert pytest.approx(Pr, rel=0.01) == 6.97


class TestOverallHTC:
    def test_wall_resistance_matters(self):
        U_thin = overall_htc(h_inside=500.0, wall_thickness=0.001)
        U_thick = overall_htc(h_inside=500.0, wall_thickness=0.010)
        assert U_thick < U_thin

    def test_glass_vs_steel(self):
        U_steel = overall_htc(h_inside=500.0, wall_conductivity=16.0)
        U_glass = overall_htc(h_inside=500.0, wall_conductivity=1.1)
        assert U_glass < U_steel

    def test_limiting_resistance(self):
        """With very low h_inside, U ≈ h_inside."""
        U = overall_htc(h_inside=5.0, h_jacket=10_000.0, wall_thickness=0.001)
        assert U < 5.5  # close to h_inside


class TestMixingEfficiency:
    def test_turbulent_near_one(self):
        eta = mixing_efficiency(100_000)
        assert eta > 0.95

    def test_laminar_low(self):
        eta = mixing_efficiency(1.0)
        assert eta < 0.25

    def test_monotonic(self):
        """Efficiency should increase with Re."""
        Re_values = [1, 10, 100, 1000, 10_000, 100_000]
        etas = [mixing_efficiency(Re) for Re in Re_values]
        for i in range(1, len(etas)):
            assert etas[i] >= etas[i - 1]

    def test_zero_re(self):
        eta = mixing_efficiency(0.0)
        assert eta == pytest.approx(0.20)  # eta_min (diffusion floor)


class TestPowerDraw:
    def test_rushton_power(self, rushton, thin_fluid):
        P = power_draw(rushton, thin_fluid)
        # P = 5.0 * 1000 * 2^3 * 0.16^5 ≈ 4.19 W
        expected = 5.0 * 1000.0 * (120 / 60)**3 * 0.16**5
        assert pytest.approx(P, rel=0.01) == expected

    def test_power_scales_with_cube_of_speed(self, thin_fluid):
        a1 = AgitatorParams(speed_rpm=60, diameter_m=0.16)
        a2 = AgitatorParams(speed_rpm=120, diameter_m=0.16)
        P1 = power_draw(a1, thin_fluid)
        P2 = power_draw(a2, thin_fluid)
        assert pytest.approx(P2 / P1, rel=0.01) == 8.0


class TestComputeFluidMechanics:
    def test_full_computation(self, rushton, thin_fluid):
        fm = compute_fluid_mechanics(
            agitator=rushton,
            fluid=thin_fluid,
            vessel_diameter=0.50,
            wetted_area=0.50,
        )
        assert isinstance(fm, FluidMechanicsState)
        assert fm.Re > 10_000
        assert fm.regime == "turbulent"
        assert fm.mixing_efficiency > 0.95
        assert fm.UA_dynamic > 0
        assert fm.UA_kW_per_K > 0

    def test_thick_fluid_low_efficiency(self, rushton, thick_fluid):
        fm = compute_fluid_mechanics(
            agitator=rushton,
            fluid=thick_fluid,
            vessel_diameter=0.50,
            wetted_area=0.50,
        )
        assert fm.mixing_efficiency < 0.3
        assert fm.regime == "laminar"

    def test_ua_scales_with_area(self, rushton, thin_fluid):
        fm1 = compute_fluid_mechanics(
            agitator=rushton, fluid=thin_fluid,
            vessel_diameter=0.50, wetted_area=0.25,
        )
        fm2 = compute_fluid_mechanics(
            agitator=rushton, fluid=thin_fluid,
            vessel_diameter=0.50, wetted_area=0.50,
        )
        assert pytest.approx(fm2.UA_dynamic / fm1.UA_dynamic, rel=0.01) == 2.0
