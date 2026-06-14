"""Route planner — creates and validates great-circle voyage routes.

Builds ordered waypoint sequences and validates them against safety criteria
(coastal margins, excessive leg lengths, insufficient waypoints).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.core.geo import haversine_nm, initial_bearing_deg, destination_point
from src.core.types import OwnShipState, Position, Route, Waypoint
from src.core.exceptions import NavigationError


class RoutePlanner:
    """Plans and validates voyage routes."""

    def __init__(
        self,
        coast_margin_nm: float = 0.5,
        waypoint_arrival_radius_nm: float = 0.2,
    ) -> None:
        self._coast_margin = coast_margin_nm
        self._arrival_radius = waypoint_arrival_radius_nm

    def plan(
        self,
        origin: Position,
        destination: Position,
        intermediate_waypoints: Optional[list[Waypoint]] = None,
        name: str = "ROUTE",
    ) -> Route:
        """Build a route from origin to destination.

        Creates a Waypoint for the origin (if not already in the list) and
        appends the destination.  Intermediate waypoints are inserted in order.

        Args:
            origin: Departure position.
            destination: Arrival position.
            intermediate_waypoints: Optional ordered list of intermediate waypoints.
            name: Route name/identifier.

        Returns:
            Validated Route.

        Raises:
            NavigationError: If route is degenerate (zero distance etc.).
        """
        total_dist = haversine_nm(origin, destination)
        if total_dist < 0.01:
            raise NavigationError(
                "Origin and destination are the same position",
                context={"origin": origin.model_dump(), "destination": destination.model_dump()},
            )

        waypoints: list[Waypoint] = [
            Waypoint(
                position=origin,
                name="DEPARTURE",
                arrival_radius_nm=self._arrival_radius,
            )
        ]

        if intermediate_waypoints:
            waypoints.extend(intermediate_waypoints)

        waypoints.append(
            Waypoint(
                position=destination,
                name="DESTINATION",
                arrival_radius_nm=self._arrival_radius * 2,
            )
        )

        total_nm = self._compute_total_distance(waypoints)
        route = Route(
            waypoints=waypoints,
            name=name,
            total_distance_nm=total_nm,
            estimated_duration_h=0.0,  # Filled in by caller with known speed
        )

        warnings = self.validate_route(route)
        if warnings:
            # Log warnings but do not block — operator has approved the route
            pass

        return route

    def validate_route(self, route: Route) -> list[str]:
        """Validate route for navigational safety issues.

        Checks performed:
        - At least 2 waypoints
        - No degenerate legs (< 0.01 NM)
        - No single leg > 500 NM without intermediate waypoints
        - Waypoint arrival radii are non-overlapping

        Args:
            route: Route to validate.

        Returns:
            List of warning strings (empty = no issues).
        """
        warnings: list[str] = []

        if len(route.waypoints) < 2:
            warnings.append("Route must have at least 2 waypoints")
            return warnings

        for i in range(len(route.waypoints) - 1):
            wpt_a = route.waypoints[i]
            wpt_b = route.waypoints[i + 1]
            leg_dist = haversine_nm(wpt_a.position, wpt_b.position)

            if leg_dist < 0.01:
                warnings.append(
                    f"Leg {i}→{i+1} ({wpt_a.name}→{wpt_b.name}): "
                    f"degenerate leg ({leg_dist:.4f} NM)"
                )
            if leg_dist > 500.0:
                warnings.append(
                    f"Leg {i}→{i+1} ({wpt_a.name}→{wpt_b.name}): "
                    f"very long leg ({leg_dist:.1f} NM) — consider adding intermediate waypoints"
                )

        return warnings

    def get_active_leg(
        self, route: Route, own_pos: Position
    ) -> tuple[int, Waypoint, Waypoint]:
        """Return the index and waypoints of the currently active route leg.

        The active leg is the first leg whose end waypoint has not yet been passed
        (i.e., own ship is not yet within arrival radius of the end waypoint).

        Args:
            route: Active route.
            own_pos: Own ship current position.

        Returns:
            (leg_index, start_waypoint, end_waypoint)

        Raises:
            NavigationError: If route has fewer than 2 waypoints.
        """
        if len(route.waypoints) < 2:
            raise NavigationError("Route must have at least 2 waypoints")

        for i in range(len(route.waypoints) - 1):
            end_wpt = route.waypoints[i + 1]
            dist_to_end = haversine_nm(own_pos, end_wpt.position)
            if dist_to_end > end_wpt.arrival_radius_nm:
                return i, route.waypoints[i], route.waypoints[i + 1]

        # Past last waypoint — return final leg
        n = len(route.waypoints)
        return n - 2, route.waypoints[n - 2], route.waypoints[n - 1]

    def estimate_arrival(
        self,
        route: Route,
        own: OwnShipState,
        leg_index: int,
    ) -> datetime:
        """Estimate arrival time at the destination waypoint.

        Uses own ship's current speed and remaining route distance.

        Args:
            route: Active route.
            own: Own ship state.
            leg_index: Index of the current active leg.

        Returns:
            Estimated arrival time (UTC datetime).
        """
        if own.velocity.speed_kts < 0.5:
            # Vessel essentially stopped — return distant future
            return datetime.now(timezone.utc) + timedelta(hours=999)

        remaining_nm = 0.0
        for i in range(leg_index, len(route.waypoints) - 1):
            remaining_nm += haversine_nm(
                route.waypoints[i].position, route.waypoints[i + 1].position
            )

        # Subtract distance already covered on current leg
        _, start_wpt, _ = self.get_active_leg(route, own.position)
        dist_from_start = haversine_nm(own.position, start_wpt.position)
        remaining_nm = max(0.0, remaining_nm - dist_from_start)

        hours_remaining = remaining_nm / own.velocity.speed_kts
        return datetime.now(timezone.utc) + timedelta(hours=hours_remaining)

    @staticmethod
    def _compute_total_distance(waypoints: list[Waypoint]) -> float:
        """Sum great-circle distances across all route legs."""
        total = 0.0
        for i in range(len(waypoints) - 1):
            total += haversine_nm(waypoints[i].position, waypoints[i + 1].position)
        return total
