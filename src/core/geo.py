"""Pure-math geospatial utilities for the autonomous ship navigation system.

All calculations use the haversine / spherical-Earth model which is accurate
to better than 0.5 % for the distances relevant to maritime navigation.
No external geo libraries are used — only the Python standard library ``math``
module and the project's own ``Position`` type.
"""
from __future__ import annotations

import math

from src.core.types import Position

# WGS-84 mean radius expressed in nautical miles.
EARTH_RADIUS_NM: float = 3440.065


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------


def haversine_nm(pos1: Position, pos2: Position) -> float:
    """Calculate the great-circle distance in nautical miles between two positions.

    Uses the haversine formula which is numerically stable for both small and
    large distances.

    Args:
        pos1: Start position.
        pos2: End position.

    Returns:
        Distance in nautical miles (always non-negative).
    """
    lat1 = math.radians(pos1.lat)
    lat2 = math.radians(pos2.lat)
    dlat = math.radians(pos2.lat - pos1.lat)
    dlon = math.radians(pos2.lon - pos1.lon)

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    # Clamp to [0, 1] to guard against floating-point drift beyond ±1.
    a = max(0.0, min(1.0, a))
    c = 2.0 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_NM * c


# ---------------------------------------------------------------------------
# Bearing
# ---------------------------------------------------------------------------


def initial_bearing_deg(pos1: Position, pos2: Position) -> float:
    """Calculate the initial bearing from *pos1* to *pos2* in degrees (0-360).

    The initial bearing is the direction one would face at *pos1* in order to
    travel along the great circle towards *pos2*.

    Args:
        pos1: Origin position.
        pos2: Destination position.

    Returns:
        Bearing in degrees, clockwise from true North, in the range [0, 360).
    """
    lat1 = math.radians(pos1.lat)
    lat2 = math.radians(pos2.lat)
    dlon = math.radians(pos2.lon - pos1.lon)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)

    bearing_rad = math.atan2(x, y)
    return normalize_bearing(math.degrees(bearing_rad))


# ---------------------------------------------------------------------------
# Destination point
# ---------------------------------------------------------------------------


def destination_point(pos: Position, bearing_deg: float, distance_nm: float) -> Position:
    """Calculate the destination position given a start, bearing, and distance.

    Uses the spherical-Earth direct (forward) formula.

    Args:
        pos: Starting position.
        bearing_deg: Initial bearing in degrees (0-360, clockwise from North).
        distance_nm: Distance to travel in nautical miles (non-negative).

    Returns:
        Destination :class:`Position` (altitude preserved from *pos*).
    """
    if distance_nm < 0.0:
        raise ValueError(f"distance_nm must be non-negative, got {distance_nm}")

    lat1 = math.radians(pos.lat)
    lon1 = math.radians(pos.lon)
    bearing_rad = math.radians(bearing_deg)
    angular_dist = distance_nm / EARTH_RADIUS_NM  # radians

    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_dist)
        + math.cos(lat1) * math.sin(angular_dist) * math.cos(bearing_rad)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_dist) * math.cos(lat1),
        math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2),
    )

    lat2_deg = math.degrees(lat2)
    # Wrap longitude to [-180, 180].
    lon2_deg = (math.degrees(lon2) + 540.0) % 360.0 - 180.0

    return Position(lat=lat2_deg, lon=lon2_deg, altitude_m=pos.altitude_m)


# ---------------------------------------------------------------------------
# Cross-track and along-track
# ---------------------------------------------------------------------------


def cross_track_error_nm(
    track_start: Position,
    track_end: Position,
    current_pos: Position,
) -> float:
    """Calculate the signed cross-track error (XTE) in nautical miles.

    The XTE is the perpendicular distance from *current_pos* to the great-circle
    track defined by *track_start* -> *track_end*.

    Sign convention: **positive** values indicate the vessel is to the **right**
    (starboard) of the intended track; negative values indicate port of track.

    Args:
        track_start: First point defining the intended track.
        track_end:   Second point defining the intended track.
        current_pos: Vessel's current position.

    Returns:
        Signed cross-track error in nautical miles.
    """
    dist_start_to_pos = haversine_nm(track_start, current_pos) / EARTH_RADIUS_NM  # angular (rad)
    bearing_start_to_pos = math.radians(initial_bearing_deg(track_start, current_pos))
    bearing_start_to_end = math.radians(initial_bearing_deg(track_start, track_end))

    # Spherical cross-track distance formula.
    xte_rad = math.asin(
        math.sin(dist_start_to_pos)
        * math.sin(bearing_start_to_pos - bearing_start_to_end)
    )
    return xte_rad * EARTH_RADIUS_NM


