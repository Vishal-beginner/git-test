"""Risk assessment engine for collision avoidance.

Converts CPA/TCPA metrics into AlarmLevel risk grades and recommended actions.
The risk matrix thresholds meet the requirements of DNV NAUT-AW and IMO MASS
guidance for Level 3/4 autonomy.
"""

from __future__ import annotations

from src.core.types import (
    AlarmLevel,
    COLREGAction,
    OwnShipState,
    RiskAssessment,
    TargetVessel,
    VesselType,
)
from src.core.constants import COLREG_SAFE_DCPA_NM, COLREG_URGENT_DCPA_NM


# DCPA bands (NM) — rows of the risk matrix
_DCPA_BANDS = [0.1, 0.25, 0.5, 1.0, 2.0]

# TCPA bands (minutes) — columns of the risk matrix
_TCPA_BANDS = [5.0, 10.0, 20.0, 30.0]

# Risk matrix[dcpa_band][tcpa_band] → AlarmLevel
# Rows: dcpa 0-0.1, 0.1-0.25, 0.25-0.5, 0.5-1.0, 1.0-2.0, >2.0
# Cols: tcpa 0-5, 5-10, 10-20, 20-30, >30
_RISK_TABLE: list[list[AlarmLevel]] = [
    # dcpa < 0.1 NM
    [AlarmLevel.EMERGENCY, AlarmLevel.EMERGENCY, AlarmLevel.ALARM, AlarmLevel.WARNING, AlarmLevel.CAUTION],
    # dcpa 0.1-0.25 NM
    [AlarmLevel.EMERGENCY, AlarmLevel.ALARM, AlarmLevel.WARNING, AlarmLevel.CAUTION, AlarmLevel.ADVISORY],
    # dcpa 0.25-0.5 NM
    [AlarmLevel.ALARM, AlarmLevel.WARNING, AlarmLevel.CAUTION, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY],
    # dcpa 0.5-1.0 NM
    [AlarmLevel.WARNING, AlarmLevel.CAUTION, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY],
    # dcpa 1.0-2.0 NM
    [AlarmLevel.CAUTION, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY],
    # dcpa > 2.0 NM
    [AlarmLevel.ADVISORY, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY, AlarmLevel.ADVISORY],
]

# Recommended action per risk level
_LEVEL_TO_ACTION: dict[AlarmLevel, COLREGAction] = {
    AlarmLevel.EMERGENCY: COLREGAction.EMERGENCY_MANEUVER,
    AlarmLevel.ALARM: COLREGAction.ALTER_STARBOARD,
    AlarmLevel.WARNING: COLREGAction.ALTER_STARBOARD,
    AlarmLevel.CAUTION: COLREGAction.MAINTAIN,
    AlarmLevel.ADVISORY: COLREGAction.MAINTAIN,
}


def _dcpa_band_index(dcpa_nm: float) -> int:
    for i, bound in enumerate(_DCPA_BANDS):
        if dcpa_nm < bound:
            return i
    return len(_DCPA_BANDS)


def _tcpa_band_index(tcpa_min: float) -> int:
    for i, bound in enumerate(_TCPA_BANDS):
        if tcpa_min < bound:
            return i
    return len(_TCPA_BANDS)


class RiskAssessor:
    """Assesses collision risk using a DCPA/TCPA matrix with vessel-type modifiers."""

    def __init__(
        self,
        dcpa_threshold_nm: float = COLREG_SAFE_DCPA_NM,
        hard_min_dcpa_nm: float = COLREG_URGENT_DCPA_NM,
    ) -> None:
        self._dcpa_threshold = dcpa_threshold_nm
        self._hard_min_dcpa = hard_min_dcpa_nm

    def assess(
        self,
        own: OwnShipState,
        target: TargetVessel,
        dcpa: float,
        tcpa: float,
    ) -> RiskAssessment:
        """Compute risk level for a single target.

        Args:
            own: Own ship state (provides visibility and speed context).
            target: Target vessel.
            dcpa: Closest point of approach in NM.
            tcpa: Time to CPA in minutes.

        Returns:
            RiskAssessment with level, recommended action, and confidence.
        """
        # Diverging vessels (TCPA < 0): risk only if already very close
        if tcpa < 0:
            if dcpa < self._hard_min_dcpa:
                level = AlarmLevel.ALARM
            elif target.range_nm < self._dcpa_threshold:
                level = AlarmLevel.CAUTION
            else:
                level = AlarmLevel.ADVISORY
            return RiskAssessment(
                target_mmsi=target.mmsi,
                dcpa_nm=dcpa,
                tcpa_min=tcpa,
                risk_level=level,
                recommended_action=_LEVEL_TO_ACTION[level],
                confidence=0.85,
            )

        # Matrix lookup
        di = _dcpa_band_index(dcpa)
        ti = _tcpa_band_index(tcpa)
        base_level = _RISK_TABLE[di][ti]

        # Upgrade risk for reduced visibility (Rule 19 conditions)
        if own.visibility_nm < 2.0:
            base_level = self._upgrade_level(base_level)

        # Upgrade risk for high-priority target types (NUC, RAM)
        if target.vessel_type in (VesselType.NUC, VesselType.RAM):
            base_level = self._upgrade_level(base_level)

        # AIS-unconfirmed contacts have lower confidence
        confidence = 1.0 if target.is_ais_confirmed else 0.75

        return RiskAssessment(
            target_mmsi=target.mmsi,
            dcpa_nm=dcpa,
            tcpa_min=tcpa,
            risk_level=base_level,
            recommended_action=_LEVEL_TO_ACTION[base_level],
            confidence=confidence,
        )

    def assess_multiple(
        self,
        own: OwnShipState,
        targets: list[TargetVessel],
    ) -> list[RiskAssessment]:
        """Assess risk for all targets and return sorted by severity.

        Args:
            own: Own ship state.
            targets: All tracked targets (must have cpa_nm and tcpa_min set).

        Returns:
            List of RiskAssessment sorted by severity (most dangerous first).
        """
        assessments = [
            self.assess(own, t, t.cpa_nm, t.tcpa_min)
            for t in targets
        ]
        severity_order = [
            AlarmLevel.EMERGENCY,
            AlarmLevel.ALARM,
            AlarmLevel.WARNING,
            AlarmLevel.CAUTION,
            AlarmLevel.ADVISORY,
        ]
        assessments.sort(key=lambda a: severity_order.index(a.risk_level))
        return assessments

    @staticmethod
    def _upgrade_level(level: AlarmLevel) -> AlarmLevel:
        """Promote a risk level one step higher (more severe)."""
        order = [
            AlarmLevel.ADVISORY,
            AlarmLevel.CAUTION,
            AlarmLevel.WARNING,
            AlarmLevel.ALARM,
            AlarmLevel.EMERGENCY,
        ]
        idx = order.index(level)
        return order[min(idx + 1, len(order) - 1)]
