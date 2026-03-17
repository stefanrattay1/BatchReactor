"""Batch (offline) simulation mode: runs to completion without real-time pacing."""

from __future__ import annotations

import copy
import csv
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit_trail import AuditTrail, build_state_snapshot
from .batch_state import BatchCommand, BatchState, BatchStateMachine
from .alarm_management import AlarmManager
from .config import ModelConfig, Settings
from .controller import BatchController, Phase
from .em_manager import EMManager
from .execution_adapters import CMAdapter, SimulationCMAdapter
from .physics import ReactorModel, ReactorState
from .procedure import Procedure, ProcedurePlayer, load_procedure
from .recipe import load_recipe  # kept for backward compat (sweep callers may import it)
from .sensor_buffer import SensorBuffer
from .test_inputs import TestInputPlayer

logger = logging.getLogger("reactor.batch")

_FEED_ZERO_THRESHOLD = 1e-9  # kg/s — rates below this are treated as "off"


def build_csv_header(model: ReactorModel) -> list[str]:
    """Build CSV header dynamically from the reaction network species."""
    species = model.network.species_names
    conversions = model.network.conversion_names
    header = ["elapsed", "dt", "wall_ms", "solve_method",
              "temperature_K", "jacket_temperature_K", "recipe_jacket_K", "actual_jacket_K"]
    for c in conversions:
        header.append(f"conversion_{c}")
    for s in species:
        header.append(f"mass_{s}_kg")
    header.append("mass_total_kg")
    for s in species:
        header.append(f"feed_{s}_kgs")
    header.extend(["viscosity_Pas", "pressure_bar", "phase", "recipe_step",
                    "operation_name", "override_source", "data_mode", "fake_sensors_active",
                    "batch_state"])
    return header


@dataclass
class BatchResult:
    """Summary of a completed batch simulation."""

    csv_path: str
    total_time_s: float
    wall_time_s: float
    final_temperature_K: float
    final_conversions: dict[str, float]
    final_phase: str
    total_ticks: int
    final_masses: dict[str, float]
    peak_temperature_K: float
    parameter_set: str = ""
    record_path: str = ""
    batch_exceptions: list[dict[str, Any]] = field(default_factory=list)
    batch_number: str = ""
    lot_number: str = ""

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("  BATCH SIMULATION COMPLETE")
        print("=" * 60)
        print(f"  Simulated time : {self.total_time_s:,.1f} s ({self.total_time_s / 60:.1f} min)")
        print(f"  Wall-clock time: {self.wall_time_s:.1f} s")
        print(f"  Speedup        : {self.total_time_s / max(self.wall_time_s, 0.001):.0f}x real-time")
        print(f"  Total ticks    : {self.total_ticks:,}")
        print(f"  Final phase    : {self.final_phase}")
        print(f"  Final temp     : {self.final_temperature_K:.1f} K ({self.final_temperature_K - 273.15:.1f} C)")
        print(f"  Peak temp      : {self.peak_temperature_K:.1f} K ({self.peak_temperature_K - 273.15:.1f} C)")
        for name, val in self.final_conversions.items():
            print(f"  Conversion {name}: {val:.4f}")
        print(f"  CSV log        : {self.csv_path}")
        print("=" * 60 + "\n")

    def to_dict(self) -> dict[str, Any]:
        return {
            "csv_path": str(self.csv_path),
            "total_time_s": round(self.total_time_s, 2),
            "wall_time_s": round(self.wall_time_s, 2),
            "speedup": round(self.total_time_s / max(self.wall_time_s, 0.001), 1),
            "final_temperature_K": round(self.final_temperature_K, 2),
            "final_temperature_C": round(self.final_temperature_K - 273.15, 2),
            "final_conversions": {k: round(v, 4) for k, v in self.final_conversions.items()},
            "final_phase": self.final_phase,
            "total_ticks": self.total_ticks,
            "final_masses": {k: round(v, 2) for k, v in self.final_masses.items()},
            "peak_temperature_K": round(self.peak_temperature_K, 2),
            "peak_temperature_C": round(self.peak_temperature_K - 273.15, 2),
            "parameter_set": self.parameter_set,
            "record_path": self.record_path,
            "batch_exceptions": self.batch_exceptions,
            "batch_number": self.batch_number,
            "lot_number": self.lot_number,
        }


@dataclass
class BatchExceptionRecord:
    timestamp_s: float
    category: str
    code: str
    message: str
    severity: str = "warning"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_s": round(self.timestamp_s, 2),
            "category": self.category,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class MaterialSpec:
    """Vendor/source traceability data for a single material input."""

    material_id: str = ""
    lot_number: str = ""
    vendor: str = ""
    grade: str = ""
    cas_number: str = ""
    notes: str = ""
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "lot_number": self.lot_number,
            "vendor": self.vendor,
            "grade": self.grade,
            "cas_number": self.cas_number,
            "notes": self.notes,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialSpec:
        return cls(
            material_id=str(data.get("material_id", "")),
            lot_number=str(data.get("lot_number", "")),
            vendor=str(data.get("vendor", "")),
            grade=str(data.get("grade", "")),
            cas_number=str(data.get("cas_number", "")),
            notes=str(data.get("notes", "")),
            properties=dict(data.get("properties", {})),
        )


