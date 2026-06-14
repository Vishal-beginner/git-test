"""Situation Awareness Agent — fuses sensors, tracks targets, generates alarms.

Runs at 2.5s cycle (matching radar sweep), continuously updating the contact
picture and risk assessments.  Higher-priority agents (COLREG, Safety) consume
the target list this agent maintains.

Priority: 80
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from src.agents.base import BaseAgent
from src.collision_avoidance.cpa import CPACalculator
from src.collision_avoidance.risk import RiskAssessor
from src.core.constants import COLREG_SAFE_DCPA_NM, COLREG_MAX_TCPA_MINUTES
from src.core.types import (
    AlarmLevel, ManeuverCommand, OwnShipState, RiskAssessment, TargetVessel,
)
from src.sensors.fusion import SensorFusion
from src.sensors.models import AISMessage, RadarContact, SensorStatus

logger = logging.getLogger(__name__)


class SituationAwarenessAgent(BaseAgent):
    """
    Fuses sensor data into a unified target picture and assesses collision risk.

    Responsibilities:
    - Call SensorFusion.fuse() each cycle
    - Update target tracks
    - Compute CPA/TCPA for all targets
    - Run RiskAssessor on all targets
    - Generate alarms when thresholds are crossed
    - Maintain the master target list for other agents
    """

    name = "SituationAwarenessAgent"
    priority = 80
    cycle_interval_s = 2.5

    def __init__(
        self,
        minimum_sensors_required: int = 2,
    ) -> None:
        super().__init__()
        self._fusion = SensorFusion(minimum_sensors_required=minimum_sensors_required)
        self._cpa_calc = CPACalculator()
        self._risk_assessor = RiskAssessor()
        self._targets: list[TargetVessel] = []
        self._risk_assessments: list[RiskAssessment] = []
        self._active_alarms: list[str] = []
        self._lock = asyncio.Lock()

        # Sensor data providers - can be set externally
        self._radar_provider: Optional[Callable] = None
        self._ais_provider: Optional[Callable] = None

    async def initialize(self) -> None:
        logger.info("SituationAwarenessAgent initialised")

    async def run_cycle(
        self, state: OwnShipState, targets: list[TargetVessel]
    ) -> list[ManeuverCommand]:
        """
        Update situation picture each cycle.

        1. Collect sensor data (radar + AIS)
        2. Fuse into target list
        3. Update tracks
        4. Compute CPA/TCPA
        5. Run risk assessment
        6. Generate alarms
        7. Return any speed-reduction commands for extreme risk
        """
        # Get sensor data
        radar_contacts: list[RadarContact] = []
        ais_messages: list[AISMessage] = []

        if self._radar_provider is not None:
            try:
                radar_contacts = await self._radar_provider()
            except Exception as exc:
                logger.error("Radar data fetch failed", extra={"error": str(exc)})

        if self._ais_provider is not None:
            try:
                ais_messages = await self._ais_provider()
            except Exception as exc:
                logger.error("AIS data fetch failed", extra={"error": str(exc)})

        # Fuse sensor data
        new_contacts = self._fusion.fuse(radar_contacts, ais_messages, state)

        # Update tracks with history
        async with self._lock:
            updated_targets = self._fusion.update_target_tracks(self._targets, new_contacts)

            # Update CPA/TCPA for each target
            targets_with_cpa = []
            for target in updated_targets:
                updated = self._cpa_calc.update_target_cpa(state, target)
                targets_with_cpa.append(updated)

            self._targets = targets_with_cpa

            # Run risk assessment
            self._risk_assessments = self._risk_assessor.assess_multiple(state, targets_with_cpa)

        # Check sensor health (DNV NAUT-AW requirement)
        sensor_statuses = self._fusion.get_sensor_health()
        offline_sensors = [s for s in sensor_statuses if not s.is_online]
        if offline_sensors:
            alarm_msg = f"SENSOR FAILURE: {[s.sensor_id for s in offline_sensors]} offline"
            if alarm_msg not in self._active_alarms:
                self._active_alarms.append(alarm_msg)
                logger.warning(
                    "sensor_degraded",
                    extra={"sensors": [s.sensor_id for s in offline_sensors]},
                )

        # Generate alarms based on risk
        commands = []
        new_alarms = []

        for assessment in self._risk_assessments:
            if assessment.risk_level in (AlarmLevel.ALARM, AlarmLevel.EMERGENCY):
                alarm_msg = (
                    f"COLLISION RISK {assessment.risk_level.value}: "
                    f"MMSI={assessment.target_mmsi} "
                    f"DCPA={assessment.dcpa_nm:.2f}NM "
                    f"TCPA={assessment.tcpa_min:.1f}min"
                )
                new_alarms.append(alarm_msg)
                logger.warning(
                    "collision_risk_alarm",
                    extra={
                        "mmsi": assessment.target_mmsi,
                        "level": assessment.risk_level.value,
                        "dcpa": round(assessment.dcpa_nm, 2),
                        "tcpa": round(assessment.tcpa_min, 1),
                    },
                )

                # Emergency: request speed reduction
                if assessment.risk_level == AlarmLevel.EMERGENCY:
                    commands.append(ManeuverCommand(
                        speed_kts=max(0.0, state.velocity.speed_kts * 0.5),
                        reason=f"EMERGENCY: CPA risk with {assessment.target_mmsi}",
                        priority=85,
                    ))
            elif assessment.risk_level == AlarmLevel.WARNING:
                alarm_msg = (
                    f"CPA WARNING: MMSI={assessment.target_mmsi} "
                    f"DCPA={assessment.dcpa_nm:.2f}NM TCPA={assessment.tcpa_min:.1f}min"
                )
                new_alarms.append(alarm_msg)

        self._active_alarms = new_alarms
        return commands

    async def shutdown(self) -> None:
        logger.info("SituationAwarenessAgent shutdown")

    async def get_targets(self) -> list[TargetVessel]:
        """Return current tracked target list (thread-safe)."""
        async with self._lock:
            return list(self._targets)

    def get_risk_assessments(self) -> list[RiskAssessment]:
        """Return most recent risk assessments."""
        return list(self._risk_assessments)

    def get_active_alarms(self) -> list[str]:
        """Return list of active alarm messages."""
        return list(self._active_alarms)

    def set_radar_provider(self, provider: Callable) -> None:
        """Set the async callable that provides radar contacts."""
        self._radar_provider = provider

    def set_ais_provider(self, provider: Callable) -> None:
        """Set the async callable that provides AIS messages."""
        self._ais_provider = provider

    def update_sensor_status(self, sensor_id: str, status: SensorStatus) -> None:
        """Update sensor health status."""
        self._fusion.register_sensor(status)
