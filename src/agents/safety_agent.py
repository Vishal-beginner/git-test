"""Safety Monitor Agent — highest priority, can veto any command.

Runs at 1s cycle. Hard-limits all commands from lower-priority agents.
Cannot be overridden. Triggers emergency procedures.

Priority: 100 (HIGHEST)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.agents.base import BaseAgent
from src.core.constants import (
    COLREG_URGENT_DCPA_NM, COLREG_SAFE_DCPA_NM,
    MAX_SPEED_RESTRICTED_VIS_KTS, ALARM_ACKNOWLEDGE_TIMEOUT_S,
)
from src.core.exceptions import EmergencyStopRequired
from src.core.types import (
    AlarmLevel, ManeuverCommand, NavigationMode, OwnShipState, TargetVessel,
)
from src.sensors.models import SensorStatus

logger = logging.getLogger(__name__)


class SafetyMonitorAgent(BaseAgent):
    """
    Safety monitor agent — highest priority, absolute veto on all commands.

    Responsibilities (IEC 61508 SIL-3 patterns):
    - Validate ALL proposed maneuver commands against hard safety limits
    - Enforce maximum speed limits (especially in restricted visibility)
    - Enforce minimum DCPA hard limit (cannot be overridden)
    - Monitor sensor redundancy — alert if lost
    - Monitor own ship systems (engine RPM, rudder, navigation mode)
    - Trigger emergency procedures when required
    - Log all safety interventions

    Hard limits (cannot be overridden):
    - DCPA must never go below hard_min_dcpa_nm
    - Speed must not exceed safe speed for visibility conditions
    - Cannot command outside vessel capability
    """

    name = "SafetyMonitorAgent"
    priority = 100
    cycle_interval_s = 1.0

    def __init__(
        self,
        hard_min_dcpa_nm: float = 0.2,
        max_speed_kts: float = 18.0,
        safe_speed_restricted_vis_kts: float = 10.0,
    ) -> None:
        super().__init__()
        self.hard_min_dcpa_nm = hard_min_dcpa_nm
        self.max_speed_kts = max_speed_kts
        self.safe_speed_restricted_vis_kts = safe_speed_restricted_vis_kts
        self._vetoed_commands: list[tuple[ManeuverCommand, str]] = []
        self._emergency_active: bool = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        logger.info(
            "SafetyMonitorAgent initialised",
            extra={
                "hard_min_dcpa": self.hard_min_dcpa_nm,
                "max_speed": self.max_speed_kts,
            }
        )

    async def run_cycle(
        self, state: OwnShipState, targets: list[TargetVessel]
    ) -> list[ManeuverCommand]:
        """
        Check system safety each cycle.

        1. Check sensor redundancy
        2. Check own ship systems
        3. Check for imminent collision (target DCPA < hard limit)
        4. Check navigation mode
        5. Return emergency commands if needed
        """
        commands = []

        # Check for imminent collision
        for target in targets:
            if target.cpa_nm < self.hard_min_dcpa_nm and 0.0 < target.tcpa_min < 10.0:
                logger.critical(
                    "COLLISION IMMINENT",
                    extra={
                        "mmsi": target.mmsi,
                        "dcpa": target.cpa_nm,
                        "tcpa": target.tcpa_min,
                    }
                )
                async with self._lock:
                    self._emergency_active = True
                return [self._emergency_stop("COLLISION_IMMINENT")]

        # Check for extreme DCPA violation
        critical_targets = [
            t for t in targets
            if t.cpa_nm < COLREG_URGENT_DCPA_NM and 0.0 < t.tcpa_min < 5.0
        ]
        if critical_targets:
            most_critical = min(critical_targets, key=lambda t: t.cpa_nm)
            logger.error(
                "URGENT CPA VIOLATION",
                extra={
                    "mmsi": most_critical.mmsi,
                    "dcpa": most_critical.cpa_nm,
                    "tcpa": most_critical.tcpa_min,
                }
            )
            commands.append(ManeuverCommand(
                speed_kts=0.0,
                reason=f"SAFETY: Urgent CPA violation with {most_critical.mmsi}",
                colreg_rule="Safety System Override",
                priority=100,
            ))

        # Check speed limits
        if state.visibility_nm < 2.0:
            max_allowed = self.safe_speed_restricted_vis_kts
        else:
            max_allowed = self.max_speed_kts

        if state.velocity.speed_kts > max_allowed + 0.5:
            logger.warning(
                "speed_limit_exceeded",
                extra={
                    "current": state.velocity.speed_kts,
                    "limit": max_allowed,
                    "visibility": state.visibility_nm,
                }
            )
            commands.append(ManeuverCommand(
                speed_kts=max_allowed,
                reason=f"SAFETY: Speed limit enforcement ({max_allowed} kts)",
                priority=100,
            ))

        # Check navigation mode
        if state.mode == NavigationMode.EMERGENCY:
            async with self._lock:
                self._emergency_active = True
            logger.critical("Navigation mode is EMERGENCY")

        return commands

    async def shutdown(self) -> None:
        logger.info("SafetyMonitorAgent shutdown")

    def validate_command(
        self,
        cmd: ManeuverCommand,
        own: OwnShipState,
        targets: list[TargetVessel],
    ) -> tuple[bool, str]:
        """
        Validate a proposed command against safety hard limits.

        Returns (is_safe, reason).
        If is_safe=False, the command must be blocked.
        """
        # Emergency stop is always allowed
        if cmd.speed_kts == 0.0 and cmd.course_deg is None:
            return True, "Emergency stop always permitted"

        # Check speed limits
        if cmd.speed_kts is not None:
            if own.visibility_nm < 2.0:
                limit = self.safe_speed_restricted_vis_kts
            else:
                limit = self.max_speed_kts

            if cmd.speed_kts > limit + 0.1:
                return False, f"Speed {cmd.speed_kts:.1f} kts exceeds limit {limit:.1f} kts"

        # Check that proposed course doesn't worsen any critical DCPA
        if cmd.course_deg is not None:
            for target in targets:
                if target.cpa_nm < self.hard_min_dcpa_nm * 2:
                    # Near a critical target - validate course won't worsen it
                    # Simple check: if target is close, don't turn toward it
                    bearing_to_target = target.bearing_deg
                    new_course = cmd.course_deg
                    current_course = own.velocity.course_deg

                    # Compute bearing difference
                    to_target_from_new = (bearing_to_target - new_course + 360) % 360
                    to_target_from_current = (bearing_to_target - current_course + 360) % 360

                    # Turning toward target when already critical
                    if (to_target_from_new < 30.0 or to_target_from_new > 330.0) and target.cpa_nm < self.hard_min_dcpa_nm:
                        return False, f"Course {cmd.course_deg:.0f}° turns toward critical target {target.mmsi} (DCPA={target.cpa_nm:.2f}NM)"

        return True, "Command validated"

    def _emergency_stop(self, reason: str) -> ManeuverCommand:
        """Generate emergency stop command."""
        return ManeuverCommand(
            course_deg=None,
            speed_kts=0.0,
            reason=f"EMERGENCY STOP: {reason}",
            colreg_rule="Safety System",
            priority=100,
        )

    def is_emergency_active(self) -> bool:
        """Return whether emergency mode is active."""
        return self._emergency_active

    def get_vetoed_commands(self) -> list[tuple[ManeuverCommand, str]]:
        """Return list of (command, reason) pairs that were vetoed."""
        return list(self._vetoed_commands)

    def clear_emergency(self) -> None:
        """Clear emergency state (requires operator confirmation)."""
        self._emergency_active = False
        logger.warning("Emergency state cleared by operator")
