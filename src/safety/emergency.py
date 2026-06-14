"""Emergency Procedures — response to critical safety failures.

Implements emergency response protocols for:
- Imminent collision
- Grounding risk
- Sensor failure
- Steering failure
- Propulsion failure

Each procedure returns a prioritized list of ManeuverCommands.
Also triggers appropriate COLREG signals (NUC lights/sounds).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from src.core.types import (
    ManeuverCommand, NavigationMode, OwnShipState, TargetVessel, AlarmLevel,
)
from src.core.geo import normalize_bearing, initial_bearing_deg, bearing_difference

logger = logging.getLogger(__name__)


class EmergencyProcedures:
    """
    Emergency response procedures per COLREG 1972, SOLAS, and flag state regulations.

    All procedures:
    1. Issue immediate safety commands
    2. Transition to appropriate navigation mode
    3. Generate appropriate COLREG signals
    4. Log the emergency for VDR
    """

    def handle_collision_imminent(
        self,
        own: OwnShipState,
        target: TargetVessel,
    ) -> list[ManeuverCommand]:
        """
        Emergency response when collision is imminent (TCPA < 2 min, DCPA < 0.1 NM).

        Actions (COLREG Rule 8(d)(e)):
        1. Hard starboard (maximum rudder) — avoid by largest possible margin
        2. Full ahead (if close) OR All stop — depending on geometry
        3. Sound signal (5+ short blasts per COLREG Rule 34(d))

        'In extremis': Take whatever action necessary to avoid collision,
        even if it requires departing from normal COLREG rules.
        """
        # Hard starboard alteration (≥ 60° for emergency per Rule 8)
        emergency_course = normalize_bearing(own.heading_deg + 90.0)  # Hard right

        # Bearing to target - used to decide engine action
        bearing_to_target = target.bearing_deg
        relative_bearing = (bearing_to_target - own.heading_deg + 360) % 360

        commands: list[ManeuverCommand] = []

        # Primary: hard starboard
        commands.append(ManeuverCommand(
            course_deg=emergency_course,
            speed_kts=own.velocity.speed_kts,  # Maintain speed to maximize turning
            reason=f"EMERGENCY: Imminent collision with {target.mmsi} — HARD STARBOARD",
            colreg_rule="Rule 8(d), Rule 17(b) in extremis",
            priority=100,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        ))

        # If target is dead ahead or close to starboard, also reduce speed
        if relative_bearing < 30.0 or relative_bearing > 330.0:
            commands.append(ManeuverCommand(
                course_deg=emergency_course,
                speed_kts=0.0,
                reason=f"EMERGENCY: Stop engines — collision imminent with {target.mmsi}",
                colreg_rule="Rule 8(e)",
                priority=100,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            ))

        # Sound signal command (represented as a ManeuverCommand with special reason)
        commands.append(ManeuverCommand(
            course_deg=None,
            speed_kts=None,
            reason="SOUND_SIGNAL: 5+ short blasts — danger signal (Rule 34(d))",
            colreg_rule="Rule 34(d)",
            priority=99,
        ))

        logger.critical(
            "COLLISION IMMINENT — Emergency procedure activated",
            extra={
                "target_mmsi": target.mmsi,
                "dcpa_nm": target.cpa_nm,
                "tcpa_min": target.tcpa_min,
                "emergency_course": emergency_course,
            }
        )

        return commands

    def handle_grounding_risk(
        self,
        own: OwnShipState,
        hazard_bearing: Optional[float] = None,
    ) -> list[ManeuverCommand]:
        """
        Emergency response when grounding risk is detected.

        Actions:
        1. Hard turn away from hazard (opposite bearing to hazard)
        2. Reduce speed
        3. Sound danger signal
        4. Prepare anchor if depth allows

        SOLAS Chapter V Regulation 34: Safe navigation and avoidance of dangerous situations.
        """
        commands: list[ManeuverCommand] = []

        if hazard_bearing is not None:
            # Turn away from hazard: reciprocal bearing + 45° to ensure clear track
            escape_bearing = normalize_bearing(hazard_bearing + 180.0)
            # Add 45° bias to starboard (conventional in open water)
            escape_course = normalize_bearing(escape_bearing + 45.0)
        else:
            # No known hazard bearing — turn hard starboard (safe convention)
            escape_course = normalize_bearing(own.heading_deg + 90.0)

        # Immediate course change
        commands.append(ManeuverCommand(
            course_deg=escape_course,
            speed_kts=max(own.velocity.speed_kts * 0.5, 2.0),  # Reduce but keep steerage
            reason=f"EMERGENCY: Grounding risk — altering to {escape_course:.0f}°",
            colreg_rule="SOLAS V/34",
            priority=100,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        ))

        # Danger signal
        commands.append(ManeuverCommand(
            course_deg=None,
            speed_kts=None,
            reason="SOUND_SIGNAL: 5+ short blasts — danger signal (Rule 34(d))",
            colreg_rule="Rule 34(d)",
            priority=99,
        ))

        logger.critical(
            "GROUNDING RISK — Emergency procedure activated",
            extra={
                "own_lat": own.position.lat,
                "own_lon": own.position.lon,
                "hazard_bearing": hazard_bearing,
                "escape_course": escape_course,
            }
        )

        return commands

    def handle_sensor_failure(
        self,
        failed_sensors: list[str],
        own: OwnShipState,
    ) -> list[ManeuverCommand]:
        """
        Emergency response to sensor failure.

        Per DNV NAUT-AW: sensor redundancy is mandatory.
        On loss of primary sensors:
        1. Reduce to safe speed (Rule 6, Rule 19)
        2. Alert remote operators
        3. Switch to last-known radar picture

        Actions:
        - Reduce speed to minimum safe speed
        - Maintain current course (safest when uncertain)
        - Generate CAUTION alarm
        """
        commands: list[ManeuverCommand] = []

        # Determine safe speed based on which sensors failed
        is_navigation_sensor = any(
            s in failed_sensors for s in ["GNSS", "GPS", "RADAR"]
        )
        is_collision_sensor = any(
            s in failed_sensors for s in ["RADAR", "AIS", "LIDAR"]
        )

        if is_navigation_sensor:
            # Cannot navigate accurately — stop and alert
            safe_speed = 0.0
            reason = f"EMERGENCY: Navigation sensor failure ({failed_sensors}) — stopping"
        elif is_collision_sensor:
            # Cannot detect targets — reduce to minimum navigable speed
            safe_speed = 4.0  # Bare steerage way
            reason = f"CAUTION: Collision sensor failure ({failed_sensors}) — reduced speed"
        else:
            # Non-critical sensor — reduce speed cautiously
            safe_speed = max(own.velocity.speed_kts * 0.5, 6.0)
            reason = f"ADVISORY: Sensor failure ({failed_sensors}) — reduced speed"

        commands.append(ManeuverCommand(
            course_deg=own.velocity.course_deg,  # Maintain course
            speed_kts=safe_speed,
            reason=reason,
            colreg_rule="Rule 6, Rule 19",
            priority=95,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))

        logger.error(
            "Sensor failure emergency procedure activated",
            extra={"failed_sensors": failed_sensors, "safe_speed": safe_speed}
        )

        return commands

    def handle_steering_failure(
        self,
        own: OwnShipState,
    ) -> list[ManeuverCommand]:
        """
        Emergency response to steering failure (loss of rudder control).

        Actions per COLREG Rule 27 (NUC):
        1. Stop engines immediately (vessel is NUC — not under command)
        2. Display NUC lights (2 all-round red lights / balls)
        3. Sound NUC signal (3 short blasts per Rule 35(e))
        4. Alert all surrounding vessels via DSC and AIS
        5. Assess anchoring feasibility

        NOTE: After steering failure, all course commands are invalid —
        only speed commands (stop) are meaningful.
        """
        commands: list[ManeuverCommand] = []

        # Stop engines — vessel is NUC
        commands.append(ManeuverCommand(
            course_deg=None,  # No steering available
            speed_kts=0.0,
            reason="EMERGENCY: Steering failure — NUC — stopping engines",
            colreg_rule="Rule 27 (NUC), Rule 35(e)",
            priority=100,
        ))

        # NUC sound signal
        commands.append(ManeuverCommand(
            course_deg=None,
            speed_kts=None,
            reason="SOUND_SIGNAL: NUC — 3 short blasts (Rule 35(e)). Display 2 all-round red lights.",
            colreg_rule="Rule 27, Rule 35(e)",
            priority=99,
        ))

        # AIS alert
        commands.append(ManeuverCommand(
            course_deg=None,
            speed_kts=None,
            reason="AIS_UPDATE: Nav status = NUC (not under command). Broadcast DSC emergency.",
            colreg_rule="SOLAS IV, ITU-R M.493",
            priority=98,
        ))

        logger.critical(
            "STEERING FAILURE — NUC procedure activated",
            extra={
                "own_lat": own.position.lat,
                "own_lon": own.position.lon,
                "own_speed": own.velocity.speed_kts,
            }
        )

        return commands

    def handle_propulsion_failure(
        self,
        own: OwnShipState,
    ) -> list[ManeuverCommand]:
        """
        Emergency response to propulsion failure (loss of main engine).

        Actions per COLREG Rule 27 (NUC):
        1. Display NUC signals immediately
        2. Sound NUC signal
        3. Assess anchor deployment (depends on depth, position, wind/current)
        4. Alert maritime rescue coordination center (MRCC)
        5. Broadcast pan-pan or mayday via DSC

        NOTE: Without propulsion, the vessel becomes NUC and drifts.
        Anchoring is the primary option if depth allows.
        """
        commands: list[ManeuverCommand] = []

        # NUC signal
        commands.append(ManeuverCommand(
            course_deg=None,
            speed_kts=None,
            reason="SOUND_SIGNAL: NUC — 3 short blasts (Rule 35(e)). Display 2 all-round red lights.",
            colreg_rule="Rule 27, Rule 35(e)",
            priority=100,
        ))

        # AIS NUC broadcast
        commands.append(ManeuverCommand(
            course_deg=None,
            speed_kts=None,
            reason="AIS_UPDATE: Nav status = NUC. Broadcast DSC MAYDAY/PAN-PAN. Contact MRCC.",
            colreg_rule="SOLAS IV, ITU-R M.825",
            priority=99,
        ))

        # Anchor assessment (can only anchor in appropriate depth/holding)
        # Current speed check: if still have way on, maintain heading into wind/current
        if own.velocity.speed_kts > 1.0:
            commands.append(ManeuverCommand(
                course_deg=own.heading_deg,  # Maintain heading to preserve steerage while way lasts
                speed_kts=None,  # No engine — cannot command speed
                reason="MAINTAIN HEADING: Use remaining way to position for anchor/rescue",
                colreg_rule="Seamanship — SOLAS V",
                priority=90,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            ))

        # Anchor deployment command (placeholder — requires depth sounder confirmation)
        commands.append(ManeuverCommand(
            course_deg=None,
            speed_kts=None,
            reason="ANCHOR_ASSESSMENT: Deploy anchor if depth < 40m and holding ground available. "
                   "ALERT: Verify depth sounder and current set before anchoring.",
            colreg_rule="Seamanship — SOLAS V",
            priority=85,
        ))

        logger.critical(
            "PROPULSION FAILURE — NUC procedure activated",
            extra={
                "own_lat": own.position.lat,
                "own_lon": own.position.lon,
                "own_speed": own.velocity.speed_kts,
                "own_heading": own.heading_deg,
            }
        )

        return commands
