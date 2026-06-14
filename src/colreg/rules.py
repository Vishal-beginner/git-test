"""COLREG 1972 Rules implementation.

Implements the International Regulations for Preventing Collisions at Sea, 1972
(COLREG), as amended.  Each method is named and documented with the exact rule
it implements.

Safety notice: All thresholds here are MINIMUM requirements. The ship operator
may configure tighter margins via SafetyConfig, but may never loosen them below
the statutory minima encoded in constants.py.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Optional
from src.core.types import (
    OwnShipState, TargetVessel, ColregEncounter, ManeuverCommand, RiskAssessment,
    EncounterType, COLREGAction, AlarmLevel, VesselType
)
from src.core.constants import (
    COLREG_SAFE_DCPA_NM, COLREG_URGENT_DCPA_NM, MIN_COLREG_ALTERATION_DEG,
    MAX_SPEED_RESTRICTED_VIS_KTS
)
from src.core.geo import normalize_bearing, bearing_difference
from src.colreg.encounter import EncounterClassifier
from src.collision_avoidance.cpa import CPACalculator


# Vessel type hierarchy per Rule 18 — lower number = higher priority (must be given way to)
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


def _expires_in(minutes: float) -> datetime:
    """Return a UTC datetime ``minutes`` from now."""
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


class COLREGRules:
    """
    Implements COLREG 1972 International Regulations for Preventing Collisions at Sea.
    All 38 rules with special focus on Rules 5-19.
    """

    def __init__(
        self,
        dcpa_threshold_nm: float = COLREG_SAFE_DCPA_NM,
        tcpa_threshold_min: float = 30.0,
        hard_min_dcpa_nm: float = 0.2,
    ) -> None:
        self.dcpa_threshold_nm = dcpa_threshold_nm
        self.tcpa_threshold_min = tcpa_threshold_min
        self.hard_min_dcpa_nm = hard_min_dcpa_nm
        self.classifier = EncounterClassifier()
        self.cpa_calc = CPACalculator()

    def rule_5_lookout(self, targets: list[TargetVessel]) -> list[TargetVessel]:
        """
        Rule 5 - Look-out:
        'Every vessel shall at all times maintain a proper look-out by sight and
        hearing as well as by all available means appropriate in the prevailing
        circumstances and conditions so as to make a full appraisal of the situation
        and of the risk of collision.'

        Returns targets requiring attention (CPA < 2NM or TCPA < 20 min).
        """
        flagged: list[TargetVessel] = []
        for t in targets:
            if t.cpa_nm < 2.0 or (t.tcpa_min > 0 and t.tcpa_min < 20.0):
                flagged.append(t)
        # Sort by range ascending — nearest threat first
        flagged.sort(key=lambda t: t.range_nm)
        return flagged

    def rule_6_safe_speed(self, own: OwnShipState, nearby_count: int = 0) -> float:
        """
        Rule 6 - Safe Speed:
        'Every vessel shall at all times proceed at a safe speed so that she can
        take proper and effective action to avoid collision and be stopped within
        a distance appropriate to the prevailing circumstances and conditions.'

        Factors: visibility, traffic density, vessel maneuverability.
        Returns max safe speed in knots.
        """
        vis = own.visibility_nm

        if vis < 0.5:
            # Dense fog: restrict to bare steerage way
            return 4.0

        if vis < 2.0:
            # Restricted visibility: moderate restriction
            return 6.0

        if vis < 5.0:
            # Light mist: cap at own current speed or 10 kts, whichever is lower
            return min(own.velocity.speed_kts, 10.0)

        # Good to moderate visibility: cap at MAX_SPEED_RESTRICTED_VIS_KTS
        if vis < 10.0:
            return min(own.velocity.speed_kts, MAX_SPEED_RESTRICTED_VIS_KTS)

        # Excellent visibility — full speed permissible subject to Rule 6 factors
        return own.velocity.speed_kts

    def rule_7_risk_of_collision(self, own: OwnShipState, target: TargetVessel) -> RiskAssessment:
        """
        Rule 7 - Risk of Collision:
        'Every vessel shall use all available means appropriate to the prevailing
        circumstances and conditions to determine if risk of collision exists.
        If there is any doubt such risk shall be deemed to exist.'

        Uses CPA/TCPA analysis.
        """
        dcpa = target.cpa_nm
        tcpa = target.tcpa_min

        if tcpa < 0:
            # Vessels are diverging — already past CPA
            if dcpa < COLREG_URGENT_DCPA_NM:
                risk_level = AlarmLevel.ALARM
                action = COLREGAction.EMERGENCY_MANEUVER
            elif dcpa < COLREG_SAFE_DCPA_NM:
                risk_level = AlarmLevel.CAUTION
                action = COLREGAction.MAINTAIN
            else:
                risk_level = AlarmLevel.ADVISORY
                action = COLREGAction.MAINTAIN
        elif dcpa < COLREG_URGENT_DCPA_NM:
            if tcpa < 5.0:
                risk_level = AlarmLevel.EMERGENCY
                action = COLREGAction.EMERGENCY_MANEUVER
            elif tcpa < 15.0:
                risk_level = AlarmLevel.ALARM
                action = COLREGAction.ALTER_STARBOARD
            elif tcpa < 30.0:
                risk_level = AlarmLevel.WARNING
                action = COLREGAction.ALTER_STARBOARD
            else:
                risk_level = AlarmLevel.CAUTION
                action = COLREGAction.MAINTAIN
        elif dcpa < COLREG_SAFE_DCPA_NM:
            if tcpa < 10.0:
                risk_level = AlarmLevel.ALARM
                action = COLREGAction.ALTER_STARBOARD
            elif tcpa < 20.0:
                risk_level = AlarmLevel.WARNING
                action = COLREGAction.ALTER_STARBOARD
            elif tcpa < 30.0:
                risk_level = AlarmLevel.CAUTION
                action = COLREGAction.MAINTAIN
            else:
                risk_level = AlarmLevel.ADVISORY
                action = COLREGAction.MAINTAIN
        elif dcpa < 1.0:
            if tcpa < 10.0:
                risk_level = AlarmLevel.WARNING
                action = COLREGAction.ALTER_STARBOARD
            elif tcpa < 20.0:
                risk_level = AlarmLevel.CAUTION
                action = COLREGAction.MAINTAIN
            else:
                risk_level = AlarmLevel.ADVISORY
                action = COLREGAction.MAINTAIN
        else:
            risk_level = AlarmLevel.ADVISORY
            action = COLREGAction.MAINTAIN

        confidence = 1.0 if target.is_ais_confirmed else 0.75

        return RiskAssessment(
            target_mmsi=target.mmsi,
            dcpa_nm=dcpa,
            tcpa_min=tcpa,
            risk_level=risk_level,
            recommended_action=action,
            confidence=confidence,
        )

    def rule_8_action_to_avoid(
        self,
        encounter: ColregEncounter,
        own: Optional[OwnShipState] = None,
    ) -> ManeuverCommand:
        """
        Rule 8 - Action to Avoid Collision:
        'Any action taken to avoid collision shall be taken in ample time and shall
        be large enough to be readily apparent to the other vessel; a succession of
        small alterations of course or speed shall be avoided.'

        Action must be positive, early, and substantial (>= 30 degrees).
        """
        course = encounter.recommended_course_deg
        if course is None:
            # Compute a default substantial starboard alteration
            base = own.velocity.course_deg if own is not None else encounter.target.velocity.course_deg
            # For head-on: own course is reciprocal of target; for others, use bearing offset
            if encounter.encounter_type == EncounterType.HEAD_ON:
                own_course = normalize_bearing(base + 180.0) if own is None else base
            else:
                own_course = base
            course = normalize_bearing(own_course + MIN_COLREG_ALTERATION_DEG)
        return ManeuverCommand(
            course_deg=course,
            speed_kts=encounter.recommended_speed_kts,
            reason=(
                f"Rule 8: Positive avoidance — large, early action for "
                f"{encounter.encounter_type.value} with {encounter.target.mmsi}; "
                f"alteration >= {MIN_COLREG_ALTERATION_DEG:.0f} deg to starboard"
            ),
            colreg_rule="8",
            priority=80,
            expires_at=_expires_in(30.0),
        )

    def rule_9_narrow_channel(self, own: OwnShipState) -> Optional[ManeuverCommand]:
        """
        Rule 9 - Narrow Channels:
        'A vessel proceeding along the course of a narrow channel or fairway shall
        keep as near to the outer limit of the channel or fairway which lies on her
        starboard side as is safe and practicable.'

        For autonomous systems: maintain starboard bias in constrained waters.
        """
        # Return a command to keep the current course, which the planner has
        # set to follow the starboard side of the narrow channel or fairway.
        return ManeuverCommand(
            course_deg=own.velocity.course_deg,
            speed_kts=own.velocity.speed_kts,
            reason=(
                "Rule 9: Narrow channel — maintain current course to keep "
                "to the starboard limit of the channel as is safe and practicable"
            ),
            colreg_rule="9",
            priority=60,
            expires_at=_expires_in(30.0),
        )

    def rule_13_overtaking(self, encounter: ColregEncounter, own: Optional[OwnShipState] = None) -> ManeuverCommand:
        """
        Rule 13 - Overtaking:
        'Notwithstanding anything contained in the Rules of Part B, Sections I and II,
        any vessel overtaking any other shall keep out of the way of the vessel being
        overtaken.'

        'A vessel shall be deemed to be overtaking when coming up with another vessel
        from a direction more than 22.5 degrees abaft her beam.'
        """
        # Own ship is overtaking — must keep clear.
        # Alter to starboard to pass the target's port side and keep well clear.
        # Compute default starboard alteration if no recommended course is given.
        course = encounter.recommended_course_deg
        if course is None and own is not None:
            course = normalize_bearing(own.velocity.course_deg + MIN_COLREG_ALTERATION_DEG)
        speed = encounter.recommended_speed_kts
        return ManeuverCommand(
            course_deg=course,
            speed_kts=speed if course is None else None if speed is None else speed,
            reason=(
                f"Rule 13: Overtaking — own ship is overtaking {encounter.target.mmsi}; "
                f"altering to starboard to pass target's port side and keep clear"
            ),
            colreg_rule="13",
            priority=82,
            expires_at=_expires_in(30.0),
        )

    def rule_14_head_on(self, encounter: ColregEncounter, own: Optional[OwnShipState] = None) -> ManeuverCommand:
        """
        Rule 14 - Head-on Situation:
        'When two power-driven vessels are meeting on reciprocal or nearly reciprocal
        courses so as to involve risk of collision each shall alter her course to starboard
        so that each shall pass on the port side of the other.'
        """
        # Both vessels must alter to starboard — each passes on the other's port side.
        # Minimum alteration is MIN_COLREG_ALTERATION_DEG (30 deg) to be "readily apparent".
        # Compute a real course if recommended_course_deg is None.
        course = encounter.recommended_course_deg
        if course is None:
            # Derive from target bearing: target is ahead (bearing ~0°), so we go starboard
            target_course = encounter.target.velocity.course_deg
            # Own heading is approximately reciprocal of target course
            own_course = normalize_bearing(target_course + 180.0)
            if own is not None:
                own_course = own.velocity.course_deg
            course = normalize_bearing(own_course + MIN_COLREG_ALTERATION_DEG)
        return ManeuverCommand(
            course_deg=course,
            speed_kts=encounter.recommended_speed_kts,
            reason=(
                f"Rule 14: Head-on — altering >= {MIN_COLREG_ALTERATION_DEG:.0f} deg "
                f"to starboard to pass port-to-port with {encounter.target.mmsi}"
            ),
            colreg_rule="14",
            priority=85,
            expires_at=_expires_in(30.0),
        )

    def rule_15_crossing(self, encounter: ColregEncounter, own: Optional[OwnShipState] = None) -> ManeuverCommand:
        """
        Rule 15 - Crossing Situation:
        'When two power-driven vessels are crossing so as to involve risk of collision,
        the vessel which has the other on her own starboard side shall keep out of the
        way and shall, if the circumstances of the case admit, avoid crossing ahead of
        the other vessel.'
        """
        def _default_course(base_course: float) -> float:
            """Compute a default starboard course alteration."""
            return normalize_bearing(base_course + MIN_COLREG_ALTERATION_DEG)

        if encounter.encounter_type == EncounterType.CROSSING_GIVE_WAY:
            course = encounter.recommended_course_deg
            if course is None:
                if own is not None:
                    # Alter to starboard from own heading
                    course = _default_course(own.velocity.course_deg)
                else:
                    # Target is on starboard bow; alter to starboard by angling
                    # away from target using target bearing as reference
                    course = normalize_bearing(encounter.target.bearing_deg + MIN_COLREG_ALTERATION_DEG)
            return ManeuverCommand(
                course_deg=course,
                speed_kts=encounter.recommended_speed_kts,
                reason=(
                    f"Rule 15: Crossing give-way — altering to starboard and passing "
                    f"astern of {encounter.target.mmsi}; shall not cross ahead"
                ),
                colreg_rule="15",
                priority=83,
                expires_at=_expires_in(30.0),
            )

        # CROSSING_STAND_ON — maintain course and speed
        course = encounter.recommended_course_deg
        speed = encounter.recommended_speed_kts
        if course is None and own is not None:
            course = own.velocity.course_deg
        if speed is None and own is not None:
            speed = own.velocity.speed_kts
        elif speed is None:
            speed = encounter.target.velocity.speed_kts  # Use target speed as proxy
        return ManeuverCommand(
            course_deg=course,
            speed_kts=speed,
            reason=(
                f"Rule 15: Crossing stand-on — maintaining course and speed; "
                f"{encounter.target.mmsi} is the give-way vessel"
            ),
            colreg_rule="15",
            priority=70,
            expires_at=_expires_in(30.0),
        )

    def rule_16_give_way_action(
        self,
        encounter: ColregEncounter,
        own: Optional[OwnShipState] = None,
    ) -> ManeuverCommand:
        """
        Rule 16 - Action by Give-way Vessel:
        'Every vessel which is directed to keep out of the way of another vessel shall,
        so far as possible, take early and substantial action to keep well clear.'

        Must NOT cross ahead of stand-on vessel.
        """
        # Early and substantial starboard action — never cross ahead of stand-on
        course = encounter.recommended_course_deg
        if course is None:
            base = own.velocity.course_deg if own is not None else 0.0
            course = normalize_bearing(base + MIN_COLREG_ALTERATION_DEG)
        return ManeuverCommand(
            course_deg=course,
            speed_kts=encounter.recommended_speed_kts,
            reason=(
                f"Rule 16: Give-way — taking early and substantial action to keep well "
                f"clear of {encounter.target.mmsi}; altering to starboard, not crossing ahead"
            ),
            colreg_rule="16",
            priority=85,
            expires_at=_expires_in(30.0),
        )

    def rule_17_stand_on_action(
        self,
        encounter: ColregEncounter,
        own: Optional[OwnShipState] = None,
        give_way_vessel_acting: bool = False,
    ) -> Optional[ManeuverCommand]:
        """
        Rule 17 - Action by Stand-on Vessel:
        'Where one of two vessels is to keep out of the way the other shall keep her
        course and speed. The latter vessel may however take action to avoid collision
        by her manoeuvre alone as soon as it becomes apparent that the vessel required
        to keep out of the way is not taking appropriate action.'
        """
        # Rule 17(a)(ii) / 17(b): risk has escalated to ALARM or EMERGENCY,
        # meaning the give-way vessel is not taking action.  Take independent
        # emergency manoeuvre to starboard (never port).
        if encounter.risk_level in (AlarmLevel.ALARM, AlarmLevel.EMERGENCY):
            course = encounter.recommended_course_deg
            if course is None:
                base = own.velocity.course_deg if own is not None else 0.0
                course = normalize_bearing(base + MIN_COLREG_ALTERATION_DEG)
            return ManeuverCommand(
                course_deg=course,
                speed_kts=encounter.recommended_speed_kts,
                reason=(
                    f"Rule 17: Stand-on vessel taking independent emergency action — "
                    f"give-way vessel {encounter.target.mmsi} not manoeuvring; "
                    f"altering to starboard to avoid collision"
                ),
                colreg_rule="17",
                priority=90,
                expires_at=_expires_in(30.0),
            )

        # Rule 17(a)(i): maintain course and speed — no command needed.
        # The navigation agent maintains its current course/speed by default.
        # Returning None tells the orchestrator not to override normal navigation.
        return None

    def rule_18_responsibilities(self, own: OwnShipState, target: TargetVessel) -> EncounterType:
        """
        Rule 18 - Responsibilities Between Vessels:
        Vessel hierarchy (from highest to lowest priority/right of way):
        1. Vessel not under command (NUC)
        2. Vessel restricted in ability to maneuver (RAM)
        3. Vessel constrained by draft (CBD)
        4. Fishing vessel
        5. Sailing vessel
        6. Power-driven vessel

        'A power-driven vessel underway shall keep out of the way of: a vessel not
        under command; a vessel restricted in ability to maneuver; a vessel engaged
        in fishing; a sailing vessel.'
        """
        own_priority = _VESSEL_PRIORITY.get(own.vessel_type, 7)
        tgt_priority = _VESSEL_PRIORITY.get(target.vessel_type, 7)

        if own_priority > tgt_priority:
            # Own ship has lower Rule 18 standing — must give way
            return EncounterType.CROSSING_GIVE_WAY

        if own_priority < tgt_priority:
            # Own ship has higher Rule 18 standing — stand on
            return EncounterType.CROSSING_STAND_ON

        # Equal priority — fall back to geometric encounter classification
        return self.classifier.classify(own, target)

    def rule_19_restricted_visibility(self, own: OwnShipState, target: TargetVessel) -> ManeuverCommand:
        """
        Rule 19 - Conduct in Restricted Visibility:
        'Every vessel shall proceed at a safe speed adapted to the prevailing
        circumstances and conditions of restricted visibility.'

        'A vessel which detects by radar alone the presence of another vessel shall
        determine if a close-quarters situation is developing and/or risk of collision
        exists. If so, she shall take avoiding action in ample time.'

        'Except where it has been ascertained that a risk of collision does not exist,
        every vessel which hears apparently forward of her beam the fog signal of another
        vessel, or which cannot avoid a close-quarters situation with another vessel
        forward of her beam, shall reduce her speed to the minimum at which she can be
        kept on her course. She shall if necessary take all way off and in any case
        navigate with extreme caution until danger of collision is over.'

        Key: Shall NOT alter to port for a vessel on own port bow. Prefer starboard.
        """
        rel_bearing = self.classifier.get_relative_bearing(own, target)
        safe_speed = self.rule_6_safe_speed(own)

        # Determine if target is forward of beam
        forward_of_beam = rel_bearing < 90.0 or rel_bearing > 270.0

        if forward_of_beam:
            # Rule 19(d)(i): shall NOT alter to port for target forward of beam.
            # Reduce to minimum steerage; if close-quarters developing, alter starboard.
            if target.cpa_nm < COLREG_SAFE_DCPA_NM and target.tcpa_min > 0 and target.tcpa_min < 20.0:
                # Close-quarters situation developing — alter starboard and reduce to minimum
                new_course = normalize_bearing(own.velocity.course_deg + MIN_COLREG_ALTERATION_DEG)
                speed = max(2.0, safe_speed * 0.5)
                reason = (
                    f"Rule 19: Restricted visibility — close-quarters with radar target "
                    f"{target.mmsi} forward of beam; altering {MIN_COLREG_ALTERATION_DEG:.0f} deg "
                    f"to starboard and reducing to minimum speed {speed:.1f} kts"
                )
            else:
                # Risk identified but not yet close-quarters — reduce speed, maintain course
                new_course = own.velocity.course_deg
                speed = safe_speed
                reason = (
                    f"Rule 19: Restricted visibility — radar target {target.mmsi} forward "
                    f"of beam; reducing to safe speed {safe_speed:.1f} kts, monitoring"
                )
        else:
            # Rule 19(d)(ii): target abeam or abaft — do NOT alter course toward target.
            # Maintain course, reduce to safe speed.
            new_course = own.velocity.course_deg
            speed = safe_speed
            reason = (
                f"Rule 19: Restricted visibility — radar target {target.mmsi} "
                f"abeam/abaft beam; maintaining course, reducing to safe speed "
                f"{safe_speed:.1f} kts; shall not alter toward target"
            )

        return ManeuverCommand(
            course_deg=new_course,
            speed_kts=speed,
            reason=reason,
            colreg_rule="19",
            priority=88,
            expires_at=_expires_in(30.0),
        )

    def get_applicable_rule(self, encounter: ColregEncounter) -> ManeuverCommand:
        """Dispatch to the correct rule method based on encounter type."""
        enc_type = encounter.encounter_type

        if enc_type == EncounterType.HEAD_ON:
            return self.rule_14_head_on(encounter)

        if enc_type == EncounterType.OVERTAKING_GIVE_WAY:
            return self.rule_13_overtaking(encounter)

        if enc_type == EncounterType.OVERTAKING_STAND_ON:
            # Stand-on in overtaking — Rule 17 may apply
            cmd = self.rule_17_stand_on_action(encounter)
            if cmd is not None:
                return cmd
            # Maintain course and speed (Rule 17(a)(i))
            return ManeuverCommand(
                course_deg=encounter.recommended_course_deg,
                speed_kts=encounter.recommended_speed_kts,
                reason=(
                    f"Rule 17 / Rule 13: Being overtaken by {encounter.target.mmsi} "
                    f"— stand-on, maintain course and speed"
                ),
                colreg_rule="13/17",
                priority=70,
                expires_at=_expires_in(30.0),
            )

        if enc_type in (EncounterType.CROSSING_GIVE_WAY, EncounterType.CROSSING_STAND_ON):
            return self.rule_15_crossing(encounter)

        if enc_type == EncounterType.SAFE:
            return ManeuverCommand(
                course_deg=encounter.recommended_course_deg,
                speed_kts=encounter.recommended_speed_kts,
                reason=f"No COLREG action required — safe separation with {encounter.target.mmsi}",
                colreg_rule=None,
                priority=10,
                expires_at=_expires_in(30.0),
            )

        # UNKNOWN or unhandled encounter type — apply Rule 8 general avoidance
        return self.rule_8_action_to_avoid(encounter)
