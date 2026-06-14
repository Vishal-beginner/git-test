"""Line-Of-Sight (LOS) path following guidance law.

The LOS algorithm computes the desired heading to follow a straight-line
route leg.  Cross-track error is fed back through an arctan function, giving
smooth convergence to the track without overshoot.

Reference: Fossen, T.I. (2011) — Handbook of Marine Craft Hydrodynamics and
Motion Control, Wiley.  Chapter 10: Line-of-Sight Guidance.

LOS guidance law:
    desired_heading = bearing(own → end_wpt) - arctan(XTE / lookahead)

where XTE is the signed cross-track error (port = negative, starboard = positive)
and lookahead is a design parameter (typically 1–3 NM for ships).
"""

from __future__ import annotations

import math
from typing import Optional

from src.core.geo import (
    cross_track_error_nm,
    haversine_nm,
    initial_bearing_deg,
    normalize_bearing,
)
from src.core.types import ManeuverCommand, OwnShipState, Route, Waypoint


class PathFollower:
    """Generates heading and speed commands to follow a route leg using LOS guidance."""

    def __init__(
        self,
        lookahead_nm: float = 1.0,
        max_cross_track_error_nm: float = 0.3,
    ) -> None:
        self._lookahead = lookahead_nm
        self._max_xte = max_cross_track_error_nm

    def compute_desired_heading(
        self,
        own: OwnShipState,
        start_wpt: Waypoint,
        end_wpt: Waypoint,
    ) -> float:
        """Compute LOS-guided desired heading to follow the track.

        Args:
            own: Own ship navigational state.
            start_wpt: Starting waypoint of the active leg.
            end_wpt: Ending waypoint of the active leg.

        Returns:
            Desired heading in degrees [0, 360).
        """
        # Bearing from start to end (track bearing)
        track_bearing = initial_bearing_deg(start_wpt.position, end_wpt.position)

        # Signed XTE: positive = own ship is to the right (starboard) of track
        xte = cross_track_error_nm(start_wpt.position, end_wpt.position, own.position)

        # LOS correction: bring ship back to track
        # Negative sign: starboard XTE (positive) → steer to port (reduce bearing)
        correction = -math.degrees(math.atan2(xte, self._lookahead))

        desired = normalize_bearing(track_bearing + correction)
        return desired

    def check_waypoint_arrival(self, own: OwnShipState, waypoint: Waypoint) -> bool:
        """Return True if own ship is within the waypoint arrival circle.

        Args:
            own: Own ship state.
            waypoint: Waypoint to check.

        Returns:
            True if within arrival radius.
        """
        dist = haversine_nm(own.position, waypoint.position)
        return dist <= waypoint.arrival_radius_nm

    def compute_speed_command(
        self,
        own: OwnShipState,
        end_wpt: Waypoint,
        max_speed_kts: float,
        distance_to_wpt_nm: Optional[float] = None,
    ) -> float:
        """Compute commanded speed for the current leg.

        Reduces speed as vessel approaches a waypoint if the next leg requires
        a significant course change, and respects any waypoint speed constraint.

        Args:
            own: Own ship state.
            end_wpt: End waypoint of the current leg.
            max_speed_kts: Maximum permitted speed.
            distance_to_wpt_nm: Overrides haversine calculation if provided.

        Returns:
            Commanded speed in knots.
        """
        if end_wpt.required_speed_kts is not None:
            return min(end_wpt.required_speed_kts, max_speed_kts)

        dist = distance_to_wpt_nm
        if dist is None:
            dist = haversine_nm(own.position, end_wpt.position)

        # Decelerate in the last 0.5 NM before waypoint
        if dist < 0.5:
            fraction = dist / 0.5
            decel_speed = max_speed_kts * (0.4 + 0.6 * fraction)
            return max(2.0, decel_speed)

        return max_speed_kts

    def get_cross_track_error(
        self, own: OwnShipState, start_wpt: Waypoint, end_wpt: Waypoint
    ) -> float:
        """Return the signed cross-track error in NM.

        Positive = starboard of track; negative = port of track.

        Args:
            own: Own ship state.
            start_wpt: Leg start waypoint.
            end_wpt: Leg end waypoint.

        Returns:
            Signed XTE in NM.
        """
        return cross_track_error_nm(start_wpt.position, end_wpt.position, own.position)

    def is_off_track(
        self, own: OwnShipState, start_wpt: Waypoint, end_wpt: Waypoint
    ) -> bool:
        """Return True if own ship has exceeded the maximum cross-track error threshold.

        Args:
            own: Own ship state.
            start_wpt: Leg start waypoint.
            end_wpt: Leg end waypoint.

        Returns:
            True if XTE exceeds configured threshold.
        """
        xte = abs(self.get_cross_track_error(own, start_wpt, end_wpt))
        return xte > self._max_xte
