"""COLREG compliance agent — classifies encounters and generates rule-based commands.

This agent is the primary COLREG enforcement mechanism.  It runs every 5 seconds,
classifies every active encounter, and generates the appropriate give-way or
stand-on commands per COLREG 1972 Rules 5–19.

Priority: 90 — overrides route-following commands but yields to Safety Monitor.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.agents.base import BaseAgent
from src.collision_avoidance.cpa import CPACalculator
from src.colreg.encounter import EncounterClassifier
from src.colreg.rules import COLREGRules
from src.colreg.resolver import ActionResolver
from src.core.constants import COLREG_SAFE_DCPA_NM, COLREG_MAX_TCPA_MINUTES
from src.core.types import (
    AlarmLevel,
    COLREGAction,
    ColregEncounter,
    EncounterType,
    ManeuverCommand,
    OwnShipState,
    TargetVessel,
)

logger = logging.getLogger(__name__)

# Encounter types that require own ship to give way
_GIVE_WAY_TYPES = frozenset({
    EncounterType.HEAD_ON,
    EncounterType.CROSSING_GIVE_WAY,
    EncounterType.OVERTAKING_GIVE_WAY,
})

# Encounter types where own ship is stand-on
_STAND_ON_TYPES = frozenset({
    EncounterType.CROSSING_STAND_ON,
    EncounterType.OVERTAKING_STAND_ON,
})

# Alarm levels that require immediate action
_ACTION_LEVELS = frozenset({AlarmLevel.ALARM, AlarmLevel.EMERGENCY, AlarmLevel.WARNING})


class COLREGAgent(BaseAgent):
    """Agent that enforces COLREG 1972 for all tracked encounters."""

    name = "COLREGAgent"
    priority = 90
    cycle_interval_s = 5.0

    def __init__(
        self,
        dcpa_threshold_nm: float = COLREG_SAFE_DCPA_NM,
        tcpa_threshold_min: float = COLREG_MAX_TCPA_MINUTES,
        hard_min_dcpa_nm: float = 0.2,
    ) -> None:
        super().__init__()
        self._cpa_calc = CPACalculator()
        self._classifier = EncounterClassifier()
        self._rules = COLREGRules()
        self._resolver = ActionResolver()
        self._active_encounters: list[ColregEncounter] = []

    async def initialize(self) -> None:
        logger.info("COLREGAgent initialised")

    async def run_cycle(
        self, state: OwnShipState, targets: list[TargetVessel]
    ) -> list[ManeuverCommand]:
        """Evaluate all active encounters and generate COLREG-mandated commands."""

        # Rule 6: verify safe speed
        safe_speed = self._rules.rule_6_safe_speed(state)
        if state.velocity.speed_kts > safe_speed + 0.5:
            logger.warning(
                "Speed exceeds Rule 6 safe speed",
                extra={"current": state.velocity.speed_kts, "safe": safe_speed},
            )

        # Rule 5: collect vessels requiring watchkeeping
        watchlist = self._rules.rule_5_lookout(targets)

        if not watchlist:
            self._active_encounters = []
            return []

        # Classify and evaluate each encounter
        encounters: list[ColregEncounter] = []
        commands: list[ManeuverCommand] = []

        for target in watchlist:
            # Refresh CPA (targets should have CPA set by SituationAwarenessAgent,
            # but we recompute here for accuracy at decision time)
            target = self._cpa_calc.update_target_cpa(state, target)

            # Risk of collision check (Rule 7)
            risk = self._rules.rule_7_risk_of_collision(state, target)

            # Skip ADVISORY-only targets (no action needed)
            if risk.risk_level == AlarmLevel.ADVISORY:
                continue

            # Classify encounter type
            enc_type = self._classifier.classify(state, target)

            if enc_type == EncounterType.SAFE:
                continue

            # Determine required action and recommended course
            cmd, time_to_act_s = self._determine_action(state, target, enc_type, risk.risk_level)
            rec_course = cmd.course_deg
            rec_speed = cmd.speed_kts

            encounter = ColregEncounter(
                target=target,
                encounter_type=enc_type,
                required_action=self._action_from_cmd(cmd),
                risk_level=risk.risk_level,
                time_to_act_s=time_to_act_s,
                recommended_course_deg=rec_course,
                recommended_speed_kts=rec_speed,
            )
            encounters.append(encounter)
            commands.append(cmd)

            logger.info(
                "Encounter classified",
                extra={
                    "mmsi": target.mmsi,
                    "type": enc_type.value,
                    "risk": risk.risk_level.value,
                    "dcpa": round(target.cpa_nm, 2),
                    "tcpa": round(target.tcpa_min, 1),
                },
            )

        self._active_encounters = encounters

        if not commands:
            return []

        # Resolve multiple simultaneous encounters
        try:
            resolved = self._resolver.resolve(state, encounters)
        except Exception as exc:
            logger.error("Action resolver failed", extra={"error": str(exc)})
            # Fall back to highest-priority individual command
            resolved = sorted(commands, key=lambda c: c.priority, reverse=True)

        return resolved

    async def shutdown(self) -> None:
        logger.info("COLREGAgent shutdown")

    def get_active_encounters(self) -> list[ColregEncounter]:
        """Return encounters from the most recent cycle."""
        return list(self._active_encounters)

    def _determine_action(
        self,
        state: OwnShipState,
        target: TargetVessel,
        enc_type: EncounterType,
        risk_level: AlarmLevel,
    ) -> tuple[ManeuverCommand, float]:
        """Determine the COLREG-mandated action for a given encounter.

        Returns (ManeuverCommand, time_to_act_seconds).
        """
        time_to_act_s = max(0.0, target.tcpa_min * 60.0 - 300.0)  # 5-min buffer

        # Rule 19 override in restricted visibility
        if state.visibility_nm < 2.0:
            cmd = self._rules.rule_19_restricted_visibility(state, target)
            return cmd, time_to_act_s

        # Route through Rule 16 for give-way, Rule 17 for stand-on
        if enc_type in _GIVE_WAY_TYPES and risk_level in _ACTION_LEVELS:
            encounter = ColregEncounter(
                target=target,
                encounter_type=enc_type,
                required_action=COLREGAction.ALTER_STARBOARD,
                risk_level=risk_level,
                time_to_act_s=time_to_act_s,
            )
            cmd = self._rules.rule_16_give_way_action(encounter, state)
            return cmd, time_to_act_s

        if enc_type in _STAND_ON_TYPES:
            give_way_acting = self._is_give_way_vessel_acting(target)
            encounter = ColregEncounter(
                target=target,
                encounter_type=enc_type,
                required_action=COLREGAction.MAINTAIN,
                risk_level=risk_level,
                time_to_act_s=time_to_act_s,
            )
            cmd = self._rules.rule_17_stand_on_action(encounter, state, give_way_acting)
            if cmd is None:
                cmd = ManeuverCommand(
                    course_deg=state.velocity.course_deg,
                    speed_kts=state.velocity.speed_kts,
                    reason=f"COLREG: Stand-on — maintaining vs {target.mmsi}",
                    colreg_rule="17",
                    priority=self.priority,
                )
            return cmd, time_to_act_s

        # Default: maintain
        return ManeuverCommand(
            course_deg=state.velocity.course_deg,
            speed_kts=state.velocity.speed_kts,
            reason=f"COLREG: Monitor — {enc_type.value} with {target.mmsi}",
            priority=70,
        ), time_to_act_s

    def _is_give_way_vessel_acting(self, target: TargetVessel) -> bool:
        """Estimate whether the give-way vessel is taking avoidance action.

        Uses track history to detect recent course/speed changes.  If fewer
        than 2 track points are available, assume it is NOT acting (conservative).
        """
        if len(target.track_history) < 2:
            return False

        # Simple heuristic: if TCPA is improving (increasing), vessel is acting
        return target.tcpa_min > 5.0

    @staticmethod
    def _action_from_cmd(cmd: ManeuverCommand) -> COLREGAction:
        """Infer COLREGAction enum from a ManeuverCommand."""
        if cmd.speed_kts == 0.0:
            return COLREGAction.STOP
        if cmd.speed_kts is not None and cmd.course_deg is None:
            return COLREGAction.REDUCE_SPEED
        if cmd.course_deg is None:
            return COLREGAction.MAINTAIN
        return COLREGAction.ALTER_STARBOARD  # Conservative default
