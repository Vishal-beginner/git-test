"""Pydantic v2 data models for the autonomous ship navigation system."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NavigationMode(str, Enum):
    AUTONOMOUS = "AUTONOMOUS"
    SUPERVISED_AUTO = "SUPERVISED_AUTO"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    ANCHORED = "ANCHORED"
    MOORED = "MOORED"


class VesselType(str, Enum):
    POWER_DRIVEN = "POWER_DRIVEN"
    SAILING = "SAILING"
    FISHING = "FISHING"
    NUC = "NUC"           # Not Under Command
    RAM = "RAM"           # Restricted in Ability to Manoeuvre
    CBD = "CBD"           # Constrained by Draught
    SEAPLANE = "SEAPLANE"
    WIG = "WIG"           # Wing-In-Ground effect craft
    PDUR = "PDUR"         # Power-Driven vessel Under Replenishment


class AlarmLevel(str, Enum):
    ADVISORY = "ADVISORY"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    ALARM = "ALARM"
    EMERGENCY = "EMERGENCY"


class EncounterType(str, Enum):
    HEAD_ON = "HEAD_ON"
    CROSSING_GIVE_WAY = "CROSSING_GIVE_WAY"
    CROSSING_STAND_ON = "CROSSING_STAND_ON"
    OVERTAKING_GIVE_WAY = "OVERTAKING_GIVE_WAY"
    OVERTAKING_STAND_ON = "OVERTAKING_STAND_ON"
    SAFE = "SAFE"
    UNKNOWN = "UNKNOWN"


class COLREGAction(str, Enum):
    MAINTAIN = "MAINTAIN"
    ALTER_STARBOARD = "ALTER_STARBOARD"
    ALTER_PORT = "ALTER_PORT"
    REDUCE_SPEED = "REDUCE_SPEED"
    STOP = "STOP"
    SOUND_SIGNAL = "SOUND_SIGNAL"
    EMERGENCY_MANEUVER = "EMERGENCY_MANEUVER"


# ---------------------------------------------------------------------------
# Core geometry / kinematic models
# ---------------------------------------------------------------------------


class Position(BaseModel):
    """WGS-84 geographic position."""

    lat: float = Field(..., description="Latitude in decimal degrees (-90 to +90)")
    lon: float = Field(..., description="Longitude in decimal degrees (-180 to +180)")
    altitude_m: float = Field(default=0.0, description="Altitude above mean sea level in metres")

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError(f"Latitude must be between -90 and 90, got {v}")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError(f"Longitude must be between -180 and 180, got {v}")
        return v

    model_config = {"frozen": True}


class Velocity(BaseModel):
    """Kinematic velocity state of a vessel."""

    speed_kts: float = Field(..., description="Speed over ground in knots (>= 0)")
    course_deg: float = Field(..., description="Course over ground in degrees (0-360)")
    rate_of_turn_deg_per_min: float = Field(
        default=0.0,
        description="Rate of turn in degrees per minute (positive = turning starboard)",
    )

    @field_validator("speed_kts")
    @classmethod
    def validate_speed(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(f"Speed must be non-negative, got {v}")
        return v

    @field_validator("course_deg")
    @classmethod
    def validate_course(cls, v: float) -> float:
        return v % 360.0

    model_config = {"frozen": True}


class VesselDimensions(BaseModel):
    """Physical dimensions of a vessel."""

    length_m: float = Field(..., gt=0, description="Overall length in metres")
    beam_m: float = Field(..., gt=0, description="Maximum beam (width) in metres")
    draft_m: float = Field(..., gt=0, description="Maximum draft in metres")
    gross_tonnage: float = Field(..., gt=0, description="Gross tonnage (GT)")

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Own ship state
# ---------------------------------------------------------------------------


class OwnShipState(BaseModel):
    """Complete navigational state of own vessel at a given instant."""

    position: Position
    velocity: Velocity
    mode: NavigationMode
    vessel_type: VesselType
    dimensions: VesselDimensions
    heading_deg: float = Field(..., description="Gyro-compass heading in degrees (0-360)")
    rudder_angle_deg: float = Field(default=0.0, description="Rudder angle; positive = starboard")
    engine_rpm: float = Field(default=0.0, description="Main engine shaft RPM")
    visibility_nm: float = Field(default=10.0, gt=0, description="Prevailing visibility in nautical miles")
    timestamp: datetime = Field(..., description="UTC timestamp of this state snapshot")

    @field_validator("heading_deg")
    @classmethod
    def validate_heading(cls, v: float) -> float:
        return v % 360.0

    @field_validator("rudder_angle_deg")
    @classmethod
    def validate_rudder(cls, v: float) -> float:
        if not -35.0 <= v <= 35.0:
            raise ValueError(f"Rudder angle must be between -35 and +35 degrees, got {v}")
        return v

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ---------------------------------------------------------------------------
# Target vessel
# ---------------------------------------------------------------------------


class TargetVessel(BaseModel):
    """Tracked target vessel with CPA/TCPA and AIS data."""

    mmsi: str = Field(..., description="9-digit MMSI identifier or radar track ID")
    name: str = Field(default="", description="Vessel name from AIS")
    position: Position
    velocity: Velocity
    vessel_type: VesselType = Field(default=VesselType.POWER_DRIVEN)
    cpa_nm: float = Field(default=999.0, description="Closest Point of Approach distance in NM")
    tcpa_min: float = Field(default=999.0, description="Time to CPA in minutes")
    bearing_deg: float = Field(default=0.0, description="Bearing from own ship in degrees (0-360)")
    range_nm: float = Field(default=0.0, description="Range from own ship in nautical miles")
    track_history: list[Position] = Field(default_factory=list, description="Historical position track")
    last_updated: datetime = Field(..., description="UTC timestamp of last data update")
    is_ais_confirmed: bool = Field(default=False, description="True if AIS data confirms radar contact")

    @field_validator("mmsi")
    @classmethod
    def validate_mmsi(cls, v: str) -> str:
        # Allow 9-digit MMSIs as well as synthetic radar track IDs (e.g. "RADAR_001")
        stripped = v.strip()
        if stripped.isdigit() and len(stripped) != 9:
            raise ValueError(f"Numeric MMSI must be exactly 9 digits, got '{v}'")
        return stripped

    @field_validator("bearing_deg")
    @classmethod
    def validate_bearing(cls, v: float) -> float:
        return v % 360.0

    @field_validator("range_nm")
    @classmethod
    def validate_range(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(f"Range must be non-negative, got {v}")
        return v

    @field_validator("last_updated")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ---------------------------------------------------------------------------
# COLREG encounter
# ---------------------------------------------------------------------------


class ColregEncounter(BaseModel):
    """A classified COLREG encounter with risk level and required action."""

    target: TargetVessel
    encounter_type: EncounterType
    required_action: COLREGAction
    risk_level: AlarmLevel
    time_to_act_s: float = Field(..., ge=0.0, description="Seconds remaining before action must be taken")
    recommended_course_deg: Optional[float] = Field(
        default=None, description="Recommended altered course in degrees (0-360)"
    )
    recommended_speed_kts: Optional[float] = Field(
        default=None, description="Recommended altered speed in knots"
    )

    @field_validator("recommended_course_deg")
    @classmethod
    def validate_recommended_course(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            return v % 360.0
        return v

    @field_validator("recommended_speed_kts")
    @classmethod
    def validate_recommended_speed(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0.0:
            raise ValueError(f"Recommended speed must be non-negative, got {v}")
        return v


# ---------------------------------------------------------------------------
# Route planning
# ---------------------------------------------------------------------------


class Waypoint(BaseModel):
    """A single waypoint within a planned route."""

    position: Position
    name: str = Field(default="", description="Human-readable waypoint name")
    arrival_radius_nm: float = Field(
        default=0.2, gt=0, description="Radius within which waypoint is considered reached (NM)"
    )
    required_speed_kts: Optional[float] = Field(
        default=None, description="Override speed for this waypoint leg (knots)"
    )
    notes: str = Field(default="", description="Operational notes (e.g. TSS, restricted area)")

    @field_validator("required_speed_kts")
    @classmethod
    def validate_required_speed(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0.0:
            raise ValueError(f"Required speed must be non-negative, got {v}")
        return v


class Route(BaseModel):
    """An ordered sequence of waypoints forming a planned voyage route."""

    waypoints: list[Waypoint] = Field(..., min_length=1, description="Ordered list of waypoints")
    name: str = Field(default="", description="Route name / identifier")
    total_distance_nm: float = Field(default=0.0, ge=0.0, description="Pre-computed total route distance (NM)")
    estimated_duration_h: float = Field(default=0.0, ge=0.0, description="Estimated transit time in hours")


# ---------------------------------------------------------------------------
# Maneuver commands
# ---------------------------------------------------------------------------


class ManeuverCommand(BaseModel):
    """An authoritative navigation command issued by the COLREG / routing agent."""

    course_deg: Optional[float] = Field(default=None, description="New course to steer in degrees (0-360)")
    speed_kts: Optional[float] = Field(default=None, description="New speed in knots")
    reason: str = Field(..., description="Human-readable reason for this command")
    colreg_rule: Optional[str] = Field(default=None, description="COLREG rule number justifying this command")
    priority: int = Field(default=50, ge=0, le=100, description="Command priority 0 (lowest) to 100 (highest)")
    expires_at: Optional[datetime] = Field(default=None, description="UTC time after which this command is void")

    @field_validator("course_deg")
    @classmethod
    def validate_course(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            return v % 360.0
        return v

    @field_validator("speed_kts")
    @classmethod
    def validate_speed(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0.0:
            raise ValueError(f"Speed must be non-negative, got {v}")
        return v

    @field_validator("expires_at")
    @classmethod
    def ensure_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @model_validator(mode="after")
    def require_at_least_one_action(self) -> ManeuverCommand:
        if self.course_deg is None and self.speed_kts is None:
            raise ValueError("ManeuverCommand must specify at least one of course_deg or speed_kts")
        return self


# ---------------------------------------------------------------------------
# Sensor data
# ---------------------------------------------------------------------------


class SensorReading(BaseModel):
    """A single sensor observation payload."""

    sensor_id: str = Field(..., description="Unique sensor instance identifier")
    sensor_type: str = Field(..., description="Sensor type string (e.g. 'RADAR', 'AIS', 'LIDAR', 'GPS')")
    data: dict = Field(..., description="Raw sensor payload; schema depends on sensor_type")
    quality: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Data quality factor 0.0 (unusable) to 1.0 (perfect)",
    )
    timestamp: datetime = Field(..., description="UTC timestamp when reading was captured")

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ---------------------------------------------------------------------------
# VDR / voyage log
# ---------------------------------------------------------------------------


class VoyageLogEntry(BaseModel):
    """A single VDR-compliant snapshot recorded at regular watchkeeping intervals."""

    timestamp: datetime = Field(..., description="UTC timestamp of this log entry")
    own_state: OwnShipState
    targets: list[TargetVessel] = Field(default_factory=list, description="All tracked targets at this instant")
    active_encounters: list[ColregEncounter] = Field(
        default_factory=list, description="Active COLREG encounters at this instant"
    )
    active_alarms: list[str] = Field(default_factory=list, description="Active alarm identifiers")
    maneuver_commands: list[ManeuverCommand] = Field(
        default_factory=list, description="Maneuver commands active at this instant"
    )

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    """Computed risk metrics for a specific target vessel."""

    target_mmsi: str = Field(..., description="Target vessel MMSI")
    dcpa_nm: float = Field(..., description="Distance at Closest Point of Approach (NM)")
    tcpa_min: float = Field(..., description="Time to CPA in minutes")
    risk_level: AlarmLevel
    recommended_action: COLREGAction
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence in this assessment (0-1)")

    @field_validator("target_mmsi")
    @classmethod
    def validate_mmsi(cls, v: str) -> str:
        stripped = v.strip()
        if stripped.isdigit() and len(stripped) != 9:
            raise ValueError(f"Numeric MMSI must be exactly 9 digits, got '{v}'")
        return stripped
