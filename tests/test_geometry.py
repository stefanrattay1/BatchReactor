"""Unit tests for the geometry module."""

import math
import pytest

from reactor.geometry import (
    CylindricalFlatBottom,
    CylindricalTorispherical,
    build_geometry,
)


class TestCylindricalFlatBottom:
    def test_vessel_volume(self):
        g = CylindricalFlatBottom(diameter_m=0.50, height_m=0.60)
        expected = math.pi * 0.25**2 * 0.60
        assert pytest.approx(g.vessel_volume, rel=1e-6) == expected

    def test_liquid_level_half_full(self):
        g = CylindricalFlatBottom(diameter_m=0.50, height_m=0.60)
        V_half = g.vessel_volume / 2
        h = g.liquid_level(V_half)
        assert pytest.approx(h, rel=1e-4) == 0.30

    def test_liquid_level_clamped(self):
        """Level should not exceed vessel height."""
        g = CylindricalFlatBottom(diameter_m=0.50, height_m=0.60)
        h = g.liquid_level(g.vessel_volume * 2)
        assert h == pytest.approx(0.60)

    def test_wetted_area_empty(self):
        g = CylindricalFlatBottom(diameter_m=0.50, height_m=0.60)
        A = g.wetted_area(0.0)
        # Only bottom disc is wetted
        assert pytest.approx(A, rel=1e-4) == math.pi * 0.25**2

    def test_wetted_area_full(self):
        g = CylindricalFlatBottom(diameter_m=0.50, height_m=0.60)
        A = g.wetted_area(g.vessel_volume)
        expected = math.pi * 0.25**2 + math.pi * 0.50 * 0.60
        assert pytest.approx(A, rel=1e-4) == expected

    def test_cross_section(self):
        g = CylindricalFlatBottom(diameter_m=0.40, height_m=0.50)
        assert pytest.approx(g.cross_section_area(), rel=1e-6) == math.pi * 0.20**2

    def test_aspect_ratio(self):
        g = CylindricalFlatBottom(diameter_m=0.50, height_m=1.00)
        assert pytest.approx(g.aspect_ratio()) == 2.0


class TestCylindricalTorispherical:
    def test_vessel_volume_larger_than_cylinder(self):
        """Volume should be larger than a plain cylinder of same dimensions."""
        D, H = 0.50, 0.60
        g = CylindricalTorispherical(diameter_m=D, height_m=H)
        V_cyl = math.pi * (D / 2)**2 * H
        assert g.vessel_volume > V_cyl

    def test_head_volume_approximation(self):
        """ASME F&D head volume should be approximately 0.0847 * D³."""
        D = 0.50
        g = CylindricalTorispherical(diameter_m=D, height_m=0.60)
        expected = 0.0847 * D**3
        assert pytest.approx(g._head_volume, rel=1e-3) == expected

    def test_liquid_level_full_head(self):
        g = CylindricalTorispherical(diameter_m=0.50, height_m=0.60)
        h = g.liquid_level(g._head_volume)
        assert pytest.approx(h, rel=1e-2) == g._head_depth

    def test_liquid_level_above_head(self):
        g = CylindricalTorispherical(diameter_m=0.50, height_m=0.60)
        V = g._head_volume + g.cross_section_area() * 0.30
        h = g.liquid_level(V)
        assert pytest.approx(h, rel=1e-2) == g._head_depth + 0.30

    def test_wetted_area_monotonically_increases(self):
        g = CylindricalTorispherical(diameter_m=0.50, height_m=0.60)
        volumes = [g.vessel_volume * f for f in [0.1, 0.3, 0.5, 0.7, 1.0]]
        areas = [g.wetted_area(V) for V in volumes]
        for i in range(1, len(areas)):
            assert areas[i] > areas[i - 1]


class TestBuildGeometry:
    def test_empty_config_returns_default(self):
        g = build_geometry({})
        assert isinstance(g, CylindricalFlatBottom)

    def test_flat_bottom_from_config(self):
        cfg = {"type": "cylindrical_flat", "diameter_m": 0.40, "height_m": 0.50}
        g = build_geometry(cfg)
        assert isinstance(g, CylindricalFlatBottom)
        assert g.diameter_m == 0.40

    def test_torispherical_from_config(self):
        cfg = {"type": "cylindrical_torispherical", "diameter_m": 0.50, "height_m": 0.60}
        g = build_geometry(cfg)
        assert isinstance(g, CylindricalTorispherical)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown geometry"):
            build_geometry({"type": "sphere"})

    def test_liquid_volume_helper(self):
        g = CylindricalFlatBottom(diameter_m=0.50, height_m=0.60)
        masses = {"water": 50.0}       # 50 kg
        densities = {"water": 1000.0}  # kg/m³
        V = g.liquid_volume_m3(masses, densities)
        assert pytest.approx(V) == 0.05  # 50 L = 0.05 m³
