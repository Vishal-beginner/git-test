"""Tests for CPA/TCPA calculation."""
from __future__ import annotations

import math
import pytest
from datetime import datetime, timezone

from src.core.types import (
    Position, Velocity, OwnShipState, TargetVessel, NavigationMode,
    VesselType, VesselDimensions,
)
from src.collision_avoidance.cpa import CPACalculator, _speed_course_to_vxy
from src.core.geo import haversine_nm


def make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=0.0, heading=0.0):
    return OwnShipState(
        position=Position(lat=lat, lon=lon),
        velocity=Velocity(speed_kts=speed, course_deg=course),
        mode=NavigationMode.AUTONOMOUS,
        vessel_type=VesselType.POWER_DRIVEN,
        dimensions=VesselDimensions(length_m=180.0, beam_m=28.0, draft_m=9.5, gross_tonnage=25000.0),
        heading_deg=heading or course,
        timestamp=datetime.now(timezone.utc),
    )


def make_target(lat=0.0, lon=0.0, speed=10.0, course=180.0, mmsi="123456789"):
    return TargetVessel(
        mmsi=mmsi,
        name="TEST",
        position=Position(lat=lat, lon=lon),
        velocity=Velocity(speed_kts=speed, course_deg=course),
        vessel_type=VesselType.POWER_DRIVEN,
        last_updated=datetime.now(timezone.utc),
    )


class TestSpeedCourseConversion:
    """Unit tests for the _speed_course_to_vxy helper."""

    def test_north(self):
        """60 kts north = 1 NM/min northward, no east component."""
        vx, vy = _speed_course_to_vxy(60.0, 0.0)
        assert abs(vx) < 1e-9
        assert abs(vy - 1.0) < 1e-6

    def test_east(self):
        """60 kts east = 1 NM/min eastward, no north component."""
        vx, vy = _speed_course_to_vxy(60.0, 90.0)
        assert abs(vx - 1.0) < 1e-6
        assert abs(vy) < 1e-9

    def test_south(self):
        """60 kts south = 1 NM/min southward (negative vy)."""
        vx, vy = _speed_course_to_vxy(60.0, 180.0)
        assert abs(vx) < 1e-9
        assert abs(vy + 1.0) < 1e-6

    def test_west(self):
        """60 kts west = 1 NM/min westward (negative vx)."""
        vx, vy = _speed_course_to_vxy(60.0, 270.0)
        assert abs(vx + 1.0) < 1e-6
        assert abs(vy) < 1e-9

    def test_zero_speed(self):
        """Zero speed gives zero velocity components."""
        vx, vy = _speed_course_to_vxy(0.0, 45.0)
        assert vx == 0.0
        assert vy == 0.0


