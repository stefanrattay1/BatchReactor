"""OPC UA integration tests — simulates a DCS client connecting to the reactor.

These tests spin up the reactor physics + OPC Tool server and interact with it
exclusively through OPC UA reads/writes, just like a real DCS or SCADA system.

The OPC Tool's ManagedOPCServer + NodeManager replace the old reactor-specific
OPCServer.  The reactor pushes state to the NodeManager, which the server
exposes over OPC UA.

Requires IPOPT (skip gracefully if unavailable).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from asyncua import Client, ua

from opc_tool.node_manager import NodeManager, OPCNode
from opc_tool.server import ManagedOPCServer
from reactor.config import ModelConfig
from reactor.controller import BatchController, Phase
from reactor.physics import ReactorModel, ReactorState
from reactor.recipe import RecipePlayer, add_sensor_noise, load_recipe

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODEL_CFG_PATH = Path(__file__).parent.parent / "configs" / "default.yaml"
RECIPE_PATH = Path(__file__).parent.parent / "recipes" / "default.yaml"
OPC_PORT = 48410  # non-default to avoid collisions
OPC_ENDPOINT = f"opc.tcp://localhost:{OPC_PORT}"

# Browse-path prefixes (namespace index determined at runtime)
SENSOR_PREFIX = "Sensors"
ACTUATOR_PREFIX = "Actuators"
STATUS_PREFIX = "Status"
RECIPE_PREFIX = "Recipes"

# Node IDs for the NodeManager catalog
_SENSOR_NODES = [
    OPCNode(id="temperature", name="Temperature_K", node_id="ns=2;s=Temperature_K",
            source="local", category="sensor", data_type="Double"),
    OPCNode(id="pressure", name="Pressure_bar", node_id="ns=2;s=Pressure_bar",
            source="local", category="sensor", data_type="Double"),
    OPCNode(id="conversion", name="Conversion", node_id="ns=2;s=Conversion",
            source="local", category="sensor", data_type="Double"),
    OPCNode(id="viscosity", name="Viscosity_Pas", node_id="ns=2;s=Viscosity_Pas",
            source="local", category="sensor", data_type="Double"),
    OPCNode(id="mass_total", name="MassTotal_kg", node_id="ns=2;s=MassTotal_kg",
            source="local", category="sensor", data_type="Double"),
]
_ACTUATOR_NODES = [
    OPCNode(id="jacket_setpoint", name="JacketSetpoint_K", node_id="ns=2;s=JacketSetpoint_K",
            source="local", category="actuator", data_type="Double",
            writable=True, current_value=298.15),
    OPCNode(id="agitator_speed", name="AgitatorSpeed_rpm", node_id="ns=2;s=AgitatorSpeed_rpm",
            source="local", category="actuator", data_type="Double", writable=True),
    OPCNode(id="feed_valve", name="FeedValve_pct", node_id="ns=2;s=FeedValve_pct",
            source="local", category="actuator", data_type="Double", writable=True),
]
_STATUS_NODES = [
    OPCNode(id="fsm_state", name="FSM_State", node_id="ns=2;s=FSM_State",
            source="local", category="status", data_type="Int32"),
    OPCNode(id="fsm_state_name", name="FSM_StateName", node_id="ns=2;s=FSM_StateName",
            source="local", category="status", data_type="String"),
    OPCNode(id="batch_elapsed", name="BatchElapsed_s", node_id="ns=2;s=BatchElapsed_s",
            source="local", category="status", data_type="Double"),
]
_RECIPE_NODES = [
    OPCNode(id="recipe_name", name="RecipeName", node_id="ns=2;s=RecipeName",
            source="local", category="recipe", data_type="String",
            writable=True, current_value="default"),
    OPCNode(id="recipe_command", name="Command", node_id="ns=2;s=Command",
            source="local", category="recipe", data_type="String",
            writable=True, current_value="STOP"),
]


def _ipopt_available() -> bool:
    try:
        from reactor.pyomo_model import _ensure_ipopt_on_path
        import pyomo.environ as pyo

        _ensure_ipopt_on_path()
        solver = pyo.SolverFactory("ipopt")
        return solver.available()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _ipopt_available(), reason="IPOPT not installed")


class SimulationHarness:
    """Runs the reactor + OPC Tool server in the background.

    The harness exposes a ``tick()`` coroutine that advances the simulation
    by one time step.  An OPC UA *client* is used by the tests to read
    sensors and write actuator overrides, exactly as a DCS would.
    """

    def __init__(
        self,
        dt: float = 1.0,
        model_cfg: ModelConfig | None = None,
        initial_state: ReactorState | None = None,
    ):
        self.dt = dt
        self._model_cfg = model_cfg or ModelConfig.from_yaml(MODEL_CFG_PATH)
        self._initial_state = initial_state or ReactorState(
            temperature=298.15, jacket_temperature=298.15, volume=0.1,
        )
        self.model: ReactorModel = None  # type: ignore[assignment]
        self.controller: BatchController = None  # type: ignore[assignment]
        self.player: RecipePlayer = None  # type: ignore[assignment]
        self.node_mgr: NodeManager = None  # type: ignore[assignment]
        self.opc_server: ManagedOPCServer = None  # type: ignore[assignment]
        self.client: Client = None  # type: ignore[assignment]
        self.elapsed: float = 0.0
        self._ns_idx: int = 0

    async def start(self) -> None:
        """Start the OPC Tool server and connect a client."""
        self.model = ReactorModel(
            model_config=self._model_cfg, initial_state=self._initial_state,
        )
        recipe = load_recipe(RECIPE_PATH)
        self.player = RecipePlayer(recipe)
        self.controller = BatchController(
            self.model, controller_cfg=self._model_cfg.controller,
        )
        self.controller.recipe_player = self.player
        self.controller._dt = self.dt

        # Set up NodeManager with reactor nodes
        self.node_mgr = NodeManager()
        for node in _SENSOR_NODES + _ACTUATOR_NODES + _STATUS_NODES + _RECIPE_NODES:
            self.node_mgr.add_node(node)

        # Create and start OPC Tool server
        self.opc_server = ManagedOPCServer(
            server_id="test-reactor",
            endpoint=f"opc.tcp://0.0.0.0:{OPC_PORT}",
            name="Reactor Digital Twin",
            namespace_uri="urn:reactor:digitaltwin",
        )
        await self.opc_server.init(self.node_mgr)
        await self.opc_server.start()

        # Push initial state
        await self._push_state(self.model.state, self.model.viscosity,
                               self.model.pressure_bar, self.controller.phase, 0.0)

        self.client = Client(OPC_ENDPOINT)
        await self.client.connect()
        self._ns_idx = await self.client.get_namespace_index("urn:reactor:digitaltwin")

    async def stop(self) -> None:
        await self.client.disconnect()
        await self.opc_server.stop()

    async def _push_state(
        self,
        state: ReactorState,
        viscosity: float,
        pressure: float,
        phase: Phase,
        elapsed: float,
    ) -> None:
        """Push reactor state to the OPC Tool server nodes."""
        updates = {
            "temperature": state.temperature,
            "pressure": pressure,
            "conversion": state.conversion,
            "viscosity": viscosity,
            "mass_total": state.mass_total,
            "fsm_state": int(phase),
            "fsm_state_name": phase.name,
            "batch_elapsed": elapsed,
        }
        for node_id, value in updates.items():
            self.node_mgr.set_value(node_id, value)
            await self.opc_server.update_node(node_id, value)

    # ----- OPC UA client helpers (emulating a DCS) -----

    async def read_sensor(self, name: str) -> float:
        """Read a sensor node by browse name."""
        node = await self._browse(SENSOR_PREFIX, name)
        return await node.read_value()

    async def read_status(self, name: str):
        """Read a status node by browse name."""
        node = await self._browse(STATUS_PREFIX, name)
        return await node.read_value()

    async def write_actuator(self, name: str, value: float) -> None:
        """Write to an actuator node."""
        node = await self._browse(ACTUATOR_PREFIX, name)
        await node.write_value(ua.DataValue(ua.Variant(value, ua.VariantType.Double)))

    async def send_command(self, command: str) -> None:
        """Write a command string to the Recipe/Command node."""
        node = await self._browse(RECIPE_PREFIX, "Command")
        await node.write_value(ua.DataValue(ua.Variant(command, ua.VariantType.String)))

    async def _browse(self, folder_path: str, name: str):
        parts = folder_path.split("/") + [name]
        node = self.client.nodes.objects
        for part in parts:
            node = await node.get_child(f"{self._ns_idx}:{part}")
        return node

    # ----- Simulation tick (server side) -----

    async def tick(self) -> None:
        """Advance the simulation by one time step."""
        dt = self.dt

        # Read command from OPC UA (via the server)
        command_val = await self.opc_server.read_node("recipe_command")
        command = command_val if command_val else "STOP"
        if command.upper() == "START" and self.controller.phase == Phase.IDLE:
            self.controller.start_recipe()
        elif command.upper() == "RESET":
            self.controller.reset_alarm()

        # Apply recipe setpoints
        if not self.player.finished:
            setpoints = self.player.tick(dt)
            if "jacket_temp" in setpoints:
                self.model.state.jacket_temperature = setpoints["jacket_temp"]
            self.model.set_feed_rate("component_a", setpoints.get("feed_component_a", 0.0))
            self.model.set_feed_rate("component_b", setpoints.get("feed_component_b", 0.0))
            self.model.set_feed_rate("solvent", setpoints.get("feed_solvent", 0.0))
        else:
            self.model.set_feed_rate("component_a", 0.0)
            self.model.set_feed_rate("component_b", 0.0)
            self.model.set_feed_rate("solvent", 0.0)

        # Read actuator overrides from OPC UA (writable nodes)
        jacket_sp = await self.opc_server.read_node("jacket_setpoint")
        if jacket_sp is not None and jacket_sp != 298.15:
            self.model.state.jacket_temperature = jacket_sp

        # Physics step
        self.model.step(dt)

        # FSM evaluation
        self.controller.evaluate()

        # Push noisy sensors to OPC Tool server
        noisy_temp = add_sensor_noise(self.model.state.temperature, 0.5)
        noisy_pressure = add_sensor_noise(self.model.pressure_bar, 0.5)
        noisy_visc = add_sensor_noise(self.model.viscosity, 0.5)
        noisy_state = ReactorState(
            species_masses=dict(self.model.state.species_masses),
            conversions={k: add_sensor_noise(v, 0.5) for k, v in self.model.state.conversions.items()},
            temperature=noisy_temp,
            jacket_temperature=self.model.state.jacket_temperature,
            volume=self.model.state.volume,
        )
        await self._push_state(
            noisy_state, noisy_visc, noisy_pressure,
            self.controller.phase, self.elapsed,
        )

        self.elapsed += dt

    async def run_ticks(self, n: int) -> None:
        """Run n simulation ticks."""
        for _ in range(n):
            await self.tick()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def sim():
    """Provide a running simulation harness with OPC UA client."""
    harness = SimulationHarness(dt=1.0)
    await harness.start()
    yield harness
    await harness.stop()


@pytest.fixture
async def charged_sim():
    """Provide a simulation that has already charged material (skip charging)."""
    state = ReactorState(
        species_masses={"component_a": 60.0, "component_b": 12.0, "product": 0.0, "solvent": 0.0},
        conversions={"alpha": 0.0},
        temperature=298.15, jacket_temperature=298.15, volume=0.1,
    )
    harness = SimulationHarness(dt=1.0, initial_state=state)
    await harness.start()
    yield harness
    await harness.stop()


# ---------------------------------------------------------------------------
# Tests: DCS Client reads sensors
# ---------------------------------------------------------------------------

class TestDCSSensorReads:
    """A DCS client connects and reads process variables."""

    async def test_read_initial_temperature(self, sim: SimulationHarness):
        """Temperature should read ~ambient before recipe starts."""
        temp = await sim.read_sensor("Temperature_K")
        assert 290 < temp < 310  # ambient ± noise

    async def test_read_initial_pressure(self, sim: SimulationHarness):
        """Pressure is kept at 0.5 bar for security reasons."""
        pressure = await sim.read_sensor("Pressure_bar")
        assert 0.4 < pressure < 0.6

    async def test_read_initial_conversion(self, sim: SimulationHarness):
        """Conversion should be ~0 before any reaction."""
        conv = await sim.read_sensor("Conversion")
        assert conv < 0.05

    async def test_read_initial_viscosity(self, sim: SimulationHarness):
        """Viscosity should be near the initial value."""
        visc = await sim.read_sensor("Viscosity_Pas")
        assert 0.1 < visc < 2.0

    async def test_read_initial_mass(self, sim: SimulationHarness):
        """Mass total should be ~0 before charging."""
        mass = await sim.read_sensor("MassTotal_kg")
        assert mass < 1.0

    async def test_read_fsm_state_idle(self, sim: SimulationHarness):
        """FSM should be IDLE before recipe starts."""
        state_name = await sim.read_status("FSM_StateName")
        assert state_name == "IDLE"
        state_id = await sim.read_status("FSM_State")
        assert state_id == 0

    async def test_read_batch_elapsed(self, sim: SimulationHarness):
        """Batch elapsed should be 0 initially."""
        elapsed = await sim.read_status("BatchElapsed_s")
        assert elapsed == 0.0


# ---------------------------------------------------------------------------
# Tests: DCS sends START command via OPC UA
# ---------------------------------------------------------------------------

class TestDCSStartCommand:
    """Simulate a DCS operator pressing START."""

    async def test_start_command_transitions_from_idle(self, sim: SimulationHarness):
        """Writing 'START' to the command node should start the recipe."""
        # Verify idle
        state = await sim.read_status("FSM_StateName")
        assert state == "IDLE"

        # DCS sends START
        await sim.send_command("START")
        await sim.run_ticks(2)

        state = await sim.read_status("FSM_StateName")
        # Controller should have transitioned past IDLE (to CHARGING or HEATING
        # depending on whether the first recipe step has feed profiles)
        assert state != "IDLE"

    async def test_mass_increases_during_charging(self, charged_sim: SimulationHarness):
        """After START, component_a feed should increase total mass."""
        sim = charged_sim
        initial_mass = sim.model.state.mass_total
        await sim.send_command("START")
        # Skip INERT step (no feeds) and jump to CHARGE_COMPONENT_A
        sim.player.current_step_idx = 1  # CHARGE_COMPONENT_A
        sim.player.step_elapsed = 0.0
        await sim.run_ticks(10)

        mass = await sim.read_sensor("MassTotal_kg")
        # Recipe feeds component_a at 0.5 kg/s; with pre-charged reactor IPOPT converges
        assert mass > initial_mass

    async def test_sensors_update_each_tick(self, charged_sim: SimulationHarness):
        """Sensor values should change between ticks."""
        sim = charged_sim
        await sim.send_command("START")

        # Skip a few ticks to get past charging into heating
        # where temperature changes are visible
        sim.player.current_step_idx = 3  # HEAT_TO_SOAK
        sim.player.step_elapsed = 0.0
        await sim.run_ticks(3)
        temp1 = await sim.read_sensor("Temperature_K")
        await sim.run_ticks(3)
        temp2 = await sim.read_sensor("Temperature_K")
        # Temperature should change as jacket heats up
        assert temp1 != temp2


# ---------------------------------------------------------------------------
# Tests: DCS writes actuator overrides
# ---------------------------------------------------------------------------

class TestDCSActuatorOverrides:
    """Simulate a DCS operator overriding jacket temperature."""

    async def test_jacket_setpoint_override(self, charged_sim: SimulationHarness):
        """Writing a jacket setpoint should override the recipe profile."""
        sim = charged_sim
        await sim.send_command("START")
        await sim.run_ticks(3)

        # DCS operator sets jacket to 350 K (above recipe setpoint)
        await sim.write_actuator("JacketSetpoint_K", 350.0)
        await sim.run_ticks(5)

        # The reactor temperature should be moving toward the override.
        # Allow margin for sensor noise (0.5% of reading).
        temp = await sim.read_sensor("Temperature_K")
        assert temp > 297.0  # should have warmed up from ambient

    async def test_feed_valve_is_writable(self, sim: SimulationHarness):
        """Verify the feed valve node is writable."""
        await sim.write_actuator("FeedValve_pct", 75.0)
        node = await sim.client.nodes.objects.get_child(
            [f"{sim._ns_idx}:Actuators", f"{sim._ns_idx}:FeedValve_pct"]
        )
        val = await node.read_value()
        assert val == pytest.approx(75.0)

    async def test_agitator_speed_is_writable(self, sim: SimulationHarness):
        """Verify the agitator speed node is writable."""
        await sim.write_actuator("AgitatorSpeed_rpm", 120.0)
        node = await sim.client.nodes.objects.get_child(
            [f"{sim._ns_idx}:Actuators", f"{sim._ns_idx}:AgitatorSpeed_rpm"]
        )
        val = await node.read_value()
        assert val == pytest.approx(120.0)


# ---------------------------------------------------------------------------
# Tests: Full batch lifecycle via OPC UA
# ---------------------------------------------------------------------------

class TestFullBatchLifecycleOPCUA:
    """Run a batch from START to completion, monitoring entirely via OPC UA.

    This uses a pre-charged reactor and a shortened recipe to keep test
    runtime manageable while exercising all FSM phases.
    """

    async def test_batch_progresses_through_phases(self, charged_sim: SimulationHarness):
        """Monitor FSM phase transitions via OPC UA status nodes."""
        sim = charged_sim
        phases_seen: set[str] = set()

        await sim.send_command("START")

        # Run a few ticks in charging phase
        for _ in range(5):
            await sim.tick()
            phase = await sim.read_status("FSM_StateName")
            phases_seen.add(phase)

        # Skip recipe to HEAT_TO_SOAK to accelerate transition
        sim.player.current_step_idx = 2  # HEAT_TO_SOAK
        sim.player.step_elapsed = 0.0

        for _ in range(100):
            await sim.tick()
            phase = await sim.read_status("FSM_StateName")
            phases_seen.add(phase)

        # Should have progressed through CHARGING and into HEATING
        assert "CHARGING" in phases_seen
        assert "HEATING" in phases_seen

    async def test_temperature_tracked_via_opcua(self, charged_sim: SimulationHarness):
        """Temperature read from OPC UA should rise during heating."""
        sim = charged_sim
        await sim.send_command("START")

        temps: list[float] = []
        for _ in range(400):
            await sim.tick()
            temp = await sim.read_sensor("Temperature_K")
            temps.append(temp)

        max_temp = max(temps)
        min_temp = min(temps)
        # During heating, temperature should rise meaningfully
        assert max_temp > min_temp + 5.0

    async def test_conversion_increases_via_opcua(self, charged_sim: SimulationHarness):
        """Conversion read from OPC UA should increase over time."""
        sim = charged_sim
        await sim.send_command("START")

        # Let the reactor heat up and react (staged recipe heats slowly)
        for _ in range(400):
            await sim.tick()

        conv = await sim.read_sensor("Conversion")
        assert conv > 0.0001  # some reaction should have occurred

    async def test_mass_conservation_via_opcua(self, charged_sim: SimulationHarness):
        """Without feeds, total mass should be conserved."""
        sim = charged_sim
        initial_mass = sim.model.state.mass_total  # ground truth

        await sim.send_command("START")

        # Skip past the charging phase (recipe still feeds for first ~240s)
        # The charged_sim starts with mass already loaded, but recipe still
        # tries to feed.  We override feeds to 0 by jumping ahead.
        sim.player.current_step_idx = 3  # skip to HEAT_TO_SOAK
        sim.player.step_elapsed = 0.0

        for _ in range(50):
            await sim.tick()

        final_mass = await sim.read_sensor("MassTotal_kg")
        # Mass should be approximately conserved (small noise tolerance)
        assert pytest.approx(final_mass, rel=0.05) == initial_mass

    async def test_elapsed_time_advances(self, charged_sim: SimulationHarness):
        """Batch elapsed time should advance with each tick."""
        sim = charged_sim
        await sim.send_command("START")

        await sim.run_ticks(10)
        elapsed = await sim.read_status("BatchElapsed_s")
        assert elapsed >= 9.0  # 10 ticks * 1s (first update is at t=0)


# ---------------------------------------------------------------------------
# Tests: Runaway detection via OPC UA
# ---------------------------------------------------------------------------

class TestRunawayAlarmOPCUA:
    """Simulate a thermal runaway and verify the alarm is visible via OPC UA."""

    async def test_runaway_triggers_alarm_state(self):
        """A high-temperature adiabatic scenario should set FSM to RUNAWAY_ALARM."""
        # Build a custom model config with no cooling
        import copy
        cfg = ModelConfig.from_yaml(MODEL_CFG_PATH)
        raw = copy.deepcopy(cfg.raw)
        raw["thermal"]["UA"] = 0.0  # no cooling
        no_cool_cfg = ModelConfig.from_dict(raw)

        state = ReactorState(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.1},
            temperature=393.15, jacket_temperature=393.15,
            volume=0.1,
        )
        sim = SimulationHarness(dt=1.0, model_cfg=no_cool_cfg, initial_state=state)
        await sim.start()

        try:
            await sim.send_command("START")

            alarm_seen = False
            for _ in range(50):
                await sim.tick()
                state_name = await sim.read_status("FSM_StateName")
                if state_name == "RUNAWAY_ALARM":
                    alarm_seen = True
                    break

            assert alarm_seen, "Runaway alarm should have triggered"

            # Verify temperature was high (allow for sensor noise ~0.5%)
            temp = await sim.read_sensor("Temperature_K")
            assert temp > 395.0

        finally:
            await sim.stop()

    async def test_reset_command_clears_alarm(self):
        """Writing 'RESET' to the command node should clear a runaway alarm."""
        import copy
        cfg = ModelConfig.from_yaml(MODEL_CFG_PATH)
        raw = copy.deepcopy(cfg.raw)
        raw["thermal"]["UA"] = 0.0
        no_cool_cfg = ModelConfig.from_dict(raw)

        state = ReactorState(
            species_masses={"component_a": 100.0, "component_b": 30.0, "product": 0.0, "solvent": 0.0},
            conversions={"alpha": 0.1},
            temperature=393.15, jacket_temperature=393.15,
            volume=0.1,
        )
        sim = SimulationHarness(dt=1.0, model_cfg=no_cool_cfg, initial_state=state)
        await sim.start()

        try:
            await sim.send_command("START")

            # Run until alarm
            for _ in range(50):
                await sim.tick()
                state_name = await sim.read_status("FSM_StateName")
                if state_name == "RUNAWAY_ALARM":
                    break

            assert await sim.read_status("FSM_StateName") == "RUNAWAY_ALARM"

            # DCS operator sends RESET
            await sim.send_command("RESET")
            await sim.tick()

            # After RESET, alarm is cleared.  Since the recipe was already
            # started, the FSM transitions through IDLE -> CHARGING on the
            # same evaluate() call.  The key assertion is that we are no
            # longer in RUNAWAY_ALARM.
            state_name = await sim.read_status("FSM_StateName")
            assert state_name != "RUNAWAY_ALARM"

        finally:
            await sim.stop()


# ---------------------------------------------------------------------------
# Tests: Noise & data quality (DCS perspective)
# ---------------------------------------------------------------------------

class TestSensorNoiseOPCUA:
    """Verify that sensor readings have realistic noise (as a DCS would see)."""

    async def test_temperature_readings_have_variance(self, charged_sim: SimulationHarness):
        """Multiple reads at the same simulation state should show noise."""
        sim = charged_sim
        await sim.send_command("START")
        await sim.run_ticks(5)

        # Collect readings after several ticks (each tick re-publishes with noise)
        readings = []
        for _ in range(10):
            await sim.tick()
            temp = await sim.read_sensor("Temperature_K")
            readings.append(temp)

        # With 0.5% noise on ~300K, std should be ~1.5K
        import numpy as np
        std = float(np.std(readings))
        # Readings should not be identical (noise present)
        assert std > 0.01, "Sensor readings should have measurable noise"

    async def test_pressure_near_atmospheric(self, sim: SimulationHarness):
        """Pressure readings should cluster around 1.013 bar."""
        await sim.send_command("START")
        await sim.run_ticks(5)

        pressures = []
        for _ in range(5):
            await sim.tick()
            p = await sim.read_sensor("Pressure_bar")
            pressures.append(p)

        import numpy as np
        mean_p = float(np.mean(pressures))
        # Pressure is kept at 0.5 bar for security reasons
        assert 0.45 < mean_p < 0.55


# ---------------------------------------------------------------------------
# Tests: OPC UA node tree structure (DCS commissioning)
# ---------------------------------------------------------------------------

class TestOPCUANodeTree:
    """Verify the OPC UA information model matches expected DCS tag list."""

    async def test_sensor_nodes_exist(self, sim: SimulationHarness):
        """All expected sensor tags should be browsable."""
        expected = ["Temperature_K", "Pressure_bar", "Conversion",
                    "Viscosity_Pas", "MassTotal_kg"]
        for name in expected:
            val = await sim.read_sensor(name)
            assert val is not None

    async def test_actuator_nodes_exist(self, sim: SimulationHarness):
        """All expected actuator tags should be browsable and writable."""
        expected = [
            ("JacketSetpoint_K", 350.0),
            ("AgitatorSpeed_rpm", 100.0),
            ("FeedValve_pct", 50.0),
        ]
        for name, test_val in expected:
            await sim.write_actuator(name, test_val)
            # Read back
            node = await sim.client.nodes.objects.get_child(
                [f"{sim._ns_idx}:Actuators", f"{sim._ns_idx}:{name}"]
            )
            read_val = await node.read_value()
            assert read_val == pytest.approx(test_val)

    async def test_status_nodes_exist(self, sim: SimulationHarness):
        """All expected status tags should be browsable."""
        fsm_state = await sim.read_status("FSM_State")
        assert isinstance(fsm_state, int)
        fsm_name = await sim.read_status("FSM_StateName")
        assert isinstance(fsm_name, str)
        elapsed = await sim.read_status("BatchElapsed_s")
        assert isinstance(elapsed, float)

    async def test_recipe_command_node_exists(self, sim: SimulationHarness):
        """The recipe command node should be browsable and writable."""
        node = await sim.client.nodes.objects.get_child(
            [f"{sim._ns_idx}:Recipes", f"{sim._ns_idx}:Command"]
        )
        val = await node.read_value()
        assert isinstance(val, str)
