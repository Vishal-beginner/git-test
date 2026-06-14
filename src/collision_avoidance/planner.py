"""Collision avoidance maneuver planner.

Determines and validates avoidance maneuvers, simulates their outcome to
ensure they achieve the required safe passing distance, and computes
return-to-track maneuvers once the threat has cleared.

Design principles (COLREG Rule 8):
- Prefer course alterations over speed reductions
- Course alterations must be to STARBOARD in head-on / crossing give-way
- Alterations must be >= 30° to be "readily apparent"
- Maneuvers must be taken in ample time
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.collision_avoidance.cpa import CPACalculator
from src.core.constants import MIN_COLREG_ALTERATION_DEG, COLREG_SAFE_DCPA_NM
from src.core.geo import normalize_bearing, bearing_difference
from src.core.types import (
    AlarmLevel,
    COLREGAction,
    ColregEncounter,
    EncounterType,
    ManeuverCommand,
    OwnShipState,
    Route,
    TargetVessel,
)


class AvoidancePlanner:
    """Plans COLREG-compliant avoidance maneuvers and manages post-avoidance resumption."""

    def __init__(self, safe_dcpa_nm: float = COLREG_SAFE_DCPA_NM) -> None:
        self._safe_dcpa = safe_dcpa_nm
        self._cpa_calc = CPACalculator()

    def plan_avoidance(
        self,
        own: OwnShipState,
        encounters: list[ColregEncounter],
        route: Route,
    ) -> list[ManeuverCommand]:
        """Plan avoidance maneuvers for all active encounters.

        Only give-way encounters require action from own ship.  Stand-on
        encounters are monitored and acted on only if the give-way vessel
        is not manoeuvring (Rule 17).

        Args:
            own: Own ship state.
            encounters: All active COLREG encounters.
            route: Active voyage route (used for resume-track planning).

        Returns:
            List of ManeuverCommands ordered by priority (highest first).
        """
        commands: list[ManeuverCommand] = []

        give_way_encounters = [
            e for e in encounters
            if e.encounter_type in (
                EncounterType.HEAD_ON,
                EncounterType.CROSSING_GIVE_WAY,
                EncounterType.OVERTAKING_GIVE_WAY,
            )
            and e.risk_level in (AlarmLevel.ALARM, AlarmLevel.EMERGENCY, AlarmLevel.WARNING)
        ]

        if not give_way_encounters:
            return commands

        # Sort by most severe first
        severity_order = [
            AlarmLevel.EMERGENCY, AlarmLevel.ALARM, AlarmLevel.WARNING,
            AlarmLevel.CAUTION, AlarmLevel.ADVISORY,
        ]
        give_way_encounters.sort(key=lambda e: severity_order.index(e.risk_level))

        # Compute a composite avoidance course that clears ALL give-way threats
        avoidance_course = self._compute_composite_avoidance(own, give_way_encounters)

        if avoidance_course is not None:
            primary = give_way_encounters[0]
            commands.append(
                ManeuverCommand(
                    course_deg=avoidance_course,
                    speed_kts=own.velocity.speed_kts,
                    reason=(
                        f"COLREG avoidance: {primary.encounter_type.value} "
                        f"with {primary.target.mmsi} — course {avoidance_course:.1f}°"
                    ),
                    colreg_rule="8/16",
                    priority=85,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                )
            )
        else:
            # Course alteration insufficient — add speed reduction as backup
            commands.append(
                ManeuverCommand(
                    course_deg=own.velocity.course_deg,
                    speed_kts=own.velocity.speed_kts * 0.5,
                    reason="COLREG avoidance: reducing speed — no clear course available",
                    colreg_rule="8",
                    priority=83,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
                )
            )

        return commands

    def compute_return_to_track(
        self, own: OwnShipState, route: Route, active_leg_idx: int
    ) -> ManeuverCommand:
        """Generate a command to resume the planned route after avoidance.

        Called when all threats have cleared (all targets have DCPA > safe threshold).

        Args:
            own: Own ship state.
            route: Active voyage route.
            active_leg_idx: Index of the current active route leg.

        Returns:
            ManeuverCommand to resume track.
        """
        from src.core.geo import initial_bearing_deg

        if active_leg_idx >= len(route.waypoints) - 1:
            # At or past last waypoint — maintain current course
            return ManeuverCommand(
                course_deg=own.velocity.course_deg,
                speed_kts=own.velocity.speed_kts,
                reason="Route complete — maintaining course",
                priority=40,
            )

        next_wpt = route.waypoints[active_leg_idx + 1]
        track_bearing = initial_bearing_deg(own.position, next_wpt.position)

        return ManeuverCommand(
            course_deg=track_bearing,
            speed_kts=own.velocity.speed_kts,
            reason=f"Resuming track to {next_wpt.name} after avoidance maneuver",
            priority=45,
        )

    def simulate_maneuver(
        self,
        own: OwnShipState,
        command: ManeuverCommand,
        all_targets: list[TargetVessel],
        steps: int = 20,
        step_interval_min: float = 1.0,
    ) -> float:
        """Simulate a proposed maneuver and return the minimum future DCPA achieved.

        Propagates own ship and all targets forward using dead reckoning for
        `steps` time steps.  Returns the minimum DCPA across all targets and steps.

        Args:
            own: Current own ship state.
            command: Proposed maneuver to simulate.
            all_targets: All currently tracked targets.
            steps: Number of simulation steps.
            step_interval_min: Duration of each step in minutes.

        Returns:
            Minimum DCPA in NM across all targets over the simulation horizon.
        """
        from src.core.types import Velocity, Position

        sim_course = command.course_deg if command.course_deg is not None else own.velocity.course_deg
        sim_speed = command.speed_kts if command.speed_kts is not None else own.velocity.speed_kts

        own_vel = Velocity(speed_kts=sim_speed, course_deg=sim_course)

        min_dcpa = float("inf")

        for step in range(1, steps + 1):
            dt_s = step * step_interval_min * 60.0

            # Dead-reckon own ship
            own_pos = self._cpa_calc.predict_position(own.position, own_vel, dt_s)

            # Create simulated own state
            from src.core.types import OwnShipState
            sim_own = OwnShipState(
                position=own_pos,
                velocity=own_vel,
                mode=own.mode,
                vessel_type=own.vessel_type,
                dimensions=own.dimensions,
                heading_deg=sim_course,
            )

            for target in all_targets:
                tgt_pos = self._cpa_calc.predict_position(
                    target.position, target.velocity, dt_s
                )
                from src.core.types import TargetVessel
                sim_target = TargetVessel(
                    mmsi=target.mmsi,
                    position=tgt_pos,
                    velocity=target.velocity,
                    cpa_nm=0.0,
                    tcpa_min=0.0,
                    range_nm=0.0,
                    last_updated=target.last_updated,
                )
                dcpa, _ = self._cpa_calc.calculate(sim_own, sim_target)
                min_dcpa = min(min_dcpa, dcpa)

        return min_dcpa if min_dcpa < float("inf") else 999.0

    def _compute_composite_avoidance(
        self,
        own: OwnShipState,
        encounters: list[ColregEncounter],
    ) -> float | None:
        """Find a single course alteration that clears all give-way encounters.

        Searches starboard arcs first (preferred per COLREG for head-on/crossing).
        Returns the course in degrees, or None if no adequate course found.
        """
        current = own.velocity.course_deg

        # Try starboard alterations first: 30°, 45°, 60°, 90°, 120°
        # Then port alterations (only if no starboard option works): 30°, 45°, 60°
        candidates: list[float] = []
        for delta in range(30, 181, 15):
            candidates.append(normalize_bearing(current + delta))  # Starboard
        for delta in range(30, 91, 15):
            candidates.append(normalize_bearing(current - delta))  # Port (last resort)

        for candidate_course in candidates:
            candidate_cmd = ManeuverCommand(
                course_deg=candidate_course,
                speed_kts=own.velocity.speed_kts,
                reason="Candidate",
                priority=50,
            )

            # Simulate and check minimum DCPA
            target_list = [e.target for e in encounters]
            min_dcpa = self.simulate_maneuver(own, candidate_cmd, target_list, steps=15)

            if min_dcpa >= self._safe_dcpa:
                # Verify this course doesn't cross ahead of any crossing stand-on
                valid = True
                for enc in encounters:
                    if enc.encounter_type == EncounterType.CROSSING_GIVE_WAY:
                        alteration = bearing_difference(current, candidate_course)
                        # Port alteration in crossing give-way → violates Rule 15/16
                        if alteration < -5.0:
                            valid = False
                            break
                if valid:
                    return candidate_course

        return None
