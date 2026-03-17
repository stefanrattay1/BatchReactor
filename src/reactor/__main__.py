"""Main entry point for the reactor digital twin simulation."""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import time
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import copy

from .audit_trail import AuditTrail, build_state_snapshot
from .batch import build_csv_header
from .alarm_management import AlarmManager
from .batch_state import BatchCommand, BatchState, BatchStateMachine
from .config import ModelConfig, Settings
from .controller import BatchController
from .em_manager import EMManager
from .execution_adapters import CMAdapter, SimulationCMAdapter
from .opc_tool_client import OPCToolClient
from .opc_mapping import OPCMappingManager
from .playback import DataPackagePlayer
from .physics import ReactorModel, ReactorState
from .procedure import ProcedurePlayer, load_procedure
from .recipe import add_sensor_noise, load_recipe  # load_recipe kept for compat
from .sensor_buffer import SensorBuffer
from .test_inputs import TestInputPlayer

logger = logging.getLogger("reactor")


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


def resolve_project_root() -> Path:
    """Resolve the project root for config/recipe/assets lookups.

    When installed as a package, __file__ lives in site-packages, so
    prefer the current working directory if it contains runtime assets.
    """
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "configs").is_dir() and (candidate / "recipes").is_dir():
            return candidate
    return candidates[0]


