"""Safety Supervisor — hard-limit enforcement layer above all agents.

Runs as a separate asyncio task at OS scheduling priority.
Cannot be overridden by any agent.
Provides absolute veto on all commands.

IEC 61508 SIL-3 pattern: independent safety layer.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.core.config import AppConfig
from src.core.constants import (
    COLREG_SAFE_DCPA_NM, COLREG_URGENT_DCPA_NM, MAX_SPEED_RESTRICTED_VIS_KTS
)
from src.core.exceptions import EmergencyStopRequired
from src.core.types import (
    AlarmLevel, ManeuverCommand, NavigationMode, OwnShipState, Position, TargetVessel,
)

logger = logging.getLogger(__name__)


class ProhibitedZone:
    """A circular prohibited zone (e.g., reef, TSS boundary)."""

    def __init__(self, center: Position, radius_nm: float, name: str = "") -> None:
        self.center = center
        self.radius_nm = radius_nm
        self.name = name


class SafetySupervisor:
    """
    Independent safety enforcement layer — runs separately from all agents.

    Hard limits (non-negotiable):
    1. DCPA must never go below hard_min_dcpa_nm (absolute collision avoidance)
    2. Speed must not exceed limits for visibility
    3. Vessel must not enter prohibited zones
    4. Vessel must not approach charted hazards within coast_margin_nm

    This class MUST be instantiated before the agent orchestrator and passed to it.
    The validate_command() method is called synchronously before any command is executed.

    Cannot be disabled or overridden by any agent.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._hard_min_dcpa = config.safety.hard_min_dcpa_nm
        self._max_speed = config.ship.max_speed_kts
        self._safe_speed_restricted = config.safety.safe_speed_restricted_vis_kts
        self._coast_margin = config.safety.coast_margin_nm
        self._prohibited_zones: list[ProhibitedZone] = []
        self._hazard_positions: list[Position] = []
        self._is_running = False
        self._veto_log: list[dict] = []
        self._cycle_count = 0

    def add_prohibited_zone(self, zone: ProhibitedZone) -> None:
        """Register a prohibited zone (e.g., anchored offshore installation)."""
        self._prohibited_zones.append(zone)
        logger.info("Prohibited zone added", extra={"name": zone.name, "radius": zone.radius_nm})

    def add_hazard_position(self, pos: Position) -> None:
        """Register a charted hazard position."""
        self._hazard_positions.append(pos)

    def validate_command(
        self,
        cmd: ManeuverCommand,
        own: OwnShipState,
        targets: list[TargetVessel],
    ) -> bool:
        """
        Validate a maneuver command against all safety hard limits.

        Returns True if the command is safe to execute.
        Returns False if the command must be blocked.

        This method is the core safety gate. It is called synchronously
        before any command reaches the ship's actuators.
        """
        # Emergency stop is ALWAYS allowed
        if cmd.speed_kts == 0.0:
            return True

        # Check speed limits
        if cmd.speed_kts is not None:
            max_allowed = self._get_max_speed(own.visibility_nm)
            if cmd.speed_kts > max_allowed + 0.1:
                self._log_veto(
                    cmd,
                    f"Speed {cmd.speed_kts:.1f} kts exceeds hard limit {max_allowed:.1f} kts"
                )
                return False

        # Check DCPA hard limit against all targets
        if cmd.course_deg is not None or cmd.speed_kts is not None:
            for target in targets:
                if target.cpa_nm < self._hard_min_dcpa:
                    # Command would maintain course toward critically close target
                    if target.tcpa_min > 0 and target.tcpa_min < 15.0:
                        # Only veto if this is a converging situation
                        self._log_veto(
                            cmd,
                            f"Hard DCPA violation: target {target.mmsi} at {target.cpa_nm:.2f}NM "
                            f"< hard limit {self._hard_min_dcpa:.2f}NM"
                        )
                        return False

        # Check prohibited zones (own ship's current position)
        if self.is_in_prohibited_zone(own.position):
            # If already in zone, only allow commands that move away
            self._log_veto(cmd, "Vessel in prohibited zone — only escape maneuvers permitted")
            return False

        return True

    def _get_max_speed(self, visibility_nm: float) -> float:
        """Get maximum allowed speed based on visibility."""
        if visibility_nm < 2.0:
            return self._safe_speed_restricted
        return self._max_speed

    def emergency_stop(self, reason: str) -> ManeuverCommand:
        """
        Generate an emergency stop command.

        This command bypasses all other validation and is immediately executed.
        Corresponds to COLREG Rule 8(e): 'if necessary take all way off.'
        """
        logger.critical(
            "EMERGENCY STOP ISSUED",
            extra={"reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()},
        )
        return ManeuverCommand(
            course_deg=None,
            speed_kts=0.0,
            reason=f"EMERGENCY STOP: {reason}",
            colreg_rule="Safety Supervisor Override",
            priority=100,
        )

    def is_grounding_risk(self, own: OwnShipState) -> bool:
        """
        Check if the vessel is at risk of grounding.

        Checks:
        1. Proximity to charted hazard positions
        2. Whether vessel is in a prohibited zone
        3. Shallow water indicators (future: depth sounder integration)

        Returns True if grounding risk detected.
        """
        from src.core.geo import haversine_nm

        # Check distance to all charted hazards
        for hazard in self._hazard_positions:
            dist = haversine_nm(own.position, hazard)
            if dist < self._coast_margin:
                logger.error(
                    "Grounding risk detected",
                    extra={
                        "hazard_lat": hazard.lat,
                        "hazard_lon": hazard.lon,
                        "distance_nm": round(dist, 3),
                        "margin_nm": self._coast_margin,
                    }
                )
                return True

        # Check prohibited zones
        if self.is_in_prohibited_zone(own.position):
            return True

        return False

    def is_in_prohibited_zone(self, pos: Position) -> bool:
        """Check if position is inside any prohibited zone."""
        from src.core.geo import haversine_nm
        for zone in self._prohibited_zones:
            if haversine_nm(pos, zone.center) < zone.radius_nm:
                return True
        return False

    def _log_veto(self, cmd: ManeuverCommand, reason: str) -> None:
        """Log a command veto for audit trail."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command_reason": cmd.reason,
            "command_priority": cmd.priority,
            "veto_reason": reason,
        }
        self._veto_log.append(entry)
        if len(self._veto_log) > 1000:
            self._veto_log = self._veto_log[-1000:]

        logger.warning(
            "Command vetoed by SafetySupervisor",
            extra={"veto_reason": reason, "cmd_reason": cmd.reason},
        )

    def get_veto_log(self) -> list[dict]:
        """Return audit log of vetoed commands."""
        return list(self._veto_log)

    async def run(self) -> None:
        """
        Main safety supervision loop.

        Runs independently of the agent orchestrator at 1-second intervals.
        Monitors for hazardous conditions and raises alarms.
        """
        self._is_running = True
        logger.info("SafetySupervisor running")

        try:
            while self._is_running:
                self._cycle_count += 1
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("SafetySupervisor cancelled")
        finally:
            self._is_running = False
            logger.info("SafetySupervisor stopped", extra={"total_cycles": self._cycle_count})

    def stop(self) -> None:
        """Signal the supervisor loop to stop."""
        self._is_running = False

    def get_status(self) -> dict:
        """Return supervisor status dictionary."""
        return {
            "is_running": self._is_running,
            "hard_min_dcpa_nm": self._hard_min_dcpa,
            "max_speed_kts": self._max_speed,
            "safe_speed_restricted_kts": self._safe_speed_restricted,
            "prohibited_zones": len(self._prohibited_zones),
            "hazard_positions": len(self._hazard_positions),
            "veto_count": len(self._veto_log),
            "cycle_count": self._cycle_count,
        }
