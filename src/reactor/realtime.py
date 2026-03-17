"""Main entry point for running the procedure against physical OPC equipment in real-time.

This module replaces physics model execution with direct OPC mapping interactions.
It uses an `OpcCMAdapter` instead of a `SimulationCMAdapter` for control modules.
It executes the BatchEngine at 1 Hz synchronous loop, enforcing a physical heartbeat (watchdog).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .batch import build_csv_header
from .batch_state import BatchCommand, BatchState, BatchStateMachine
from .config import ModelConfig, Settings
from .controller import BatchController
from .em_manager import EMManager
from .execution_adapters import CMAdapter, OpcCMAdapter
from .opc_mapping import OPCMappingManager
from .opc_tool_client import OPCToolClient
from .physics import ReactorModel, ReactorState
from .procedure import ProcedurePlayer, load_procedure


logger = logging.getLogger("reactor.realtime")


async def run_realtime(settings: Settings) -> None:
    """Run the exact procedure against physical equipment in real-time."""
    
    # Ensure physical execution mode
    from .config import ExecutionMode
    settings.execution_mode = ExecutionMode.PHYSICAL
    
    project_root = Path.cwd()

    # --- Load model config ---
    cfg_path = Path(settings.model_config_file)
    if not cfg_path.is_absolute():
        cfg_path = project_root / cfg_path
    model_cfg = ModelConfig.from_file(cfg_path)
    logger.info("Loaded model config from %s", cfg_path)

    # --- Dummy physics model (used for constants and structures only) ---
    initial_state = ReactorState()
    model = ReactorModel(model_config=model_cfg, initial_state=initial_state)

    # --- Load recipe ---
    recipe_path = Path(settings.recipe_file)
    if not recipe_path.is_absolute():
        recipe_path = project_root / recipe_path
    procedure = load_procedure(recipe_path)
    player = ProcedurePlayer(procedure)
    
    # --- Controller ---
    dt = settings.tick_interval
    controller = BatchController(model, controller_cfg=model_cfg.controller)
    controller.recipe_player = player
    controller._dt = dt

    # --- Init OPC ---
    opc_tool = OPCToolClient(base_url=settings.opc_tool_url)
    if await opc_tool.check_health():
        logger.info("Connected to OPC Tool at %s", settings.opc_tool_url)
    else:
        logger.error("OPC Tool not reachable at %s. Real-time execution requires OPC!", settings.opc_tool_url)
        return

    mapping_path = project_root / "configs" / "opc_mappings.json"
    mapping_mgr = OPCMappingManager(mapping_path)
    
    opc_cache: dict[str, Any] = {}
    opc_write_queue: list[tuple[str, Any]] = []

    # --- Equipment Module Manager (ISA-88 layer) ---
    em_manager: EMManager | None = None
    if model_cfg.has_equipment:
        def _opc_adapter_factory(cm_tag: str, em_tag: str) -> CMAdapter:
            return OpcCMAdapter(opc_cache, opc_write_queue, mapping_mgr)

        em_manager = EMManager(
            equipment_cfg=model_cfg.equipment,
            adapter_factory=_opc_adapter_factory,
        )

    # --- ISA-88 Batch State Machine ---
    batch_sm = BatchStateMachine()

    # --- CSV Log ---
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    csv_path = log_dir / f"live_realtime_{datetime.now():%Y%m%d_%H%M%S}.csv"
    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(build_csv_header(model) + ["watchdog"])

    logger.info("Starting real-time execution loop. dt=%.2f s", dt)
    
    # Automatically start batch machine
    batch_sm.dispatch(BatchCommand.START, 0.0)
    controller.start_recipe()

    elapsed = 0.0
    wall_start = time.monotonic()
    watchdog_counter = 0

    try:
        while True:
            tick_start = time.monotonic()
            
            # --- 1. Read Inputs via OPC ---
            read_mappings = mapping_mgr.get_read_mappings()
            node_ids = [m.opc_node_id for m in read_mappings if m.enabled]
            
            if node_ids:
                try:
                    values = await opc_tool.get_values_bulk(node_ids)
                    for mapping in read_mappings:
                        if not mapping.enabled:
                            continue
                        raw_val = values.get(mapping.opc_node_id)
                        if raw_val is not None:
                            val = mapping.apply_transform(raw_val)
                            # Provide direct caching for OpcCMAdapter mappings
                            # E.g. command / feedback mappings.
                            opc_cache[mapping.reactor_var] = val
                            
                            # Inject generic process values into the dummy model state directly
                            if mapping.reactor_var == "temperature":
                                model.state.temperature = val
                            elif mapping.reactor_var == "jacket_temperature":
                                model.state.jacket_temperature = val
                            elif hasattr(model.state, mapping.reactor_var):
                                setattr(model.state, mapping.reactor_var, val)
                except Exception as e:
                    logger.error("OPC Read failure: %s", e)
                    # Trigger OPC communication fault -> HOLD batch
                    if batch_sm.state == BatchState.RUNNING:
                        logger.warning("Triggering HOLD due to OPC read failure!")
                        batch_sm.dispatch(BatchCommand.HOLD, elapsed)

            # --- 2. Execute Control Logic ---
            if batch_sm.is_physics_active:
                setpoints: dict[str, object] = {}
                if batch_sm.is_procedure_active and not player.finished:
                    tick_context: dict[str, object] = {
                        "temperature_K": float(model.state.temperature),
                    }
                    if em_manager is not None:
                        tick_context["em_status"] = em_manager.get_mode_snapshot()

                    setpoints = player.tick(dt, context=tick_context)
                    
                    if em_manager is not None:
                        em_manager.dispatch_recipe_modes(setpoints)
                        em_manager.tick(dt)
                
                controller.evaluate()
                
                if player.finished and batch_sm.state == BatchState.RUNNING:
                    batch_sm.complete(elapsed)
                    
            if batch_sm.state in (BatchState.COMPLETE, BatchState.ABORTED, BatchState.STOPPED):
                logger.info("Batch terminated with state: %s. Exiting realtime loop.", batch_sm.state)
                break

            # --- 3. Watchdog & Write Outputs via OPC ---
            watchdog_counter = (watchdog_counter + 1) % 10000
            
            # Form write payload
            write_updates: dict[str, Any] = {}
            write_mappings = mapping_mgr.get_write_mappings()
            mapping_dict = {m.reactor_var: m.opc_node_id for m in write_mappings if m.enabled}
            
            # Watchdog heartbeat
            if "watchdog" in mapping_dict:
                write_updates[mapping_dict["watchdog"]] = watchdog_counter
                
            # Pop items from the write queue of the CM Adapters
            while opc_write_queue:
                key, value = opc_write_queue.pop(0)
                if key in mapping_dict: # logical -> node_id via mapping
                    write_updates[mapping_dict[key]] = value
                else:
                    # assume standard raw node id mapping from OpcCMAdapter abstraction
                    write_updates[key] = value

            if write_updates:
                try:
                    await opc_tool.write_values_bulk(write_updates)
                except Exception as e:
                    logger.error("OPC Write failure: %s", e)
                    # Safety interlock!
                    if batch_sm.state == BatchState.RUNNING:
                        logger.warning("Triggering HOLD due to OPC write failure!")
                        batch_sm.dispatch(BatchCommand.HOLD, elapsed)

            # --- 4. Log ---
            s = model.state
            row = [
                round(elapsed, 2), dt, 0.0, "realtime",
                round(s.temperature, 4), round(s.jacket_temperature, 4),
                0.0, 0.0,
            ]
            for c in model.network.conversion_names:
                row.append(0.0)
            for sp in model.network.species_names:
                row.append(0.0)
            row.append(0.0)
            for sp in model.network.species_names:
                row.append(0.0)
            row.extend([
                0.0, 0.0, controller.phase.name,
                player.current_step.name if player.current_step else "DONE",
                player.current_operation_name or "DONE",
                "opc", "physical", False, batch_sm.state.value,
                watchdog_counter
            ])
            csv_writer.writerow(row)

            # Sleep exactly `dt` wallclock seconds, minus execution time.
            elapsed += dt
            tick_elapsed = time.monotonic() - tick_start
            sleep_time = max(0.0, dt - tick_elapsed)
            
            if tick_elapsed > dt * 1.5:
                logger.warning("Tick overrun! execution time %.3fs > interval %.3fs", tick_elapsed, dt)
                
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        logger.info("Realtime execution cancelled")
    except Exception as e:
        logger.exception("Fatal runtime error in realtime execute: %s", e)
    finally:
        csv_file.close()
        logger.info("CSV log saved: %s", csv_path)
        await opc_tool.close()
        logger.info("Realtime shutdown complete. Elapsed wall clock: %.1fs", (time.monotonic() - wall_start))


def main() -> None:
    parser = argparse.ArgumentParser("Realtime Execution Entrypoint")
    parser.add_argument("--config", type=str, required=True)
    parser.add_argument("--recipe", type=str, required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    
    settings = Settings()
    settings.recipe_file = args.recipe
    settings.model_config_file = args.config
    
    asyncio.run(run_realtime(settings))

if __name__ == "__main__":
    main()