async def run_simulation(settings: Settings) -> None:
    """Run the reactor simulation loop."""
    project_root = resolve_project_root()
    if settings.build_frontend and settings.enable_web:
        frontend_dir = project_root / "frontend"
        npm = shutil.which("npm")
        if not npm:
            logger.warning("npm not found; skipping frontend build")
        elif not frontend_dir.exists():
            logger.warning("frontend directory not found; skipping frontend build")
        else:
            logger.info("Building frontend (npm run build)...")
            try:
                subprocess.run([npm, "run", "build"], cwd=str(frontend_dir), check=True)
            except subprocess.CalledProcessError as exc:
                logger.warning("Frontend build failed: %s", exc)

    # --- Load model config ---
    cfg_path = Path(settings.model_config_file)
    if not cfg_path.is_absolute():
        cfg_path = project_root / cfg_path
    model_cfg = ModelConfig.from_file(cfg_path)
    logger.info("Loaded model config from %s", cfg_path)

    # --- Initialise physics model ---
    ic = model_cfg.initial_conditions
    reactor_cfg = model_cfg.reactor
    initial_state = ReactorState(
        temperature=ic.get("temperature", 298.15),
        jacket_temperature=ic.get("jacket_temperature", 298.15),
        volume=reactor_cfg.get("volume_m3", 0.1),
    )
    model = ReactorModel(model_config=model_cfg, initial_state=initial_state)
    logger.info("Reactor: %.1f m³ working volume, %.1f L vessel capacity, %.1f bar",
                model.state.volume, model.vessel_volume_L, model.pressure_bar)

    # --- Load recipe as ISA-88 Procedure ---
    recipe_path = Path(settings.recipe_file)
    if not recipe_path.is_absolute():
        recipe_path = project_root / recipe_path
    procedure = load_procedure(recipe_path)
    player = ProcedurePlayer(procedure)
    n_ops = sum(len(up.operations) for up in procedure.unit_procedures)
    logger.info("Loaded recipe: %s (%d phases, %d operations)",
                procedure.name, len(procedure.phases_flat), n_ops)

    # --- Load test inputs (optional) ---
    # Use a mutable dict so the web API can load/replace test inputs at runtime.
    test_state: dict[str, TestInputPlayer | None] = {"player": None}
    if settings.test_inputs_file:
        ti_path = Path(settings.test_inputs_file)
        if not ti_path.is_absolute():
            ti_path = project_root / ti_path
        test_state["player"] = TestInputPlayer.from_yaml(ti_path)
        logger.info(
            "Loaded test inputs: %s (%d events)",
            test_state["player"].active_name,
            len(test_state["player"].plan.events),
        )

    # --- Sensor buffer for synchronized external inputs ---
    sensor_buffer = SensorBuffer()

    # --- Shared simulation state (readable by web API) ---
    sim_state: dict = {
        "recipe_jacket_K": settings.initial_temp_k,
        "actual_jacket_K": settings.initial_temp_k,
        "override_active": False,
        "override_source": "none",
        "elapsed_s": 0.0,
        "tick_interval": settings.tick_interval,
        "simulation_solve_count": 0,
        # Config management
        "pending_config": None,
        "active_config_file": settings.model_config_file,
        "base_config_raw": copy.deepcopy(model_cfg.raw),
    }

    # --- Data package playback (optional) ---
    playback_state: dict[str, DataPackagePlayer | None] = {"player": None}
    if settings.data_package_file:
        dp_path = Path(settings.data_package_file)
        if not dp_path.is_absolute():
            dp_path = project_root / dp_path
        playback_state["player"] = DataPackagePlayer.from_json(dp_path)
        logger.info(
            "Loaded data package: %s (%d snapshots)",
            playback_state["player"].package.name,
            playback_state["player"].package.total_snapshots,
        )

    # --- CSV log file ---
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    csv_path = log_dir / f"sim_{datetime.now():%Y%m%d_%H%M%S}.csv"
    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_header = build_csv_header(model)
    csv_writer.writerow(csv_header)
    csv_file.flush()
    logger.info("CSV log: %s", csv_path)

    # --- Initialise controller ---
    controller = BatchController(model, controller_cfg=model_cfg.controller)
    controller.recipe_player = player
    controller._dt = settings.tick_interval

    # --- Initialise Equipment Module Manager (optional ISA-88 layer) ---
    em_manager: EMManager | None = None
    if model_cfg.has_equipment:
        def _sim_adapter_factory(cm_tag: str, em_tag: str) -> CMAdapter:
            src = f"em:{em_tag}" if em_tag else f"cm:{cm_tag}"
            return SimulationCMAdapter(model, sensor_buffer, src)

        em_manager = EMManager(
            equipment_cfg=model_cfg.equipment,
            adapter_factory=_sim_adapter_factory,
        )
        logger.info(
            "Equipment modules: %d EMs, %d CMs",
            len(em_manager._ems), len(em_manager._cms),
        )

    # --- Audit trail ---
    audit_trail: AuditTrail | None = None
    if settings.audit_trail_enabled:
        from datetime import datetime as _dt
        audit_log_path = log_dir / f"audit_{_dt.now():%Y%m%d_%H%M%S}.jsonl"
        audit_trail = AuditTrail(
            log_path=audit_log_path,
            enable_hash_chain=settings.audit_trail_hash_chain,
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

    # --- Initialise OPC Tool client ---
    opc_tool: OPCToolClient | None = None
    mapping_mgr: OPCMappingManager | None = None

    if settings.opc_tool_enabled:
        opc_tool = OPCToolClient(base_url=settings.opc_tool_url)
        if await opc_tool.check_health():
            logger.info("Connected to OPC Tool at %s", settings.opc_tool_url)
        else:
            logger.warning(
                "OPC Tool not reachable at %s — running without OPC integration "
                "(will retry every 30s)",
                settings.opc_tool_url,
            )

        mapping_path = project_root / "configs" / "opc_mappings.json"
        mapping_mgr = OPCMappingManager(mapping_path)
        logger.info(
            "OPC mappings: %d read, %d write",
            len(mapping_mgr.get_read_mappings()),
            len(mapping_mgr.get_write_mappings()),
        )

    # --- Optionally start web dashboard ---
    web_task: asyncio.Task | None = None
    if settings.enable_web:
        from .web import create_app, start_web_server

        app = create_app(
            model, controller, player, settings,
            test_state=test_state, sim_state=sim_state,
            playback_state=playback_state, csv_path=csv_path,
            opc_tool_client=opc_tool,
            mapping_manager=mapping_mgr,
            sensor_buffer=sensor_buffer,
            em_manager=em_manager,
            batch_sm=batch_sm,
            alarm_manager=alarm_manager,
            audit_trail=audit_trail,
        )
        web_task = asyncio.create_task(start_web_server(app, settings.web_port))
        logger.info("Web dashboard at http://localhost:%d", settings.web_port)

    elapsed = 0.0
    wall_ticks = 0  # counts loop iterations for auto-start delay
    started = False
    simulation_solve_count = 0
    last_phase_idx = player.current_phase_idx
    last_controller_phase = controller.phase

    try:
        while True:
            tick_start = time.monotonic()

            # --- Read current tick interval (changeable at runtime via web API) ---
            dt = sim_state["tick_interval"]

            # --- Playback mode: replay recorded data, skip all physics ---
            pb_player = playback_state.get("player")
            if pb_player is not None:
                if pb_player.playing:
                    # Log playback start once
                    if not hasattr(pb_player, '_logged_start'):
                        logger.info("⏵ [PLAYBACK] Starting: %s", pb_player.package.name)
                        pb_player._logged_start = True
                    pb_player.tick()
                await asyncio.sleep(
                    pb_player.package.tick_interval if pb_player.playing else dt
                )
                continue

            # --- Check for commands via OPC Tool (read "command" node if mapped) ---
            if opc_tool and opc_tool.available and mapping_mgr:
                try:
                    read_mappings = mapping_mgr.get_read_mappings()
                    if read_mappings:
                        node_ids = [m.opc_node_id for m in read_mappings if m.enabled]
                        if node_ids:
                            values = await opc_tool.get_values_bulk(node_ids)
                            for mapping in read_mappings:
                                if not mapping.enabled:
                                    continue
                                raw_val = values.get(mapping.opc_node_id)
                                if raw_val is None:
                                    continue
                                # Handle command nodes specially
                                if mapping.reactor_var == "command":
                                    cmd = str(raw_val).upper()
                                    if cmd == "START" and batch_sm.state == BatchState.IDLE:
                                        batch_sm.dispatch(BatchCommand.START, elapsed)
                                        controller.start_recipe()
                                        started = True
                                        logger.info("Recipe started via OPC Tool command")
                                    elif cmd == "HOLD":
                                        batch_sm.dispatch(BatchCommand.HOLD, elapsed)
                                        logger.info("Batch HOLD via OPC Tool command")
                                    elif cmd == "RESTART":
                                        batch_sm.dispatch(BatchCommand.RESTART, elapsed)
                                        logger.info("Batch RESTART via OPC Tool command")
                                    elif cmd == "ABORT":
                                        batch_sm.dispatch(BatchCommand.ABORT, elapsed)
                                        logger.info("Batch ABORT via OPC Tool command")
                                    elif cmd == "RESET":
                                        controller.reset_alarm()
                                        logger.info("Alarm reset via OPC Tool command")
                                else:
                                    transformed = mapping.apply_transform(raw_val)
                                    sensor_buffer.write(
                                        mapping.reactor_var, transformed,
                                        source="opc_tool", priority=mapping.priority,
                                    )
                except Exception as e:
                    logger.warning("OPC Tool read failed: %s", e)
            elif opc_tool and not opc_tool.available:
                # Periodically retry connection
                await opc_tool.maybe_reconnect()

            # --- Check for commands from web API ---
            web_cmd = await controller.get_pending_command()
            if web_cmd:
                if web_cmd == "START" and batch_sm.state == BatchState.IDLE:
                    batch_sm.dispatch(BatchCommand.START, elapsed)
                    controller.start_recipe()
                    started = True
                    logger.info("Recipe started via web API")
                elif web_cmd == "HOLD":
                    batch_sm.dispatch(BatchCommand.HOLD, elapsed)
                    logger.info("Batch HOLD via web API")
                elif web_cmd == "RESTART":
                    batch_sm.dispatch(BatchCommand.RESTART, elapsed)
                    logger.info("Batch RESTART via web API")
                elif web_cmd == "ABORT":
                    batch_sm.dispatch(BatchCommand.ABORT, elapsed)
                    logger.info("Batch ABORT via web API")
                elif web_cmd == "RESET":
                    controller.reset_alarm()
                    logger.info("Alarm reset via web API")
                elif web_cmd == "STOP":
                    batch_sm.dispatch(BatchCommand.STOP, elapsed)
                    controller.stop()
                    started = False
                    logger.info("Recipe stopped via web API")

            # --- Process test input events ---
            test_player = test_state["player"]
            if test_player is not None:
                for event in test_player.due_events(elapsed):
                    if event.action == "command":
                        cmd = str(event.value).upper()
                        if cmd == "START" and batch_sm.state == BatchState.IDLE:
                            batch_sm.dispatch(BatchCommand.START, elapsed)
                            controller.start_recipe()
                            started = True
                            logger.info("[TEST-INPUT t=%.1fs] START command", elapsed)
                        elif cmd == "HOLD":
                            batch_sm.dispatch(BatchCommand.HOLD, elapsed)
                            logger.info("[TEST-INPUT t=%.1fs] HOLD command", elapsed)
                        elif cmd == "RESTART":
                            batch_sm.dispatch(BatchCommand.RESTART, elapsed)
                            logger.info("[TEST-INPUT t=%.1fs] RESTART command", elapsed)
                        elif cmd == "ABORT":
                            batch_sm.dispatch(BatchCommand.ABORT, elapsed)
                            logger.info("[TEST-INPUT t=%.1fs] ABORT command", elapsed)
                        elif cmd == "RESET":
                            controller.reset_alarm()
                            logger.info("[TEST-INPUT t=%.1fs] RESET command", elapsed)
                        elif cmd == "STOP":
                            batch_sm.dispatch(BatchCommand.STOP, elapsed)
                            controller.stop()
                            started = False
                            logger.info("[TEST-INPUT t=%.1fs] STOP command", elapsed)
                    elif event.action == "set_jacket":
                        temp = float(event.value)
                        sensor_buffer.write(
                            "jacket_temperature", temp,
                            source="test_input", priority=60,
                        )
                        logger.info(
                            "[TEST-INPUT t=%.1fs] jacket setpoint -> %.1f K",
                            elapsed, temp,
                        )
                    elif event.action == "clear_jacket":
                        sensor_buffer.clear_source("test_input")
                        logger.info(
                            "[TEST-INPUT t=%.1fs] jacket override cleared", elapsed,
                        )

            # --- Auto-start if not waiting for OPC UA command ---
            wall_ticks += 1
            if not started and batch_sm.state == BatchState.IDLE and wall_ticks * dt >= 1.0 and settings.auto_start:
                batch_sm.dispatch(BatchCommand.START, elapsed)
                controller.start_recipe()
                started = True
                logger.info("Recipe auto-started")

            # --- Only run physics when simulation is active ---
            if started:
                # ===== PHASE 1: COLLECT — all sources write to buffer =====

                # Recipe setpoints
                setpoints: dict[str, object] = {}
                recipe_jacket_K = model.state.jacket_temperature
                if batch_sm.is_procedure_active and not player.finished:
                    tick_context: dict[str, object] = {
                        "conversion": float(model.state.conversion),
                        "temperature_K": float(model.state.temperature),
                    }
                    if em_manager is not None:
                        tick_context["em_status"] = em_manager.get_mode_snapshot()

                    setpoints = player.tick(dt, context=tick_context)
                    if "jacket_temp" in setpoints:
                        recipe_jacket_K = setpoints["jacket_temp"]
                        sensor_buffer.write(
                            "jacket_temperature", recipe_jacket_K,
                            source="recipe", priority=10,
                        )
                    # Feed rates bypass the buffer (not state variables)
                    for index, sp_name in enumerate(model.network.species_names):
                        generic_key = None
                        if index == 0:
                            generic_key = "feed_component_a"
                        elif index == 1:
                            generic_key = "feed_component_b"

                        rate = setpoints.get(generic_key, 0.0) if generic_key is not None else 0.0
                        model.set_feed_rate(sp_name, float(rate or 0.0))
                else:
                    # HELD, STOPPED, or recipe finished: zero all feeds
                    for sp_name in model.network.species_names:
                        model.set_feed_rate(sp_name, 0.0)

                # (OPC Tool reads already wrote to buffer above)

                # ===== EM/CM layer: dispatch recipe modes + tick EMs =====
                if em_manager is not None:
                    em_manager.dispatch_recipe_modes(setpoints if batch_sm.is_procedure_active and not player.finished else {})
                    em_manager.tick(dt)

                # ===== PHASE 2 + 3: RESOLVE & APPLY =====
                resolved_sources = sensor_buffer.apply_to_state(model.state)

                # Determine override tracking from resolved sources
                jacket_source = resolved_sources.get("jacket_temperature", "recipe")
                override_source = "none" if jacket_source == "recipe" else jacket_source
                actual_jacket_K = model.state.jacket_temperature

                # Update shared state for web API
                sim_state["recipe_jacket_K"] = recipe_jacket_K
                sim_state["actual_jacket_K"] = actual_jacket_K
                sim_state["override_active"] = override_source != "none"
                sim_state["override_source"] = override_source

                # ===== PHASE 4: STEP — physics integration (RUNNING + HELD) =====
                solve_wall_ms = 0.0
                if batch_sm.is_physics_active:
                    solve_t0 = time.monotonic()
                    model.step(dt)
                    solve_wall_ms = round((time.monotonic() - solve_t0) * 1000, 1)
                    simulation_solve_count += 1
                    sim_state["simulation_solve_count"] = simulation_solve_count
                    logger.info(
                        "[LIVE SOLVE #%d] t=%.2fs dt=%.3fs method=%s wall=%.1fms",
                        simulation_solve_count,
                        elapsed,
                        dt,
                        model.last_solve_method,
                        solve_wall_ms,
                    )

                # --- Detect recipe phase transitions ---
                if player.current_phase_idx != last_phase_idx:
                    from_name = (
                        procedure.phases_flat[last_phase_idx].name
                        if 0 <= last_phase_idx < len(procedure.phases_flat)
                        else "START"
                    )
                    to_name = player.current_step.name if player.current_step else "DONE"
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

                # --- Evaluate FSM ---
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
                from .controller import Phase as CtrlPhase
                alarm_signals: dict[str, bool] = {
                    "controller.runaway": controller.phase == CtrlPhase.RUNAWAY_ALARM,
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
                sim_state["alarm_summary"] = alarm_manager.to_dict()

                # --- Auto-complete: recipe finished while RUNNING ---
                if player.finished and batch_sm.state == BatchState.RUNNING:
                    batch_sm.complete(elapsed)

                # --- Runaway triggers ABORT ---
                if controller.phase == CtrlPhase.RUNAWAY_ALARM and batch_sm.state == BatchState.RUNNING:
                    batch_sm.dispatch(BatchCommand.ABORT, elapsed)

                # --- Log to CSV ---
                s = model.state
                # Determine data mode and fake sensors state for CSV
                data_mode = "playback" if (pb_player and pb_player.playing) else ("test_input" if test_player is not None else "live")
                fake_sensors_active = sim_state.get("fake_sensors_enabled", False)
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
                    override_source,
                    data_mode,
                    fake_sensors_active,
                    batch_sm.state.value,
                ])
                csv_writer.writerow(row)
                csv_file.flush()

            # --- Write reactor state to OPC Tool ---
            if opc_tool and opc_tool.available and mapping_mgr:
                try:
                    write_mappings = mapping_mgr.get_write_mappings()
                    if write_mappings:
                        updates: dict[str, object] = {}
                        for mapping in write_mappings:
                            if not mapping.enabled:
                                continue
                            # Resolve reactor variable to a value
                            val = _resolve_reactor_var(
                                mapping.reactor_var, model, controller, elapsed, settings,
                                sim_state,
                            )
                            if val is not None:
                                updates[mapping.opc_node_id] = val
                        if updates:
                            await opc_tool.write_values_bulk(updates)
                except Exception as e:
                    logger.warning("OPC Tool write failed: %s", e)

            if started:
                elapsed += dt
                sim_state["elapsed_s"] = elapsed

            # Log progress periodically
            if started and int(elapsed) % 30 == 0 and abs(elapsed % 30) < dt:
                # Determine mode prefix
                mode_prefix = "[PLAYBACK]" if pb_player and pb_player.playing else "[TEST-INPUT]" if test_player is not None else "[LIVE]"
                logger.info(
                    "%s solve#=%d t=%.0fs  T=%.1fK  alpha=%.3f  phase=%s  visc=%.1f",
                    mode_prefix,
                    simulation_solve_count,
                    elapsed,
                    model.state.temperature,
                    model.state.conversion,
                    controller.phase.name,
                    model.viscosity,
                )

            # Sleep only the remaining time to maintain consistent tick intervals
            tick_elapsed = time.monotonic() - tick_start
            sleep_time = max(0, dt - tick_elapsed)
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        logger.info("Simulation cancelled")
    finally:
        csv_file.close()
        logger.info("CSV log saved: %s", csv_path)
        if audit_trail is not None:
            audit_trail.close()
            logger.info("Audit trail saved: %s", audit_trail._log_path)
        if web_task is not None:
            web_task.cancel()
        if opc_tool:
            await opc_tool.close()
            logger.info("OPC Tool client closed")


