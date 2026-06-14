"""Application configuration loader for the autonomous ship navigation system.

Supports YAML file loading with environment variable overrides.
Sub-configs use pydantic BaseModel for strict validation; the top-level
AppConfig aggregates them all.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-configuration models (plain BaseModel — validated, not env-driven)
# ---------------------------------------------------------------------------


class ShipConfig(BaseModel):
    """Identity and physical characteristics of own vessel."""

    mmsi: str = Field(..., description="9-digit MMSI")
    name: str = Field(..., description="Vessel name as registered")
    vessel_type: str = Field(..., description="Vessel type string matching VesselType enum")
    dimensions: dict = Field(
        ...,
        description="Raw dimension data; required keys: length_m, beam_m, draft_m, gross_tonnage",
    )
    max_speed_kts: float = Field(..., gt=0, description="Vessel's maximum speed in knots")
    min_speed_kts: float = Field(default=0.0, ge=0.0, description="Minimum maneuvering speed in knots")

    @field_validator("mmsi")
    @classmethod
    def validate_mmsi(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped.isdigit() or len(stripped) != 9:
            raise ValueError(f"MMSI must be exactly 9 digits, got '{v}'")
        return stripped

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, v: dict) -> dict:
        required_keys = {"length_m", "beam_m", "draft_m", "gross_tonnage"}
        missing = required_keys - set(v.keys())
        if missing:
            raise ValueError(f"dimensions dict is missing required keys: {missing}")
        for key in required_keys:
            if not isinstance(v[key], (int, float)) or v[key] <= 0:
                raise ValueError(
                    f"dimensions.{key} must be a positive number, got {v[key]!r}"
                )
        return v

    @model_validator(mode="after")
    def validate_speed_range(self) -> ShipConfig:
        if self.min_speed_kts >= self.max_speed_kts:
            raise ValueError(
                f"min_speed_kts ({self.min_speed_kts}) must be less than "
                f"max_speed_kts ({self.max_speed_kts})"
            )
        return self


class SafetyConfig(BaseModel):
    """COLREG and collision-avoidance safety thresholds."""

    dcpa_threshold_nm: float = Field(
        default=0.5, gt=0, description="CPA distance threshold for risk alerting (NM)"
    )
    tcpa_threshold_min: float = Field(
        default=15.0, gt=0, description="Time-to-CPA threshold for risk alerting (minutes)"
    )
    safe_speed_restricted_vis_kts: float = Field(
        default=10.0, gt=0, description="Maximum speed in restricted visibility (knots)"
    )
    coast_margin_nm: float = Field(
        default=0.5, gt=0, description="Minimum standoff from charted hazards (NM)"
    )
    hard_min_dcpa_nm: float = Field(
        default=0.2, gt=0, description="Hard minimum CPA — triggers emergency manoeuvre below this (NM)"
    )

    @model_validator(mode="after")
    def validate_dcpa_hierarchy(self) -> SafetyConfig:
        if self.hard_min_dcpa_nm >= self.dcpa_threshold_nm:
            raise ValueError(
                f"hard_min_dcpa_nm ({self.hard_min_dcpa_nm}) must be less than "
                f"dcpa_threshold_nm ({self.dcpa_threshold_nm})"
            )
        return self


class SensorConfig(BaseModel):
    """Sensor suite parameters."""

    radar_range_nm: float = Field(default=12.0, gt=0, description="Radar detection range (NM)")
    ais_range_nm: float = Field(default=20.0, gt=0, description="AIS reception range (NM)")
    lidar_range_m: float = Field(default=200.0, gt=0, description="LIDAR detection range (metres)")
    minimum_sensors_required: int = Field(
        default=2, ge=1, description="Minimum number of functioning sensors for autonomous mode"
    )


class NavigationConfig(BaseModel):
    """Route following and path-planning parameters."""

    route_planning_margin_nm: float = Field(
        default=0.5, gt=0, description="Lateral clearance margin during route planning (NM)"
    )
    waypoint_arrival_radius_nm: float = Field(
        default=0.2, gt=0, description="Radius within which a waypoint is considered reached (NM)"
    )
    max_cross_track_error_nm: float = Field(
        default=0.3, gt=0, description="Maximum allowable cross-track error before correction (NM)"
    )
    los_lookahead_nm: float = Field(
        default=1.0, gt=0, description="Line-of-Sight guidance lookahead distance (NM)"
    )


class RemoteOpsConfig(BaseModel):
    """Remote operations centre connectivity settings."""

    api_host: str = Field(default="0.0.0.0", description="REST API bind address")
    api_port: int = Field(default=8080, ge=1, le=65535, description="REST API port")
    websocket_port: int = Field(default=8081, ge=1, le=65535, description="WebSocket push port")
    heartbeat_interval_s: float = Field(
        default=5.0, gt=0, description="Interval between heartbeat messages (seconds)"
    )

    @model_validator(mode="after")
    def validate_port_conflict(self) -> RemoteOpsConfig:
        if self.api_port == self.websocket_port:
            raise ValueError(
                f"api_port and websocket_port must differ, both set to {self.api_port}"
            )
        return self


# ---------------------------------------------------------------------------
# Top-level application config
# ---------------------------------------------------------------------------


class AppConfig(BaseModel):
    """Root configuration aggregating all subsystem configs."""

    ship: ShipConfig
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    sensors: SensorConfig = Field(default_factory=SensorConfig)
    navigation: NavigationConfig = Field(default_factory=NavigationConfig)
    remote_ops: RemoteOpsConfig = Field(default_factory=RemoteOpsConfig)


# ---------------------------------------------------------------------------
# Default configuration factory
# ---------------------------------------------------------------------------


def _build_default_config() -> AppConfig:
    """Build a minimal valid AppConfig using safe defaults.

    Required ship-identity fields are sourced from environment variables so
    that containerised deployments can inject them without a config file.
    Falls back to clearly-marked placeholder values that will generate
    operational warnings when detected at runtime.
    """
    mmsi = os.environ.get("SHIP_MMSI", "000000000")
    name = os.environ.get("SHIP_NAME", "UNNAMED VESSEL")
    vessel_type = os.environ.get("SHIP_VESSEL_TYPE", "POWER_DRIVEN")

    ship_cfg = ShipConfig(
        mmsi=mmsi,
        name=name,
        vessel_type=vessel_type,
        dimensions={
            "length_m": float(os.environ.get("SHIP_LENGTH_M", "100.0")),
            "beam_m": float(os.environ.get("SHIP_BEAM_M", "20.0")),
            "draft_m": float(os.environ.get("SHIP_DRAFT_M", "5.0")),
            "gross_tonnage": float(os.environ.get("SHIP_GROSS_TONNAGE", "5000.0")),
        },
        max_speed_kts=float(os.environ.get("SHIP_MAX_SPEED_KTS", "15.0")),
        min_speed_kts=float(os.environ.get("SHIP_MIN_SPEED_KTS", "0.0")),
    )

    return AppConfig(ship=ship_cfg)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_config(path: str) -> AppConfig:
    """Load application configuration from a YAML file.

    The YAML structure must mirror the ``AppConfig`` model hierarchy.  Any
    fields not present in the file receive their pydantic defaults.

    Environment variables override file values for critical ship identity
    fields (``SHIP_MMSI``, ``SHIP_NAME``, ``SHIP_VESSEL_TYPE``,
    ``SHIP_MAX_SPEED_KTS``).

    If the file does not exist a warning is logged and a default configuration
    is returned so that the system can start in a degraded / test mode.

    Args:
        path: Filesystem path to the YAML configuration file.

    Returns:
        A fully-validated :class:`AppConfig` instance.

    Raises:
        ValueError: If the YAML file exists but contains invalid configuration.
        yaml.YAMLError: If the file cannot be parsed as valid YAML.
        OSError: If the file exists but cannot be read due to permissions.
    """
    config_path = Path(path)

    if not config_path.exists():
        logger.warning(
            "Configuration file not found at '%s'; using default configuration. "
            "Set SHIP_MMSI, SHIP_NAME, and other SHIP_* environment variables to "
            "customise defaults.",
            path,
        )
        return _build_default_config()

    if not config_path.is_file():
        raise ValueError(
            f"Configuration path '{path}' exists but is not a regular file."
        )

    logger.info("Loading configuration from '%s'", path)

    with open(config_path, encoding="utf-8") as f:
        raw_data: Any = yaml.safe_load(f)

    if raw_data is None:
        logger.warning(
            "Configuration file '%s' is empty; using default configuration.", path
        )
        return _build_default_config()

    if not isinstance(raw_data, dict):
        raise ValueError(
            f"Configuration file '{path}' must contain a YAML mapping at the top "
            f"level, got {type(raw_data).__name__}."
        )

    # Apply environment variable overrides for ship identity fields so that
    # container deployments can inject them at runtime without editing the file.
    ship_data: dict = dict(raw_data.get("ship", {}))
    if "SHIP_MMSI" in os.environ:
        ship_data["mmsi"] = os.environ["SHIP_MMSI"]
    if "SHIP_NAME" in os.environ:
        ship_data["name"] = os.environ["SHIP_NAME"]
    if "SHIP_VESSEL_TYPE" in os.environ:
        ship_data["vessel_type"] = os.environ["SHIP_VESSEL_TYPE"]
    if "SHIP_MAX_SPEED_KTS" in os.environ:
        ship_data["max_speed_kts"] = float(os.environ["SHIP_MAX_SPEED_KTS"])
    if ship_data:
        raw_data = {**raw_data, "ship": ship_data}

    try:
        config = AppConfig(**raw_data)
    except Exception as exc:
        raise ValueError(
            f"Configuration file '{path}' failed validation: {exc}"
        ) from exc

    logger.info(
        "Configuration loaded successfully for vessel '%s' (MMSI %s).",
        config.ship.name,
        config.ship.mmsi,
    )
    return config
