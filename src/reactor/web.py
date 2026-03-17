"""FastAPI web dashboard for live reactor monitoring."""

from __future__ import annotations

import asyncio
import copy
import csv
import glob
import json
import math
import os
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ModelConfig, load_data_file
from .playback import DataPackagePlayer
from .procedure import load_procedure
from .recipe import load_recipe, add_sensor_noise

if TYPE_CHECKING:
    from .controller import BatchController
    from .physics import ReactorModel
    from .procedure import ProcedurePlayer
    from .config import Settings
    from .test_inputs import TestInputPlayer


def resolve_project_root() -> Path:
    """Resolve the project root for config/recipe/static lookups."""
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "configs").is_dir() and (candidate / "recipes").is_dir():
            return candidate
    return candidates[0]


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge *override* into a copy of *base* (non-destructive)."""
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


class CommandRequest(BaseModel):
    """Request body for command endpoint."""
    command: str


class ActuatorOverride(BaseModel):
    """Request body for actuator override."""
    actuator: str
    value: float


class TestScenario(BaseModel):
    """Request body for running a test scenario."""
    scenario: str
    params: dict = {}


class RecipeSelect(BaseModel):
    """Request body for selecting a recipe."""
    filename: str


class DataPackageSelect(BaseModel):
    """Request body for selecting a data package."""
    filename: str


class TestInputLoad(BaseModel):
    """Request body for loading a test input file."""
    filename: str


class ConfigSelect(BaseModel):
    """Request body for selecting a model config file."""
    filename: str


class ConfigUpdate(BaseModel):
    """Request body for updating model config values."""
    config: dict


class OPCMappingRequest(BaseModel):
    """Request body for adding/updating an OPC Tool mapping."""
    opc_node_id: str
    reactor_var: str
    direction: str = "read"
    transform: str = "value"
    priority: int = 50
    enabled: bool = True


class BatchRunRequest(BaseModel):
    """Request body for starting a batch simulation run."""
    recipe: str | None = None
    config: str | None = None
    post_recipe_time: float | None = None
    stop_conversion: float | None = None
    parameter_set: str | None = None
    batch_identity: dict | None = None


class SweepRunRequest(BaseModel):
    """Request body for starting a parametric sweep.

    ``param_path`` uses dot-notation into the YAML config (e.g. "kinetics.A2").
    ``values`` is the list of values to test (one batch per value).
    ``max_workers`` limits parallel batch runs (default 4).
    """
    param_path: str
    values: list[float]
    recipe: str | None = None
    config: str | None = None
    max_workers: int = 4
    parameter_set: str | None = None


class EquipmentModeRequest(BaseModel):
    """Request body for EM mode change."""
    em_tag: str
    mode: str


class AlarmAcknowledgeRequest(BaseModel):
    """Request body for acknowledging an alarm."""

    alarm_id: str
    operator_id: str


class AlarmSuppressionRequest(BaseModel):
    """Request body for manual alarm suppression/unsuppression."""

    alarm_id: str
    suppressed: bool
    operator_id: str
    reason: str = ""


def create_app(
    model: "ReactorModel",
    controller: "BatchController",
    player: "ProcedurePlayer",
    settings: "Settings",
    *,
    test_state: dict[str, Any] | None = None,
    sim_state: dict[str, Any] | None = None,
    playback_state: dict[str, Any] | None = None,
    csv_path: Path | None = None,
    opc_tool_client: Any | None = None,
    mapping_manager: Any | None = None,
    sensor_buffer: Any | None = None,
    em_manager: Any | None = None,
    batch_sm: Any | None = None,
    alarm_manager: Any | None = None,
    audit_trail: Any | None = None,
) -> FastAPI:
    """Create a FastAPI app that serves live reactor data."""

    app = FastAPI(title="Reactor Digital Twin Dashboard")

    # Enable CORS for cross-origin requests
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    project_root = resolve_project_root()
    dashboard_dir = project_root / "frontend" / "dist"
    if not dashboard_dir.exists():
        dashboard_dir = project_root / "dashboard"
    recipes_dir = project_root / "recipes"
    configs_dir = project_root / "configs"
    test_inputs_dir = project_root / "test_inputs"
    data_packages_dir = project_root / "data_packages"

    # Default shared dicts if not provided
    if test_state is None:
        test_state = {"player": None}
    if playback_state is None:
        playback_state = {"player": None}
    if sim_state is None:
        sim_state = {
            "recipe_jacket_K": 298.15,
            "actual_jacket_K": 298.15,
            "override_active": False,
            "override_source": "none",
            "elapsed_s": 0.0,
            "fake_sensors_enabled": False,  # Disabled by default (true/clean data)
        }

    # Ensure config tracking keys exist
    if "pending_config" not in sim_state:
        sim_state["pending_config"] = None
    if "active_config_file" not in sim_state:
        sim_state["active_config_file"] = settings.model_config_file
    if "base_config_raw" not in sim_state:
        sim_state["base_config_raw"] = copy.deepcopy(model._cfg.raw) if model._cfg else {}

    # Store actuator overrides and test scenario state
    actuator_overrides: dict[str, float] = {}
    test_scenario_state: dict = {"active": None, "params": {}}

    # Mount assets directory (Vite puts assets in /assets by default)
    # Using StaticFiles to serve the assets folder
    if (dashboard_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(dashboard_dir / "assets")), name="assets")

    @app.get("/")
    async def index():
        response = FileResponse(dashboard_dir / "index.html")
        response.headers["Cache-Control"] = "no-store"
        return response
    
    # Catch-all for history mode routing if needed (though index.html handles it for client-side routing)
    # But since we use hash based routing or basic single page, just serving / is enough for now.
    # We remove explicit favicon handlers if they are in the root of dist, otherwise:
    
    @app.get("/favicon.ico")
    async def favicon_ico():
        if (dashboard_dir / "favicon.ico").exists():
            return FileResponse(dashboard_dir / "favicon.ico")
        return FileResponse(dashboard_dir / "favicon.svg", media_type="image/svg+xml")

    @app.get("/favicon.svg")
    async def favicon_svg():
        return FileResponse(dashboard_dir / "favicon.svg", media_type="image/svg+xml")

    @app.get("/api/state")
    async def get_state():
        # Playback mode: return recorded snapshot directly
        pb = playback_state.get("player")
        if pb is not None and pb.current_snapshot is not None:
            return JSONResponse(pb.current_snapshot)

        s = model.state
        # Apply noise only if fake sensors are enabled
        fake_sensors = sim_state.get("fake_sensors_enabled", False)
        temp_measured = add_sensor_noise(s.temperature, settings.noise_pct) if fake_sensors else s.temperature
        return JSONResponse({
            "temperature_K": round(s.temperature, 2),
            "temperature_C": round(s.temperature - 273.15, 2),
            "temperature_measured_K": round(temp_measured, 2),
            "temperature_measured_C": round(temp_measured - 273.15, 2),
            "jacket_temperature_K": round(s.jacket_temperature, 2),
            "conversion": round(s.conversion, 4),
            "viscosity_Pas": round(model.viscosity, 1),
            "pressure_bar": round(model.pressure_bar, 3),
            "mass_component_a_kg": round(s.species_masses.get("component_a", 0.0), 2),
            "mass_component_b_kg": round(s.species_masses.get("component_b", 0.0), 2),
            "mass_product_kg": round(s.species_masses.get("product", 0.0), 2),
            "mass_solvent_kg": round(s.species_masses.get("solvent", 0.0), 2),
            "mass_total_kg": round(s.mass_total, 2),
            "phase": controller.phase.name,
            "phase_id": int(controller.phase),
            "dt_dt": round(controller.dt_dt, 3),
            "recipe_step": player.current_step.name if player.current_step else "DONE",
            "recipe_step_idx": player.current_step_idx,
            "recipe_operation": player.current_operation_name or "DONE",
            "recipe_elapsed_s": round(player.total_elapsed, 1),
            "recipe_finished": player.finished,
            "simulation_running": controller._recipe_started,
            "actuator_overrides": actuator_overrides,
            "test_scenario": test_scenario_state["active"],
            "volume_L": round(model.volume_L, 2),
            "fill_pct": round(model.fill_pct, 1),
            # Feed rates
            "feed_rate_component_a": round(model.get_feed_rate("component_a"), 3),
            "feed_rate_component_b": round(model.get_feed_rate("component_b"), 3),
            "feed_rate_solvent": round(model.get_feed_rate("solvent"), 3),
            # Agitator
            "agitator_speed_rpm": model._reactor_cfg.get("agitator_speed_rpm", 0),
            # Fluid mechanics (when mixing model is enabled)
            "mixing_enabled": model.mixing_enabled,
            "reynolds_number": round(model.reynolds_number, 1),
            "mixing_efficiency": round(model.mixing_efficiency, 4),
            "dynamic_UA_kW_K": round(model.dynamic_UA, 4) if model.dynamic_UA is not None else None,
            "wetted_area_m2": round(model.wetted_area, 4) if model.geometry else None,
            "liquid_level_m": round(model.liquid_level, 4) if model.geometry else None,
            "flow_regime": model.fluid_mechanics_state.regime if model.fluid_mechanics_state else None,
            # Setpoint vs actual tracking
            "recipe_jacket_setpoint_K": round(sim_state.get("recipe_jacket_K", model.state.jacket_temperature), 2),
            "override_active": sim_state.get("override_active", False),
            "override_source": sim_state.get("override_source", "none"),
            # Test inputs
            "test_input_active": test_state["player"] is not None,
            "test_input_name": test_state["player"].active_name if test_state["player"] else None,
            # Playback mode
            "playback_active": playback_state["player"] is not None and (playback_state["player"].playing if hasattr(playback_state["player"], "playing") else True),
            "playback_name": playback_state["player"].package.name if playback_state["player"] and hasattr(playback_state["player"], "package") else None,
            # Data mode indicator (live/test_input/playback)
            "data_mode": "playback" if (playback_state["player"] is not None and (playback_state["player"].playing if hasattr(playback_state["player"], "playing") else True)) else ("test_input" if test_state["player"] is not None else "live"),
            # Sensors
            "sensors_enabled": settings.sensors_enabled,
            "fake_sensors_enabled": sim_state.get("fake_sensors_enabled", False),
            # Tick interval
            "tick_interval": sim_state.get("tick_interval", settings.tick_interval),
            # Config state
            "config_pending": sim_state.get("pending_config") is not None,
            "active_config_file": sim_state.get("active_config_file", ""),
            # Equipment modules summary
            "equipment_modules": em_manager.get_em_list() if em_manager else [],
            # ISA-88 Batch State
            "batch_state": batch_sm.state.value if batch_sm else "IDLE",
        })

    @app.get("/api/config")
    async def get_config():
        """Return simulation configuration."""
        return JSONResponse({
            "opc_port": settings.opc_port,
            "web_port": settings.web_port,
            "tick_interval": sim_state.get("tick_interval", settings.tick_interval),
            "noise_pct": settings.noise_pct,
            "auto_start": settings.auto_start,
            "recipe_file": settings.recipe_file,
            "model_config_file": settings.model_config_file,
            "opc_endpoint": f"opc.tcp://localhost:{settings.opc_port}",
        })

    @app.post("/api/config/tick_interval")
    async def set_tick_interval(request: Request):
        """Change the simulation tick interval at runtime."""
        data = await request.json()
        value = float(data.get("value", 0.5))
        value = max(0.1, min(5.0, value))  # Clamp to 0.1–5.0s
        sim_state["tick_interval"] = value
        return JSONResponse({"status": "ok", "tick_interval": value})

    @app.get("/api/recipes")
    async def list_recipes():
        """Return list of available recipe files with details."""
        recipe_files = sorted(
            [*recipes_dir.glob("*.yaml"), *recipes_dir.glob("*.xml")],
            key=lambda p: p.name,
        )
        recipes = []
        for f in recipe_files:
            try:
                proc = load_procedure(f)
                n_ops = sum(len(up.operations) for up in proc.unit_procedures)
                recipes.append({
                    "filename": f.name,
                    "name": proc.name,
                    "steps": len(proc.phases_flat),
                    "total_duration": proc.total_duration,
                    "operation_count": n_ops,
                })
            except Exception:
                recipes.append({"filename": f.name, "name": f.stem, "steps": 0, "total_duration": 0,
                                 "operation_count": 0})
        return JSONResponse({
            "recipes": recipes,
            "current": player.procedure.name,
            "current_file": settings.recipe_file,
        })

    @app.get("/api/recipe/current")
    async def get_current_recipe():
        """Return the current procedure structure with ISA-88 hierarchy."""
        proc = player.procedure
        phase_global_idx = 0
        unit_procedures_out = []
        for up in proc.unit_procedures:
            operations_out = []
            for op in up.operations:
                phases_out = []
                for phase in op.phases:
                    profiles = {
                        ch: {
                            "type": p.profile_type.value,
                            "start_value": p.start_value,
                            "end_value": p.end_value,
                        }
                        for ch, p in phase.profiles.items()
                    }
                    phases_out.append({
                        "index": phase_global_idx,
                        "name": phase.name,
                        "duration": phase.duration,
                        "profiles": profiles,
                        "is_current": phase_global_idx == player.current_phase_idx,
                        "is_completed": phase_global_idx < player.current_phase_idx,
                    })
                    phase_global_idx += 1
                operations_out.append({
                    "name": op.name,
                    "total_duration": op.total_duration,
                    "phases": phases_out,
                    "is_current": op.name == player.current_operation_name,
                })
            unit_procedures_out.append({
                "name": up.name,
                "total_duration": up.total_duration,
                "operations": operations_out,
            })
        return JSONResponse({
            "name": proc.name,
            "total_duration": proc.total_duration,
            "current_phase_idx": player.current_phase_idx,
            "current_operation_name": player.current_operation_name,
            "current_unit_procedure_name": player.current_unit_procedure_name,
            "phase_elapsed": player.phase_elapsed,
            "unit_procedures": unit_procedures_out,
        })

    @app.post("/api/recipes/select")
    async def select_recipe(request: RecipeSelect):
        """Switch to a different recipe. Only allowed when simulation is not running."""
        if controller._recipe_started:
            return JSONResponse(
                {"error": "Cannot switch recipe while simulation is running. Stop first."},
                status_code=400,
            )

        recipe_path = recipes_dir / request.filename
        if not recipe_path.exists():
            recipe_path = recipes_dir / f"{request.filename}.yaml"
        if not recipe_path.exists():
            recipe_path = recipes_dir / f"{request.filename}.xml"
        if not recipe_path.exists():
            return JSONResponse(
                {"error": f"Recipe not found: {request.filename}"},
                status_code=404,
            )

        try:
            new_proc = load_procedure(recipe_path)
        except Exception as e:
            return JSONResponse({"error": f"Failed to load recipe: {e}"}, status_code=400)

        player.load(new_proc)
        settings.recipe_file = str(recipe_path)

        return JSONResponse({
            "status": "ok",
            "recipe": new_proc.name,
            "steps": len(new_proc.phases_flat),
            "total_duration": new_proc.total_duration,
        })

    @app.get("/api/recipe/{filename}")
    async def get_recipe_details(filename: str):
        """Return full details of a specific recipe."""
        recipe_path = recipes_dir / filename
        if not recipe_path.exists():
            recipe_path = recipes_dir / f"{filename}.yaml"
        if not recipe_path.exists():
            recipe_path = recipes_dir / f"{filename}.xml"
        if not recipe_path.exists():
            return JSONResponse({"error": f"Recipe not found: {filename}"}, status_code=404)

        r = load_recipe(recipe_path)
        data = {
            "name": r.name,
            "steps": [
                {
                    "name": s.name,
                    "duration": s.duration,
                    "profiles": {
                        ch: {"type": p.profile_type.value, "start": p.start_value, "end": p.end_value}
                        for ch, p in s.profiles.items()
                    },
                }
                for s in r.steps
            ],
        }
        return JSONResponse(data)

    @app.get("/api/recipe/{filename}/b2mml")
    async def get_recipe_b2mml(filename: str):
        """Return a B2MML XML document for the given recipe file."""
        from fastapi.responses import Response
        from .procedure import to_b2mml
        recipe_path = recipes_dir / filename
        if not recipe_path.exists():
            recipe_path = recipes_dir / f"{filename}.yaml"
        if not recipe_path.exists():
            recipe_path = recipes_dir / f"{filename}.xml"
        if not recipe_path.exists():
            return JSONResponse({"error": f"Recipe not found: {filename}"}, status_code=404)
        try:
            proc = load_procedure(recipe_path)
            xml_str = to_b2mml(proc)
            return Response(content=xml_str, media_type="application/xml")
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/scenarios")
    async def list_scenarios():
        """Return available test scenarios."""
        scenarios = [
            {
                "id": "normal",
                "name": "Normal Batch",
                "description": "Full batch lifecycle: START → CHARGING → HEATING → EXOTHERM → COOLING → DISCHARGING",
            },
            {
                "id": "override",
                "name": "Jacket Override",
                "description": "DCS jacket temperature override during heating phase",
            },
            {
                "id": "runaway",
                "name": "Thermal Runaway",
                "description": "Trigger thermal runaway alarm by overheating, then RESET",
            },
            {
                "id": "custom",
                "name": "Custom Profile",
                "description": "Apply custom jacket temperature profile",
            },
        ]
        return JSONResponse({
            "scenarios": scenarios,
            "active": test_scenario_state["active"],
        })

    @app.post("/api/scenario/activate")
    async def activate_scenario(request: TestScenario):
        """Activate a test scenario."""
        test_scenario_state["active"] = request.scenario
        test_scenario_state["params"] = request.params
        
        # Apply scenario-specific settings
        if request.scenario == "runaway":
            # Set very high jacket temperature to trigger runaway
            temp = request.params.get("jacket_temp", 500.0)
            actuator_overrides["jacket_temp"] = temp
            if sensor_buffer is not None:
                sensor_buffer.write("jacket_temperature", temp, source="web_api", priority=30)
            else:
                model.state.jacket_temperature = temp
        elif request.scenario == "override":
            # Apply jacket override
            temp = request.params.get("jacket_temp", 373.15)
            actuator_overrides["jacket_temp"] = temp
            if sensor_buffer is not None:
                sensor_buffer.write("jacket_temperature", temp, source="web_api", priority=30)
            else:
                model.state.jacket_temperature = temp
        
        return JSONResponse({
            "status": "ok",
            "scenario": request.scenario,
            "params": request.params,
        })

    @app.post("/api/scenario/deactivate")
    async def deactivate_scenario():
        """Deactivate current test scenario."""
        test_scenario_state["active"] = None
        test_scenario_state["params"] = {}
        actuator_overrides.clear()
        if sensor_buffer is not None:
            sensor_buffer.clear_source("web_api")
        return JSONResponse({"status": "ok"})

    @app.post("/api/command")
    async def send_command(request: CommandRequest):
        """Send a command to the controller (START, HOLD, RESTART, STOP, ABORT, RESET)."""
        cmd = request.command.upper()
        valid_commands = {"START", "HOLD", "RESTART", "STOP", "ABORT", "RESET"}
        if cmd not in valid_commands:
            return JSONResponse({"error": f"Unknown command: {cmd}"}, status_code=400)

        # Route commands to playback player if active
        pb = playback_state.get("player")
        if pb is not None:
            if cmd == "START":
                pb.start()
            elif cmd == "STOP":
                pb.stop()
            elif cmd == "RESET":
                pb.reset()
            return JSONResponse({"status": "ok", "command": cmd, "mode": "playback"})

        # Audit trail: log the command
        if audit_trail is not None:
            elapsed_s = sim_state.get("elapsed_s", 0.0) if sim_state else 0.0
            audit_trail.emit(
                event_type="command",
                source="web_api",
                actor="web_api",
                action="send_command",
                subject="batch_state",
                details={
                    "command": cmd,
                    "batch_state_before": batch_sm.state.value if batch_sm else "N/A",
                },
                elapsed_s=elapsed_s,
            )

        # Forward to controller (legacy path for START/STOP/RESET)
        if cmd in ("START", "STOP", "RESET"):
            controller.send_command(cmd)
        # Also forward HOLD/RESTART/ABORT — the main loop handles
        # batch_sm dispatch via get_pending_command()
        elif cmd in ("HOLD", "RESTART", "ABORT"):
            controller.send_command(cmd)

        resp: dict[str, Any] = {"status": "ok", "command": cmd}
        if batch_sm:
            resp["batch_state"] = batch_sm.state.value
        return JSONResponse(resp)

    @app.post("/api/actuator/override")
    async def override_actuator(request: ActuatorOverride):
        """Override an actuator value."""
        if audit_trail is not None:
            elapsed_s = sim_state.get("elapsed_s", 0.0) if sim_state else 0.0
            audit_trail.emit(
                event_type="actuator_override",
                source="web_api",
                actor="web_api",
                action="override",
                subject=f"actuator:{request.actuator}",
                details={"actuator": request.actuator, "value": request.value},
                elapsed_s=elapsed_s,
            )
        actuator = request.actuator.lower()
        if actuator == "jacket_temp":
            actuator_overrides["jacket_temp"] = request.value
            if sensor_buffer is not None:
                sensor_buffer.write("jacket_temperature", request.value, source="web_api", priority=30)
            else:
                model.state.jacket_temperature = request.value
            return JSONResponse({"status": "ok", "actuator": actuator, "value": request.value})
        elif actuator == "feed_component_a":
            actuator_overrides["feed_component_a"] = request.value
            model.set_feed_rate("component_a", request.value)
            return JSONResponse({"status": "ok", "actuator": actuator, "value": request.value})
        elif actuator == "feed_component_b":
            actuator_overrides["feed_component_b"] = request.value
            model.set_feed_rate("component_b", request.value)
            return JSONResponse({"status": "ok", "actuator": actuator, "value": request.value})
        elif actuator == "feed_solvent":
            actuator_overrides["feed_solvent"] = request.value
            model.set_feed_rate("solvent", request.value)
            return JSONResponse({"status": "ok", "actuator": actuator, "value": request.value})
        elif actuator == "clear":
            actuator_overrides.clear()
            if sensor_buffer is not None:
                sensor_buffer.clear_source("web_api")
            return JSONResponse({"status": "ok", "message": "All overrides cleared"})
        else:
            return JSONResponse({"error": f"Unknown actuator: {actuator}"}, status_code=400)

    @app.post("/api/fake_sensors/toggle")
    async def toggle_fake_sensors():
        """Toggle fake/noisy sensor data on or off."""
        current = sim_state.get("fake_sensors_enabled", False)
        sim_state["fake_sensors_enabled"] = not current
        return JSONResponse({
            "status": "ok",
            "fake_sensors_enabled": sim_state["fake_sensors_enabled"]
        })

    @app.get("/api/actuator/overrides")
    async def get_overrides():
        """Get current actuator overrides."""
        return JSONResponse(actuator_overrides)

    @app.get("/api/sensor_buffer/status")
    async def get_sensor_buffer_status():
        """Get the current sensor buffer state (buffered values, sticky, last resolved)."""
        if sensor_buffer is None:
            return JSONResponse({"error": "Sensor buffer not available"}, status_code=503)
        return JSONResponse(sensor_buffer.get_status())

    # ------------------------------------------------------------------
    # Audit trail endpoints
    # ------------------------------------------------------------------

    @app.get("/api/audit/events")
    async def get_audit_events(n: int = 50):
        """Return the most recent *n* audit trail events."""
        if audit_trail is None:
            return JSONResponse({"events": [], "enabled": False})
        return JSONResponse({
            "events": audit_trail.recent(n),
            "total": audit_trail.event_count,
            "enabled": True,
        })

    @app.get("/api/audit/verify")
    async def verify_audit_chain():
        """Verify the cryptographic hash chain integrity of the audit trail."""
        if audit_trail is None:
            return JSONResponse({"enabled": False, "valid": True, "last_valid_sequence": 0})
        valid, last_valid = audit_trail.verify_chain()
        return JSONResponse({
            "enabled": True,
            "valid": valid,
            "total_events": audit_trail.event_count,
            "last_valid_sequence": last_valid,
        })

    _STATE_KEY_ALIAS = {
        "temperature": "temperature_K",
        "temperature_k": "temperature_K",
        "jacket_temperature": "jacket_temperature_K",
        "jacket_temperature_k": "jacket_temperature_K",
        "mass_total": "mass_total_kg",
        "phase_name": "phase",
        "feed_component_a": "feed_rate_component_a",
        "feed_component_b": "feed_rate_component_b",
        "feed_a": "feed_rate_component_a",
        "feed_b": "feed_rate_component_b",
        "feed_solvent": "feed_rate_solvent",
    }

    _DEFAULT_CATEGORY_META = {
        "sensor": {"color": "#22c55e", "icon": "S", "writable": False},
        "pump": {"color": "#3b82f6", "icon": "P", "writable": True},
        "valve": {"color": "#f59e0b", "icon": "V", "writable": True},
        "agitator": {"color": "#64748b", "icon": "A", "writable": True},
        "actuator": {"color": "#f59e0b", "icon": "A", "writable": True},
        "status": {"color": "#3b82f6", "icon": "#", "writable": False},
        "recipe": {"color": "#64748b", "icon": "R", "writable": True},
    }

    _KNOWN_ID_BY_STATE = {
        "temperature_K": "temperature",
        "pressure_bar": "pressure",
        "conversion": "conversion",
        "viscosity_Pas": "viscosity",
        "mass_total_kg": "mass_total",
        "jacket_temperature_K": "jacket_temp",
        "agitator_speed_rpm": "agitator_speed",
        "feed_rate_component_a": "feed_component_a",
        "feed_rate_component_b": "feed_component_b",
        "feed_rate_solvent": "feed_solvent",
        "phase_id": "fsm_state",
        "phase": "fsm_state_name",
        "recipe_elapsed_s": "batch_elapsed",
    }

    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
        return slug or "node"

    def _normalize_state_key(key: str) -> str:
        if not key:
            return ""
        norm = key.strip()
        return _STATE_KEY_ALIAS.get(norm.lower(), norm)

    def _cm_category(cm_type: str) -> str:
        cmt = (cm_type or "").strip().lower()
        if cmt == "sensor":
            return "sensor"
        if cmt == "pump":
            return "pump"
        if cmt in {"valve_onoff", "valve_control"}:
            return "valve"
        if cmt == "motor":
            return "agitator"
        return "actuator"

    def _build_node_catalog() -> list[dict[str, Any]]:
        core_nodes: list[dict[str, Any]] = [
            {"id": "temperature", "name": "Temperature", "opc_path": "Sensors/Temperature_K", "state_key": "temperature_K", "unit": "K", "category": "sensor", "data_type": "Double", "writable": False, "default_color": "#ef4444", "default_icon": "T"},
            {"id": "pressure", "name": "Pressure", "opc_path": "Sensors/Pressure_bar", "state_key": "pressure_bar", "unit": "bar", "category": "sensor", "data_type": "Double", "writable": False, "default_color": "#a855f7", "default_icon": "P"},
            {"id": "conversion", "name": "Conversion", "opc_path": "Sensors/Conversion", "state_key": "conversion", "unit": "", "category": "sensor", "data_type": "Double", "writable": False, "default_color": "#22c55e", "default_icon": "X"},
            {"id": "viscosity", "name": "Viscosity", "opc_path": "Sensors/Viscosity_Pas", "state_key": "viscosity_Pas", "unit": "Pa·s", "category": "sensor", "data_type": "Double", "writable": False, "default_color": "#f97316", "default_icon": "V"},
            {"id": "mass_total", "name": "Total Mass", "opc_path": "Sensors/MassTotal_kg", "state_key": "mass_total_kg", "unit": "kg", "category": "sensor", "data_type": "Double", "writable": False, "default_color": "#14b8a6", "default_icon": "M"},
            {"id": "fill_level", "name": "Fill Level", "opc_path": "Sensors/Fill_pct", "state_key": "fill_pct", "unit": "%", "category": "sensor", "data_type": "Double", "writable": False, "default_color": "#06b6d4", "default_icon": "L"},
            {"id": "fsm_state", "name": "FSM State", "opc_path": "Status/FSM_State", "state_key": "phase_id", "unit": "", "category": "status", "data_type": "Int32", "writable": False, "default_color": "#3b82f6", "default_icon": "#"},
            {"id": "fsm_state_name", "name": "FSM State Name", "opc_path": "Status/FSM_StateName", "state_key": "phase", "unit": "", "category": "status", "data_type": "String", "writable": False, "default_color": "#3b82f6", "default_icon": "S"},
            {"id": "batch_elapsed", "name": "Batch Elapsed", "opc_path": "Status/BatchElapsed_s", "state_key": "recipe_elapsed_s", "unit": "s", "category": "status", "data_type": "Double", "writable": False, "default_color": "#3b82f6", "default_icon": "E"},
            {"id": "recipe_command", "name": "Recipe Command", "opc_path": "Recipe/Command", "state_key": "", "unit": "", "category": "recipe", "data_type": "String", "writable": True, "default_color": "#64748b", "default_icon": "C"},
            {"id": "recipe_name", "name": "Recipe Name", "opc_path": "Recipe/RecipeName", "state_key": "", "unit": "", "category": "recipe", "data_type": "String", "writable": True, "default_color": "#64748b", "default_icon": "R"},
        ]

        raw_cfg = getattr(getattr(model, "_cfg", None), "raw", {})
        equipment_cfg = raw_cfg.get("equipment", {}) if isinstance(raw_cfg, dict) else {}
        cm_cfgs = equipment_cfg.get("control_modules", []) if isinstance(equipment_cfg, dict) else []

        dynamic_nodes: list[dict[str, Any]] = []
        if isinstance(cm_cfgs, list):
            for cm in cm_cfgs:
                if not isinstance(cm, dict):
                    continue
                tag = str(cm.get("tag", "")).strip()
                if not tag:
                    continue

                cm_type = str(cm.get("type", "")).strip().lower()
                category = _cm_category(cm_type)
                maps_to = _normalize_state_key(str(cm.get("maps_to", "")).strip())
                canonical_id = _KNOWN_ID_BY_STATE.get(maps_to, _slug(tag))
                meta = _DEFAULT_CATEGORY_META.get(category, _DEFAULT_CATEGORY_META["actuator"])

                data_type = "Double"
                if category in {"status", "recipe"}:
                    data_type = "String"

                dynamic_nodes.append({
                    "id": canonical_id,
                    "name": str(cm.get("name", tag)),
                    "opc_path": f"Equipment/{tag}/PV",
                    "state_key": maps_to,
                    "unit": str(cm.get("unit", "")),
                    "category": category,
                    "data_type": data_type,
                    "writable": bool(meta["writable"]),
                    "default_color": str(meta["color"]),
                    "default_icon": str(meta["icon"]),
                    "tag": tag,
                    "cm_type": cm_type,
                })

        merged_nodes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for node in [*core_nodes, *dynamic_nodes]:
            node_id = str(node.get("id", "")).strip()
            if not node_id:
                continue
            unique_id = node_id
            suffix = 2
            while unique_id in seen_ids:
                unique_id = f"{node_id}_{suffix}"
                suffix += 1
            if unique_id != node_id:
                node = {**node, "id": unique_id}
            merged_nodes.append(node)
            seen_ids.add(unique_id)

        return merged_nodes

    @app.get("/api/connections")
    async def get_connections():
        """Get available connection endpoints."""
        node_catalog = _build_node_catalog()
        sensors = [n["id"] for n in node_catalog if n.get("category") == "sensor"]
        pumps = [n["id"] for n in node_catalog if n.get("category") == "pump"]
        valves = [n["id"] for n in node_catalog if n.get("category") == "valve"]
        agitators = [n["id"] for n in node_catalog if n.get("category") == "agitator"]
        actuators = [
            n["id"]
            for n in node_catalog
            if n.get("category") in {"actuator", "pump", "valve", "agitator"}
        ]
        status_nodes = [n["id"] for n in node_catalog if n.get("category") == "status"]
        recipe_nodes = [n["id"] for n in node_catalog if n.get("category") == "recipe"]

        return JSONResponse({
            "opc_ua": {
                "endpoint": f"opc.tcp://localhost:{settings.opc_port}",
                "namespace": "urn:reactor:digitaltwin",
                "security": "None",
                "nodes": {
                    "sensors": sensors,
                    "actuators": actuators,
                    "pumps": pumps,
                    "valves": valves,
                    "agitators": agitators,
                    "status": status_nodes,
                    "recipe": recipe_nodes,
                },
                "node_catalog": node_catalog,
            },
            "web_api": {
                "base_url": f"http://localhost:{settings.web_port}",
                "endpoints": [
                    {"path": "/api/state", "method": "GET", "description": "Current reactor state"},
                    {"path": "/api/command", "method": "POST", "description": "Send command (START/HOLD/RESTART/STOP/ABORT/RESET)"},
                    {"path": "/api/batch/state", "method": "GET", "description": "ISA-88 batch state machine status and history"},
                    {"path": "/api/recipes", "method": "GET", "description": "List available recipes"},
                    {"path": "/api/actuator/override", "method": "POST", "description": "Override actuator"},
                    {"path": "/api/batch/records", "method": "GET", "description": "List completed batch data records"},
                    {"path": "/api/batch/records/{batch_id}", "method": "GET", "description": "Get full batch data record"},
                ],
            },
        })

    @app.get("/api/model/parameters")
    async def get_model_parameters():
        """Get current model parameters."""
        cfg = model._cfg
        if cfg is None:
            return JSONResponse({"error": "No model config loaded"}, status_code=404)
        return JSONResponse({
            "kinetics": cfg.kinetics,
            "thermal": cfg.thermal,
            "viscosity": cfg.viscosity,
            "controller": cfg.controller,
        })

    @app.get("/api/model/simulation/options")
    async def get_simulation_options():
        """Get available simulation model options and current selections."""
        cfg = model._cfg
        if cfg is None:
            return JSONResponse({"error": "No model config loaded"}, status_code=404)

        try:
            from .viscosity_models import VISCOSITY_REGISTRY
            from .heat_transfer_models import HEAT_TRANSFER_REGISTRY
            from .mixing_models import MIXING_REGISTRY
            from .energy_models import ENERGY_REGISTRY
        except ImportError:
            return JSONResponse({"error": "Model registries unavailable"}, status_code=500)

        return JSONResponse({
            "current": cfg.simulation.get("models", {}),
            "available": {
                "viscosity": sorted(VISCOSITY_REGISTRY.keys()),
                "heat_transfer": sorted(HEAT_TRANSFER_REGISTRY.keys()),
                "mixing": sorted(MIXING_REGISTRY.keys()),
                "energy": sorted(ENERGY_REGISTRY.keys()),
            },
            "constraints": {
                "mixing_enabled": bool(cfg.mixing.get("enabled", False)),
                "has_geometry": bool(cfg.geometry),
            },
        })

    # ---- Model Config Management Endpoints ----

    _REACTOR_CONFIG_SECTIONS = frozenset(
        {"kinetics", "reaction_network", "thermal", "reactor", "physics", "controller"}
    )

    @app.get("/api/configs")
    async def list_configs():
        """Return list of available model config files (YAML and JSON)."""
        config_files = sorted(
            [*configs_dir.glob("*.yaml"), *configs_dir.glob("*.json")],
            key=lambda p: p.name,
        )
        configs = []
        for f in config_files:
            try:
                data = load_data_file(f)
                if not isinstance(data, dict):
                    continue
                # Skip non-reactor files (OPC connections, P&ID layouts, etc.)
                if not _REACTOR_CONFIG_SECTIONS.intersection(data.keys()):
                    continue

                # Skip files that cannot be loaded as a valid reactor model config
                ModelConfig.from_dict(data)

                has_network = "reaction_network" in data
                sections = [k for k in data.keys()]
                configs.append({
                    "filename": f.name,
                    "name": f.stem.replace("_", " ").title(),
                    "has_reaction_network": has_network,
                    "sections": sections,
                })
            except Exception:
                pass
        return JSONResponse({
            "configs": configs,
            "active_file": sim_state.get("active_config_file", ""),
        })

    @app.post("/api/configs/select")
    async def select_config(request: ConfigSelect):
        """Load a different model config file. Only allowed when not running."""
        if controller._recipe_started:
            return JSONResponse(
                {"error": "Cannot switch config while simulation is running. Stop first."},
                status_code=400,
            )
        config_path = configs_dir / request.filename
        if not config_path.exists():
            config_path = configs_dir / f"{request.filename}.yaml"
        if not config_path.exists():
            config_path = configs_dir / f"{request.filename}.json"
        if not config_path.exists():
            return JSONResponse(
                {"error": f"Config not found: {request.filename}"},
                status_code=404,
            )
        try:
            new_cfg = ModelConfig.from_file(config_path)
        except Exception as e:
            return JSONResponse({"error": f"Failed to load config: {e}"}, status_code=400)

        # Apply immediately (reinitialize model and controller)
        try:
            model.reinitialize(new_cfg)
            controller.reinitialize(model, new_cfg.controller)
        except Exception as e:
            return JSONResponse({"error": f"Config is not a valid reactor config: {e}"}, status_code=400)
        if player:
            player.reset()

        sim_state["base_config_raw"] = copy.deepcopy(new_cfg.raw)
        sim_state["active_config_file"] = str(config_path)
        sim_state["pending_config"] = None

        return JSONResponse({
            "status": "ok",
            "filename": request.filename,
            "sections": list(new_cfg.raw.keys()),
        })

    @app.get("/api/model/config/full")
    async def get_full_config():
        """Return the full model config (base + pending edits merged)."""
        base = sim_state.get("base_config_raw", {})
        pending = sim_state.get("pending_config")
        if pending:
            merged = _deep_merge(base, pending)
        else:
            merged = copy.deepcopy(base)
        return JSONResponse({
            "config": merged,
            "pending": pending,
            "active_file": sim_state.get("active_config_file", ""),
        })

    @app.post("/api/model/config/update")
    async def update_config(request: ConfigUpdate):
        """Update model config values (stored as pending, applied on reset)."""
        if sim_state.get("pending_config") is None:
            sim_state["pending_config"] = {}
        sim_state["pending_config"] = _deep_merge(sim_state["pending_config"], request.config)
        return JSONResponse({
            "status": "ok",
            "pending": sim_state["pending_config"],
        })

    @app.post("/api/model/config/apply")
    async def apply_pending_config():
        """Apply pending config changes (reinitialize model). Only when not running."""
        if controller._recipe_started:
            return JSONResponse(
                {"error": "Cannot apply config while simulation is running. Stop first."},
                status_code=400,
            )
        pending = sim_state.get("pending_config")
        if not pending:
            return JSONResponse({"status": "ok", "message": "No pending changes"})

        base = sim_state.get("base_config_raw", {})
        merged = _deep_merge(base, pending)
        new_cfg = ModelConfig.from_dict(merged)

        model.reinitialize(new_cfg)
        controller.reinitialize(model, new_cfg.controller)
        if player:
            player.reset()

        sim_state["base_config_raw"] = merged
        sim_state["pending_config"] = None

        return JSONResponse({"status": "ok", "message": "Config applied"})

    @app.post("/api/model/config/discard")
    async def discard_pending_config():
        """Discard pending config changes."""
        sim_state["pending_config"] = None
        return JSONResponse({"status": "ok"})

    # ---- Data Package Playback Endpoints ----

    @app.get("/api/data_packages")
    async def list_data_packages():
        """Return list of available data packages."""
        if not data_packages_dir.exists():
            return JSONResponse({"packages": [], "active": None})
        packages = []
        for f in sorted(data_packages_dir.glob("*.json")):
            try:
                with open(f) as fp:
                    raw = json.load(fp)
                meta = raw["metadata"]
                packages.append({
                    "filename": f.name,
                    "name": meta["name"],
                    "recipe_name": meta["recipe_name"],
                    "total_duration": meta["total_duration"],
                    "total_snapshots": meta["total_snapshots"],
                    "tick_interval": meta["tick_interval"],
                    "generated_at": meta["generated_at"],
                })
            except Exception:
                packages.append({"filename": f.name, "name": f.stem})
        pb = playback_state.get("player")
        return JSONResponse({
            "packages": packages,
            "active": pb.package.name if pb else None,
        })

    @app.post("/api/data_packages/select")
    async def select_data_package(request: DataPackageSelect):
        """Load a data package and activate playback mode."""
        if controller._recipe_started:
            return JSONResponse(
                {"error": "Cannot switch to playback while simulation is running."},
                status_code=400,
            )
        dp_path = data_packages_dir / request.filename
        if not dp_path.exists():
            return JSONResponse(
                {"error": f"Package not found: {request.filename}"},
                status_code=404,
            )
        try:
            playback_state["player"] = DataPackagePlayer.from_json(dp_path)
        except Exception as e:
            return JSONResponse({"error": f"Failed to load package: {e}"}, status_code=400)
        return JSONResponse({
            "status": "ok",
            "name": playback_state["player"].package.name,
            "snapshots": playback_state["player"].package.total_snapshots,
            "total_duration": playback_state["player"].package.total_duration,
        })

    @app.post("/api/data_packages/deactivate")
    async def deactivate_data_package():
        """Deactivate playback mode and return to live simulation."""
        playback_state["player"] = None
        return JSONResponse({"status": "ok"})

    # ---- OPC Tool Integration Endpoints ----

    @app.get("/api/opc-tool/status")
    async def opc_tool_status():
        """Check OPC Tool connection status."""
        if not opc_tool_client:
            return JSONResponse({"available": False, "url": "", "reason": "OPC Tool integration disabled"})
        return JSONResponse({
            "available": opc_tool_client.available,
            "url": opc_tool_client.base_url,
        })

    @app.get("/api/opc-tool/nodes")
    async def opc_tool_nodes(category: str | None = None):
        """Proxy node list from OPC Tool (for mapping UI)."""
        if not opc_tool_client or not opc_tool_client.available:
            return JSONResponse({"nodes": [], "error": "OPC Tool not available"})
        try:
            nodes = await opc_tool_client.list_nodes(category=category)
            return JSONResponse({"nodes": nodes})
        except Exception as e:
            return JSONResponse({"nodes": [], "error": str(e)})

    @app.get("/api/opc-tool/mappings")
    async def get_opc_mappings():
        """Get current OPC Tool <-> reactor mappings."""
        if not mapping_manager:
            return JSONResponse({"mappings": []})
        return JSONResponse({
            "mappings": [m.to_dict() for m in mapping_manager.list_mappings()]
        })

    @app.post("/api/opc-tool/mappings")
    async def add_opc_mapping(request: OPCMappingRequest):
        """Add or update an OPC Tool mapping."""
        if not mapping_manager:
            return JSONResponse({"error": "OPC Tool integration not configured"}, status_code=503)

        from .opc_mapping import NodeMapping
        mapping = NodeMapping(
            opc_node_id=request.opc_node_id,
            reactor_var=request.reactor_var,
            direction=request.direction,
            transform=request.transform,
            priority=request.priority,
            enabled=request.enabled,
        )
        mapping_manager.add_mapping(mapping)
        return JSONResponse({"status": "ok", "mapping": mapping.to_dict()})

    @app.delete("/api/opc-tool/mappings/{opc_node_id}")
    async def remove_opc_mapping(opc_node_id: str, direction: str | None = None):
        """Remove an OPC Tool mapping."""
        if not mapping_manager:
            return JSONResponse({"error": "OPC Tool integration not configured"}, status_code=503)
        if mapping_manager.remove_mapping(opc_node_id, direction):
            return JSONResponse({"status": "ok"})
        return JSONResponse({"error": "Mapping not found"}, status_code=404)

    # ---- Batch Simulation Endpoints ----

    @app.post("/api/batch/run")
    async def start_batch_run(request: BatchRunRequest):
        """Start a batch simulation in a background thread."""
        from .batch import BatchRunner
        from .config import Settings

        runner: BatchRunner | None = sim_state.get("batch_runner")
        if runner is not None and runner.is_running:
            return JSONResponse(
                {"error": "A batch simulation is already running"},
                status_code=400,
            )

        # Build settings for the batch run
        batch_settings = Settings()
        batch_settings.batch_mode = True
        if request.recipe:
            recipe_path = recipes_dir / request.recipe
            if not recipe_path.exists():
                return JSONResponse(
                    {"error": f"Recipe not found: {request.recipe}"},
                    status_code=404,
                )
            batch_settings.recipe_file = str(recipe_path)
        else:
            batch_settings.recipe_file = settings.recipe_file
        if request.config:
            config_path = configs_dir / request.config
            if not config_path.exists():
                return JSONResponse(
                    {"error": f"Config not found: {request.config}"},
                    status_code=404,
                )
            batch_settings.model_config_file = str(config_path)
        else:
            batch_settings.model_config_file = sim_state.get(
                "active_config_file", settings.model_config_file
            )
        if request.post_recipe_time is not None:
            batch_settings.batch_post_recipe_time = request.post_recipe_time
        if request.stop_conversion is not None:
            batch_settings.batch_stop_conversion = request.stop_conversion
        if request.parameter_set:
            batch_settings.batch_parameter_set = request.parameter_set
        if request.batch_identity:
            batch_settings.batch_identity = request.batch_identity

        runner = BatchRunner()
        batch_run_count = int(sim_state.get("batch_run_count", 0)) + 1
        sim_state["batch_run_count"] = batch_run_count
        logger.info(
            "[BATCH RUN #%d] Full simulation refresh requested (recipe=%s, config=%s)",
            batch_run_count,
            request.recipe or batch_settings.recipe_file,
            request.config or batch_settings.model_config_file,
        )
        sim_state["batch_runner"] = runner
        runner.start_in_thread(batch_settings)

        return JSONResponse({
            "status": "ok",
            "message": "Batch simulation started",
            "batch_run_count": batch_run_count,
        })

    @app.get("/api/batch/state")
    async def get_batch_state():
        """Get the ISA-88 batch state machine status and history."""
        if batch_sm is None:
            return JSONResponse({"state": "IDLE", "state_entered_at_s": 0, "history": []})
        return JSONResponse(batch_sm.to_dict())

    @app.get("/api/alarms")
    async def get_alarms():
        """Get current formal alarm state (active alarms + definitions)."""
        if alarm_manager is None:
            return JSONResponse({
                "active": [],
                "active_count": 0,
                "unacknowledged_count": 0,
                "history_count": 0,
                "definitions": [],
            })
        return JSONResponse(alarm_manager.to_dict())

    @app.get("/api/alarms/history")
    async def get_alarm_history(limit: int = 200):
        """Get alarm lifecycle history, including operator-attributed events."""
        if alarm_manager is None:
            return JSONResponse({"history": []})
        return JSONResponse({"history": alarm_manager.get_history(limit=limit)})

    @app.post("/api/alarms/ack")
    async def acknowledge_alarm(req: AlarmAcknowledgeRequest):
        """Acknowledge an active alarm with operator identity."""
        if alarm_manager is None:
            return JSONResponse({"error": "Alarm manager not available"}, status_code=503)
        elapsed_s = float(sim_state.get("elapsed_s", 0.0))
        ok = alarm_manager.acknowledge(
            req.alarm_id,
            operator_id=req.operator_id,
            elapsed_s=elapsed_s,
        )
        if not ok:
            return JSONResponse(
                {"error": f"Alarm cannot be acknowledged: {req.alarm_id}"},
                status_code=400,
            )
        return JSONResponse({"status": "ok", "alarm_id": req.alarm_id, "operator_id": req.operator_id})

    @app.post("/api/alarms/suppress")
    async def set_alarm_suppression(req: AlarmSuppressionRequest):
        """Manually suppress or unsuppress a single alarm."""
        if alarm_manager is None:
            return JSONResponse({"error": "Alarm manager not available"}, status_code=503)
        elapsed_s = float(sim_state.get("elapsed_s", 0.0))
        ok = alarm_manager.set_manual_suppression(
            req.alarm_id,
            suppressed=req.suppressed,
            operator_id=req.operator_id,
            elapsed_s=elapsed_s,
            reason=req.reason,
        )
        if not ok:
            return JSONResponse(
                {"error": f"Unknown alarm: {req.alarm_id}"},
                status_code=404,
            )
        return JSONResponse(
            {
                "status": "ok",
                "alarm_id": req.alarm_id,
                "suppressed": req.suppressed,
                "operator_id": req.operator_id,
            }
        )

    @app.get("/api/batch/status")
    async def get_batch_status():
        """Get the current batch simulation status and progress."""
        from .batch import BatchRunner

        runner: BatchRunner | None = sim_state.get("batch_runner")
        if runner is None:
            return JSONResponse({"status": "idle"})
        return JSONResponse(runner.get_status_dict())

    @app.post("/api/batch/cancel")
    async def cancel_batch_run():
        """Cancel a running batch simulation."""
        from .batch import BatchRunner

        runner: BatchRunner | None = sim_state.get("batch_runner")
        if runner is None or not runner.is_running:
            return JSONResponse(
                {"error": "No batch simulation is running"},
                status_code=400,
            )
        runner.cancel()
        return JSONResponse({"status": "ok", "message": "Batch cancellation requested"})

    # ---- Parametric Sweep Endpoints ----

    @app.post("/api/sweep/run")
    async def start_sweep_run(request: SweepRunRequest):
        """Start a parametric sweep in a background thread."""
        from .batch import SweepConfig, SweepRunner

        runner: SweepRunner | None = sim_state.get("sweep_runner")
        if runner is not None and runner.is_running:
            return JSONResponse(
                {"error": "A sweep is already running"},
                status_code=400,
            )
        if not request.values:
            return JSONResponse({"error": "values must be a non-empty list"}, status_code=400)

        batch_settings = Settings()
        batch_settings.batch_mode = True
        if request.recipe:
            recipe_path = recipes_dir / request.recipe
            if not recipe_path.exists():
                return JSONResponse(
                    {"error": f"Recipe not found: {request.recipe}"},
                    status_code=404,
                )
            batch_settings.recipe_file = str(recipe_path)
        else:
            batch_settings.recipe_file = settings.recipe_file
        if request.config:
            config_path = configs_dir / request.config
            if not config_path.exists():
                return JSONResponse(
                    {"error": f"Config not found: {request.config}"},
                    status_code=404,
                )
            batch_settings.model_config_file = str(config_path)
        else:
            batch_settings.model_config_file = sim_state.get(
                "active_config_file", settings.model_config_file
            )
        if request.parameter_set:
            batch_settings.batch_parameter_set = request.parameter_set

        sweep_cfg = SweepConfig(
            param_path=request.param_path,
            values=request.values,
        )
        runner = SweepRunner()
        sim_state["sweep_runner"] = runner
        runner.start_in_thread(batch_settings, sweep_cfg, max_workers=request.max_workers)
        return JSONResponse({"status": "ok", "message": "Sweep started", "n_runs": len(request.values)})

    @app.get("/api/sweep/status")
    async def get_sweep_status():
        """Get the current sweep status and results."""
        from .batch import SweepRunner

        runner: SweepRunner | None = sim_state.get("sweep_runner")
        if runner is None:
            return JSONResponse({"status": "idle"})
        return JSONResponse(runner.get_status_dict())

    @app.post("/api/sweep/cancel")
    async def cancel_sweep_run():
        """Cancel a running sweep."""
        from .batch import SweepRunner

        runner: SweepRunner | None = sim_state.get("sweep_runner")
        if runner is None or not runner.is_running:
            return JSONResponse({"error": "No sweep is running"}, status_code=400)
        runner.cancel()
        return JSONResponse({"status": "ok", "message": "Sweep cancellation requested"})

    # ---- Batch Log Endpoints ----

    @app.get("/api/batch/logs")
    async def list_batch_logs():
        """List available batch CSV log files."""
        log_dir = project_root / "logs"
        if not log_dir.exists():
            return JSONResponse({"logs": []})
        logs = []
        for f in sorted(log_dir.glob("batch_*.csv"), reverse=True):
            stat = f.stat()
            # Count rows (subtract 1 for header)
            with open(f) as fp:
                row_count = sum(1 for _ in fp) - 1
            logs.append({
                "filename": f.name,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified": stat.st_mtime,
                "rows": max(row_count, 0),
            })
        return JSONResponse({"logs": logs})

    @app.get("/api/batch/logs/{filename}")
    async def get_batch_log_data(filename: str, max_points: int = 1000):
        """Return batch CSV data as JSON column arrays."""
        if not re.match(r"^batch_\d{8}_\d{6}\.csv$", filename):
            return JSONResponse({"error": "Invalid filename"}, status_code=400)
        csv_file = project_root / "logs" / filename
        if not csv_file.exists():
            return JSONResponse({"error": "File not found"}, status_code=404)

        with open(csv_file, newline="") as f:
            reader = csv.reader(f)
            columns = next(reader)
            rows = list(reader)

        # Downsample if too many rows
        total = len(rows)
        if total > max_points:
            step = total / max_points
            sampled = [rows[int(i * step)] for i in range(max_points)]
            # Always include the last row
            if sampled[-1] != rows[-1]:
                sampled.append(rows[-1])
            rows = sampled

        # Build column arrays
        data: dict[str, list] = {col: [] for col in columns}
        numeric_cols = {
            "elapsed", "dt", "wall_ms", "temperature_K", "jacket_temperature_K",
            "recipe_jacket_K", "actual_jacket_K", "mass_total_kg",
            "viscosity_Pas", "pressure_bar",
        }
        # Also treat dynamic conversion/mass/feed columns as numeric
        for col in columns:
            if col.startswith(("conversion_", "mass_", "feed_")):
                numeric_cols.add(col)

        for row in rows:
            for i, col in enumerate(columns):
                val = row[i] if i < len(row) else ""
                if col in numeric_cols:
                    try:
                        val = float(val)
                        if math.isnan(val) or math.isinf(val):
                            val = None
                    except (ValueError, TypeError):
                        val = None
                data[col].append(val)

        return JSONResponse({"columns": columns, "data": data, "total_rows": total})

    # ---- Batch Record Endpoints (ISA-88 Ch. 6) ----

    @app.get("/api/batch/records")
    async def list_batch_records():
        """List completed batch data records with summary info."""
        log_dir = project_root / "logs"
        if not log_dir.exists():
            return JSONResponse({"records": []})
        records = []
        for f in sorted(log_dir.glob("batch_record_*.json"), reverse=True):
            try:
                with open(f) as fp:
                    data = json.load(fp)
                identity = data.get("identity", {})
                records.append({
                    "filename": f.name,
                    "batch_id": data.get("batch_id", ""),
                    "batch_number": identity.get("batch_number", ""),
                    "lot_number": identity.get("lot_number", ""),
                    "product_code": identity.get("product_code", ""),
                    "recipe_name": data.get("recipe_name", ""),
                    "status": data.get("status", ""),
                    "started_at": data.get("started_at", ""),
                    "completed_at": data.get("completed_at", ""),
                    "total_time_s": data.get("total_time_s", 0),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return JSONResponse({"records": records})

    @app.get("/api/batch/records/{batch_id}")
    async def get_batch_record(batch_id: str):
        """Retrieve a full batch data record by batch_id."""
        if not re.match(r"^\d{8}_\d{6}$", batch_id):
            return JSONResponse({"error": "Invalid batch_id format"}, status_code=400)
        record_path = project_root / "logs" / f"batch_record_{batch_id}.json"
        if not record_path.exists():
            return JSONResponse({"error": "Record not found"}, status_code=404)
        with open(record_path) as f:
            data = json.load(f)
        return JSONResponse(data)

    # --- P&ID Layout Persistence ---

    pid_layout_file = project_root / "configs" / "pid_layout.json"

    @app.get("/api/pid/layout")
    async def get_pid_layout():
        """Return saved P&ID node positions."""
        if pid_layout_file.exists():
            try:
                return JSONResponse(json.loads(pid_layout_file.read_text()))
            except Exception:
                return JSONResponse({})
        return JSONResponse({})

    @app.post("/api/pid/layout")
    async def save_pid_layout(request: Request):
        """Save P&ID node positions to file."""
        try:
            data = await request.json()
            pid_layout_file.parent.mkdir(parents=True, exist_ok=True)
            pid_layout_file.write_text(json.dumps(data, indent=2))
            return JSONResponse({"status": "ok"})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    @app.delete("/api/pid/layout")
    async def reset_pid_layout():
        """Delete saved P&ID node positions, reverting to defaults."""
        try:
            if pid_layout_file.exists():
                pid_layout_file.unlink()
            return JSONResponse({"status": "ok"})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    # =====================================================================
    # Equipment Module / Control Module endpoints (ISA-88 layer)
    # =====================================================================

    @app.get("/api/equipment/status")
    async def get_equipment_status():
        """Full EM + CM status tree."""
        if em_manager is None:
            return JSONResponse({"equipment_modules": {}, "control_modules": {}})
        return JSONResponse(em_manager.get_status())

    @app.get("/api/equipment/modules")
    async def get_equipment_modules():
        """Summary list of EMs for dropdown rendering."""
        if em_manager is None:
            return JSONResponse([])
        return JSONResponse(em_manager.get_em_list())

    @app.post("/api/equipment/mode")
    async def set_equipment_mode(req: EquipmentModeRequest):
        """Request an EM mode change."""
        if em_manager is None:
            return JSONResponse(
                {"error": "No equipment modules configured"}, status_code=400,
            )
        ok = em_manager.request_mode(req.em_tag, req.mode)
        if not ok:
            return JSONResponse(
                {"error": f"Mode change rejected for {req.em_tag} -> {req.mode}"},
                status_code=400,
            )
        return JSONResponse({"status": "ok", "em_tag": req.em_tag, "mode": req.mode})

    @app.get("/api/equipment/em/{em_tag}")
    async def get_em_detail(em_tag: str):
        """Single EM detail status."""
        if em_manager is None:
            return JSONResponse({"error": "No equipment modules configured"}, status_code=404)
        status = em_manager.get_em_status(em_tag)
        if status is None:
            return JSONResponse({"error": f"EM '{em_tag}' not found"}, status_code=404)
        return JSONResponse(status)

    @app.get("/api/equipment/cm/{cm_tag}")
    async def get_cm_detail(cm_tag: str):
        """Single CM detail status."""
        if em_manager is None:
            return JSONResponse({"error": "No equipment modules configured"}, status_code=404)
        status = em_manager.get_cm_status(cm_tag)
        if status is None:
            return JSONResponse({"error": f"CM '{cm_tag}' not found"}, status_code=404)
        return JSONResponse(status)

    return app


async def start_web_server(app: FastAPI, port: int) -> None:
    """Run uvicorn in the current event loop."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