def _resolve_reactor_var(
    var: str,
    model: ReactorModel,
    controller: "BatchController",
    elapsed: float,
    settings: Settings,
    sim_state: dict,
) -> object | None:
    """Resolve a reactor variable name to its current value for OPC writes."""
    fake_sensors = sim_state.get("fake_sensors_enabled", False)

    if var == "temperature":
        val = model.state.temperature
        return add_sensor_noise(val, settings.noise_pct) if fake_sensors else val
    if var == "conversion":
        return model.state.conversion
    if var == "viscosity":
        val = model.viscosity
        return add_sensor_noise(val, settings.noise_pct) if fake_sensors else val
    if var == "pressure_bar":
        val = model.pressure_bar
        return add_sensor_noise(val, settings.noise_pct) if fake_sensors else val
    if var == "mass_total":
        return model.state.mass_total
    if var == "jacket_temperature":
        return model.state.jacket_temperature
    if var == "fsm_state":
        return int(controller.phase)
    if var == "fsm_state_name":
        return controller.phase.name
    if var == "batch_elapsed":
        return elapsed
    return None


def main_sync() -> None:
    """Synchronous entry point for console_scripts."""
    parser = argparse.ArgumentParser(description="Reactor Digital Twin Simulator")
    parser.add_argument("--batch", action="store_true",
                        help="Run in batch mode (no real-time pacing, no OPC UA/web)")
    parser.add_argument("--realtime", action="store_true",
                        help="Run in real-time mode against physical equipment (OPC UA)")
    parser.add_argument("--recipe", type=str, default=None,
                        help="Recipe YAML file (overrides REACTOR_RECIPE_FILE)")
    parser.add_argument("--config", type=str, default=None,
                        help="Model config file (YAML or JSON)")
    parser.add_argument("--test-inputs", type=str, default=None,
                        help="Test inputs YAML file")
    parser.add_argument("--post-recipe-time", type=float, default=None,
                        help="Seconds to continue after recipe finishes (batch mode)")
    parser.add_argument("--stop-conversion", type=float, default=None,
                        help="Stop when conversion reaches this value (batch mode)")
    parser.add_argument("--build-frontend", action="store_true",
                        help="Build the frontend before starting the web server")
    parser.add_argument("--batch-number", type=str, default=None,
                        help="Batch number for ISA-88 traceability (auto-generated if omitted)")
    parser.add_argument("--lot-number", type=str, default=None,
                        help="Lot number for ISA-88 traceability (auto-generated if omitted)")
    parser.add_argument("--product-code", type=str, default=None,
                        help="Product code for ISA-88 traceability")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    # Suppress noisy asyncua address_space warnings about missing standard nodes
    logging.getLogger("asyncua.server.address_space").setLevel(logging.WARNING)

    settings = Settings()

    # CLI overrides
    if args.batch:
        settings.batch_mode = True
    if args.realtime:
        settings.realtime_mode = True
    if args.recipe:
        settings.recipe_file = args.recipe
    if args.config:
        settings.model_config_file = args.config
    if args.test_inputs:
        settings.test_inputs_file = args.test_inputs
    if args.post_recipe_time is not None:
        settings.batch_post_recipe_time = args.post_recipe_time
    if args.stop_conversion is not None:
        settings.batch_stop_conversion = args.stop_conversion
    if args.build_frontend:
        settings.build_frontend = True
    # Build batch identity from CLI args
    cli_identity: dict[str, str] = {}
    if args.batch_number:
        cli_identity["batch_number"] = args.batch_number
    if args.lot_number:
        cli_identity["lot_number"] = args.lot_number
    if args.product_code:
        cli_identity["product_code"] = args.product_code
    if cli_identity:
        settings.batch_identity = cli_identity

    if settings.realtime_mode:
        from .realtime import run_realtime
        asyncio.run(run_realtime(settings))
    elif settings.batch_mode:
        from .batch import run_batch
        result = run_batch(settings)
        result.print_summary()
    else:
        asyncio.run(run_simulation(settings))


if __name__ == "__main__":
    main_sync()