@dataclass
class BatchIdentity:
    """ISA-88 Chapter 6 batch identification and material traceability."""

    batch_number: str = ""
    lot_number: str = ""
    product_code: str = ""
    material_ids: dict[str, str] = field(default_factory=dict)
    material_specs: dict[str, MaterialSpec] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_number": self.batch_number,
            "lot_number": self.lot_number,
            "product_code": self.product_code,
            "material_ids": dict(self.material_ids),
            "material_specs": {
                sp: spec.to_dict() for sp, spec in self.material_specs.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BatchIdentity:
        if not isinstance(data, dict):
            return cls()
        raw_specs = data.get("material_specs") or {}
        specs = {
            sp: MaterialSpec.from_dict(v if isinstance(v, dict) else {})
            for sp, v in raw_specs.items()
        }
        return cls(
            batch_number=str(data.get("batch_number", "")),
            lot_number=str(data.get("lot_number", "")),
            product_code=str(data.get("product_code", "")),
            material_ids={k: str(v) for k, v in (data.get("material_ids") or {}).items()},
            material_specs=specs,
        )


@dataclass
class FlowEvent:
    """Timestamped record of a material feed or discharge flow."""

    event_type: str       # "feed" | "discharge"
    species: str          # species key, or "ALL" for discharge
    start_time_s: float
    end_time_s: float
    mass_kg: float
    avg_rate_kgs: float
    material_id: str = ""
    lot_number: str = ""
    phase_name: str = ""
    operation_name: str = ""
    open: bool = False    # True if feed was still active at batch end

    def to_dict(self) -> dict[str, Any]:
        duration = max(self.end_time_s - self.start_time_s, 0.0)
        return {
            "event_type": self.event_type,
            "species": self.species,
            "start_time_s": round(self.start_time_s, 2),
            "end_time_s": round(self.end_time_s, 2),
            "duration_s": round(duration, 2),
            "mass_kg": round(self.mass_kg, 4),
            "avg_rate_kgs": round(self.avg_rate_kgs, 6),
            "material_id": self.material_id,
            "lot_number": self.lot_number,
            "phase_name": self.phase_name,
            "operation_name": self.operation_name,
            "open": self.open,
        }


@dataclass
class BatchDataRecord:
    batch_id: str
    recipe_name: str
    parameter_set: str
    started_at: str
    completed_at: str
    status: str
    stop_reason: str
    total_ticks: int
    total_time_s: float
    wall_time_s: float
    exceptions: list[BatchExceptionRecord] = field(default_factory=list)
    phase_events: list[dict[str, Any]] = field(default_factory=list)
    parameterization: dict[str, Any] = field(default_factory=dict)
    final_batch_state: str = "IDLE"
    batch_state_history: list[dict[str, Any]] = field(default_factory=list)
    identity: BatchIdentity = field(default_factory=BatchIdentity)
    input_materials: dict[str, float] = field(default_factory=dict)
    output_materials: dict[str, float] = field(default_factory=dict)
    flow_events: list[FlowEvent] = field(default_factory=list)
    alarm_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "recipe_name": self.recipe_name,
            "parameter_set": self.parameter_set,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "total_ticks": self.total_ticks,
            "total_time_s": round(self.total_time_s, 2),
            "wall_time_s": round(self.wall_time_s, 3),
            "exceptions": [e.to_dict() for e in self.exceptions],
            "phase_events": self.phase_events,
            "parameterization": self.parameterization,
            "final_batch_state": self.final_batch_state,
            "batch_state_history": self.batch_state_history,
            "identity": self.identity.to_dict(),
            "input_materials": {k: round(v, 4) for k, v in self.input_materials.items()},
            "output_materials": {k: round(v, 4) for k, v in self.output_materials.items()},
            "flow_events": [e.to_dict() for e in self.flow_events],
            "alarm_history": self.alarm_history,
        }


def _build_alarm_snapshot(
    *,
    elapsed: float,
    model: ReactorModel,
    controller: BatchController,
    batch_sm: BatchStateMachine,
    player: ProcedurePlayer,
) -> dict[str, Any]:
    return {
        "elapsed_s": round(float(elapsed), 3),
        "temperature_K": round(float(model.state.temperature), 4),
        "jacket_temperature_K": round(float(model.state.jacket_temperature), 4),
        "conversion": round(float(model.state.conversion), 6),
        "controller_phase": controller.phase.name,
        "batch_state": batch_sm.state.value,
        "recipe_step": player.current_step.name if player.current_step else "DONE",
        "operation_name": player.current_operation_name or "DONE",
    }

class BatchRunner:
    """Runs a batch simulation with progress tracking for the web UI."""

    def __init__(self) -> None:
        self.status: str = "idle"  # idle, running, completed, error, cancelled
        self.progress: dict[str, Any] = {}
        self.result: BatchResult | None = None
        self.error_message: str = ""
        self._cancel_flag = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def cancel(self) -> None:
        self._cancel_flag.set()

    def start_in_thread(self, settings: Settings) -> None:
        """Launch the batch run in a background thread."""
        if self.is_running:
            raise RuntimeError("Batch is already running")
        self._cancel_flag.clear()
        self.status = "running"
        self.result = None
        self.error_message = ""
        self.progress = {}
        self._thread = threading.Thread(target=self._run, args=(settings,), daemon=True)
        self._thread.start()

    def _run(self, settings: Settings) -> None:
        try:
            result = _run_batch_impl(settings, self.progress, self._cancel_flag)
            if self._cancel_flag.is_set():
                self.status = "cancelled"
            else:
                self.status = "completed"
            self.result = result
        except Exception as e:
            logger.exception("Batch run failed")
            self.status = "error"
            self.error_message = str(e)

    def get_status_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            **self.progress,
        }
        if self.result is not None:
            d["result"] = self.result.to_dict()
        if self.error_message:
            d["error"] = self.error_message
        return d


