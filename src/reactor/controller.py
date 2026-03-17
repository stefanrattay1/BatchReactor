"""Batch controller with finite state machine and runaway detection."""

from __future__ import annotations

import asyncio
from collections import deque
from enum import IntEnum

from .physics import ReactorModel
from .recipe import RecipePlayer

# Default thresholds (used when no config dict is provided)
_DEFAULT_CONTROLLER_CFG = {
    "cure_temp_K": 353.15,
    "cool_done_temp_K": 313.15,
    "runaway_temp_K": 473.15,
    "runaway_dT_dt": 2.0,
    "conversion_done": 0.95,
    "dt_window": 10,
}


class Phase(IntEnum):
    """Reactor operational phases."""

    IDLE = 0
    CHARGING = 1
    HEATING = 2
    EXOTHERM = 3
    COOLING = 4
    DISCHARGING = 5
    RUNAWAY_ALARM = 6


class BatchController:
    """Monitors reactor physics and manages the FSM phase transitions."""

    def __init__(
        self,
        model: ReactorModel,
        controller_cfg: dict | None = None,
    ):
        self.model = model
        self.phase = Phase.IDLE
        self.recipe_player: RecipePlayer | None = None
        self._recipe_started = False

        # Command queue for web API integration
        self._command_queue: asyncio.Queue[str] = asyncio.Queue()

        cfg = controller_cfg or _DEFAULT_CONTROLLER_CFG

        self._cure_temp = cfg["cure_temp_K"]
        self._cool_done_temp = cfg["cool_done_temp_K"]
        self._runaway_temp = cfg["runaway_temp_K"]
        self._runaway_dt_dt = cfg["runaway_dT_dt"]
        self._conversion_done = cfg["conversion_done"]

        dt_window = cfg.get("dt_window", 10)
        self._temp_history: deque[float] = deque(maxlen=dt_window)
        self._dt: float = 0.5  # tick interval, set by main loop

    @property
    def dt_dt(self) -> float:
        """Estimate dT/dt from recent temperature history (K/s)."""
        if len(self._temp_history) < 2:
            return 0.0
        temps = list(self._temp_history)
        # Simple finite difference over the window
        return (temps[-1] - temps[0]) / (len(temps) * self._dt)

    def start_recipe(self) -> None:
        """Signal that the recipe has been started."""
        self._recipe_started = True

    def reset_alarm(self) -> None:
        """Manually reset a runaway alarm back to IDLE."""
        if self.phase == Phase.RUNAWAY_ALARM:
            self.phase = Phase.IDLE

    def stop(self) -> None:
        """Stop the recipe and return to IDLE state."""
        self._recipe_started = False
        self.phase = Phase.IDLE
        if self.recipe_player:
            self.recipe_player.reset()

    def reinitialize(self, model: ReactorModel, controller_cfg: dict | None = None) -> None:
        """Re-initialize the controller with a new model and config."""
        self.model = model
        self.phase = Phase.IDLE
        self._recipe_started = False

        cfg = controller_cfg or _DEFAULT_CONTROLLER_CFG
        self._cure_temp = cfg["cure_temp_K"]
        self._cool_done_temp = cfg["cool_done_temp_K"]
        self._runaway_temp = cfg["runaway_temp_K"]
        self._runaway_dt_dt = cfg["runaway_dT_dt"]
        self._conversion_done = cfg["conversion_done"]

        dt_window = cfg.get("dt_window", 10)
        self._temp_history = deque(maxlen=dt_window)

        if self.recipe_player:
            self.recipe_player.reset()

    def send_command(self, command: str) -> None:
        """Queue a command from the web API."""
        try:
            self._command_queue.put_nowait(command.upper())
        except asyncio.QueueFull:
            pass  # Drop command if queue is full

    async def get_pending_command(self) -> str | None:
        """Get a pending command from the queue (non-blocking)."""
        try:
            return self._command_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def evaluate(self) -> Phase:
        """Evaluate FSM transitions based on current physics state.

        Call this once per tick after stepping the physics model.
        """
        s = self.model.state
        self._temp_history.append(s.temperature)

        # Check runaway from any state (except IDLE and already alarmed)
        if self.phase not in (Phase.IDLE, Phase.RUNAWAY_ALARM):
            if self._is_runaway():
                self.phase = Phase.RUNAWAY_ALARM
                return self.phase

        if self.phase == Phase.IDLE:
            if self._recipe_started:
                self.phase = Phase.CHARGING

        elif self.phase == Phase.CHARGING:
            # Transition when feeds stop (recipe player moves past charging steps)
            if self.recipe_player and self._charging_complete():
                self.phase = Phase.HEATING

        elif self.phase == Phase.HEATING:
            if s.temperature >= self._cure_temp:
                self.phase = Phase.EXOTHERM

        elif self.phase == Phase.EXOTHERM:
            if s.conversion >= self._conversion_done:
                self.phase = Phase.COOLING

        elif self.phase == Phase.COOLING:
            if s.temperature <= self._cool_done_temp:
                self.phase = Phase.DISCHARGING

        elif self.phase == Phase.DISCHARGING:
            pass  # stays until externally reset

        elif self.phase == Phase.RUNAWAY_ALARM:
            pass  # sticky — requires manual reset

        return self.phase

    def _is_runaway(self) -> bool:
        T = self.model.state.temperature
        return T > self._runaway_temp or self.dt_dt > self._runaway_dt_dt

    def _charging_complete(self) -> bool:
        """Check if the recipe has moved past charging steps."""
        if self.recipe_player is None:
            return False
        step = self.recipe_player.current_step
        if step is None:
            return True
        # Charging is done once we're past steps that feed the primary two components.
        # The first two network species are treated as the charging pair.
        charging_channels = [f"feed_{name}" for name in self.model.network.species_names[:2]]
        charging_channels.extend(["feed_component_a", "feed_component_b"])
        return all(channel not in step.profiles for channel in charging_channels)