def along_track_distance_nm(
    track_start: Position,
    track_end: Position,
    current_pos: Position,
) -> float:
    """Calculate the along-track distance from *track_start* to the closest point
    on the track to *current_pos*.

    A positive result means the closest-point lies ahead of *track_start* (towards
    *track_end*); a negative result means it lies behind *track_start*.

    Args:
        track_start: First point defining the intended track.
        track_end:   Second point defining the intended track.
        current_pos: Vessel's current position.

    Returns:
        Along-track distance in nautical miles.
    """
    dist_start_to_pos = haversine_nm(track_start, current_pos) / EARTH_RADIUS_NM  # angular (rad)
    xte_rad = (
        cross_track_error_nm(track_start, track_end, current_pos) / EARTH_RADIUS_NM
    )  # angular (rad)

    # cos(along-track angle) = cos(dist) / cos(xte)
    cos_xte = math.cos(xte_rad)
    if abs(cos_xte) < 1e-15:
        # Degenerate case: vessel is essentially at the pole of the track great-circle.
        return 0.0

    cos_atd = math.cos(dist_start_to_pos) / cos_xte
    # Clamp to [-1, 1] to handle floating-point artefacts.
    cos_atd = max(-1.0, min(1.0, cos_atd))
    atd_rad = math.acos(cos_atd)
    return atd_rad * EARTH_RADIUS_NM


# ---------------------------------------------------------------------------
# Bearing utilities
# ---------------------------------------------------------------------------


def normalize_bearing(bearing: float) -> float:
    """Normalize *bearing* to the range [0, 360).

    Args:
        bearing: Bearing in degrees (any value).

    Returns:
        Equivalent bearing in [0, 360).
    """
    return bearing % 360.0


def bearing_difference(b1: float, b2: float) -> float:
    """Return the signed angular difference from bearing *b1* to bearing *b2*.

    The result is in the range (-180, +180].  A positive value means *b2* is
    clockwise (to starboard) of *b1*; a negative value means counter-clockwise
    (to port).

    Args:
        b1: Reference bearing in degrees.
        b2: Target bearing in degrees.

    Returns:
        Signed difference in degrees in (-180, +180].
    """
    diff = (b2 - b1) % 360.0
    if diff > 180.0:
        diff -= 360.0
    return diff


# ---------------------------------------------------------------------------
# Cartesian conversion helpers
# ---------------------------------------------------------------------------


def pos_to_cartesian_nm(pos: Position, origin: Position) -> tuple[float, float]:
    """Convert a geographic position to local Cartesian coordinates (NM).

    The local frame has:
    - **x** pointing East
    - **y** pointing North
    - Origin at *origin*.

    The conversion uses an equirectangular (flat-Earth) approximation scaled by
    the cosine of the mean latitude, which gives sub-metre accuracy within ~50 NM
    of the origin — more than adequate for ship collision-avoidance applications.

    Args:
        pos:    The position to convert.
        origin: The local coordinate origin.

    Returns:
        ``(x_nm, y_nm)`` tuple in nautical miles.
    """
    dlat = pos.lat - origin.lat
    dlon = pos.lon - origin.lon

    # Scale longitude difference by the cosine of the mean latitude to account
    # for meridian convergence.
    mean_lat_rad = math.radians((pos.lat + origin.lat) / 2.0)

    # 1 degree of latitude ≈ EARTH_RADIUS_NM * π / 180
    deg_to_nm = EARTH_RADIUS_NM * math.pi / 180.0

    y_nm = dlat * deg_to_nm
    x_nm = dlon * deg_to_nm * math.cos(mean_lat_rad)
    return (x_nm, y_nm)


def cartesian_nm_to_pos(x: float, y: float, origin: Position) -> Position:
    """Convert local Cartesian NM coordinates back to a geographic Position.

    This is the inverse of :func:`pos_to_cartesian_nm`.  The same
    equirectangular approximation is used; accuracy degrades beyond ~50 NM from
    *origin*.

    Args:
        x:      East offset from origin in nautical miles.
        y:      North offset from origin in nautical miles.
        origin: The local coordinate origin.

    Returns:
        :class:`Position` corresponding to ``(x, y)`` relative to *origin*.
    """
    deg_to_nm = EARTH_RADIUS_NM * math.pi / 180.0

    dlat = y / deg_to_nm
    # Use the origin latitude as the reference for the longitude scale factor
    # (consistent with the forward transformation at small offsets).
    origin_lat_rad = math.radians(origin.lat)
    cos_lat = math.cos(origin_lat_rad)
    if abs(cos_lat) < 1e-15:
        # At the poles, longitude is undefined; return origin longitude.
        dlon = 0.0
    else:
        dlon = x / (deg_to_nm * cos_lat)

    lat = origin.lat + dlat
    # Wrap longitude to [-180, 180].
    lon = (origin.lon + dlon + 540.0) % 360.0 - 180.0

    # Clamp latitude to valid range (should only be needed in extreme edge cases).
    lat = max(-90.0, min(90.0, lat))

    return Position(lat=lat, lon=lon, altitude_m=origin.altitude_m)
