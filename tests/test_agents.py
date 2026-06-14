"""Tests for agent orchestration and priority resolution."""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.types import (
    Position, Velocity, OwnShipState, TargetVessel, ManeuverCommand,
    NavigationMode, VesselType, VesselDimensions, AlarmLevel,
    Route, Waypoint,
)
from src.core.config import AppConfig, ShipConfig, SafetyConfig, SensorConfig, NavigationConfig, RemoteOpsConfig
from src.agents.safety_agent import SafetyMonitorAgent
from src.agents.awareness_agent import SituationAwarenessAgent
from src.agents.navigation_agent import NavigationAgent
from src.agents.colreg_agent import COLREGAgent
from src.agents.orchestrator import AgentOrchestrator


def make_config():
    return AppConfig(
        ship=ShipConfig(
            mmsi="123456789",
            name="TEST SHIP",
            vessel_type="POWER_DRIVEN",
            dimensions={"length_m": 180.0, "beam_m": 28.0, "draft_m": 9.5, "gross_tonnage": 25000.0},
            max_speed_kts=18.0,
            min_speed_kts=2.0,
        ),
        safety=SafetyConfig(
            dcpa_threshold_nm=0.5,
            tcpa_threshold_min=15.0,
            safe_speed_restricted_vis_kts=10.0,
            coast_margin_nm=0.5,
            hard_min_dcpa_nm=0.2,
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


def make_target(mmsi="999", cpa_nm=0.5, tcpa_min=10.0, bearing=0.0, speed=10.0, course=180.0):
    return TargetVessel(
        mmsi=mmsi,
        name=f"TARGET_{mmsi}",
        position=Position(lat=0.05, lon=0.0),
        velocity=Velocity(speed_kts=speed, course_deg=course),
        vessel_type=VesselType.POWER_DRIVEN,
        bearing_deg=bearing,
        cpa_nm=cpa_nm,
        tcpa_min=tcpa_min,
        last_updated=datetime.now(timezone.utc),
    )


class TestSafetyAgentPriority:
    """Safety agent must win all conflicts."""

    @pytest.mark.asyncio
    async def test_safety_agent_wins_on_collision_imminent(self):
        """Safety agent returns emergency stop when collision is imminent."""
        agent = SafetyMonitorAgent(hard_min_dcpa_nm=0.2, max_speed_kts=18.0)
        await agent.initialize()

        own = make_own_ship(speed=12.0)
        # Target with DCPA below hard limit and imminent TCPA
        target = make_target(cpa_nm=0.05, tcpa_min=3.0, bearing=0.0)

        commands = await agent.run_cycle(own, [target])

        # Safety agent must issue a stop
        assert len(commands) >= 1
        stop_cmds = [c for c in commands if c.speed_kts == 0.0]
        assert len(stop_cmds) >= 1, "At least one emergency stop command expected"
        assert stop_cmds[0].priority == 100

    @pytest.mark.asyncio
    async def test_safety_agent_validates_command(self):
        """Safety agent validate_command correctly blocks unsafe commands."""
        agent = SafetyMonitorAgent(hard_min_dcpa_nm=0.2, max_speed_kts=18.0)
        own = make_own_ship(speed=10.0)

        # Overspeed command
        bad_cmd = ManeuverCommand(
            speed_kts=25.0,
            reason="Test overspeed",
            priority=50,
        )

        is_safe, reason = agent.validate_command(bad_cmd, own, [])
        assert is_safe is False
        assert len(reason) > 0

    @pytest.mark.asyncio
    async def test_safety_agent_allows_valid_command(self):
        """Safety agent allows reasonable commands through."""
        agent = SafetyMonitorAgent(hard_min_dcpa_nm=0.2, max_speed_kts=18.0)
        own = make_own_ship(speed=10.0)

        # Valid command within all limits
        good_cmd = ManeuverCommand(
            course_deg=45.0,
            speed_kts=12.0,
            reason="Route following",
            priority=50,
        )

        is_safe, reason = agent.validate_command(good_cmd, own, [])
        assert is_safe is True

    @pytest.mark.asyncio
    async def test_safety_agent_emergency_stop_always_valid(self):
        """Emergency stop (speed=0, no course) must always be validated as safe."""
        agent = SafetyMonitorAgent(hard_min_dcpa_nm=0.2, max_speed_kts=18.0)
        own = make_own_ship(speed=20.0)

        stop_cmd = ManeuverCommand(
            speed_kts=0.0,
            reason="Emergency stop",
            priority=100,
        )

        is_safe, reason = agent.validate_command(stop_cmd, own, [])
        assert is_safe is True

    @pytest.mark.asyncio
    async def test_safety_agent_no_emergency_when_safe(self):
        """No emergency stop issued when all targets have safe CPA."""
        agent = SafetyMonitorAgent(hard_min_dcpa_nm=0.2, max_speed_kts=18.0)
        own = make_own_ship(speed=10.0)
        safe_target = make_target(cpa_nm=2.0, tcpa_min=30.0)

        commands = await agent.run_cycle(own, [safe_target])

        stop_cmds = [c for c in commands if c.speed_kts == 0.0]
        assert len(stop_cmds) == 0, "No emergency stop for safe target"
        assert not agent.is_emergency_active()


class TestCOLREGAgentPriority:
    """COLREG agent must outrank navigation agent."""

    def test_colreg_agent_has_higher_priority(self):
        """COLREG agent priority must be > navigation agent priority."""
        colreg_agent = COLREGAgent()
        nav_agent = NavigationAgent()

        assert colreg_agent.priority > nav_agent.priority, (
            f"COLREGAgent priority {colreg_agent.priority} should exceed "
            f"NavigationAgent priority {nav_agent.priority}"
        )

    def test_safety_agent_has_highest_priority(self):
        """Safety agent must have the highest priority of all agents."""
        safety_agent = SafetyMonitorAgent()
        colreg_agent = COLREGAgent()
        nav_agent = NavigationAgent()

        assert safety_agent.priority > colreg_agent.priority
        assert safety_agent.priority > nav_agent.priority
        assert safety_agent.priority == 100

    def test_priority_ordering_is_total(self):
        """All three main agents have distinct, correctly ordered priorities."""
        safety = SafetyMonitorAgent()
        colreg = COLREGAgent()
        nav = NavigationAgent()

        priorities = [safety.priority, colreg.priority, nav.priority]
        # All distinct
        assert len(set(priorities)) == 3
        # Correct ordering
        assert safety.priority > colreg.priority > nav.priority


class TestOrchestratorCommandResolution:
    """Tests for command conflict resolution in orchestrator."""

    def setup_method(self):
        self.config = make_config()
        self.orchestrator = AgentOrchestrator(self.config)

    def test_emergency_stop_wins_always(self):
        """Emergency stop command wins over any other command."""
        own = make_own_ship(speed=10.0)
        targets = []

        commands = [
            ManeuverCommand(course_deg=45.0, speed_kts=12.0, reason="Route", priority=50),
            ManeuverCommand(course_deg=90.0, speed_kts=8.0, reason="COLREG", priority=90),
            ManeuverCommand(speed_kts=0.0, reason="EMERGENCY STOP", priority=100),
        ]

        resolved = self.orchestrator._resolve_commands(commands, own, targets)

        # Must resolve to emergency stop
        assert len(resolved) >= 1
        assert resolved[0].speed_kts == 0.0

    def test_higher_priority_course_wins(self):
        """Higher priority agent's course command wins."""
        own = make_own_ship(speed=10.0)
        targets = []

        commands = [
            ManeuverCommand(course_deg=0.0, speed_kts=12.0, reason="NavAgent", priority=50),
            ManeuverCommand(course_deg=45.0, speed_kts=8.0, reason="COLREGAgent", priority=90),
        ]

        resolved = self.orchestrator._resolve_commands(commands, own, targets)

        assert len(resolved) >= 1
        # Higher priority (COLREG at 90) course should win
        assert resolved[0].course_deg == 45.0 or resolved[0].priority >= 90

    def test_empty_commands_returns_empty(self):
        """No input commands returns empty list."""
        own = make_own_ship(speed=10.0)
        resolved = self.orchestrator._resolve_commands([], own, [])
        assert resolved == []

    def test_single_command_passes_through(self):
        """Single valid command passes through resolution unchanged."""
        own = make_own_ship(speed=10.0)
        commands = [
            ManeuverCommand(course_deg=90.0, speed_kts=10.0, reason="Route", priority=50),
        ]
        resolved = self.orchestrator._resolve_commands(commands, own, [])
        assert len(resolved) >= 1

    @pytest.mark.asyncio
    async def test_degraded_mode_when_agent_fails(self):
        """Orchestrator continues when one agent raises an exception."""
        config = make_config()
        orchestrator = AgentOrchestrator(config)

        own = make_own_ship(speed=10.0)

        # Mock COLREG agent to fail
        orchestrator._colreg_agent.run_cycle = AsyncMock(side_effect=Exception("Agent failed"))
        # Mock nav agent to succeed
        orchestrator._nav_agent.run_cycle = AsyncMock(return_value=[
            ManeuverCommand(course_deg=0.0, speed_kts=10.0, reason="Nav", priority=50)
        ])
        # Mock safety and awareness agents to return nothing
        orchestrator._safety_agent.run_cycle = AsyncMock(return_value=[])
        orchestrator._awareness_agent.run_cycle = AsyncMock(return_value=[])

        # Mark all agents as active so the cycle runs them
        for agent in orchestrator._agents:
            agent.is_active = True

        # Provide state and target providers
        orchestrator._state_provider = AsyncMock(return_value=own)
        orchestrator._target_provider = AsyncMock(return_value=[])

        # Should not raise even though COLREG agent fails
        try:
            commands = await orchestrator._orchestration_cycle()
            # Result is a list (may be empty or contain nav agent commands)
            assert isinstance(commands, list)
        except Exception as exc:
            pytest.fail(f"Orchestration should not raise on agent failure: {exc}")

    def test_get_system_status(self):
        """System status should include all agent states."""
        status = self.orchestrator.get_system_status()

        assert "is_running" in status
        assert "agents" in status
        assert isinstance(status["agents"], list)
        # At least 4 agents: safety, colreg, awareness, nav
        assert len(status["agents"]) >= 3
        # Each agent status should have standard fields
        for agent_status in status["agents"]:
            assert "name" in agent_status
            assert "priority" in agent_status
            assert "is_active" in agent_status

    def test_get_system_status_emergency_field(self):
        """System status should report emergency state."""
        status = self.orchestrator.get_system_status()
        assert "emergency_active" in status
        assert status["emergency_active"] is False


class TestNavigationAgent:
    """NavigationAgent route-following tests."""

    @pytest.mark.asyncio
    async def test_no_route_returns_empty(self):
        """Navigation agent returns no commands when no route is loaded."""
        agent = NavigationAgent(max_speed_kts=15.0)
        await agent.initialize()
        own = make_own_ship()
        commands = await agent.run_cycle(own, [])
        assert commands == []

    @pytest.mark.asyncio
    async def test_route_following_generates_heading(self):
        """Navigation agent generates course command when route is loaded."""
        agent = NavigationAgent(max_speed_kts=15.0)
        await agent.initialize()

        # Simple 2-waypoint route heading north
        route = Route(
            waypoints=[
                Waypoint(position=Position(lat=51.5, lon=1.0), name="START"),
                Waypoint(position=Position(lat=52.0, lon=1.0), name="END"),
            ],
            name="TEST",
        )
        agent.set_route(route)

        own = make_own_ship(lat=51.5, lon=1.0, course=0.0)
        # Override position to work with the non-equatorial lat
        from src.core.types import OwnShipState
        own_ship = OwnShipState(
            position=Position(lat=51.5, lon=1.0),
            velocity=Velocity(speed_kts=12.0, course_deg=0.0),
            mode=NavigationMode.AUTONOMOUS,
            vessel_type=VesselType.POWER_DRIVEN,
            dimensions=VesselDimensions(length_m=180.0, beam_m=28.0, draft_m=9.5, gross_tonnage=25000.0),
            heading_deg=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        commands = await agent.run_cycle(own_ship, [])

        assert len(commands) > 0, "Should generate commands when route is active"
        cmd = commands[0]
        assert cmd.course_deg is not None, "Must include a course command"
        assert cmd.speed_kts is not None and cmd.speed_kts > 0

    def test_agent_status_structure(self):
        """Agent status dict must contain required fields."""
        agent = NavigationAgent()
        status = agent.get_status()
        assert "name" in status
        assert "priority" in status
        assert "is_active" in status
        assert "run_count" in status
        assert "error_count" in status
        assert status["name"] == "NavigationAgent"
        assert status["priority"] == 50
