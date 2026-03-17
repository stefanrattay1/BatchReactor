#!/usr/bin/env python3
"""Interactive OPC UA client for the reactor digital twin.

Usage:
    python scripts/opcua_client.py              # default: monitor mode
    python scripts/opcua_client.py start        # send START then monitor
    python scripts/opcua_client.py reset        # send RESET then monitor
    python scripts/opcua_client.py set-jacket 360.0   # override jacket temp
    python scripts/opcua_client.py monitor      # just poll sensors

Connects to opc.tcp://localhost:4840 by default.
Set REACTOR_OPC_ENDPOINT env var to change.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from asyncua import Client, ua


ENDPOINT = os.environ.get("REACTOR_OPC_ENDPOINT", "opc.tcp://localhost:4840")
NAMESPACE = "urn:reactor:digitaltwin"
POLL_INTERVAL = 1.0  # seconds


async def get_nodes(client: Client, idx: int) -> dict:
    """Build a dict of node references for easy access."""
    reactor = await client.nodes.objects.get_child(f"{idx}:Reactor")
    sensors = await reactor.get_child(f"{idx}:Sensors")
    actuators = await reactor.get_child(f"{idx}:Actuators")
    status = await reactor.get_child(f"{idx}:Status")
    recipe = await reactor.get_child(f"{idx}:Recipe")

    return {
        "temperature": await sensors.get_child(f"{idx}:Temperature_K"),
        "pressure": await sensors.get_child(f"{idx}:Pressure_bar"),
        "conversion": await sensors.get_child(f"{idx}:Conversion"),
        "viscosity": await sensors.get_child(f"{idx}:Viscosity_Pas"),
        "mass_total": await sensors.get_child(f"{idx}:MassTotal_kg"),
        "fsm_state": await status.get_child(f"{idx}:FSM_State"),
        "fsm_state_name": await status.get_child(f"{idx}:FSM_StateName"),
        "batch_elapsed": await status.get_child(f"{idx}:BatchElapsed_s"),
        "jacket_setpoint": await actuators.get_child(f"{idx}:JacketSetpoint_K"),
        "agitator_speed": await actuators.get_child(f"{idx}:AgitatorSpeed_rpm"),
        "feed_valve": await actuators.get_child(f"{idx}:FeedValve_pct"),
        "command": await recipe.get_child(f"{idx}:Command"),
        "recipe_name": await recipe.get_child(f"{idx}:RecipeName"),
    }


async def read_all_sensors(nodes: dict) -> dict:
    """Read all sensor and status values."""
    return {
        "Temperature (K)": await nodes["temperature"].read_value(),
        "Pressure (bar)": await nodes["pressure"].read_value(),
        "Conversion": await nodes["conversion"].read_value(),
        "Viscosity (Pa.s)": await nodes["viscosity"].read_value(),
        "Mass Total (kg)": await nodes["mass_total"].read_value(),
        "FSM State": await nodes["fsm_state_name"].read_value(),
        "Batch Elapsed (s)": await nodes["batch_elapsed"].read_value(),
    }


def print_sensors(values: dict, elapsed_wall: float) -> None:
    """Pretty-print sensor readings."""
    print(f"\n--- Reactor Status (wall time: {elapsed_wall:.1f}s) ---")
    for key, val in values.items():
        if isinstance(val, float):
            print(f"  {key:>20s}: {val:>10.3f}")
        else:
            print(f"  {key:>20s}: {val}")
    print()


async def monitor(client: Client, nodes: dict, duration: float = 60.0) -> None:
    """Poll sensors every POLL_INTERVAL seconds."""
    t0 = time.time()
    print(f"Monitoring for {duration:.0f}s (Ctrl+C to stop)...")
    try:
        while time.time() - t0 < duration:
            values = await read_all_sensors(nodes)
            print_sensors(values, time.time() - t0)
            await asyncio.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped.")


async def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "monitor"

    print(f"Connecting to {ENDPOINT} ...")
    async with Client(ENDPOINT) as client:
        idx = await client.get_namespace_index(NAMESPACE)
        nodes = await get_nodes(client, idx)
        print(f"Connected. Namespace index: {idx}")

        if command == "start":
            print("Sending START command...")
            await nodes["command"].write_value(
                ua.DataValue(ua.Variant("START", ua.VariantType.String))
            )
            await monitor(client, nodes, duration=300.0)

        elif command == "reset":
            print("Sending RESET command...")
            await nodes["command"].write_value(
                ua.DataValue(ua.Variant("RESET", ua.VariantType.String))
            )
            await monitor(client, nodes, duration=30.0)

        elif command == "set-jacket":
            if len(args) < 2:
                print("Usage: set-jacket <temperature_K>")
                sys.exit(1)
            temp = float(args[1])
            print(f"Setting jacket setpoint to {temp:.1f} K...")
            await nodes["jacket_setpoint"].write_value(
                ua.DataValue(ua.Variant(temp, ua.VariantType.Double))
            )
            await monitor(client, nodes, duration=60.0)

        elif command == "monitor":
            await monitor(client, nodes, duration=300.0)

        elif command == "snapshot":
            values = await read_all_sensors(nodes)
            print_sensors(values, 0.0)

        else:
            print(f"Unknown command: {command}")
            print("Commands: start, reset, set-jacket <K>, monitor, snapshot")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
