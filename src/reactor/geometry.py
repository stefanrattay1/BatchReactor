"""Reactor vessel geometry models.

Provides modular geometry calculations (wetted area, liquid level, etc.)
for different vessel shapes. Used by the physics engine to compute
geometry-dependent heat transfer and mixing parameters.

All geometry classes implement the ReactorGeometry protocol so they can
be swapped transparently.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ReactorGeometry(ABC):
    """Protocol for reactor vessel geometry.

    All volumes in m³, all lengths in m, all areas in m².
    """

    @property
    @abstractmethod
    def vessel_volume(self) -> float:
        """Total vessel volume in m³."""

    @property
    @abstractmethod
    def inner_diameter(self) -> float:
        """Inner diameter of the cylindrical section in m."""

    @abstractmethod
    def liquid_level(self, V_liquid: float) -> float:
        """Compute liquid level (height from bottom) given liquid volume.

        Args:
            V_liquid: Liquid volume in m³.

        Returns:
            Liquid level in m.
        """

    @abstractmethod
    def wetted_area(self, V_liquid: float) -> float:
        """Compute wetted wall area given liquid volume.

        This is the area through which jacket heat transfer occurs.

        Args:
            V_liquid: Liquid volume in m³.

        Returns:
            Wetted wall + bottom area in m².
        """

    @abstractmethod
    def cross_section_area(self) -> float:
        """Cross-sectional area of the cylindrical section in m²."""

    @abstractmethod
    def aspect_ratio(self) -> float:
        """Height-to-diameter ratio of the cylindrical section."""

    def liquid_volume_m3(self, species_masses: dict[str, float],
                         densities: dict[str, float]) -> float:
        """Compute total liquid volume from species masses and densities.

        Args:
            species_masses: Dict of species_name -> mass in kg.
            densities: Dict of species_name -> density in kg/m³.

        Returns:
            Total liquid volume in m³.
        """
        total = 0.0
        for sp, mass in species_masses.items():
            rho = densities.get(sp, 1000.0)  # default water density
            total += mass / rho
        return total


# ---------------------------------------------------------------------------
# Cylindrical tank with flat bottom
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CylindricalFlatBottom(ReactorGeometry):
    """Simple vertical cylinder with a flat bottom.

    Parameters:
        diameter_m: Inner diameter in metres.
        height_m: Straight-side (cylindrical) height in metres.
    """

    diameter_m: float = 0.50   # 500 mm
    height_m: float = 0.60     # 600 mm

    @property
    def vessel_volume(self) -> float:
        r = self.diameter_m / 2
        return math.pi * r**2 * self.height_m

    @property
    def inner_diameter(self) -> float:
        return self.diameter_m

    def cross_section_area(self) -> float:
        r = self.diameter_m / 2
        return math.pi * r**2

    def aspect_ratio(self) -> float:
        return self.height_m / self.diameter_m

    def liquid_level(self, V_liquid: float) -> float:
        A = self.cross_section_area()
        if A <= 0:
            return 0.0
        h = V_liquid / A
        return min(h, self.height_m)

    def wetted_area(self, V_liquid: float) -> float:
        r = self.diameter_m / 2
        h = self.liquid_level(V_liquid)
        # Bottom disc + cylindrical wall up to liquid level
        A_bottom = math.pi * r**2
        A_wall = math.pi * self.diameter_m * h
        return A_bottom + A_wall


# ---------------------------------------------------------------------------
# Cylindrical tank with torispherical bottom head
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CylindricalTorispherical(ReactorGeometry):
    """Vertical cylinder with a torispherical (dished) bottom head.

    Standard ASME F&D head: crown radius = D, knuckle radius = 0.06*D.

    Parameters:
        diameter_m: Inner diameter in metres.
        height_m: Straight-side (cylindrical) height in metres.
        head_depth_m: Depth of the torispherical dish (default: auto-calculated).
    """

    diameter_m: float = 0.50
    height_m: float = 0.60
    head_depth_m: float | None = None

    def __post_init__(self) -> None:
        if self.head_depth_m is None:
            # Standard ASME F&D head depth ≈ 0.1935 * D
            object.__setattr__(self, "head_depth_m", 0.1935 * self.diameter_m)

    @property
    def _head_depth(self) -> float:
        return self.head_depth_m or 0.1935 * self.diameter_m

    @property
    def _head_volume(self) -> float:
        """Approximate volume of the torispherical head.

        Uses ASME approximation: V_head ≈ 0.0847 * D³
        """
        D = self.diameter_m
        return 0.0847 * D**3

    @property
    def vessel_volume(self) -> float:
        r = self.diameter_m / 2
        V_cyl = math.pi * r**2 * self.height_m
        return V_cyl + self._head_volume

    @property
    def inner_diameter(self) -> float:
        return self.diameter_m

    def cross_section_area(self) -> float:
        r = self.diameter_m / 2
        return math.pi * r**2

    def aspect_ratio(self) -> float:
        total_h = self.height_m + self._head_depth
        return total_h / self.diameter_m

    def liquid_level(self, V_liquid: float) -> float:
        V_head = self._head_volume
        if V_liquid <= V_head:
            # Liquid is within the dished head — linearise for simplicity
            frac = V_liquid / V_head if V_head > 0 else 0.0
            return frac * self._head_depth
        # Above the head: remaining volume fills the cylinder
        V_cyl = V_liquid - V_head
        A = self.cross_section_area()
        h_cyl = V_cyl / A if A > 0 else 0.0
        return self._head_depth + min(h_cyl, self.height_m)

    def wetted_area(self, V_liquid: float) -> float:
        r = self.diameter_m / 2
        V_head = self._head_volume

        # Head surface area (approximate): A_head ≈ 0.9314 * D²
        A_head_full = 0.9314 * self.diameter_m**2

        if V_liquid <= V_head:
            # Partially filled head — scale area linearly with volume fraction
            frac = V_liquid / V_head if V_head > 0 else 0.0
            return frac * A_head_full

        # Full head + cylindrical wall
        V_cyl = V_liquid - V_head
        A = self.cross_section_area()
        h_cyl = V_cyl / A if A > 0 else 0.0
        h_cyl = min(h_cyl, self.height_m)

        A_wall = math.pi * self.diameter_m * h_cyl
        return A_head_full + A_wall


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------

_GEOMETRY_REGISTRY: dict[str, type[ReactorGeometry]] = {
    "cylindrical_flat": CylindricalFlatBottom,
    "cylindrical_torispherical": CylindricalTorispherical,
}


def register_geometry(name: str, cls: type[ReactorGeometry]) -> None:
    """Register a custom geometry class for use in YAML configs."""
    _GEOMETRY_REGISTRY[name] = cls


def build_geometry(config: dict) -> ReactorGeometry:
    """Build a ReactorGeometry instance from a config dict.

    Config format::

        geometry:
          type: cylindrical_torispherical
          diameter_m: 0.50
          height_m: 0.60

    If no config or empty dict is supplied, returns a default
    CylindricalFlatBottom sized to match the legacy 100 L vessel.

    Args:
        config: Geometry configuration dict.

    Returns:
        A ReactorGeometry instance.

    Raises:
        ValueError: If the geometry type is not recognised.
    """
    if not config:
        # Default: size a flat-bottom cylinder to hold ~100 L
        # D=0.50 m, H=0.51 m gives ~100 L
        return CylindricalFlatBottom(diameter_m=0.50, height_m=0.51)

    geo_type = config.get("type", "cylindrical_flat")
    cls = _GEOMETRY_REGISTRY.get(geo_type)
    if cls is None:
        raise ValueError(
            f"Unknown geometry type '{geo_type}'. "
            f"Available: {list(_GEOMETRY_REGISTRY.keys())}"
        )

    # Pass all keys except 'type' to the constructor
    kwargs = {k: v for k, v in config.items() if k != "type"}
    return cls(**kwargs)
