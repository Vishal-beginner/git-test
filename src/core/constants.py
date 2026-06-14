"""Safety-critical constants — DO NOT modify without formal change control."""
from enum import IntEnum

# COLREG safety margins
COLREG_SAFE_DCPA_NM = 0.5          # Closest point of approach threshold (nm)
COLREG_URGENT_DCPA_NM = 0.25       # Urgent action threshold (nm)
COLREG_MAX_TCPA_MINUTES = 30       # Max time horizon for risk assessment (min)

# Encounter bearing sectors (degrees relative to own heading)
HEAD_ON_SECTOR_DEG = 6.0           # ±6° from dead ahead
OVERTAKING_SECTOR_DEG = 67.5       # ±67.5° from dead astern (112.5° to 247.5°)
# Crossing is everything else (between head-on and overtaking)

# Safe speed factors
MAX_SPEED_RESTRICTED_VIS_KTS = 12.0
MIN_STOPPING_MARGIN_NM = 0.5       # Must be able to stop within half NM at safe speed

# Rudder action thresholds
MIN_COLREG_ALTERATION_DEG = 30.0   # Min course change to be "substantial" per Rule 8
EMERGENCY_STOP_RPM = 0             # Full astern condition

# Watchkeeping intervals
RADAR_SCAN_INTERVAL_S = 2.5        # 24 rpm radar = 2.5s per sweep
AIS_UPDATE_INTERVAL_S = 6.0        # Class A AIS update at 6s for underway
SITUATION_EVAL_INTERVAL_S = 5.0    # Agent decision cycle

# Track history
MAX_TRACK_HISTORY_POINTS = 100
TRACK_HISTORY_INTERVAL_S = 10.0

# Geofencing
COAST_SAFETY_MARGIN_NM = 0.5       # Min distance from charted land/hazards

# Classification society requirements (DNV NAUT-AW)
REDUNDANCY_REQUIRED = True         # N+1 sensor redundancy
WATCHKEEPING_LOG_INTERVAL_S = 30   # VDR (Voyage Data Recorder) log interval
ALARM_ACKNOWLEDGE_TIMEOUT_S = 60   # Unacknowledged alarm escalation time