class TestCPACalculator:

    def setup_method(self):
        self.calc = CPACalculator()

    def test_head_on_approach_dcpa_near_zero(self):
        """Two vessels on reciprocal courses approaching each other head-on."""
        # Own at origin going north
        own = make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=0.0)
        # Target 5 NM north (1 min of lat = 1 NM, so 5/60 deg) going south (head-on)
        target = make_target(lat=5.0 / 60.0, lon=0.0, speed=10.0, course=180.0)

        dcpa, tcpa = self.calc.calculate(own, target)

        # Head-on: DCPA should be approximately 0 (same longitude)
        assert dcpa < 0.1, f"Head-on DCPA should be near 0, got {dcpa:.4f} NM"
        assert tcpa > 0, "TCPA should be positive (converging)"

    def test_diverging_vessels_tcpa_negative(self):
        """Vessels already past closest point - TCPA should be negative."""
        # Own going north at 10 kts
        own = make_own_ship(lat=0.0, lon=0.0, speed=5.0, course=0.0)
        # Target same course but ahead and faster (diverging)
        target = make_target(lat=2.0 / 60.0, lon=0.0, speed=15.0, course=0.0)

        dcpa, tcpa = self.calc.calculate(own, target)

        # Vessels moving apart: TCPA < 0
        assert tcpa < 0, f"Diverging vessels: TCPA should be negative, got {tcpa:.2f}"
        # DCPA is non-negative
        assert dcpa >= 0

    def test_parallel_vessels_high_dcpa(self):
        """Two vessels going in same direction, side by side - no collision risk."""
        # Own at origin going north
        own = make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=0.0)
        # Target 1 NM to east (1/60 deg lon ~1 NM at equator), also going north at same speed
        target = make_target(lat=0.0, lon=1.0 / 60.0, speed=10.0, course=0.0)

        dcpa, tcpa = self.calc.calculate(own, target)

        # Parallel tracks: DCPA should be approximately the separation distance (~1 NM)
        assert dcpa > 0.8, f"Parallel tracks DCPA should be ~1 NM, got {dcpa:.4f}"

    def test_crossing_scenario_dcpa(self):
        """Crossing scenario: target on starboard bow, own going north."""
        # Own going north
        own = make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=0.0)
        # Target going west from east, will cross our path ahead
        target = make_target(lat=0.05, lon=0.05, speed=10.0, course=270.0)

        dcpa, tcpa = self.calc.calculate(own, target)

        # Should compute a finite non-negative DCPA
        assert dcpa >= 0
        # TCPA should be positive (approaching)
        assert tcpa > 0

    def test_stationary_target(self):
        """Target is not moving - DCPA is current separation, TCPA based on own speed."""
        own = make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=0.0)
        # Stationary target 3 NM ahead (3/60 deg north)
        target = make_target(lat=3.0 / 60.0, lon=0.0, speed=0.0, course=0.0)

        dcpa, tcpa = self.calc.calculate(own, target)

        # We are approaching: DCPA ~ 0 (on same track), TCPA > 0
        assert tcpa > 0, "Should be converging toward stationary target"
        assert dcpa < 0.2, f"Stationary target on collision course: DCPA={dcpa:.4f}"
        # At 10 kts, 3 NM takes 18 minutes
        assert 10.0 < tcpa < 25.0, f"Expected TCPA ~18 min, got {tcpa:.1f} min"

    def test_vector_dcpa_head_on(self):
        """Direct test of vector DCPA calculation for head-on scenario."""
        # Own at (0,0) going north at 10 kts -> vy = 10/60 NM/min
        # Target at (0,10) going south at 10 kts -> vy = -10/60 NM/min
        speed_nm_min = 10.0 / 60.0
        dcpa, tcpa = self.calc.calculate_vector_dcpa(
            0.0, 0.0, 0.0, speed_nm_min,      # own: at origin, going north
            0.0, 10.0, 0.0, -speed_nm_min,    # target: 10 NM north, going south
        )

        assert dcpa < 0.01, f"Head-on same track: DCPA should be ~0, got {dcpa:.4f}"
        assert tcpa > 0, "Should be approaching"
        # At closing speed of 2*speed_nm_min, 10 NM takes 30 min
        assert 25.0 < tcpa < 35.0, f"Expected TCPA ~30 min, got {tcpa:.1f} min"

    def test_vector_dcpa_symmetric(self):
        """DCPA is symmetric: swapping own and target gives same result."""
        # Own going north, target 5 NM away going south
        speed = 1.0 / 60.0  # NM/min
        dcpa1, tcpa1 = self.calc.calculate_vector_dcpa(
            0.0, 0.0, 0.0, speed,
            0.0, 5.0 / 60.0, 0.0, -speed,
        )
        # Swap own and target
        dcpa2, tcpa2 = self.calc.calculate_vector_dcpa(
            0.0, 5.0 / 60.0, 0.0, -speed,
            0.0, 0.0, 0.0, speed,
        )
        assert abs(dcpa1 - dcpa2) < 1e-6, "DCPA must be symmetric"

    def test_vector_dcpa_parallel(self):
        """Two vessels moving north on parallel tracks: DCPA equals lateral separation."""
        speed_nm_min = 10.0 / 60.0
        lateral_sep = 2.0  # NM
        dcpa, tcpa = self.calc.calculate_vector_dcpa(
            0.0, 0.0, 0.0, speed_nm_min,              # own at (0,0)
            lateral_sep, 0.0, 0.0, speed_nm_min,       # target 2 NM east
        )
        assert abs(dcpa - lateral_sep) < 0.01, f"Parallel track DCPA should be ~{lateral_sep} NM, got {dcpa:.4f}"

    def test_predict_position_dead_reckoning(self):
        """Test dead reckoning position prediction."""
        own = make_own_ship(lat=10.0, lon=10.0, speed=60.0, course=0.0)
        # At 60 kts north for 1 hour = 60 NM north
        predicted = self.calc.predict_position(own.position, own.velocity, time_delta_s=3600.0)

        dist = haversine_nm(own.position, predicted)
        assert abs(dist - 60.0) < 0.5, f"Expected 60 NM, got {dist:.2f} NM"
        assert predicted.lat > own.position.lat, "Should have moved north"
        assert abs(predicted.lon - own.position.lon) < 0.01, "Should stay on same longitude"

    def test_dcpa_always_non_negative(self):
        """DCPA must always be >= 0 regardless of geometry."""
        own = make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=90.0)

        # Various targets in different positions and courses
        test_cases = [
            make_target(lat=0.1, lon=0.1, speed=12.0, course=270.0, mmsi="111111111"),
            make_target(lat=-0.1, lon=-0.1, speed=5.0, course=45.0, mmsi="222222222"),
            make_target(lat=0.0, lon=0.2, speed=0.0, course=0.0, mmsi="333333333"),
            make_target(lat=0.05, lon=0.05, speed=15.0, course=180.0, mmsi="444444444"),
        ]

        for target in test_cases:
            dcpa, tcpa = self.calc.calculate(own, target)
            assert dcpa >= 0, f"DCPA must be >= 0, got {dcpa} for target {target.mmsi}"

    def test_same_velocity_dcpa_equals_range(self):
        """If vessels have identical velocity, DCPA equals current range."""
        own = make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=45.0)
        # Same velocity, 2 NM to east
        target = make_target(lat=0.0, lon=2.0 / 60.0, speed=10.0, course=45.0)

        dcpa, tcpa = self.calc.calculate(own, target)

        current_range = haversine_nm(own.position, target.position)
        assert abs(dcpa - current_range) < 0.1, (
            f"Same velocity: DCPA {dcpa:.3f} NM should approximately equal "
            f"current range {current_range:.3f} NM"
        )

    def test_update_target_cpa_refreshes_values(self):
        """update_target_cpa should refresh cpa_nm, tcpa_min, range_nm, bearing_deg."""
        own = make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=0.0)
        # Target with default (stale) cpa=999
        target = make_target(lat=3.0 / 60.0, lon=0.0, speed=10.0, course=180.0)
        assert target.cpa_nm == 999.0  # Default stale value

        updated = self.calc.update_target_cpa(own, target)

        assert updated.cpa_nm < 999.0, "CPA should have been updated from stale value"
        assert updated.range_nm > 0, "Range should be computed"
        assert 0.0 <= updated.bearing_deg < 360.0
