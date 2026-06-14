"""COLREG action resolver — resolves multiple simultaneous encounters.

When own ship faces multiple COLREG encounters simultaneously, this module
determines the composite maneuver that satisfies all applicable rules.

Priority: EMERGENCY > ALARM encounters > WARNING > CAUTION.
Safety rule: the most restrictive constraint wins.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from src.core.types import (
    OwnShipState, ColregEncounter, ManeuverCommand, EncounterType,
    COLREGAction, AlarmLevel
)
from src.core.exceptions import ManeuverConflictError
from src.core.geo import normalize_bearing, bearing_difference
from src.core.constants import MIN_COLREG_ALTERATION_DEG, COLREG_SAFE_DCPA_NM


# Severity ordering for AlarmLevel — higher value = more severe
_SEVERITY: dict[AlarmLevel, int] = {
    AlarmLevel.ADVISORY: 0,
    AlarmLevel.CAUTION: 1,
    AlarmLevel.WARNING: 2,
    AlarmLevel.ALARM: 3,
    AlarmLevel.EMERGENCY: 4,
}


class ActionResolver:
    """
    Resolves multiple simultaneous COLREG encounters into a safe, unified maneuver command.
    Handles the complex case of multiple vessels requiring different actions.
    """

    def __init__(self, hard_min_dcpa_nm: float = 0.2) -> None:
        self.hard_min_dcpa_nm = hard_min_dcpa_nm

    def resolve(
        self,
        own: OwnShipState,
        encounters: list[ColregEncounter],
        commands: Optional[list[ManeuverCommand]] = None,
    ) -> list[ManeuverCommand]:
        """
        Resolve multiple encounters into a prioritized list of maneuver commands.
        Most critical encounter (highest risk_level) takes priority.
        Validates that the resulting maneuver doesn't create new risks.
        """
        if not encounters:
            return []

        # Import here to avoid circular imports at module level
        from src.colreg.rules import COLREGRules
        rules = COLREGRules()

        # Sort encounters by risk level — highest severity first
        sorted_encounters = sorted(
            encounters,
            key=self._priority_sort_key,
            reverse=True,
        )

        # Generate a ManeuverCommand for each encounter using the applicable rule
        commands: list[ManeuverCommand] = []
        for enc in sorted_encounters:
            cmd = rules.get_applicable_rule(enc)
            commands.append(cmd)

        if not commands:
            return []

        # The primary command comes from the most critical encounter
        primary = commands[0]

        # If primary command is safe against all encounters, return all commands in order
        primary_safe = all(
            self.validate_proposed_maneuver(own, primary, enc)
            for enc in sorted_encounters
        )

        if primary_safe:
            return commands

        # Primary command conflicts — find the most restrictive starboard alteration
        # that satisfies all encounters.
        safe_headings = self.compute_safe_course_options(own, sorted_encounters)
        if safe_headings:
            # Pick the heading with the largest starboard deviation from current course
            # (most restrictive) to ensure we keep well clear of all threats.
            def starboard_deviation(h: float) -> float:
                diff = bearing_difference(own.velocity.course_deg, h)
                return diff if diff >= 0 else diff + 360.0

            most_restrictive = max(safe_headings, key=starboard_deviation)

            # Build a consolidated command using the most critical encounter's metadata
            primary_enc = sorted_encounters[0]
            consolidated = ManeuverCommand(
                course_deg=most_restrictive,
                speed_kts=primary_enc.recommended_speed_kts,
                reason=(
                    f"ActionResolver: consolidated maneuver for {len(encounters)} encounters; "
                    f"most restrictive safe course {most_restrictive:.1f} deg"
                ),
                colreg_rule="8/16",
                priority=95,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
            return [consolidated] + commands[1:]

        # No safe heading found — raise conflict error for Safety Supervisor escalation
        raise ManeuverConflictError(
            "No safe heading found that satisfies all simultaneous COLREG encounters",
            agent_a="COLREGAgent",
            agent_b="SafetyMonitor",
            context={
                "encounter_count": len(encounters),
                "encounter_types": [e.encounter_type.value for e in sorted_encounters],
                "risk_levels": [e.risk_level.value for e in sorted_encounters],
            },
        )

    def validate_proposed_maneuver(
        self,
        own: OwnShipState,
        command: ManeuverCommand,
        all_encounters: list[ColregEncounter]
    ) -> bool:
        """
        Validate that a proposed maneuver doesn't create new collision risks.
        Returns True if maneuver is safe, False if it creates new risks.
        """
        if command.course_deg is None:
            # Speed-only command; check speed doesn't increase risk
            return True

        # Accept a single encounter or a list for convenience
        encounter_list: list[ColregEncounter]
        if isinstance(all_encounters, list):
            encounter_list = all_encounters
        else:
            encounter_list = [all_encounters]  # type: ignore[unreachable]

        for enc in encounter_list:
            if not self._check_heading_safe(command.course_deg, own, [enc]):
                return False

            # Rule 15/16: give-way vessel must NOT cross ahead of stand-on vessel
            if enc.encounter_type == EncounterType.CROSSING_GIVE_WAY:
                # Port alteration is forbidden in a crossing give-way situation
                alteration = bearing_difference(own.heading_deg, command.course_deg)
                if alteration < -5.0:
                    return False

                # Check we are not crossing ahead: if the proposed course puts the
                # target from our starboard to port side, we may be crossing its bow.
                old_rel = bearing_difference(own.heading_deg, enc.target.bearing_deg)
                new_rel = bearing_difference(command.course_deg, enc.target.bearing_deg)
                if old_rel > 0.0 and new_rel < 0.0 and enc.target.cpa_nm < COLREG_SAFE_DCPA_NM:
                    return False

            # Emergency encounters require high-priority commands only
            if enc.risk_level == AlarmLevel.EMERGENCY and command.priority < 90:
                return False

        return True

    def compute_safe_course_options(
        self,
        own: OwnShipState,
        encounters: list[ColregEncounter]
    ) -> list[float]:
        """
        Returns list of safe headings (in degrees) that avoid all encounters.
        Checks 360 degrees in 5-degree increments.
        """
        safe_headings: list[float] = []
        current = own.velocity.course_deg

        # Evaluate candidates from current-90 to current+90 (180 deg arc, preferring
        # starboard alterations per COLREG Rule 8 guidance), then the rest of the circle.
        candidates: list[float] = []
        for delta in range(-90, 91, 5):
            candidates.append(normalize_bearing(current + delta))
        # Also check the full circle for completeness
        for delta in range(91, 270, 5):
            h = normalize_bearing(current + delta)
            if h not in candidates:
                candidates.append(h)

        for heading in candidates:
            if self._check_heading_safe(heading, own, encounters):
                safe_headings.append(heading)

        return safe_headings

    def _priority_sort_key(self, encounter: ColregEncounter) -> int:
        """Sort key for encounters - highest risk first."""
        priority_map = {
            AlarmLevel.EMERGENCY: 5,
            AlarmLevel.ALARM: 4,
            AlarmLevel.WARNING: 3,
            AlarmLevel.CAUTION: 2,
            AlarmLevel.ADVISORY: 1,
        }
        return priority_map.get(encounter.risk_level, 0)

    def _check_heading_safe(
        self,
        heading: float,
        own: OwnShipState,
        encounters: list[ColregEncounter]
    ) -> bool:
        """Check if a given heading would be safe relative to all encounters."""
        for enc in encounters:
            target = enc.target

            # Compute the new relative bearing of the target under the proposed heading
            new_rel_bearing = (target.bearing_deg - heading) % 360.0

            # Compute approximate new CPA under proposed heading:
            # Project own ship velocity along the new heading.
            own_speed = own.velocity.speed_kts
            own_new_vx = own_speed * math.sin(math.radians(heading)) / 60.0
            own_new_vy = own_speed * math.cos(math.radians(heading)) / 60.0

            tgt_vx = target.velocity.speed_kts * math.sin(math.radians(target.velocity.course_deg)) / 60.0
            tgt_vy = target.velocity.speed_kts * math.cos(math.radians(target.velocity.course_deg)) / 60.0

            # Relative velocity under proposed heading
            dvx = tgt_vx - own_new_vx
            dvy = tgt_vy - own_new_vy

            # Current separation vector (own is origin)
            from src.core.geo import pos_to_cartesian_nm
            tx, ty = pos_to_cartesian_nm(target.position, own.position)

            speed_sq = dvx * dvx + dvy * dvy
            if speed_sq < 1e-10:
                # Parallel tracks — separation is current range; check it's adequate
                current_range = math.sqrt(tx * tx + ty * ty)
                if current_range < COLREG_SAFE_DCPA_NM:
                    return False
                continue

            tcpa = -(tx * dvx + ty * dvy) / speed_sq
            if tcpa < 0:
                # Diverging under proposed heading — safe for this encounter
                continue

            dcpa_x = tx + dvx * tcpa
            dcpa_y = ty + dvy * tcpa
            new_dcpa = math.sqrt(dcpa_x * dcpa_x + dcpa_y * dcpa_y)

            if new_dcpa < COLREG_SAFE_DCPA_NM:
                # Proposed heading would bring us within unsafe CPA threshold
                return False

            # For give-way situations, also reject port alterations
            if enc.encounter_type == EncounterType.CROSSING_GIVE_WAY:
                alteration = bearing_difference(own.heading_deg, heading)
                if alteration < -5.0:
                    return False

        return True
