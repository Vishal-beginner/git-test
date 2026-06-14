"""CPA/TCPA calculator for collision avoidance.

Closest Point of Approach (CPA) and Time to CPA (TCPA) are the primary
risk metrics in maritime collision avoidance.  All calculations use a local
Cartesian NM coordinate frame centred on the own ship.

Mathematical basis:
    Let dx = tgt_x - own_x  (NM)
        dy = tgt_y - own_y  (NM)
        dvx = tgt_vx - own_vx  (NM/min)
        dvy = tgt_vy - own_vy  (NM/min)

    TCPA = -(dx·dvx + dy·dvy) / (dvx² + dvy²)  [minutes]
    DCPA = |dx + dvx·TCPA, dy + dvy·TCPA|        [NM]

If TCPA < 0 vessels are diverging; DCPA is still reported as the range at
the point of closest approach (which may be in the past).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from src.core.geo import pos_to_cartesian_nm
from src.core.types import OwnShipState, Position, TargetVessel, Velocity


def _speed_course_to_vxy(speed_kts: float, course_deg: float) -> tuple[float, float]:
    """Convert speed (kts) + course (deg) to Cartesian velocity components (NM/min).

    X = East, Y = North.

    Args:
        speed_kts: Speed in knots.
        course_deg: True course in degrees [0, 360).

    Returns:
        (vx, vy) in NM/min.
    """
    course_rad = math.radians(course_deg)
    vx = speed_kts * math.sin(course_rad) / 60.0
    vy = speed_kts * math.cos(course_rad) / 60.0
    return vx, vy


class CPACalculator:
    """Computes CPA and TCPA for own ship vs a single target vessel."""

    def calculate(
        self, own: OwnShipState, target: TargetVessel
    ) -> tuple[float, float]:
        """Compute (DCPA in NM, TCPA in minutes) for own ship and target.

        Args:
            own: Own ship navigational state.
            target: Target vessel with current position and velocity.

        Returns:
            (dcpa_nm, tcpa_min) — TCPA may be negative (diverging vessels).
        """
        origin = own.position

        ox, oy = pos_to_cartesian_nm(own.position, origin)
        tx, ty = pos_to_cartesian_nm(target.position, origin)

        own_vx, own_vy = _speed_course_to_vxy(own.velocity.speed_kts, own.velocity.course_deg)
        tgt_vx, tgt_vy = _speed_course_to_vxy(target.velocity.speed_kts, target.velocity.course_deg)

        return self.calculate_vector_dcpa(ox, oy, own_vx, own_vy, tx, ty, tgt_vx, tgt_vy)

    def calculate_vector_dcpa(
        self,
        own_x: float,
        own_y: float,
        own_vx: float,
        own_vy: float,
        tgt_x: float,
        tgt_y: float,
        tgt_vx: float,
        tgt_vy: float,
    ) -> tuple[float, float]:
        """Compute CPA directly from Cartesian positions and velocities.

        All units: NM for position, NM/min for velocity.

        Args:
            own_x, own_y: Own ship position in local NM frame.
            own_vx, own_vy: Own ship velocity (NM/min).
            tgt_x, tgt_y: Target position in local NM frame.
            tgt_vx, tgt_vy: Target velocity (NM/min).

        Returns:
            (dcpa_nm, tcpa_min).
        """
        dx = tgt_x - own_x
        dy = tgt_y - own_y
        dvx = tgt_vx - own_vx
        dvy = tgt_vy - own_vy

        speed_sq = dvx * dvx + dvy * dvy

        if speed_sq < 1e-10:
            # Vessels have identical velocity vectors — range is constant
            dcpa = math.sqrt(dx * dx + dy * dy)
            return dcpa, 0.0  # No convergence, CPA is now

        # Time of closest approach in minutes
        tcpa = -(dx * dvx + dy * dvy) / speed_sq

        # Position at CPA
        dcpa_x = dx + dvx * tcpa
        dcpa_y = dy + dvy * tcpa
        dcpa = math.sqrt(dcpa_x * dcpa_x + dcpa_y * dcpa_y)

        return dcpa, tcpa

    def predict_position(self, position: Position, velocity: Velocity, time_delta_s: float) -> Position:
        """Dead-reckon a position forward (or backward) by time_delta_s seconds.

        Uses rhumb-line approximation valid for short intervals (< 30 min).

        Args:
            position: Starting position.
            velocity: Current velocity.
            time_delta_s: Time delta in seconds (negative = backward).

        Returns:
            Predicted Position.
        """
        from src.core.geo import destination_point

        time_h = time_delta_s / 3600.0
        distance_nm = velocity.speed_kts * abs(time_h)
        course = velocity.course_deg if time_delta_s >= 0 else (velocity.course_deg + 180.0) % 360.0
        return destination_point(position, course, distance_nm)

    def update_target_cpa(self, own: OwnShipState, target: TargetVessel) -> TargetVessel:
        """Return a copy of target with refreshed CPA/TCPA values.

        Args:
            own: Own ship state.
            target: Target vessel (existing CPA/TCPA will be overwritten).

        Returns:
            TargetVessel with updated cpa_nm and tcpa_min.
        """
        from src.core.geo import haversine_nm, initial_bearing_deg

        dcpa, tcpa = self.calculate(own, target)
        range_nm = haversine_nm(own.position, target.position)
        bearing = initial_bearing_deg(own.position, target.position)

        target.cpa_nm = dcpa
        target.tcpa_min = tcpa
        target.range_nm = range_nm
        target.bearing_deg = bearing
        target.last_updated = datetime.now(timezone.utc)
        return target
