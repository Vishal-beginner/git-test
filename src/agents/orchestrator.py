"""Agent Orchestrator — coordinates all agents and resolves command conflicts.

Creates, starts, and monitors all navigation agents. Each cycle:
1. Collects commands from all agents
2. Resolves conflicts using priority ordering
3. Safety agent always has veto power
4. Continues in degraded mode if an agent fails
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Callable, Optional

from src.agents.base import BaseAgent
from src.agents.awareness_agent import SituationAwarenessAgent
from src.agents.colreg_agent import COLREGAgent
from src.agents.navigation_agent import NavigationAgent
from src.agents.safety_agent import SafetyMonitorAgent
from src.core.types import (
    ManeuverCommand, NavigationMode, OwnShipState, Route, TargetVessel,
    Position, Velocity, VesselDimensions, VesselType,
)
from src.core.config import AppConfig
from src.core.constants import SITUATION_EVAL_INTERVAL_S
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _make_default_state() -> OwnShipState:
    """Create a safe default OwnShipState for initialization."""
    from src.core.types import VesselDimensions
    return OwnShipState(
        position=Position(lat=0.0, lon=0.0),
        velocity=Velocity(speed_kts=0.0, course_deg=0.0),
        mode=NavigationMode.AUTONOMOUS,
        vessel_type=VesselType.POWER_DRIVEN,
        dimensions=VesselDimensions(
            length_m=180.0,
            beam_m=28.0,
            draft_m=9.5,
            gross_tonnage=25000.0,
        ),
        heading_deg=0.0,
        timestamp=datetime.now(timezone.utc),
    )


class AgentOrchestrator:
    """
    Orchestrates all navigation agents.

    Architecture:
    - Each agent runs in its own asyncio task
    - Orchestrator polls agents each cycle for their commands
    - Commands are merged by priority (highest wins for same resource)
    - Safety agent can veto any command regardless of source
    - Graceful degradation: if an agent fails, the system continues
    """

    ORCHESTRATION_INTERVAL_S = SITUATION_EVAL_INTERVAL_S

    def __init__(
        self,
        config: AppConfig,
        safety_supervisor: Optional[object] = None,  # SafetySupervisor
        vdr: Optional[object] = None,  # VoyageDataRecorder
    ) -> None:
        self._config = config
        self._safety_supervisor = safety_supervisor
        self._vdr = vdr

        # Create agents
        self._safety_agent = SafetyMonitorAgent(
            hard_min_dcpa_nm=config.safety.hard_min_dcpa_nm,
            max_speed_kts=config.ship.max_speed_kts,
            safe_speed_restricted_vis_kts=config.safety.safe_speed_restricted_vis_kts,
        )
        self._awareness_agent = SituationAwarenessAgent(
            minimum_sensors_required=config.sensors.minimum_sensors_required,
        )
        self._colreg_agent = COLREGAgent(
            dcpa_threshold_nm=config.safety.dcpa_threshold_nm,
            tcpa_threshold_min=config.safety.tcpa_threshold_min,
            hard_min_dcpa_nm=config.safety.hard_min_dcpa_nm,
        )
        self._nav_agent = NavigationAgent(
            max_speed_kts=config.ship.max_speed_kts,
            los_lookahead_nm=config.navigation.los_lookahead_nm,
            waypoint_arrival_radius_nm=config.navigation.waypoint_arrival_radius_nm,
        )

        # All agents ordered by priority (highest first)
        self._agents: list[BaseAgent] = [
            self._safety_agent,
            self._colreg_agent,
            self._awareness_agent,
            self._nav_agent,
        ]

        # Shared state
        self._current_state: OwnShipState = _make_default_state()
        self._current_targets: list[TargetVessel] = []
        self._active_commands: list[ManeuverCommand] = []
        self._state_lock = asyncio.Lock()
        self._is_running = False

        # External state providers
        self._state_provider: Optional[Callable] = None
        self._target_provider: Optional[Callable] = None

    def set_state_provider(self, provider: Callable) -> None:
        """Set async callable that returns current OwnShipState."""
        self._state_provider = provider

    def set_target_provider(self, provider: Callable) -> None:
        """Set async callable that returns current target list."""
        self._target_provider = provider

    def set_route(self, route: Route) -> None:
        """Load a route into the navigation agent."""
        self._nav_agent.set_route(route)

    async def _get_state(self) -> OwnShipState:
        """Get current own ship state."""
        if self._state_provider is not None:
            try:
                return await self._state_provider()
            except Exception as exc:
                logger.error("State provider failed", extra={"error": str(exc)})
        async with self._state_lock:
            return self._current_state

    async def _get_targets(self) -> list[TargetVessel]:
        """Get current target list (from awareness agent)."""
        if self._target_provider is not None:
            try:
                return await self._target_provider()
            except Exception as exc:
                logger.error("Target provider failed", extra={"error": str(exc)})
        return await self._awareness_agent.get_targets()

    def _resolve_commands(
        self,
        all_commands: list[ManeuverCommand],
        state: OwnShipState,
        targets: list[TargetVessel],
    ) -> list[ManeuverCommand]:
        """
        Resolve multiple commands from different agents into a unified set.

        Resolution rules:
        1. Emergency stops always win
        2. Higher priority commands override lower priority for same dimension (course/speed)
        3. Safety agent can veto any command
        """
        if not all_commands:
            return []

        # Sort by priority (highest first)
        sorted_cmds = sorted(all_commands, key=lambda c: c.priority, reverse=True)

        # Find the highest-priority course command and speed command separately
        resolved_course: Optional[float] = None
        resolved_speed: Optional[float] = None
        resolved_reason = ""
        resolved_colreg_rule: Optional[str] = None

        # Emergency stop takes absolute precedence
        emergency_stops = [c for c in sorted_cmds if c.speed_kts == 0.0]
        if emergency_stops:
            return [emergency_stops[0]]  # First (highest priority) emergency stop

        for cmd in sorted_cmds:
            if resolved_course is None and cmd.course_deg is not None:
                resolved_course = cmd.course_deg
                resolved_reason = cmd.reason
                resolved_colreg_rule = cmd.colreg_rule
            if resolved_speed is None and cmd.speed_kts is not None:
                resolved_speed = cmd.speed_kts
                if not resolved_reason:
                    resolved_reason = cmd.reason

        if resolved_course is None and resolved_speed is None:
            return []

        final_cmd = ManeuverCommand(
            course_deg=resolved_course,
            speed_kts=resolved_speed,
            reason=resolved_reason,
            colreg_rule=resolved_colreg_rule,
            priority=sorted_cmds[0].priority if sorted_cmds else 50,
        )

        # Apply safety supervisor veto if available
        if self._safety_supervisor is not None:
            is_safe = self._safety_supervisor.validate_command(final_cmd, state, targets)
            if not is_safe:
                logger.warning(
                    "Command vetoed by safety supervisor",
                    extra={"reason": final_cmd.reason},
                )
                # Return emergency stop if safety supervisor rejects
                return [ManeuverCommand(
                    speed_kts=0.0,
                    reason="SAFETY SUPERVISOR VETO",
                    priority=100,
                )]

        # Apply safety agent validation
        is_safe, veto_reason = self._safety_agent.validate_command(final_cmd, state, targets)
        if not is_safe:
            logger.warning(
                "Command vetoed by safety agent",
                extra={"reason": veto_reason},
            )
            return [ManeuverCommand(
                speed_kts=state.velocity.speed_kts * 0.5,
                reason=f"SAFETY VETO: {veto_reason}",
                priority=100,
            )]

        return [final_cmd]

    async def _orchestration_cycle(self) -> list[ManeuverCommand]:
        """
        Run one orchestration cycle — collect all agent commands and resolve.
        """
        state = await self._get_state()
        targets = await self._get_targets()

        all_commands: list[ManeuverCommand] = []

        for agent in self._agents:
            if not agent.is_active:
                continue
            try:
                cmds = await agent.run_cycle(state, targets)
                all_commands.extend(cmds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Agent cycle failed",
                    extra={"agent": agent.name, "error": str(exc)},
                    exc_info=True,
                )
                # Continue with other agents (degraded mode)

        # Resolve conflicts
        resolved = self._resolve_commands(all_commands, state, targets)

        async with self._state_lock:
            self._active_commands = resolved

        return resolved

    async def run(self) -> None:
        """Main orchestration loop."""
        self._is_running = True

        # Initialize all agents
        for agent in self._agents:
            agent.is_active = True
            try:
                await agent.initialize()
            except Exception as exc:
                logger.error(
                    "Agent initialization failed",
                    extra={"agent": agent.name, "error": str(exc)},
                )

        logger.info("AgentOrchestrator running", extra={"agents": [a.name for a in self._agents]})

        try:
            while self._is_running:
                try:
                    commands = await self._orchestration_cycle()
                    if commands:
                        logger.info(
                            "Commands resolved",
                            extra={
                                "count": len(commands),
                                "top_priority": commands[0].priority if commands else None,
                                "reason": commands[0].reason if commands else None,
                            }
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "Orchestration cycle error",
                        extra={"error": str(exc)},
                        exc_info=True,
                    )

                await asyncio.sleep(self.ORCHESTRATION_INTERVAL_S)
        except asyncio.CancelledError:
            logger.info("AgentOrchestrator cancelled")
        finally:
            await self._shutdown_all()

    async def _shutdown_all(self) -> None:
        """Shutdown all agents gracefully."""
        self._is_running = False
        for agent in self._agents:
            agent.is_active = False
            try:
                await agent.shutdown()
            except Exception as exc:
                logger.error(
                    "Agent shutdown error",
                    extra={"agent": agent.name, "error": str(exc)},
                )

    def get_active_commands(self) -> list[ManeuverCommand]:
        """Return the most recently resolved commands."""
        return list(self._active_commands)

    def get_system_status(self) -> dict:
        """Return system health status dictionary."""
        return {
            "is_running": self._is_running,
            "agents": [agent.get_status() for agent in self._agents],
            "active_command_count": len(self._active_commands),
            "active_targets": len(self._current_targets),
            "awareness_alarms": self._awareness_agent.get_active_alarms(),
            "colreg_encounters": len(self._colreg_agent.get_active_encounters()),
            "emergency_active": self._safety_agent.is_emergency_active(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def update_own_state(self, state: OwnShipState) -> None:
        """Update own ship state (called from sensor integration layer)."""
        async with self._state_lock:
            self._current_state = state

    def get_awareness_agent(self) -> SituationAwarenessAgent:
        """Return the situation awareness agent."""
        return self._awareness_agent

    def get_colreg_agent(self) -> COLREGAgent:
        """Return the COLREG agent."""
        return self._colreg_agent

    def stop(self) -> None:
        """Stop the orchestrator."""
        self._is_running = False