@dataclass
class SweepConfig:
    """Configuration for a parametric sensitivity sweep.

    Runs one full batch simulation per value in ``values``, varying a single
    parameter specified by ``param_path`` (dot-notation into the YAML config).

    Common paths::

        "kinetics.A2"                       # pre-exponential factor
        "kinetics.Ea2"                      # activation energy (J/mol)
        "thermal.Cp"                        # specific heat (kJ/kg·K)
        "thermal.UA"                        # heat transfer coefficient (kW/K)
        "initial_conditions.temperature"    # initial reactor temperature (K)
    """

    param_path: str
    values: list[float]


@dataclass
class SweepResult:
    """Result for one parameter value in a sweep run."""

    param_value: float
    result: BatchResult | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"param_value": self.param_value}
        if self.result is not None:
            d.update(self.result.to_dict())
        if self.error:
            d["error"] = self.error
        return d


def _apply_config_override(raw: dict, path: str, value: Any) -> dict:
    """Deep-copy *raw* and set the nested key identified by dot-notation *path*.

    Example::

        _apply_config_override(cfg, "kinetics.A2", 1e9)
        # equivalent to: cfg["kinetics"]["A2"] = 1e9
    """
    data = copy.deepcopy(raw)
    keys = path.split(".")
    node = data
    for k in keys[:-1]:
        if k not in node or not isinstance(node[k], dict):
            node[k] = {}
        node = node[k]
    node[keys[-1]] = value
    return data


def _apply_batch_parameter_set(
    model_cfg: ModelConfig,
    procedure: Procedure,
    settings: Settings,
    parameter_set_name: str,
) -> tuple[ModelConfig, Procedure, dict[str, Any]]:
    """Apply runtime batch parameterization to model config and procedure.

    Parameter sets are expected under ``batch_parameter_sets`` in model config.
    Supported keys per set:
      - target_mass_kg: float
      - feed_scale: float (optional, auto-derived from target/base mass)
      - duration_scale: float
      - phase_duration_scales: {phase_name: float}
      - profile_scales: {channel: float}
      - model_overrides: {"path.to.key": value}
    """
    if not parameter_set_name:
        return model_cfg, procedure, {"applied": False}

    all_sets = model_cfg.raw.get("batch_parameter_sets", {})
    if not isinstance(all_sets, dict) or parameter_set_name not in all_sets:
        raise ValueError(f"Unknown batch parameter set: {parameter_set_name}")

    param_set = all_sets[parameter_set_name]
    if not isinstance(param_set, dict):
        raise ValueError(f"Invalid batch parameter set format: {parameter_set_name}")

    base_mass = float(settings.batch_mass_kg)
    target_mass = float(param_set.get("target_mass_kg", base_mass))
    derived_feed_scale = target_mass / base_mass if base_mass > 0 else 1.0
    feed_scale = float(param_set.get("feed_scale", derived_feed_scale))
    duration_scale = float(param_set.get("duration_scale", 1.0))
    phase_duration_scales = param_set.get("phase_duration_scales", {}) or {}
    profile_scales = param_set.get("profile_scales", {}) or {}

    procedure_scaled = copy.deepcopy(procedure)
    for phase in procedure_scaled.phases_flat:
        phase_factor = float(phase_duration_scales.get(phase.name, 1.0))
        phase.duration = max(0.001, phase.duration * duration_scale * phase_factor)
        for channel, profile in phase.profiles.items():
            channel_factor = profile_scales.get(channel)
            if channel_factor is None and channel.startswith("feed_"):
                channel_factor = feed_scale
            if channel_factor is not None:
                factor = float(channel_factor)
                profile.start_value *= factor
                profile.end_value *= factor
            profile.duration = phase.duration

    raw_scaled = copy.deepcopy(model_cfg.raw)
    model_overrides = param_set.get("model_overrides", {}) or {}
    for path, value in model_overrides.items():
        raw_scaled = _apply_config_override(raw_scaled, str(path), value)
    model_cfg_scaled = ModelConfig.from_dict(raw_scaled)

    summary = {
        "applied": True,
        "name": parameter_set_name,
        "base_mass_kg": round(base_mass, 4),
        "target_mass_kg": round(target_mass, 4),
        "feed_scale": round(feed_scale, 6),
        "duration_scale": round(duration_scale, 6),
        "profile_scales": profile_scales,
        "phase_duration_scales": phase_duration_scales,
        "model_overrides": model_overrides,
    }
    return model_cfg_scaled, procedure_scaled, summary


