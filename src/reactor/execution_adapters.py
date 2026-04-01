"""Control Module Execution Adapters.

Provides the interface and concrete implementations for connecting
Control Modules either to the ReactorModel (simulation) or to
physical OPC tags (physical execution).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .physics import ReactorModel
    from .sensor_buffer import SensorBuffer
    from .opc_mapping import OPCMappingManager


logger = logging.getLogger("reactor.execution_adapters")


class CMAdapter(ABC):
    """Base class for Control Module Execution Adapters."""

    @abstractmethod
    def write_output(self, key: str, value: Any, priority: int = 40) -> None:
        """Write a command or state to the underlying system.
        
        Args:
            key: The target mapping key (e.g. 'feed_component_a' or 'XV-101.Command').
            value: The value to write.
            priority: Only used in simulation (SensorBuffer priority).
        """

    @abstractmethod
    def read_input(self, key: str) -> Any | None:
        """Read a process value from the underlying system."""


class SimulationCMAdapter(CMAdapter):
    """Adapter for simulation: writes to SensorBuffer, reads from ReactorModel."""

    def __init__(
        self,
        model: ReactorModel,
        sensor_buffer: SensorBuffer,
        source_name: str,
    ):
        self._model = model
        self._sensor_buffer = sensor_buffer
        self._source_name = source_name

    def write_output(self, key: str, value: Any, priority: int = 40) -> None:
        if not key:
            return
        self._sensor_buffer.write(key, float(value), source=self._source_name, priority=priority)

    def read_input(self, key: str) -> float | None:
        if not key:
            return None

        aliases = {
            "temperature": "temperature_K",
            "temperature_k": "temperature_K",
            "jacket_temperature": "jacket_temperature_K",
            "jacket_temperature_k": "jacket_temperature_K",
            "mass_total": "mass_total_kg",
            "feed_component_a": "feed_rate_component_a",
            "feed_component_b": "feed_rate_component_b",
            "feed_solvent": "feed_rate_solvent",
            "viscosity": "viscosity_Pas",
        }
        canonical_key = aliases.get(str(key).strip().lower(), key)

        state = self._model.state
        if canonical_key == "temperature_K":
            return float(state.temperature)

        if canonical_key == "jacket_temperature_K":
            return float(state.jacket_temperature)

        if canonical_key == "mass_total_kg":
            return float(state.mass_total)

        if canonical_key in {
            "mass_component_a_kg",
            "mass_component_b_kg",
            "mass_product_kg",
            "mass_solvent_kg",
        }:
            species = canonical_key.removeprefix("mass_").removesuffix("_kg")
            return float(state.species_masses.get(species, 0.0))

        if canonical_key == "viscosity_Pas":
            try:
                return float(self._model.viscosity)
            except Exception:
                return None

        if canonical_key == "agitator_speed_rpm":
            try:
                return float(self._model._reactor_cfg.get("agitator_speed_rpm", 0.0))
            except Exception:
                return None

        if hasattr(state, canonical_key):
            return getattr(state, canonical_key)

        if canonical_key.startswith("feed_rate_"):
            species = canonical_key.replace("feed_rate_", "", 1)
            try:
                return float(self._model.get_feed_rate(species))
            except Exception:
                return None

        if canonical_key == "fill_pct":
            try:
                return float(self._model.fill_pct)
            except Exception:
                return None

        if canonical_key == "volume_L":
            try:
                return float(self._model.volume_L)
            except Exception:
                return None

        if canonical_key == "pressure_bar":
            try:
                return float(self._model.pressure_bar)
            except Exception:
                return None

        return None


class OpcCMAdapter(CMAdapter):
    """Adapter for physical equipment via OPC.
    
    Reads and writes are performed synchronously against an in-memory
    OPC cache that is serviced by a background I/O thread, avoiding
    blocking the execution engine.
    """

    def __init__(
        self,
        opc_cache: dict[str, Any],
        opc_write_queue: list[tuple[str, Any]],
        mapping_manager: OPCMappingManager | None = None,
    ):
        """
        Args:
            opc_cache: Shared dictionary containing the latest tag values.
            opc_write_queue: Shared list to enqueue (target_node, value) tuples.
            mapping_manager: To resolve logical keys to node IDs, if needed.
        """
        self._cache = opc_cache
        self._write_queue = opc_write_queue
        self._mapping_manager = mapping_manager

    def write_output(self, key: str, value: Any, priority: int = 40) -> None:
        if not key:
            return
        # If the key is already an OPC Node ID (assumed if it contains typically OPC chars like '=')
        # Otherwise, resolve it via mapping_manager if necessary, or treat it as command abstraction.
        # For now, we simply enqueue the raw key. OpcMapping logic handles mapping.
        self._write_queue.append((key, value))

    def read_input(self, key: str) -> Any | None:
        if not key:
            return None
        return self._cache.get(key)

