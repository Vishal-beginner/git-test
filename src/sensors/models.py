"""Sensor data models for the ship navigation system.

Defines typed data classes for each sensor source (RADAR, AIS, GNSS, weather).
All timestamps are UTC datetime objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from src.core.types import Position


class RadarContact(BaseModel):
    """A single ARPA/RADAR tracked contact."""

    track_id: str = Field(..., description="Radar track identifier")
    range_nm: float = Field(..., ge=0.0, description="Slant range in nautical miles")
    bearing_deg: float = Field(..., ge=0.0, lt=360.0, description="True bearing in degrees")
    speed_kts: float = Field(default=0.0, ge=0.0, description="ARPA-derived speed estimate")
    course_deg: float = Field(default=0.0, ge=0.0, lt=360.0, description="ARPA-derived course")
    doppler_kts: Optional[float] = Field(default=None, description="Doppler speed if available")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Track confidence 0-1")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"frozen": True}


class AISMessage(BaseModel):
    """Class A or B AIS position report (ITU-R M.1371)."""

    mmsi: str = Field(..., description="9-digit MMSI number")
    name: str = Field(default="", description="Vessel name (AIS Type 5)")
    call_sign: str = Field(default="", description="Radio call sign")
    vessel_type: int = Field(default=0, description="AIS vessel type code")
    position: Position
    speed_kts: float = Field(..., ge=0.0, description="Speed over ground in knots")
    course_deg: float = Field(..., ge=0.0, lt=360.0, description="Course over ground")
    heading_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0, description="True heading (511 = N/A)")
    nav_status: int = Field(default=0, description="AIS navigational status code")
    rate_of_turn: Optional[float] = Field(default=None, description="ROT in deg/min, +ve = stbd")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"frozen": True}

    @property
    def nav_status_text(self) -> str:
        """Human-readable AIS navigational status."""
        _STATUS: dict[int, str] = {
            0: "Under way using engine",
            1: "At anchor",
            2: "Not under command",
            3: "Restricted manoeuvrability",
            4: "Constrained by her draught",
            5: "Moored",
            6: "Aground",
            7: "Engaged in fishing",
            8: "Under way sailing",
            15: "Undefined",
        }
        return _STATUS.get(self.nav_status, f"Status {self.nav_status}")


class GNSSFix(BaseModel):
    """GNSS (GPS/GNSS) position fix."""

    position: Position
    accuracy_m: float = Field(..., ge=0.0, description="Estimated position error in metres")
    satellites: int = Field(..., ge=0, description="Satellites used in fix")
    hdop: float = Field(..., ge=0.0, description="Horizontal dilution of precision")
    fix_type: str = Field(default="3D", description="Fix type: No fix / 2D / 3D / DGNSS")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"frozen": True}


class WeatherData(BaseModel):
    """Meteorological and sea state data."""

    wind_speed_kts: float = Field(..., ge=0.0, description="True wind speed in knots")
    wind_direction_deg: float = Field(..., ge=0.0, lt=360.0, description="True wind direction (from)")
    wave_height_m: float = Field(default=0.0, ge=0.0, description="Significant wave height in metres")
    visibility_nm: float = Field(default=10.0, ge=0.0, description="Meteorological visibility in NM")
    pressure_hpa: float = Field(default=1013.25, description="Barometric pressure in hPa")
    sea_state: int = Field(default=0, ge=0, le=9, description="Douglas sea state scale")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"frozen": True}


class SensorStatus(BaseModel):
    """Health and availability status of a single sensor system."""

    sensor_id: str = Field(..., description="Sensor identifier string")
    sensor_type: str = Field(..., description="Sensor type (RADAR, AIS, GNSS, LIDAR, etc.)")
    is_online: bool = Field(..., description="True if sensor is providing valid data")
    last_update: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_count: int = Field(default=0, ge=0, description="Cumulative error count since startup")
    quality_pct: float = Field(default=100.0, ge=0.0, le=100.0, description="Signal quality percentage")
    error_message: str = Field(default="", description="Last error description if offline")

    model_config = {"frozen": False}