class SweepRunner:
    """Runs a parametric sweep: one batch per parameter value, in parallel."""

    def __init__(self) -> None:
        self.status: str = "idle"
        self.results: list[SweepResult] = []
        self.progress: dict[str, Any] = {}
        self.error_message: str = ""
        self._cancel_flag = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def cancel(self) -> None:
        self._cancel_flag.set()

    def start_in_thread(
        self,
        settings: Settings,
        sweep_cfg: SweepConfig,
        max_workers: int = 4,
    ) -> None:
        if self.is_running:
            raise RuntimeError("Sweep is already running")
        self._cancel_flag.clear()
        self.status = "running"
        self.results = []
        self.error_message = ""
        self.progress = {"completed": 0, "total": len(sweep_cfg.values)}
        self._thread = threading.Thread(
            target=self._run,
            args=(settings, sweep_cfg, max_workers),
            daemon=True,
        )
        self._thread.start()

    def _run(self, settings: Settings, sweep_cfg: SweepConfig, max_workers: int) -> None:
        try:
            self.results = run_sweep(
                settings, sweep_cfg, max_workers=max_workers,
                progress=self.progress, cancel_flag=self._cancel_flag,
            )
            self.status = "cancelled" if self._cancel_flag.is_set() else "completed"
        except Exception as e:
            logger.exception("Sweep run failed")
            self.status = "error"
            self.error_message = str(e)

    def get_status_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status, **self.progress}
        if self.results:
            d["results"] = [r.to_dict() for r in self.results]
        if self.error_message:
            d["error"] = self.error_message
        return d


def run_sweep(
    settings: Settings,
    sweep_cfg: SweepConfig,
    *,
    max_workers: int = 4,
    progress: dict[str, Any] | None = None,
    cancel_flag: threading.Event | None = None,
) -> list[SweepResult]:
    """Run a parametric sweep synchronously, returning results for each value.

    Each value in ``sweep_cfg.values`` triggers an independent batch run with
    the parameter at ``sweep_cfg.param_path`` overridden to that value.
    Runs are executed in parallel using a thread pool.

    Args:
        settings: Base settings (config file path, recipe, tick interval, etc.).
        sweep_cfg: Which parameter to sweep and over which values.
        max_workers: Maximum parallel batch runs.
        progress: Optional dict updated with ``{"completed": N, "total": M}``.
        cancel_flag: Optional event; sets early-stop on all pending runs.

    Returns:
        List of SweepResult in the same order as ``sweep_cfg.values``.
    """
    project_root = Path(__file__).parent.parent.parent
    cfg_path = Path(settings.model_config_file)
    if not cfg_path.is_absolute():
        cfg_path = project_root / cfg_path

    from .config import load_data_file
    base_raw = load_data_file(cfg_path)

    n = len(sweep_cfg.values)
    sweep_results: list[SweepResult | None] = [None] * n

    def _run_one(idx: int, value: float) -> tuple[int, SweepResult]:
        if cancel_flag is not None and cancel_flag.is_set():
            return idx, SweepResult(param_value=value, error="cancelled")
        modified_raw = _apply_config_override(base_raw, sweep_cfg.param_path, value)
        model_cfg = ModelConfig.from_dict(modified_raw)
        try:
            result = _run_batch_impl(settings, {}, cancel_flag, model_cfg=model_cfg)
            return idx, SweepResult(param_value=value, result=result)
        except Exception as exc:
            logger.warning("Sweep point %s=%s failed: %s", sweep_cfg.param_path, value, exc)
            return idx, SweepResult(param_value=value, error=str(exc))

    completed = 0
    if progress is not None:
        progress.update({"completed": 0, "total": n})

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, i, v): i for i, v in enumerate(sweep_cfg.values)}
        for fut in as_completed(futures):
            idx, sr = fut.result()
            sweep_results[idx] = sr
            completed += 1
            if progress is not None:
                progress["completed"] = completed

    return [r for r in sweep_results if r is not None]


def run_batch(settings: Settings) -> BatchResult:
    """Run a complete batch simulation synchronously (for CLI use)."""
    progress: dict[str, Any] = {}
    return _run_batch_impl(settings, progress, cancel_flag=None)


