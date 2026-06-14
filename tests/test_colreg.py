"""Tests for COLREG encounter classification and rule application."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from src.core.types import (
    Position, Velocity, OwnShipState, TargetVessel, ColregEncounter,
    ManeuverCommand, AlarmLevel, EncounterType, COLREGAction,
    NavigationMode, VesselType, VesselDimensions,
)
from src.colreg.encounter import EncounterClassifier
from src.colreg.rules import COLREGRules
from src.core.constants import MIN_COLREG_ALTERATION_DEG
from src.core.geo import destination_point


# ── Factories ─────────────────────────────────────────────────────────────────

def make_own_ship(
    lat=51.5, lon=1.0, speed=10.0, course=0.0, heading=0.0,
    vessel_type=VesselType.POWER_DRIVEN, visibility=10.0,
) -> OwnShipState:
    return OwnShipState(
        position=Position(lat=lat, lon=lon),
        velocity=Velocity(speed_kts=speed, course_deg=course),
        mode=NavigationMode.AUTONOMOUS,
        vessel_type=vessel_type,
        dimensions=VesselDimensions(length_m=180.0, beam_m=28.0, draft_m=9.5, gross_tonnage=25000.0),
        heading_deg=heading if heading else course,
        timestamp=datetime.now(timezone.utc),
        visibility_nm=visibility,
    )


def make_target(
    mmsi="123456789", bearing=0.0, range_nm=3.0, speed=10.0, course=180.0,
    cpa_nm=0.3, tcpa_min=10.0,
    vessel_type=VesselType.POWER_DRIVEN, is_ais=True,
) -> TargetVessel:
    """Create a target at given bearing/range from a fixed reference position."""
    origin = Position(lat=51.5, lon=1.0)
    tgt_pos = destination_point(origin, bearing, range_nm)
    return TargetVessel(
        mmsi=mmsi,
        name=f"TEST_{mmsi}",
        position=tgt_pos,
        velocity=Velocity(speed_kts=speed, course_deg=course),
        vessel_type=vessel_type,
        bearing_deg=bearing,
        range_nm=range_nm,
        cpa_nm=cpa_nm,
        tcpa_min=tcpa_min,
        last_updated=datetime.now(timezone.utc),
        is_ais_confirmed=is_ais,
    )


# ── EncounterClassifier tests ─────────────────────────────────────────────────

class TestEncounterClassifier:

    def setup_method(self):
        self.clf = EncounterClassifier()

    def test_head_on_classification(self):
        """Two vessels on reciprocal courses, both seeing head-on."""
        own = make_own_ship(course=0.0, heading=0.0, speed=10.0)
        # Target is dead ahead (bearing=0), on reciprocal course (180 deg)
        target = make_target(
            bearing=0.0,   # dead ahead
            course=180.0,  # on reciprocal
            cpa_nm=0.05, tcpa_min=5.0,
        )
        result = self.clf.classify(own, target)
        assert result == EncounterType.HEAD_ON

    def test_crossing_give_way_starboard(self):
        """Target on our starboard bow - we are give-way vessel."""
        own = make_own_ship(course=0.0, heading=0.0)
        # Target is at bearing 45 deg (starboard bow), crossing from right
        target = make_target(
            bearing=45.0,   # starboard bow
            course=270.0,   # heading west (crossing our path)
            cpa_nm=0.3, tcpa_min=8.0,
        )
        result = self.clf.classify(own, target)
        assert result == EncounterType.CROSSING_GIVE_WAY

    def test_crossing_stand_on_port(self):
        """Target on our port bow - we are stand-on vessel."""
        own = make_own_ship(course=0.0, heading=0.0)
        # Target is at bearing 315 deg (port bow)
        target = make_target(
            bearing=315.0,  # port bow
            course=90.0,    # heading east
            cpa_nm=0.3, tcpa_min=8.0,
        )
        result = self.clf.classify(own, target)
        assert result == EncounterType.CROSSING_STAND_ON

    def test_overtaking_classification(self):
        """We are coming up from astern - we are overtaking (give-way)."""
        own = make_own_ship(course=0.0, heading=0.0, speed=15.0)
        # Target is dead astern (bearing=180), going same direction, slower
        target = make_target(
            bearing=180.0,  # dead astern
            course=0.0,     # going same direction
            speed=8.0,      # slower
            cpa_nm=0.5, tcpa_min=15.0,
        )
        result = self.clf.classify(own, target)
        # We are overtaking: target is abaft beam and we are faster
        assert result == EncounterType.OVERTAKING_GIVE_WAY

    def test_nuc_vessel_forces_give_way(self):
        """NUC vessel - classifier returns CROSSING_STAND_ON (NUC is stand-on, we give way)."""
        own = make_own_ship(course=0.0)
        # NUC target on port bow (normally we would be stand-on geometrically)
        target = make_target(
            bearing=315.0,
            course=90.0,
            vessel_type=VesselType.NUC,
            cpa_nm=0.3, tcpa_min=5.0,
        )
        result = self.clf.classify(own, target)
        # NUC is always stand-on regardless of geometry.
        # CROSSING_STAND_ON means the target (NUC) stands on and we must give way.
        assert result == EncounterType.CROSSING_STAND_ON

    def test_safe_encounter(self):
        """Target far away with large CPA - should be SAFE."""
        own = make_own_ship()
        target = make_target(
            bearing=90.0,
            range_nm=10.0,
            cpa_nm=3.0,     # Large CPA (above 1.0 NM threshold)
            tcpa_min=60.0,  # Far in future (above 30 min threshold)
        )
        result = self.clf.classify(own, target)
        assert result == EncounterType.SAFE

    def test_relative_bearing_dead_ahead(self):
        """Relative bearing when target is dead ahead."""
        own = make_own_ship(course=45.0, heading=45.0)
        target = make_target(bearing=45.0)  # Same absolute bearing as heading
        rb = self.clf.get_relative_bearing(own, target)
        assert abs(rb) < 1.0 or abs(rb - 360.0) < 1.0  # ~0 deg relative

    def test_relative_bearing_port_side(self):
        """Relative bearing when target is on port side."""
        own = make_own_ship(course=0.0, heading=0.0)
        target = make_target(bearing=270.0)  # Due west
        rb = self.clf.get_relative_bearing(own, target)
        assert 260.0 <= rb <= 280.0  # Port side ~270 deg

    def test_relative_bearing_starboard_beam(self):
        """Relative bearing when target is on starboard beam."""
        own = make_own_ship(course=0.0, heading=0.0)
        target = make_target(bearing=90.0)  # Due east
        rb = self.clf.get_relative_bearing(own, target)
        assert 80.0 <= rb <= 100.0  # Starboard beam ~90 deg

    def test_overtaking_stand_on_when_target_faster(self):
        """When target is faster in stern arc, we are the stand-on vessel."""
        own = make_own_ship(course=0.0, heading=0.0, speed=8.0)
        target = make_target(
            bearing=180.0,  # dead astern
            course=0.0,     # same direction
            speed=15.0,     # faster than us
            cpa_nm=0.4, tcpa_min=10.0,
        )
        result = self.clf.classify(own, target)
        assert result == EncounterType.OVERTAKING_STAND_ON


# ── COLREGRules tests ─────────────────────────────────────────────────────────

class TestCOLREGRules:

    def setup_method(self):
        self.rules = COLREGRules()

    def _make_encounter(
        self,
        target: TargetVessel,
        enc_type: EncounterType,
        action: COLREGAction,
        risk_level: AlarmLevel,
        time_to_act_s: float = 300.0,
        recommended_course_deg: float = 30.0,
        recommended_speed_kts: float = 10.0,
    ) -> ColregEncounter:
        return ColregEncounter(
            target=target,
            encounter_type=enc_type,
            required_action=action,
            risk_level=risk_level,
            time_to_act_s=time_to_act_s,
            recommended_course_deg=recommended_course_deg,
            recommended_speed_kts=recommended_speed_kts,
        )

    def test_rule_14_head_on_alters_starboard(self):
        """Rule 14: head-on both alter to starboard."""
        own = make_own_ship(course=0.0, heading=0.0)
        target = make_target(bearing=0.0, course=180.0, cpa_nm=0.1, tcpa_min=5.0)
        # recommended_course_deg must be a starboard alteration from current course 0 deg
        encounter = self._make_encounter(
            target, EncounterType.HEAD_ON, COLREGAction.ALTER_STARBOARD,
            AlarmLevel.ALARM, recommended_course_deg=30.0,
        )
        cmd = self.rules.rule_14_head_on(encounter)
        # Must alter to starboard (course increases clockwise)
        assert cmd.course_deg is not None
        # New course should be to starboard of current heading (0 deg)
        delta = (cmd.course_deg - 0.0 + 360) % 360
        assert delta >= MIN_COLREG_ALTERATION_DEG  # At least 30 deg starboard

    def test_rule_14_alteration_is_substantial(self):
        """Rule 8/14: course alteration must be >= 30 deg to be readily apparent."""
        own = make_own_ship(course=0.0, heading=0.0)
        target = make_target(bearing=0.0, course=180.0, cpa_nm=0.1, tcpa_min=5.0)
        encounter = self._make_encounter(
            target, EncounterType.HEAD_ON, COLREGAction.ALTER_STARBOARD,
            AlarmLevel.ALARM, recommended_course_deg=45.0,
        )
        cmd = self.rules.rule_14_head_on(encounter)
        diff = (cmd.course_deg - 0.0 + 360) % 360
        assert diff >= 30.0, f"Alteration {diff:.1f} deg is less than 30 deg minimum"

    def test_rule_15_crossing_give_way_starboard(self):
        """Rule 15: give-way vessel (target on starboard bow) alters starboard."""
        own = make_own_ship(course=0.0)
        target = make_target(bearing=45.0, course=270.0, cpa_nm=0.2, tcpa_min=8.0)
        encounter = self._make_encounter(
            target, EncounterType.CROSSING_GIVE_WAY, COLREGAction.ALTER_STARBOARD,
            AlarmLevel.WARNING, time_to_act_s=480.0, recommended_course_deg=45.0,
        )
        cmd = self.rules.rule_15_crossing(encounter)
        assert cmd is not None
        assert cmd.course_deg is not None
        assert cmd.colreg_rule == "15"

    def test_rule_17_stand_on_maintains_course(self):
        """Rule 17(a)(i): stand-on vessel maintains course when give-way is acting (CAUTION)."""
        own = make_own_ship(course=0.0)
        target = make_target(bearing=315.0, course=90.0, cpa_nm=0.8, tcpa_min=20.0)
        encounter = self._make_encounter(
            target, EncounterType.CROSSING_STAND_ON, COLREGAction.MAINTAIN,
            AlarmLevel.CAUTION, time_to_act_s=1200.0, recommended_course_deg=0.0,
        )
        cmd = self.rules.rule_17_stand_on_action(encounter)
        # CAUTION + MAINTAIN = return None (no command needed, stand on)
        assert cmd is None

    def test_rule_17_stand_on_acts_in_extremis(self):
        """Rule 17(b): stand-on vessel takes action when give-way fails and collision imminent."""
        own = make_own_ship(course=0.0, speed=12.0)
        target = make_target(bearing=315.0, course=90.0, cpa_nm=0.05, tcpa_min=1.0)
        encounter = self._make_encounter(
            target, EncounterType.CROSSING_STAND_ON, COLREGAction.MAINTAIN,
            AlarmLevel.EMERGENCY, time_to_act_s=60.0, recommended_course_deg=45.0,
        )
        cmd = self.rules.rule_17_stand_on_action(encounter)
        # In extremis: must act
        assert cmd is not None
        # Should take action with high priority
        assert cmd.priority >= 90

    def test_rule_8_action_substantial(self):
        """Rule 8: Any action must be substantial (>= 30 degrees)."""
        own = make_own_ship(course=0.0)
        target = make_target(bearing=0.0, course=180.0, cpa_nm=0.1, tcpa_min=5.0)
        encounter = self._make_encounter(
            target, EncounterType.HEAD_ON, COLREGAction.ALTER_STARBOARD,
            AlarmLevel.ALARM, recommended_course_deg=30.0,
        )
        cmd = self.rules.rule_8_action_to_avoid(encounter)
        assert cmd.course_deg is not None
        # Alteration must be >= MIN_COLREG_ALTERATION_DEG (30 deg)
        delta = (cmd.course_deg - 0.0 + 360) % 360
        if delta > 180:
            delta = 360 - delta  # Take the smaller angle
        assert delta >= MIN_COLREG_ALTERATION_DEG

    def test_rule_5_lookout_filters_distant(self):
        """Rule 5: Only returns targets worth watching."""
        own = make_own_ship()
        # Target 1: close and converging
        t1 = make_target(mmsi="111111111", cpa_nm=0.5, tcpa_min=10.0, range_nm=3.0)
        # Target 2: very far away with safe CPA and large TCPA - outside thresholds
        t2 = make_target(
            mmsi="222222222", bearing=90.0, range_nm=20.0, cpa_nm=5.0, tcpa_min=61.0,
        )

        watchlist = self.rules.rule_5_lookout([t1, t2])

        mmsi_list = [t.mmsi for t in watchlist]
        assert "111111111" in mmsi_list
        # t2 has cpa_nm=5.0 (>2.0) and tcpa_min=61.0 (>20.0) - not flagged
        assert "222222222" not in mmsi_list

    def test_rule_6_safe_speed_fog(self):
        """Rule 6: In fog (visibility < 0.5 NM), speed must be very low."""
        own = make_own_ship(speed=12.0, visibility=0.3)  # Thick fog
        safe_speed = self.rules.rule_6_safe_speed(own)
        assert safe_speed <= 6.0  # Must be slow in fog

    def test_rule_6_safe_speed_clear(self):
        """Rule 6: In clear visibility >= 10 NM, safe speed is not restricted below own speed."""
        own = make_own_ship(speed=15.0, visibility=10.0)
        safe_speed = self.rules.rule_6_safe_speed(own)
        assert safe_speed >= 10.0  # Should allow higher speed in clear weather

    def test_rule_7_risk_imminent_emergency(self):
        """Rule 7: DCPA below urgent threshold and TCPA < 5 min gives EMERGENCY."""
        own = make_own_ship()
        target = make_target(bearing=0.0, range_nm=1.0, cpa_nm=0.05, tcpa_min=3.0)
        risk = self.rules.rule_7_risk_of_collision(own, target)
        assert risk.risk_level == AlarmLevel.EMERGENCY

    def test_rule_7_risk_advisory_safe(self):
        """Rule 7: Large DCPA and large TCPA gives ADVISORY risk."""
        own = make_own_ship()
        target = make_target(bearing=90.0, range_nm=5.0, cpa_nm=3.0, tcpa_min=40.0)
        risk = self.rules.rule_7_risk_of_collision(own, target)
        assert risk.risk_level == AlarmLevel.ADVISORY

    def test_rule_18_nuc_hierarchy(self):
        """Rule 18: NUC vessel has highest priority - power-driven must give way."""
        own = make_own_ship(vessel_type=VesselType.POWER_DRIVEN)
        target = make_target(vessel_type=VesselType.NUC, bearing=45.0, cpa_nm=0.3, tcpa_min=5.0)

        result = self.rules.rule_18_responsibilities(own, target)
        # Power-driven must give way to NUC
        assert result == EncounterType.CROSSING_GIVE_WAY

    def test_rule_18_fishing_vessel_priority(self):
        """Rule 18: Fishing vessel has priority over power-driven."""
        own = make_own_ship(vessel_type=VesselType.POWER_DRIVEN)
        target = make_target(vessel_type=VesselType.FISHING, bearing=315.0, cpa_nm=0.4, tcpa_min=8.0)

        result = self.rules.rule_18_responsibilities(own, target)
        # Power-driven must give way to fishing even on port bow
        assert result == EncounterType.CROSSING_GIVE_WAY

    def test_rule_13_overtaking_command(self):
        """Rule 13: overtaking vessel gets a give-way command with correct rule number."""
        own = make_own_ship(course=0.0, speed=15.0)
        target = make_target(bearing=180.0, course=0.0, speed=8.0, cpa_nm=0.3, tcpa_min=12.0)
        encounter = self._make_encounter(
            target, EncounterType.OVERTAKING_GIVE_WAY, COLREGAction.ALTER_STARBOARD,
            AlarmLevel.WARNING, recommended_course_deg=45.0,
        )
        cmd = self.rules.rule_13_overtaking(encounter)
        assert cmd is not None
        assert cmd.colreg_rule == "13"
        assert cmd.priority >= 80

    def test_rule_19_restricted_visibility_no_port(self):
        """Rule 19: In restricted visibility, target forward of beam implies no port alteration."""
        own = make_own_ship(course=0.0, heading=0.0, visibility=1.0)
        target = make_target(bearing=30.0, range_nm=2.0, cpa_nm=0.3, tcpa_min=5.0)
        cmd = self.rules.rule_19_restricted_visibility(own, target)
        assert cmd.course_deg is not None
        alteration = (cmd.course_deg - own.heading_deg) % 360.0
        # Must NOT be a port alteration (alteration > 180 deg means port turn)
        assert alteration <= 180.0, "Rule 19 forbids port alteration for target forward of beam"
