"""Multi-sensor fusion — combines RADAR and AIS into unified target tracks.

Fusion strategy:
  1. AIS-confirmed contacts are treated as authoritative for identity/type.
  2. RADAR contacts that cannot be associated to an AIS contact are tracked as
     radar-only (MMSI = "RADAR-<track_id>").
  3. Association gate: position within 0.3 NM AND course/speed within 15°/5 kts.
  4. If sensor count drops below the minimum required, a CAUTION alarm is raised
     (DNV NAUT-AW requires N+1 sensor redundancy).

All track lists are returned as new objects — fusion is a pure function.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from src.core.geo import haversine_nm, initial_bearing_deg
from src.core.types import (
    AlarmLevel,
    OwnShipState,
    Position,
    TargetVessel,
    Velocity,
    VesselType,
)
from src.core.exceptions import SensorFailureError
from src.sensors.models import AISMessage, RadarContact, SensorStatus

# Association gate thresholds
_ASSOC_RANGE_NM = 0.3       # Max position error for association
_ASSOC_SPEED_KTS = 5.0      # Max speed difference for association
_ASSOC_COURSE_DEG = 15.0    # Max course difference for association

# AIS vessel type → VesselType mapping (simplified)
_AIS_TYPE_MAP: dict[int, VesselType] = {
    20: VesselType.WIG,
    30: VesselType.FISHING,
    36: VesselType.SAILING,
    37: VesselType.SAILING,
    50: VesselType.RAM,      # Pilot vessel (manoeuvring restrictions)
    51: VesselType.RAM,      # SAR
    60: VesselType.POWER_DRIVEN,
    70: VesselType.POWER_DRIVEN,
    80: VesselType.POWER_DRIVEN,
}


def _ais_type_to_vessel_type(ais_type: int) -> VesselType:
    """Map AIS type code to VesselType enum."""
    for range_start, vtype in sorted(_AIS_TYPE_MAP.items()):
        if ais_type <= range_start:
            return vtype
        if ais_type // 10 == range_start // 10:
            return vtype
    return VesselType.POWER_DRIVEN


class SensorFusion:
    """Fuses RADAR and AIS data into a unified TargetVessel list."""

    def __init__(self, minimum_sensors_required: int = 2) -> None:
        self._min_sensors = minimum_sensors_required
        self._sensor_statuses: dict[str, SensorStatus] = {}

    def fuse(
        self,
        radar_contacts: list[RadarContact],
        ais_messages: list[AISMessage],
        own: OwnShipState,
    ) -> list[TargetVessel]:
        """Fuse RADAR and AIS contacts into a unified target list.

        Args:
            radar_contacts: ARPA-tracked radar contacts.
            ais_messages: Received AIS position reports.
            own: Own ship state (used to compute bearing/range).

        Returns:
            List of fused TargetVessel objects, one per unique contact.
        """
        targets: list[TargetVessel] = []
        associated_ais_mmsi: set[str] = set()

        # 1. Attempt to associate each radar contact to an AIS message
        for radar in radar_contacts:
            radar_pos = self._radar_to_position(radar, own)
            ais_match = self._find_ais_match(radar_pos, radar, ais_messages)

            if ais_match is not None:
                target = self._build_target_from_ais(ais_match, own)
                associated_ais_mmsi.add(ais_match.mmsi)
            else:
                target = self._build_target_from_radar(radar, radar_pos, own)

            targets.append(target)

        # 2. AIS contacts without a radar association (beyond radar range or masked)
        for ais in ais_messages:
            if ais.mmsi not in associated_ais_mmsi:
                range_nm = haversine_nm(own.position, ais.position)
                # Only include if within reasonable distance
                if range_nm <= 20.0:
                    target = self._build_target_from_ais(ais, own)
                    targets.append(target)

        return targets

    def update_target_tracks(
        self,
        existing: list[TargetVessel],
        new_contacts: list[TargetVessel],
    ) -> list[TargetVessel]:
        """Update existing target tracks with new contact data.

        Preserves track history from existing contacts when the same MMSI
        or track ID is detected again.

        Args:
            existing: Previously tracked targets.
            new_contacts: Freshly fused contacts from the current scan.

        Returns:
            Updated target list with preserved track histories.
        """
        existing_by_id = {t.mmsi: t for t in existing}
        updated: list[TargetVessel] = []

        for contact in new_contacts:
            if contact.mmsi in existing_by_id:
                prev = existing_by_id[contact.mmsi]
                # Append previous position to track history
                history = list(prev.track_history)
                history.append(prev.position)
                if len(history) > 100:
                    history = history[-100:]
                contact.track_history = history

            updated.append(contact)

        return updated

    def register_sensor(self, status: SensorStatus) -> None:
        """Register or update sensor health status."""
        self._sensor_statuses[status.sensor_id] = status

    def get_sensor_health(self) -> list[SensorStatus]:
        """Return health status of all registered sensors."""
        return list(self._sensor_statuses.values())

    def check_redundancy(self) -> Optional[tuple[AlarmLevel, str]]:
        """Check whether minimum sensor redundancy is maintained.

        Per DNV NAUT-AW, autonomous operations require N+1 sensors.

        Returns:
            (AlarmLevel, message) if redundancy is lost, else None.
        """
        online_count = sum(1 for s in self._sensor_statuses.values() if s.is_online)
        if online_count < self._min_sensors:
            return (
                AlarmLevel.ALARM,
                f"Sensor redundancy lost: {online_count}/{self._min_sensors} sensors online. "
                f"Degraded autonomous mode.",
            )
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _radar_to_position(self, radar: RadarContact, own: OwnShipState) -> Position:
        """Convert radar range/bearing to geographic position."""
        from src.core.geo import destination_point
        return destination_point(own.position, radar.bearing_deg, radar.range_nm)

    def _find_ais_match(
        self,
        radar_pos: Position,
        radar: RadarContact,
        ais_messages: list[AISMessage],
    ) -> Optional[AISMessage]:
        """Find the best AIS match for a radar contact within the association gate."""
        best_match: Optional[AISMessage] = None
        best_dist = float("inf")

        for ais in ais_messages:
            pos_dist = haversine_nm(radar_pos, ais.position)
            if pos_dist > _ASSOC_RANGE_NM:
                continue

            speed_diff = abs(radar.speed_kts - ais.speed_kts)
            if speed_diff > _ASSOC_SPEED_KTS:
                continue

            course_diff = abs(
                ((radar.course_deg - ais.course_deg + 180) % 360) - 180
            )
            if course_diff > _ASSOC_COURSE_DEG:
                continue

            if pos_dist < best_dist:
                best_dist = pos_dist
                best_match = ais

        return best_match

    def _build_target_from_ais(self, ais: AISMessage, own: OwnShipState) -> TargetVessel:
        """Create a TargetVessel from an AIS message."""
        range_nm = haversine_nm(own.position, ais.position)
        bearing = initial_bearing_deg(own.position, ais.position)
        vessel_type = _ais_type_to_vessel_type(ais.vessel_type)

        # Map AIS nav_status to NUC/RAM
        if ais.nav_status == 2:
            vessel_type = VesselType.NUC
        elif ais.nav_status == 3:
            vessel_type = VesselType.RAM
        elif ais.nav_status == 4:
            vessel_type = VesselType.CBD

        return TargetVessel(
            mmsi=ais.mmsi,
            name=ais.name,
            position=ais.position,
            velocity=Velocity(
                speed_kts=ais.speed_kts,
                course_deg=ais.course_deg,
                rate_of_turn_deg_per_min=ais.rate_of_turn or 0.0,
            ),
            vessel_type=vessel_type,
            cpa_nm=999.0,
            tcpa_min=999.0,
            bearing_deg=bearing,
            range_nm=range_nm,
            last_updated=ais.timestamp,
            is_ais_confirmed=True,
        )

    def _build_target_from_radar(
        self, radar: RadarContact, radar_pos: Position, own: OwnShipState
    ) -> TargetVessel:
        """Create a TargetVessel from a radar-only contact (no AIS)."""
        range_nm = haversine_nm(own.position, radar_pos)
        bearing = initial_bearing_deg(own.position, radar_pos)

        return TargetVessel(
            mmsi=f"RADAR-{radar.track_id}",
            name="",
            position=radar_pos,
            velocity=Velocity(
                speed_kts=radar.speed_kts,
                course_deg=radar.course_deg,
            ),
            vessel_type=VesselType.POWER_DRIVEN,  # Unknown type — worst-case assumption
            cpa_nm=999.0,
            tcpa_min=999.0,
            bearing_deg=bearing,
            range_nm=range_nm,
            last_updated=radar.timestamp,
            is_ais_confirmed=False,
        )
