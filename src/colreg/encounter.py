"""COLREG encounter classification.

Classifies the geometric relationship between own ship and a target vessel
into COLREG 1972 encounter categories (Rules 13, 14, 15).

Bearing sectors (relative to own heading, degrees):
  Head-on        : 0° ± 6°              (354° – 006°)
  Starboard bow  : 006° – 112.5°        CROSSING  — own ship is GIVE-WAY (Rule 15)
  Overtaking arc : 112.5° – 247.5°      Rule 13
  Port bow       : 247.5° – 354°        CROSSING  — own ship is STAND-ON  (Rule 15)
"""

from __future__ import annotations

import math

from src.core.types import OwnShipState, TargetVessel, EncounterType, VesselType
from src.core.geo import bearing_difference, normalize_bearing
from src.core.constants import HEAD_ON_SECTOR_DEG, OVERTAKING_SECTOR_DEG


# Vessels that are always stand-on regardless of geometry (Rule 18 hierarchy)
_STAND_ON_TYPES: frozenset[VesselType] = frozenset({
    VesselType.NUC,
    VesselType.RAM,
})

# COLREG Rule 18 priority — lower number = higher priority (must be given way to)
_VESSEL_PRIORITY: dict[VesselType, int] = {
    VesselType.NUC: 1,
    VesselType.RAM: 2,
    VesselType.CBD: 3,
    VesselType.FISHING: 4,
    VesselType.SAILING: 5,
    VesselType.SEAPLANE: 6,
    VesselType.WIG: 6,
    VesselType.POWER_DRIVEN: 7,
    VesselType.PDUR: 7,
}

# Safe CPA/TCPA thresholds for SAFE classification
_SAFE_CPA_NM: float = 1.0        # NM — no risk if CPA exceeds this
_SAFE_TCPA_MIN: float = 30.0     # minutes — no risk if TCPA exceeds this


class EncounterClassifier:
    """Classifies vessel encounters according to COLREG 1972 Rules 13, 14, 15."""

    def get_relative_bearing(self, own: OwnShipState, target: TargetVessel) -> float:
        """Get bearing of target relative to own ship's heading (0-360, clockwise from bow).

        0°   = dead ahead
        90°  = starboard beam
        180° = dead astern
        270° = port beam

        Args:
            own:    Own ship navigational state.
            target: The tracked target vessel.

        Returns:
            Relative bearing in degrees [0, 360).
        """
        return (target.bearing_deg - own.heading_deg) % 360.0

    def classify(self, own: OwnShipState, target: TargetVessel) -> EncounterType:
        """Classify the encounter type between own ship and target.

        Rules applied in order:
          1. SAFE:              CPA > 1.0 NM and TCPA > 30 min
          2. NUC / RAM target:  always CROSSING_STAND_ON (Rule 18 — we give way)
          3. HEAD_ON (Rule 14): target within +/-6 deg from ahead AND reciprocal check
          4. OVERTAKING (Rule 13): target in stern arc 112.5 deg to 247.5 deg
          5. CROSSING (Rule 15): everything else
             - CROSSING_GIVE_WAY : target on own starboard bow (rel 0 to 112.5 deg)
             - CROSSING_STAND_ON : target on own port bow (rel 247.5 to 360 deg)

        Args:
            own:    Own ship navigational state.
            target: The tracked target vessel (must have pre-computed cpa_nm / tcpa_min).

        Returns:
            EncounterType enum value.
        """
        # 1. Safe separation — no risk if CPA > 1 NM and TCPA > 30 min
        if target.cpa_nm > _SAFE_CPA_NM and target.tcpa_min > _SAFE_TCPA_MIN:
            return EncounterType.SAFE

        # 2. Rule 18 vessel type hierarchy — NUC and RAM are always stand-on
        # Own ship (power-driven) must always give way to NUC/RAM targets.
        if target.vessel_type in _STAND_ON_TYPES:
            return EncounterType.CROSSING_STAND_ON

        rel_bearing = self.get_relative_bearing(own, target)

        # 3. HEAD-ON — Rule 14
        # Two conditions:
        #   a) Target is within +/-HEAD_ON_SECTOR_DEG of own ship's bow
        #   b) Own ship is within +/-HEAD_ON_SECTOR_DEG of target's bow
        #      (mutual near-reciprocal courses)
        ahead = rel_bearing <= HEAD_ON_SECTOR_DEG or rel_bearing >= (360.0 - HEAD_ON_SECTOR_DEG)
        if ahead:
            # Compute own ship's bearing as seen from target's bow.
            # The true bearing FROM target TO own ship is the reciprocal of target.bearing_deg.
            own_true_bearing_from_target = normalize_bearing(target.bearing_deg + 180.0)
            # Express relative to target's heading
            rel_own_from_target = (own_true_bearing_from_target - target.velocity.course_deg) % 360.0
            reciprocal_ok = (
                rel_own_from_target <= HEAD_ON_SECTOR_DEG
                or rel_own_from_target >= (360.0 - HEAD_ON_SECTOR_DEG)
            )
            if reciprocal_ok:
                return EncounterType.HEAD_ON

        # 4. OVERTAKING — Rule 13
        # Target is in the stern arc: 112.5 deg to 247.5 deg relative to own heading
        lower_overtaking = 180.0 - OVERTAKING_SECTOR_DEG   # 112.5 deg
        upper_overtaking = 180.0 + OVERTAKING_SECTOR_DEG   # 247.5 deg
        if lower_overtaking < rel_bearing < upper_overtaking:
            # Determine if own ship is overtaking (give-way) or being overtaken (stand-on).
            # Rule 13: own ship is overtaking if it is faster — regardless of closing rate,
            # the overtaking obligation persists until "finally past and clear" (Rule 13(d)).
            own_faster = own.velocity.speed_kts > target.velocity.speed_kts
            if own_faster:
                return EncounterType.OVERTAKING_GIVE_WAY
            return EncounterType.OVERTAKING_STAND_ON

        # 5. CROSSING — Rule 15
        # Target on starboard bow (0 to 112.5 deg relative bearing): own ship gives way
        # Target on port bow (247.5 to 360 deg relative bearing): own ship stands on
        if 0.0 < rel_bearing <= 112.5:
            return EncounterType.CROSSING_GIVE_WAY
        return EncounterType.CROSSING_STAND_ON
