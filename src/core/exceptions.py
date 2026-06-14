"""Exception hierarchy for the autonomous ship navigation system.

All safety-critical exceptions include context for VDR logging and root cause analysis.
"""
from __future__ import annotations


class ShipNavException(Exception):
    """Base exception for all ship navigation system errors.

    All domain exceptions carry a human-readable *message* and an optional
    *context* dict that can hold structured diagnostic data for logging and
    alerting pipelines.
    """

    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.message: str = message
        self.context: dict = context if context is not None else {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(message={self.message!r}, context={self.context!r})"

    def __str__(self) -> str:
        if self.context:
            return f"{self.message} | context={self.context}"
        return self.message


class COLREGViolationError(ShipNavException):
    """Raised when a planned or executed manoeuvre would violate the COLREGs.

    This is a safety-critical exception. Any action that would trigger this
    must be rejected and logged to the VDR immediately.

    Attributes:
        rule_number: COLREG rule number (e.g. "8", "16", "17").
        description: Plain-language description of the violation.
    """

    def __init__(
        self,
        message: str,
        rule_number: str,
        description: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.rule_number: str = rule_number
        self.description: str = description

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"rule_number={self.rule_number!r}, "
            f"description={self.description!r}, "
            f"message={self.message!r})"
        )

    def __str__(self) -> str:
        base = f"COLREG Rule {self.rule_number} violation: {self.description}"
        if self.context:
            return f"{base} | context={self.context}"
        return base


class SafetySystemError(ShipNavException):
    """Raised when a safety-critical subsystem enters a fault state.

    Triggers immediate escalation to the safety monitor and VDR alarm logging.

    Attributes:
        system_name: Name of the affected safety system (e.g. "ECDIS", "AIS", "VDR").
    """

    def __init__(
        self,
        message: str,
        system_name: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.system_name: str = system_name

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"system_name={self.system_name!r}, "
            f"message={self.message!r})"
        )

    def __str__(self) -> str:
        base = f"Safety system failure [{self.system_name}]: {self.message}"
        if self.context:
            return f"{base} | context={self.context}"
        return base


class SensorFailureError(ShipNavException):
    """Raised when a sensor becomes unavailable or reports unusable data.

    Per DNV NAUT-AW requirements, loss of sensor redundancy must trigger
    a CAUTION alarm and reduced operational mode.

    Attributes:
        sensor_id: Unique identifier of the failed sensor instance.
        sensor_type: Category of the sensor (e.g. "RADAR", "GPS", "LIDAR").
    """

    def __init__(
        self,
        message: str,
        sensor_id: str,
        sensor_type: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.sensor_id: str = sensor_id
        self.sensor_type: str = sensor_type

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"sensor_id={self.sensor_id!r}, "
            f"sensor_type={self.sensor_type!r}, "
            f"message={self.message!r})"
        )

    def __str__(self) -> str:
        base = f"Sensor failure [{self.sensor_type}/{self.sensor_id}]: {self.message}"
        if self.context:
            return f"{base} | context={self.context}"
        return base


class NavigationError(ShipNavException):
    """Raised for general navigation faults (route computation, waypoint errors, etc.).

    Examples: invalid waypoints, route outside operational area, excessive XTE.

    Attributes:
        location: Optional geographic or logical location description where the
                  error was detected (e.g. "waypoint 3", "TSS entry").
    """

    def __init__(
        self,
        message: str,
        location: str = "",
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.location: str = location

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"location={self.location!r}, "
            f"message={self.message!r})"
        )

    def __str__(self) -> str:
        loc_part = f" at [{self.location}]" if self.location else ""
        base = f"Navigation error{loc_part}: {self.message}"
        if self.context:
            return f"{base} | context={self.context}"
        return base


class EmergencyStopRequired(ShipNavException):
    """Raised when the system determines that an immediate emergency stop is necessary.

    This is a SIL-3 safety function — must be processed within 1 second of being
    raised, bypassing all normal command queues.

    Attributes:
        reason: Precise reason that triggered the emergency stop requirement.
    """

    def __init__(
        self,
        message: str,
        reason: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.reason: str = reason

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"reason={self.reason!r}, "
            f"message={self.message!r})"
        )

    def __str__(self) -> str:
        base = f"EMERGENCY STOP REQUIRED — {self.reason}: {self.message}"
        if self.context:
            return f"{base} | context={self.context}"
        return base


class ManeuverConflictError(ShipNavException):
    """Raised when two or more manoeuvre commands cannot be simultaneously satisfied.

    The action resolver raises this when no safe compromise can be found.
    Triggers escalation to the safety monitor.

    Attributes:
        conflicting_commands: List of command descriptors (dicts or strings) that
                              are in conflict with one another.
    """

    def __init__(
        self,
        message: str,
        conflicting_commands: list,
        context: dict | None = None,
    ) -> None:
        super().__init__(message, context)
        self.conflicting_commands: list = conflicting_commands

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"conflicting_commands={self.conflicting_commands!r}, "
            f"message={self.message!r})"
        )

    def __str__(self) -> str:
        cmds = ", ".join(str(c) for c in self.conflicting_commands)
        base = f"Maneuver conflict [{cmds}]: {self.message}"
        if self.context:
            return f"{base} | context={self.context}"
        return base
