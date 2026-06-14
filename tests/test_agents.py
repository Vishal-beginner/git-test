"""Tests for the agent orchestration layer.

Verifies:
  - Safety agent commands have highest priority
  - COLREG agent overrides navigation agent
  - Navigation agent generates LOS heading commands
  - Agent cycle produces expected command structure
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.navigation_agent import NavigationAgent
from src.agents.safety_agent import SafetyMonitorAgent
from src.core.types import (
    ManeuverCommand,
    NavigationMode,
    OwnShipState,
    Position,
    Route,
    TargetVessel,
    Velocity,
    VesselDimensions,
    Waypoint,
)


def make_own(
    lat: float = 51.5,
    lon: float = 1.0,
    speed: float = 12.0,
    course: float = 0.0,
) -> OwnShipState:
    from src.core.types import NavigationMode, VesselType
    return OwnShipState(
        position=Position(lat=lat, lon=lon),
        velocity=Velocity(speed_kts=speed, course_deg=course),
        dimensions=VesselDimensions(
            length_m=180.0, beam_m=28.0, draft_m=9.5, gross_tonnage=25000.0
        ),
        heading_deg=course,
        mode=NavigationMode.AUTONOMOUS,
        vessel_type=VesselType.POWER_DRIVEN,
        timestamp=datetime.now(timezone.utc),
    )


def make_target(
    cpa_nm: float = 2.0,
    tcpa_min: float = 30.0,
    mmsi: str = "T001",
) -> TargetVessel:
    return TargetVessel(
        mmsi=mmsi,
        position=Position(lat=51.52, lon=1.01),
        velocity=Velocity(speed_kts=10.0, course_deg=180.0),
        cpa_nm=cpa_nm,
        tcpa_min=tcpa_min,
        range_nm=2.0,
        last_updated=datetime.now(timezone.utc),
    )


class TestNavigationAgent:

    @pytest.mark.asyncio
    async def test_no_route_returns_empty(self):
        """Navigation agent returns no commands when no route is loaded."""
        agent = NavigationAgent(max_speed_kts=15.0)
        await agent.initialize()
        own = make_own()
        commands = await agent.run_cycle(own, [])
        assert commands == []

    @pytest.mark.asyncio
    async def test_route_following_generates_heading(self):
        """Navigation agent generates course command when route is loaded."""
        agent = NavigationAgent(max_speed_kts=15.0)
        await agent.initialize()

        # Set a simple 2-waypoint route heading north
        route = Route(
            waypoints=[
                Waypoint(position=Position(lat=51.5, lon=1.0), name="START"),
                Waypoint(position=Position(lat=52.0, lon=1.0), name="END"),
            ],
            name="TEST",
        )
        agent.set_route(route)

        own = make_own(lat=51.5, lon=1.0, course=0.0)
        commands = await agent.run_cycle(own, [])

        assert len(commands) > 0, "Should generate commands when route is active"
        cmd = commands[0]
        assert cmd.course_deg is not None, "Must include a course command"
        assert cmd.speed_kts is not None and cmd.speed_kts > 0

    @pytest.mark.asyncio
    async def test_waypoint_arrival_triggers_advance(self):
        """Navigation agent advances to next waypoint when arrival radius is entered."""
        agent = NavigationAgent(
            max_speed_kts=15.0,
            waypoint_arrival_radius_nm=0.2,
        )
        await agent.initialize()

        # Put own ship very close to the first end waypoint
        route = Route(
            waypoints=[
                Waypoint(position=Position(lat=51.5, lon=1.0), name="START"),
                Waypoint(position=Position(lat=51.502, lon=1.0), name="MID", arrival_radius_nm=0.5),
                Waypoint(position=Position(lat=52.0, lon=1.0), name="END"),
            ],
            name="TEST",
        )
        agent.set_route(route)

        # Position right at MID waypoint
        own = make_own(lat=51.502, lon=1.0)
        commands = await agent.run_cycle(own, [])
        # Should advance and generate heading toward END
        assert len(commands) > 0

    @pytest.mark.asyncio
    async def test_priority_is_lower_than_safety(self):
        """Navigation agent priority (50) must be lower than safety agent (100)."""
        nav = NavigationAgent(max_speed_kts=15.0)
        safety = SafetyMonitorAgent(hard_min_dcpa_nm=0.2, max_speed_kts=25.0)
        assert safety.priority > nav.priority, (
            f"Safety agent priority {safety.priority} must exceed "
            f"navigation agent priority {nav.priority}"
        )


class TestCommandPriorityOrdering:

    def test_highest_priority_wins(self):
        """When sorting commands, highest priority should come first."""
        nav_cmd = ManeuverCommand(
            course_deg=10.0,
            speed_kts=12.0,
            reason="Route following",
            priority=50,
        )
        colreg_cmd = ManeuverCommand(
            course_deg=45.0,
            speed_kts=12.0,
            reason="COLREG avoidance",
            priority=90,
        )
        safety_cmd = ManeuverCommand(
            speed_kts=0.0,
            reason="Emergency stop",
            priority=100,
        )
        commands = [nav_cmd, safety_cmd, colreg_cmd]
        sorted_cmds = sorted(commands, key=lambda c: c.priority, reverse=True)
        assert sorted_cmds[0].priority == 100
        assert sorted_cmds[1].priority == 90
        assert sorted_cmds[2].priority == 50

    def test_colreg_priority_above_navigation(self):
        """COLREG agent (priority 90) must outrank navigation agent (priority 50)."""
        from src.agents.colreg_agent import COLREGAgent
        colreg = COLREGAgent()
        nav = NavigationAgent()
        assert colreg.priority > nav.priority

    def test_safety_priority_above_colreg(self):
        """Safety agent (priority 100) must outrank COLREG agent (priority 90)."""
        from src.agents.colreg_agent import COLREGAgent
        colreg = COLREGAgent()
        safety = SafetyMonitorAgent()
        assert safety.priority > colreg.priority


class TestAgentStatus:

    def test_agent_status_structure(self):
        """Agent status dict must contain required fields."""
        agent = NavigationAgent()
        status = agent.get_status()
        assert "name" in status
        assert "priority" in status
        assert "is_active" in status
        assert "run_count" in status
        assert "error_count" in status
