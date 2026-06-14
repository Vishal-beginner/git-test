"""Navigation agent — follows the planned voyage route using LOS guidance.

Generates course and speed commands to follow the active route leg.
Yields to higher-priority agents (COLREG, Safety) when they produce commands.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.agents.base import BaseAgent
from src.core.types import ManeuverCommand, OwnShipState, Route, TargetVessel
from src.navigation.route import RoutePlanner
from src.navigation.path import PathFollower

logger = logging.getLogger(__name__)


class NavigationAgent(BaseAgent):
    """Route-following agent using Line-Of-Sight guidance."""

    name = "NavigationAgent"
    priority = 50
    cycle_interval_s = 5.0

    def __init__(
        self,
        max_speed_kts: float = 15.0,
        route: Optional[Route] = None,
        los_lookahead_nm: float = 1.0,
        waypoint_arrival_radius_nm: float = 0.2,
    ) -> None:
        super().__init__()
        self._max_speed = max_speed_kts
        self._route = route
        self._active_leg_idx: int = 0
        self._planner = RoutePlanner(waypoint_arrival_radius_nm=waypoint_arrival_radius_nm)
        self._follower = PathFollower(
            lookahead_nm=los_lookahead_nm,
            max_cross_track_error_nm=0.3,
        )

    async def initialize(self) -> None:
        logger.info("NavigationAgent initialised", extra={"route": self._route.name if self._route else "None"})

    async def run_cycle(
        self, state: OwnShipState, targets: list[TargetVessel]
    ) -> list[ManeuverCommand]:
        """Generate route-following commands for the current agent cycle.

        Returns empty list if no route is loaded.
        """
        if self._route is None or len(self._route.waypoints) < 2:
            return []

        # Determine active leg
        try:
            leg_idx, start_wpt, end_wpt = self._planner.get_active_leg(
                self._route, state.position
            )
        except Exception as exc:
            logger.error("Failed to determine active leg", extra={"error": str(exc)})
            return []

        self._active_leg_idx = leg_idx

        # Check waypoint arrival
        if self._follower.check_waypoint_arrival(state, end_wpt):
            logger.info(
                "Waypoint reached",
                extra={"waypoint": end_wpt.name, "leg": leg_idx},
            )
            # Advance to next leg (if available)
            if leg_idx + 1 < len(self._route.waypoints) - 1:
                self._active_leg_idx = leg_idx + 1
                _, start_wpt, end_wpt = self._planner.get_active_leg(
                    self._route, state.position
                )
            else:
                logger.info("Final waypoint reached — voyage complete")
                return [
                    ManeuverCommand(
                        speed_kts=0.0,
                        reason="Voyage complete — arrived at destination",
                        priority=self.priority,
                    )
                ]

        # LOS heading
        desired_heading = self._follower.compute_desired_heading(state, start_wpt, end_wpt)

        # Speed command
        from src.core.geo import haversine_nm
        dist = haversine_nm(state.position, end_wpt.position)
        desired_speed = self._follower.compute_speed_command(
            state, end_wpt, self._max_speed, distance_to_wpt_nm=dist
        )

        # Log off-track warning
        if self._follower.is_off_track(state, start_wpt, end_wpt):
            xte = self._follower.get_cross_track_error(state, start_wpt, end_wpt)
            logger.warning(
                "Excessive cross-track error",
                extra={"xte_nm": round(xte, 3), "leg": leg_idx},
            )

        return [
            ManeuverCommand(
                course_deg=desired_heading,
                speed_kts=desired_speed,
                reason=(
                    f"Route following: leg {leg_idx} → {end_wpt.name}, "
                    f"dist {dist:.2f} NM"
                ),
                priority=self.priority,
            )
        ]

    async def shutdown(self) -> None:
        logger.info("NavigationAgent shutdown")

    def set_route(self, route: Route) -> None:
        """Load a new voyage route."""
        self._route = route
        self._active_leg_idx = 0
        logger.info("Route loaded", extra={"name": route.name, "waypoints": len(route.waypoints)})

    def get_active_leg_index(self) -> int:
        """Return the index of the currently active route leg."""
        return self._active_leg_idx