def _run_batch_impl(
    settings: Settings,
    progress: dict[str, Any],
    cancel_flag: threading.Event | None,
    *,
    model_cfg: ModelConfig | None = None,
) -> BatchResult:
    """Core batch simulation loop."""
    project_root = Path(__file__).parent.parent.parent
    started_at = datetime.now()
    batch_id = started_at.strftime("%Y%m%d_%H%M%S")

    # --- Load model config (or use pre-built override for sweep runs) ---
    if model_cfg is None:
        cfg_path = Path(settings.model_config_file)
        if not cfg_path.is_absolute():
            cfg_path = project_root / cfg_path
        model_cfg = ModelConfig.from_file(cfg_path)

    # --- Initialise physics model ---
    ic = model_cfg.initial_conditions
    reactor_cfg = model_cfg.reactor
    initial_state = ReactorState(
        temperature=ic.get("temperature", settings.initial_temp_k),
        jacket_temperature=ic.get("jacket_temperature", settings.initial_temp_k),
        volume=reactor_cfg.get("volume_m3", 0.1),
    )
    model = ReactorModel(model_config=model_cfg, initial_state=initial_state)

    # --- Material/Batch Identity (ISA-88 Ch. 6) ---
    identity = BatchIdentity.from_dict(settings.batch_identity)
    if not identity.batch_number:
        identity.batch_number = f"BN-{started_at:%Y%m%d-%H%M%S}"
    if not identity.lot_number:
        identity.lot_number = f"LOT-{started_at:%Y%m%d-%H%M%S}"

    # Merge default material specs from config YAML (runtime values take priority)
    config_materials = model_cfg.materials
    for species_key, spec_data in config_materials.items():
        if isinstance(spec_data, dict):
            if species_key not in identity.material_specs:
                identity.material_specs[species_key] = MaterialSpec.from_dict(spec_data)
            if species_key not in identity.material_ids and spec_data.get("material_id"):
                identity.material_ids[species_key] = str(spec_data["material_id"])

    input_materials: dict[str, float] = dict(model.state.species_masses)

    # --- Load recipe as ISA-88 Procedure ---
    recipe_path = Path(settings.recipe_file)
    if not recipe_path.is_absolute():
        recipe_path = project_root / recipe_path
    procedure = load_procedure(recipe_path)

    parameter_set_name = str(getattr(settings, "batch_parameter_set", "") or "")
    parameterization_summary: dict[str, Any] = {"applied": False}
    if parameter_set_name:
        model_cfg, procedure, parameterization_summary = _apply_batch_parameter_set(
            model_cfg, procedure, settings, parameter_set_name,
        )

    player = ProcedurePlayer(procedure)

    # --- Load test inputs (optional) ---
    test_player: TestInputPlayer | None = None
    if settings.test_inputs_file:
        ti_path = Path(settings.test_inputs_file)
        if not ti_path.is_absolute():
            ti_path = project_root / ti_path
        test_player = TestInputPlayer.from_yaml(ti_path)

    # --- Controller ---
    dt = settings.tick_interval
    controller = BatchController(model, controller_cfg=model_cfg.controller)
    controller.recipe_player = player
    controller._dt = dt

    # --- Equipment Module Manager (optional ISA-88 layer) ---
    sensor_buffer: SensorBuffer | None = None
    em_manager: EMManager | None = None
    if model_cfg.has_equipment:
        sensor_buffer = SensorBuffer()

        def _sim_adapter_factory(cm_tag: str, em_tag: str) -> CMAdapter:
            src = f"em:{em_tag}" if em_tag else f"cm:{cm_tag}"
            return SimulationCMAdapter(model, sensor_buffer, src)

        em_manager = EMManager(
            equipment_cfg=model_cfg.equipment,
            adapter_factory=_sim_adapter_factory,
        )

    # --- Audit trail ---
    audit_log_path = log_dir / f"audit_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    audit_trail: AuditTrail | None = None
    if getattr(settings, "audit_trail_enabled", True):
        audit_trail = AuditTrail(
            log_path=audit_log_path,
            enable_hash_chain=getattr(settings, "audit_trail_hash_chain", True),
        )

    # --- ISA-88 Batch State Machine ---
    def _on_batch_transition(record: dict) -> None:
        if audit_trail is None:
            return
        audit_trail.emit(
            event_type="batch_state_transition",
            source="batch_state",
            actor="system",
            action="dispatch",
            subject="batch_state",
            details=record,
            elapsed_s=record.get("at_s", 0.0),
            state_snapshot=build_state_snapshot(
                elapsed=record.get("at_s", 0.0),
                model=model, controller=controller,
                batch_sm=batch_sm, player=player,
                em_manager=em_manager,
            ) if started else None,
        )

    batch_sm = BatchStateMachine(on_transition=_on_batch_transition)
    alarm_manager = AlarmManager.from_equipment_config(model_cfg.equipment if model_cfg.has_equipment else {})

    # --- CSV ---
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    csv_path = log_dir / f"batch_{datetime.now():%Y%m%d_%H%M%S}.csv"
    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(build_csv_header(model))

    # --- Config ---
    post_recipe_time = settings.batch_post_recipe_time
    stop_conversion = settings.batch_stop_conversion
    max_time = procedure.total_duration + settings.batch_max_overtime
    total_estimate = procedure.total_duration + post_recipe_time

    # --- Initial progress ---
    progress.update({
        "elapsed": 0.0,
        "total_estimate": total_estimate,
        "pct_complete": 0.0,
        "temperature": initial_state.temperature,
        "conversion": 0.0,
        "phase": "IDLE",
        "recipe_name": procedure.name,
        "parameter_set": parameter_set_name,
        "operation_name": player.current_operation_name or "IDLE",
        "batch_state": batch_sm.state.value,
    })

    logger.info("Batch mode: recipe=%s (%.0fs, %d phases), dt=%.2fs",
                procedure.name, procedure.total_duration,
                len(procedure.phases_flat), dt)

    elapsed = 0.0
    started = False
    peak_temp = initial_state.temperature
    wall_start = time.monotonic()
    ticks = 0
    stop_reason = "completed"
    batch_exceptions: list[BatchExceptionRecord] = []
    phase_events: list[dict[str, Any]] = []
    last_phase_idx = player.current_phase_idx
    last_controller_phase = controller.phase
    _active_feeds: dict[str, dict[str, Any]] = {}
    flow_events: list[FlowEvent] = []
    _discharge_recorded = False

    def add_exception(
        *,
        category: str,
        code: str,
        message: str,
        severity: str = "warning",
        details: dict[str, Any] | None = None,
    ) -> None:
        batch_exceptions.append(BatchExceptionRecord(
            timestamp_s=elapsed,
            category=category,
            code=code,
            message=message,
            severity=severity,
            details=details or {},
        ))

    try:
        while True:
            # --- Check cancellation ---
            if cancel_flag is not None and cancel_flag.is_set():
                logger.info("Batch cancelled at t=%.0fs", elapsed)
                stop_reason = "cancelled"
                break

            # --- Test input processing ---
            if test_player is not None:
                for event in test_player.due_events(elapsed):
                    if event.action == "command":
                        cmd = str(event.value).upper()
                        if cmd == "START" and batch_sm.state == BatchState.IDLE:
                            batch_sm.dispatch(BatchCommand.START, elapsed)
                            controller.start_recipe()
                            started = True
                        elif cmd == "HOLD":
                            batch_sm.dispatch(BatchCommand.HOLD, elapsed)
                        elif cmd == "RESTART":
                            batch_sm.dispatch(BatchCommand.RESTART, elapsed)
                        elif cmd == "ABORT":
                            batch_sm.dispatch(BatchCommand.ABORT, elapsed)
                        elif cmd == "RESET":
                            controller.reset_alarm()
                        elif cmd == "STOP":
                            batch_sm.dispatch(BatchCommand.STOP, elapsed)
                            controller.stop()
                            started = False
                    elif event.action == "set_jacket":
                        model.state.jacket_temperature = float(event.value)
                    elif event.action == "clear_jacket":
                        pass

            # --- Auto-start ---
            if not started and batch_sm.state == BatchState.IDLE:
                batch_sm.dispatch(BatchCommand.START, elapsed)
                controller.start_recipe()
                started = True

            # --- Recipe (only tick procedure in RUNNING state) ---
            setpoints: dict[str, Any] = {}
            if batch_sm.is_procedure_active and not player.finished:
                tick_context: dict[str, Any] = {
                    "conversion": float(model.state.conversion),
                    "temperature_K": float(model.state.temperature),
                }
                if em_manager is not None:
                    tick_context["em_status"] = em_manager.get_mode_snapshot()

                setpoints = player.tick(dt, context=tick_context)
                if "jacket_temp" in setpoints:
                    model.state.jacket_temperature = setpoints["jacket_temp"]
                for sp_name in model.network.species_names:
                    key = f"feed_{sp_name}"
                    model.set_feed_rate(sp_name, setpoints.get(key, 0.0))
            else:
                # HELD, STOPPED, or recipe finished: zero all feeds
                for sp_name in model.network.species_names:
                    model.set_feed_rate(sp_name, 0.0)

            # --- Feed/discharge flow tracking (ISA-88 Ch. 6) ---
            for sp_name in model.network.species_names:
                rate = model.get_feed_rate(sp_name)
                if sp_name in _active_feeds:
                    if rate > _FEED_ZERO_THRESHOLD:
                        _active_feeds[sp_name]["accumulated_mass_kg"] += rate * dt
                    else:
                        entry = _active_feeds.pop(sp_name)
                        duration = elapsed - entry["start_time_s"]
                        flow_events.append(FlowEvent(
                            event_type="feed", species=sp_name,
                            start_time_s=entry["start_time_s"], end_time_s=elapsed,
                            mass_kg=entry["accumulated_mass_kg"],
                            avg_rate_kgs=entry["accumulated_mass_kg"] / max(duration, dt),
                            material_id=identity.material_ids.get(sp_name, ""),
                            lot_number=(identity.material_specs[sp_name].lot_number
                                        if sp_name in identity.material_specs else ""),
                            phase_name=entry["phase_name"],
                            operation_name=entry["operation_name"],
                        ))
                elif rate > _FEED_ZERO_THRESHOLD:
                    _active_feeds[sp_name] = {
                        "start_time_s": elapsed,
                        "accumulated_mass_kg": rate * dt,
                        "phase_name": player.current_step.name if player.current_step else "UNKNOWN",
                        "operation_name": player.current_operation_name or "UNKNOWN",
                    }

            if not _discharge_recorded:
                _cur_phase = player.current_step.name if player.current_step else ""
                if "DISCHARGE" in _cur_phase.upper():
                    flow_events.append(FlowEvent(
                        event_type="discharge", species="ALL",
                        start_time_s=elapsed, end_time_s=elapsed,
                        mass_kg=model.state.mass_total, avg_rate_kgs=0.0,
                        phase_name=_cur_phase,
                        operation_name=player.current_operation_name or "UNKNOWN",
                    ))
                    _discharge_recorded = True

            # --- EM/CM layer ---
            if em_manager is not None:
                em_manager.dispatch_recipe_modes(setpoints if batch_sm.is_procedure_active and not player.finished else {})
                em_manager.tick(dt)
                for event in em_manager.consume_events():
                    if event.get("type") == "mode_request_rejected":
                        add_exception(
                            category="EM_INTERLOCK",
                            code=str(event.get("reason", "mode_request_rejected")),
                            message=(
                                f"Mode request rejected for {event.get('em_tag')} -> "
                                f"{event.get('mode_name')}"
                            ),
                            details=event,
                        )
                    if audit_trail is not None:
                        audit_trail.emit(
                            event_type=f"em_{event.get('type', 'event')}",
                            source="em_manager",
                            actor="system",
                            action=event.get("type", "event"),
                            subject=f"em:{event.get('em_tag', '?')}",
                            details=event,
                            elapsed_s=elapsed,
                        )
                if sensor_buffer is not None:
                    sensor_buffer.apply_to_state(model.state)

            if player.current_phase_idx != last_phase_idx:
                from_name = (
                    procedure.phases_flat[last_phase_idx].name
                    if 0 <= last_phase_idx < len(procedure.phases_flat)
                    else "START"
                )
                to_name = player.current_step.name if player.current_step else "DONE"
                phase_events.append({
                    "timestamp_s": round(elapsed, 2),
                    "from_phase": from_name,
                    "to_phase": to_name,
                    "operation": player.current_operation_name or "DONE",
                })
                if audit_trail is not None:
                    audit_trail.emit(
                        event_type="recipe_phase_transition",
                        source="procedure",
                        actor="system",
                        action="transition",
                        subject="recipe_phase",
                        details={
                            "from_phase": from_name,
                            "to_phase": to_name,
                            "operation": player.current_operation_name or "DONE",
                            "phase_idx": player.current_phase_idx,
                        },
                        elapsed_s=elapsed,
                        state_snapshot=build_state_snapshot(
                            elapsed=elapsed, model=model, controller=controller,
                            batch_sm=batch_sm, player=player, em_manager=em_manager,
                        ),
                    )
                last_phase_idx = player.current_phase_idx

            recipe_jacket_K = model.state.jacket_temperature
            actual_jacket_K = model.state.jacket_temperature

            # --- Physics (active in RUNNING and HELD states) ---
            solve_wall_ms = 0.0
            if batch_sm.is_physics_active:
                solve_t0 = time.monotonic()
                model.step(dt)
                solve_wall_ms = round((time.monotonic() - solve_t0) * 1000, 1)

            # --- FSM ---
            controller.evaluate()
            if controller.phase != last_controller_phase:
                if audit_trail is not None:
                    audit_trail.emit(
                        event_type="controller_phase_transition",
                        source="controller",
                        actor="system",
                        action="transition",
                        subject="controller_phase",
                        details={
                            "from_phase": last_controller_phase.name,
                            "to_phase": controller.phase.name,
                        },
                        elapsed_s=elapsed,
                        state_snapshot=build_state_snapshot(
                            elapsed=elapsed, model=model, controller=controller,
                            batch_sm=batch_sm, player=player, em_manager=em_manager,
                        ),
                    )
                last_controller_phase = controller.phase

            # --- Formal alarm lifecycle management ---
            alarm_signals: dict[str, bool] = {
                "controller.runaway": controller.phase == Phase.RUNAWAY_ALARM,
            }
            if em_manager is not None:
                for sensor_alarm in em_manager.get_sensor_alarm_statuses():
                    tag = str(sensor_alarm.get("tag", "")).strip()
                    active = sensor_alarm.get("active", {})
                    if not tag or not isinstance(active, dict):
                        continue
                    for level, is_active in active.items():
                        alarm_signals[f"{tag}.{str(level).upper()}"] = bool(is_active)

            alarm_context: dict[str, Any] = {
                "phase": player.current_step.name if player.current_step else "DONE",
                "operation_name": player.current_operation_name or "DONE",
                "em_status": em_manager.get_mode_snapshot() if em_manager is not None else {},
            }
            alarm_manager.evaluate(
                elapsed_s=elapsed,
                signals=alarm_signals,
                snapshot=_build_alarm_snapshot(
                    elapsed=elapsed,
                    model=model,
                    controller=controller,
                    batch_sm=batch_sm,
                    player=player,
                ),
                context=alarm_context,
            )

            # --- Auto-complete: recipe finished while RUNNING ---
            if player.finished and batch_sm.state == BatchState.RUNNING:
                batch_sm.complete(elapsed)

            # --- Runaway triggers ABORT ---
            if controller.phase == Phase.RUNAWAY_ALARM and batch_sm.state == BatchState.RUNNING:
                batch_sm.dispatch(BatchCommand.ABORT, elapsed)

            # --- Track peak temp ---
            if model.state.temperature > peak_temp:
                peak_temp = model.state.temperature

            # --- CSV row ---
            s = model.state
            row = [
                round(elapsed, 2), dt, solve_wall_ms, model.last_solve_method,
                round(s.temperature, 4), round(s.jacket_temperature, 4),
                round(recipe_jacket_K, 4), round(actual_jacket_K, 4),
            ]
            for c in model.network.conversion_names:
                row.append(round(s.conversions.get(c, 0.0), 6))
            for sp in model.network.species_names:
                row.append(round(s.species_masses.get(sp, 0.0), 4))
            row.append(round(s.mass_total, 4))
            for sp in model.network.species_names:
                row.append(round(model.get_feed_rate(sp), 6))
            row.extend([
                round(model.viscosity, 2), round(model.pressure_bar, 3),
                controller.phase.name,
                player.current_step.name if player.current_step else "DONE",
                player.current_operation_name or "DONE",
                "none",
                "batch",
                False,
                batch_sm.state.value,
            ])
            csv_writer.writerow(row)
            if ticks % 100 == 0:
                csv_file.flush()

            elapsed += dt
            ticks += 1

            # --- Update progress ---
            if ticks % 10 == 0:
                progress.update({
                    "elapsed": round(elapsed, 1),
                    "pct_complete": round(min(elapsed / total_estimate * 100, 99.9), 1),
                    "temperature": round(s.temperature, 1),
                    "conversion": round(s.conversion, 4),
                    "phase": controller.phase.name,
                    "operation_name": player.current_operation_name or "DONE",
                    "batch_state": batch_sm.state.value,
                })

            # --- Log periodically ---
            if ticks % 200 == 0:
                logger.info(
                    "[BATCH] t=%.0fs  T=%.1fK  conv=%.3f  phase=%s",
                    elapsed, s.temperature, s.conversion, controller.phase.name,
                )

            # --- Stopping conditions ---
            if batch_sm.is_terminal:
                stop_reason = f"batch_{batch_sm.state.value.lower()}"
                logger.info("Batch stopped: batch state %s", batch_sm.state.value)
                break
            if player.finished and batch_sm.state == BatchState.COMPLETE and elapsed > player.total_elapsed + post_recipe_time:
                logger.info("Batch stopped: recipe finished + %.0fs post-recipe hold", post_recipe_time)
                stop_reason = "recipe_finished"
                break
            if stop_conversion > 0 and s.conversion >= stop_conversion:
                logger.info("Batch stopped: conversion %.4f >= threshold %.4f",
                            s.conversion, stop_conversion)
                stop_reason = "conversion_threshold"
                break
            if controller.phase == Phase.DISCHARGING:
                if not _discharge_recorded:
                    flow_events.append(FlowEvent(
                        event_type="discharge", species="ALL",
                        start_time_s=elapsed, end_time_s=elapsed,
                        mass_kg=model.state.mass_total, avg_rate_kgs=0.0,
                        phase_name=player.current_step.name if player.current_step else "DISCHARGING",
                        operation_name=player.current_operation_name or "UNKNOWN",
                    ))
                    _discharge_recorded = True
                logger.info("Batch stopped: FSM reached DISCHARGING")
                stop_reason = "fsm_discharging"
                break
            if controller.phase == Phase.RUNAWAY_ALARM and batch_sm.state == BatchState.ABORTED:
                logger.info("Batch stopped: RUNAWAY_ALARM (ABORTED)")
                stop_reason = "runaway_alarm"
                break
            if elapsed > max_time:
                logger.info("Batch stopped: max time %.0fs exceeded", max_time)
                stop_reason = "max_time_exceeded"
                break
    finally:
        # Flush any feeds still active at batch end
        for sp_name, entry in _active_feeds.items():
            duration = elapsed - entry["start_time_s"]
            flow_events.append(FlowEvent(
                event_type="feed", species=sp_name,
                start_time_s=entry["start_time_s"], end_time_s=elapsed,
                mass_kg=entry["accumulated_mass_kg"],
                avg_rate_kgs=entry["accumulated_mass_kg"] / max(duration, dt),
                material_id=identity.material_ids.get(sp_name, ""),
                lot_number=(identity.material_specs[sp_name].lot_number
                            if sp_name in identity.material_specs else ""),
                phase_name=entry["phase_name"],
                operation_name=entry["operation_name"],
                open=True,
            ))
        _active_feeds.clear()
        csv_file.close()
        if audit_trail is not None:
            audit_trail.close()

    wall_time = time.monotonic() - wall_start
    output_materials: dict[str, float] = dict(model.state.species_masses)

    completed_at = datetime.now()

    record_path = log_dir / f"batch_record_{batch_id}.json"
    record = BatchDataRecord(
        batch_id=batch_id,
        recipe_name=procedure.name,
        parameter_set=parameter_set_name,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        status="cancelled" if stop_reason == "cancelled" else "completed",
        stop_reason=stop_reason,
        total_ticks=ticks,
        total_time_s=elapsed,
        wall_time_s=wall_time,
        exceptions=batch_exceptions,
        phase_events=phase_events,
        parameterization=parameterization_summary,
        final_batch_state=batch_sm.state.value,
        batch_state_history=batch_sm.history,
        identity=identity,
        input_materials=input_materials,
        output_materials=output_materials,
        flow_events=flow_events,
        alarm_history=alarm_manager.get_history(),
    )
    with open(record_path, "w") as f:
        json.dump(record.to_dict(), f, indent=2)

    # Update progress to 100%
    progress.update({
        "elapsed": round(elapsed, 1),
        "pct_complete": 100.0,
        "temperature": round(model.state.temperature, 1),
        "conversion": round(model.state.conversion, 4),
        "phase": controller.phase.name,
        "operation_name": player.current_operation_name or "DONE",
        "batch_state": batch_sm.state.value,
    })

    result = BatchResult(
        csv_path=str(csv_path),
        total_time_s=elapsed,
        wall_time_s=wall_time,
        final_temperature_K=model.state.temperature,
        final_conversions=dict(model.state.conversions),
        final_phase=controller.phase.name,
        total_ticks=ticks,
        final_masses=dict(model.state.species_masses),
        peak_temperature_K=peak_temp,
        parameter_set=parameter_set_name,
        record_path=str(record_path),
        batch_exceptions=[e.to_dict() for e in batch_exceptions],
        batch_number=identity.batch_number,
        lot_number=identity.lot_number,
    )

    logger.info("Batch complete: %.0fs simulated in %.1fs wall time (%.0fx)",
                elapsed, wall_time, elapsed / max(wall_time, 0.001))
    return result
