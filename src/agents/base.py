"""Abstract base class for all navigation system agents.

Each agent runs an independent asyncio loop at a configured interval,
processes the current ship state and target list, and returns zero or more
ManeuverCommands.  Higher priority commands override lower-priority ones in
the orchestrator.

Agent priority scale (0-100):
  100  SafetyMonitorAgent  — absolute veto power
   90  COLREGAgent         — regulatory compliance
   85  AvoidancePlannerAgent
   80  SituationAwarenessAgent
   50  NavigationAgent     — route following
   40  WeatherAgent        — routing optimization
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from src.core.types import ManeuverCommand, OwnShipState, TargetVessel

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all ship navigation agents."""

    name: str = "BaseAgent"
    priority: int = 50
    cycle_interval_s: float = 5.0

    def __init__(self) -> None:
        self.is_active: bool = False
        self._task: Optional[asyncio.Task] = None
        self._last_run: Optional[datetime] = None
        self._run_count: int = 0
        self._error_count: int = 0
        self._last_commands: list[ManeuverCommand] = []

    @abstractmethod
    async def initialize(self) -> None:
        """Perform one-time initialization (e.g., load config, connect to services)."""

    @abstractmethod
    async def run_cycle(
        self,
        state: OwnShipState,
        targets: list[TargetVessel],
    ) -> list[ManeuverCommand]:
        """Execute one agent decision cycle.

        Args:
            state: Current own ship navigational state.
            targets: All currently tracked target vessels (with CPA/TCPA set).

        Returns:
            List of ManeuverCommands (may be empty).  Commands are consumed by
            the orchestrator, which resolves conflicts and applies priority ordering.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Release any resources held by this agent."""

    async def start_loop(
        self,
        state_provider,
        target_provider,
    ) -> None:
        """Start the agent's decision loop.

        Calls run_cycle() at cycle_interval_s frequency.  Errors inside
        run_cycle() are caught and logged without stopping the loop; the agent
        is marked as degraded after 3 consecutive errors.

        Args:
            state_provider: Async callable returning OwnShipState.
            target_provider: Async callable returning list[TargetVessel].
        """
        self.is_active = True
        await self.initialize()
        logger.info("Agent started", extra={"agent": self.name, "priority": self.priority})

        while self.is_active:
            try:
                state = await state_provider()
                targets = await target_provider()
                commands = await self.run_cycle(state, targets)
                self._last_commands = commands
                self._last_run = datetime.now(timezone.utc)
                self._run_count += 1
                self._error_count = 0  # Reset on success
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._error_count += 1
                logger.error(
                    "Agent cycle error",
                    extra={"agent": self.name, "error": str(exc), "count": self._error_count},
                    exc_info=True,
                )
                if self._error_count >= 3:
                    logger.critical(
                        "Agent degraded — 3 consecutive errors",
                        extra={"agent": self.name},
                    )

            await asyncio.sleep(self.cycle_interval_s)

        await self.shutdown()
        logger.info("Agent stopped", extra={"agent": self.name})

    def stop(self) -> None:
        """Signal the agent loop to stop after the current cycle."""
        self.is_active = False

    def get_last_commands(self) -> list[ManeuverCommand]:
        """Return commands from the most recent cycle."""
        return list(self._last_commands)

    def get_status(self) -> dict:
        """Return agent health status dictionary."""
        return {
            "name": self.name,
            "priority": self.priority,
            "is_active": self.is_active,
            "run_count": self._run_count,
            "error_count": self._error_count,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_command_count": len(self._last_commands),
        }
