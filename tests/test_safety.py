"""Tests for SafetySupervisor validation logic."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.core.types import (
    Position, Velocity, OwnShipState, TargetVessel, ManeuverCommand,
    NavigationMode, VesselType, VesselDimensions, AlarmLevel,
)
from src.core.config import AppConfig, ShipConfig, SafetyConfig, SensorConfig, NavigationConfig, RemoteOpsConfig
from src.safety.supervisor import SafetySupervisor, ProhibitedZone


def make_config(
    max_speed=18.0,
    hard_min_dcpa=0.2,
    safe_speed_restricted=10.0,
    dcpa_threshold=0.5,
    tcpa_threshold=15.0,
):
    return AppConfig(
        ship=ShipConfig(
            mmsi="123456789",
            name="TEST SHIP",
            vessel_type="POWER_DRIVEN",
            dimensions={"length_m": 180.0, "beam_m": 28.0, "draft_m": 9.5, "gross_tonnage": 25000.0},
            max_speed_kts=max_speed,
            min_speed_kts=2.0,
        ),
        safety=SafetyConfig(
            dcpa_threshold_nm=dcpa_threshold,
            tcpa_threshold_min=tcpa_threshold,
            safe_speed_restricted_vis_kts=safe_speed_restricted,
            coast_margin_nm=0.5,
            hard_min_dcpa_nm=hard_min_dcpa,
        ),
        sensors=SensorConfig(
            radar_range_nm=12.0,
            ais_range_nm=20.0,
            lidar_range_m=200.0,
            minimum_sensors_required=2,
        ),
        navigation=NavigationConfig(
            route_planning_margin_nm=0.5,
            waypoint_arrival_radius_nm=0.2,
            max_cross_track_error_nm=0.3,
            los_lookahead_nm=1.0,
        ),
        remote_ops=RemoteOpsConfig(
            api_host="0.0.0.0",
            api_port=8080,
            websocket_port=8081,
            heartbeat_interval_s=5.0,
        ),
    )


def make_own_ship(lat=0.0, lon=0.0, speed=10.0, course=0.0, visibility=10.0):
    return OwnShipState(
        position=Position(lat=lat, lon=lon),
        velocity=Velocity(speed_kts=speed, course_deg=course),
        mode=NavigationMode.AUTONOMOUS,
        vessel_type=VesselType.POWER_DRIVEN,
        dimensions=VesselDimensions(length_m=180.0, beam_m=28.0, draft_m=9.5, gross_tonnage=25000.0),
        heading_deg=course,
        timestamp=datetime.now(timezone.utc),
        visibility_nm=visibility,
    )


def make_target(mmsi="999", lat=0.0, lon=0.0, speed=10.0, course=180.0, cpa_nm=0.5, tcpa_min=10.0, bearing=0.0):
    return TargetVessel(
        mmsi=mmsi,
        name=f"TARGET_{mmsi}",
        position=Position(lat=lat, lon=lon),
        velocity=Velocity(speed_kts=speed, course_deg=course),
        vessel_type=VesselType.POWER_DRIVEN,
        bearing_deg=bearing,
        cpa_nm=cpa_nm,
        tcpa_min=tcpa_min,
        last_updated=datetime.now(timezone.utc),
    )


class TestSafetySupervisor:

    def setup_method(self):
        self.config = make_config()
        self.supervisor = SafetySupervisor(self.config)

    def test_emergency_stop_always_accepted(self):
        """Emergency stop command (speed=0) must always be accepted."""
        own = make_own_ship(speed=15.0)
        targets = []

        # Emergency stop: speed=0, no course
        stop_cmd = ManeuverCommand(
            speed_kts=0.0,
            reason="EMERGENCY STOP",
            priority=100,
        )

        result = self.supervisor.validate_command(stop_cmd, own, targets)
        assert result is True

    def test_command_rejected_if_dcpa_below_hard_limit(self):
        """Command must be rejected if a target's DCPA is below hard minimum and converging."""
        own = make_own_ship(speed=10.0, course=0.0)

        # Target with DCPA below hard limit (0.2 NM) AND converging (tcpa > 0, < 15 min)
        critical_target = make_target(
            cpa_nm=0.05,    # Below hard_min_dcpa_nm=0.2
            tcpa_min=5.0,   # Converging and within 15-min window
            bearing=0.0,    # Dead ahead
        )

        # Command that maintains course toward the critical target
        cmd = ManeuverCommand(
            course_deg=0.0,
            speed_kts=10.0,
            reason="Route following",
            priority=50,
        )

        result = self.supervisor.validate_command(cmd, own, [critical_target])
        # Should be rejected (DCPA < hard limit with converging target)
        assert result is False

    def test_speed_limit_enforcement(self):
        """Commands exceeding max speed should be rejected."""
        own = make_own_ship(speed=10.0, visibility=10.0)

        # Command exceeding max speed (18.0 kts)
        fast_cmd = ManeuverCommand(
            course_deg=0.0,
            speed_kts=25.0,  # Way over the 18.0 limit
            reason="Test overspeed",
            priority=50,
        )

        result = self.supervisor.validate_command(fast_cmd, own, [])
        assert result is False

    def test_speed_limit_in_restricted_visibility(self):
        """Speed must be limited in restricted visibility (< 2.0 NM)."""
        own = make_own_ship(speed=8.0, visibility=1.0)  # Restricted visibility

        # Command exceeding restricted visibility speed limit (10.0 kts)
        fast_cmd = ManeuverCommand(
            course_deg=0.0,
            speed_kts=15.0,  # Over safe_speed_restricted_vis=10.0
            reason="Test restricted visibility speed",
            priority=50,
        )

        result = self.supervisor.validate_command(fast_cmd, own, [])
        assert result is False

    def test_normal_command_accepted(self):
        """A safe, reasonable command should be accepted."""
        own = make_own_ship(speed=10.0, visibility=10.0)

        cmd = ManeuverCommand(
            course_deg=45.0,
            speed_kts=12.0,
            reason="Route following",
            priority=50,
        )

        result = self.supervisor.validate_command(cmd, own, [])
        assert result is True

    def test_emergency_stop_generation(self):
        """emergency_stop() should return a ManeuverCommand with speed=0."""
        stop_cmd = self.supervisor.emergency_stop("Test emergency")

        assert stop_cmd.speed_kts == 0.0
        assert stop_cmd.priority == 100
        assert "EMERGENCY" in stop_cmd.reason.upper()

    def test_grounding_risk_detection(self):
        """is_grounding_risk() should detect proximity to hazards within coast_margin."""
        # Add a hazard near our position
        # 0.005 deg lat * 60 NM/deg = 0.3 NM < coast_margin_nm=0.5
        hazard = Position(lat=0.005, lon=0.0)
        self.supervisor.add_hazard_position(hazard)

        own = make_own_ship(lat=0.0, lon=0.0)  # Near the hazard

        result = self.supervisor.is_grounding_risk(own)
        assert result is True

    def test_no_grounding_risk_when_clear(self):
        """is_grounding_risk() should return False when no hazards are close."""
        own = make_own_ship(lat=10.0, lon=20.0)  # Far from default (no hazards added)

        result = self.supervisor.is_grounding_risk(own)
        assert result is False

    def test_prohibited_zone_detection(self):
        """Vessel in prohibited zone should be detected."""
        # Add a prohibited zone at origin
        zone = ProhibitedZone(
            center=Position(lat=0.0, lon=0.0),
            radius_nm=1.0,
            name="Test Zone",
        )
        self.supervisor.add_prohibited_zone(zone)

        own = make_own_ship(lat=0.0, lon=0.0)  # Inside zone

        # is_in_prohibited_zone should confirm
        assert self.supervisor.is_in_prohibited_zone(own.position) is True

    def test_command_rejected_in_prohibited_zone(self):
        """Command while in prohibited zone should fail."""
        zone = ProhibitedZone(
            center=Position(lat=0.0, lon=0.0),
            radius_nm=1.0,
            name="Test Zone",
        )
        self.supervisor.add_prohibited_zone(zone)

        own = make_own_ship(lat=0.0, lon=0.0)  # Inside zone
        cmd = ManeuverCommand(
            course_deg=90.0,
            speed_kts=10.0,
            reason="Test",
            priority=50,
        )
        result = self.supervisor.validate_command(cmd, own, [])
        assert result is False

    def test_veto_log_records_rejections(self):
        """Vetoed commands should be recorded in veto log."""
        own = make_own_ship(speed=10.0)

        # Issue a bad command (way over speed limit)
        bad_cmd = ManeuverCommand(
            speed_kts=50.0,  # Way over limit
            reason="Test veto logging",
            priority=50,
        )
        self.supervisor.validate_command(bad_cmd, own, [])

        log = self.supervisor.get_veto_log()
        assert len(log) >= 1
        # Veto log entries are dicts with veto_reason and command_reason fields
        assert any(
            "50.0" in str(entry.get("veto_reason", "")) or
            "50.0" in str(entry.get("command_reason", "")) or
            "speed" in str(entry.get("veto_reason", "")).lower()
            for entry in log
        )

    def test_veto_log_is_list_of_dicts(self):
        """get_veto_log() returns a list of dict entries."""
        own = make_own_ship(speed=10.0)
        bad_cmd = ManeuverCommand(speed_kts=99.0, reason="Bad command", priority=50)
        self.supervisor.validate_command(bad_cmd, own, [])

        log = self.supervisor.get_veto_log()
        assert isinstance(log, list)
        assert len(log) >= 1
        assert isinstance(log[0], dict)
        # Each entry should have a timestamp and veto_reason
        assert "timestamp" in log[0]
        assert "veto_reason" in log[0]

    def test_get_status_structure(self):
        """get_status() should return a dict with required fields."""
        status = self.supervisor.get_status()
        assert "is_running" in status
        assert "hard_min_dcpa_nm" in status
        assert "max_speed_kts" in status
        assert "prohibited_zones" in status
        assert "veto_count" in status

    def test_speed_at_boundary_accepted(self):
        """Command at exactly the speed limit (with 0.1 kts tolerance) should be accepted."""
        own = make_own_ship(speed=10.0, visibility=10.0)
        # max_speed is 18.0, tolerance is 0.1 in the code
        boundary_cmd = ManeuverCommand(
            course_deg=0.0,
            speed_kts=18.0,  # Exactly at max speed
            reason="Max speed test",
            priority=50,
        )
        result = self.supervisor.validate_command(boundary_cmd, own, [])
        assert result is True
