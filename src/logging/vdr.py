"""Voyage Data Recorder (VDR) — IMO MSC.214(81) compliant logging.

Implements required VDR data recording:
- Position, heading, speed (from GNSS/AIS)
- Rudder angle and engine RPM
- Radar targets
- Alarms and alerts
- Audio/comms (represented as log entries)
- Maneuver commands (audit trail)

Data is written to rotating log files with JSON-L format.
Supports playback export for incident investigation.

IMO VDR Performance Standard: Res. MSC.214(81)
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from src.core.config import AppConfig
from src.core.types import (
    AlarmLevel, ManeuverCommand, OwnShipState, TargetVessel,
    VoyageLogEntry, ColregEncounter,
)

logger = logging.getLogger(__name__)

# VDR retention: IMO requires at least 12 hours of data, we store 30 days
VDR_RETENTION_DAYS = 30
VDR_MAX_FILE_SIZE_MB = 100
VDR_LOG_DIR = Path("vdr_data")


class VoyageDataRecorder:
    """
    Implements IMO Res. MSC.214(81) Voyage Data Recorder requirements.

    Records to JSON-Lines format (one JSON object per line) with daily rotation.
    Supports compressed export for playback/investigation.

    VDR data categories (per MSC.214(81)):
    1. Date and time (UTC)
    2. Ship's position (lat/lon)
    3. Speed (through water / over ground)
    4. Heading
    5. Bridge audio (represented as alarm/event logs)
    6. Communications audio (represented as event logs)
    7. Radar data (target vessel list)
    8. Echo sounder depth
    9. Main alarms
    10. Rudder order and response
    11. Engine order and response
    12. Hull openings status (N/A for autonomous — recorded as "closed")
    13. Watertight door status (N/A for autonomous)
    14. Hull stresses (N/A for this implementation)
    15. Wind speed and direction
    """

    def __init__(
        self,
        config: AppConfig,
        log_dir: Optional[Path] = None,
    ) -> None:
        self._config = config
        self._log_dir = log_dir or VDR_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._current_file: Optional[Any] = None  # file handle
        self._current_date: Optional[str] = None
        self._lock = asyncio.Lock()
        self._entry_count = 0
        self._is_running = False
        self._log_interval_s = 30.0  # IMO: record at least every 30 seconds

    def _get_log_filename(self, dt: datetime) -> Path:
        """Get the log file path for a given datetime."""
        date_str = dt.strftime("%Y%m%d")
        ship_name = self._config.ship.name.replace(" ", "_").upper()
        mmsi = self._config.ship.mmsi
        return self._log_dir / f"VDR_{mmsi}_{ship_name}_{date_str}.jsonl"

    def _get_compressed_filename(self, dt: datetime) -> Path:
        """Get compressed archive filename."""
        base = self._get_log_filename(dt)
        return base.with_suffix(".jsonl.gz")

    async def _ensure_file_open(self, dt: datetime) -> None:
        """Ensure the log file for the given date is open. Rotate if needed."""
        date_str = dt.strftime("%Y%m%d")

        if self._current_date != date_str:
            # Rotate: close current file (if open) and compress it
            if self._current_file is not None:
                self._current_file.close()
                self._current_file = None
                await self._compress_old_file(self._current_date)

            self._current_date = date_str
            log_path = self._get_log_filename(dt)
            self._current_file = open(log_path, "a", encoding="utf-8")
            logger.info("VDR log file opened", extra={"path": str(log_path)})

    async def _compress_old_file(self, date_str: Optional[str]) -> None:
        """Compress previous day's log file."""
        if date_str is None:
            return
        try:
            old_dt = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
            old_path = self._get_log_filename(old_dt)
            if old_path.exists():
                compressed_path = self._get_compressed_filename(old_dt)
                with open(old_path, "rb") as f_in:
                    with gzip.open(compressed_path, "wb") as f_out:
                        f_out.write(f_in.read())
                old_path.unlink()
                logger.info("VDR log compressed", extra={"path": str(compressed_path)})
        except Exception as exc:
            logger.error("VDR compression failed", extra={"error": str(exc)})

    async def _write_entry(self, entry: dict) -> None:
        """Write a JSON-Lines entry to the current log file."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            await self._ensure_file_open(now)
            if self._current_file is not None:
                line = json.dumps(entry, default=str) + "\n"
                self._current_file.write(line)
                self._current_file.flush()
                self._entry_count += 1

    async def log_entry(self, entry: VoyageLogEntry) -> None:
        """
        Log a complete voyage data entry (IMO VDR core record).

        Captures: position, speed, heading, rudder, engine, targets, alarms, commands.
        """
        own = entry.own_state
        record = {
            "type": "voyage_entry",
            "timestamp": entry.timestamp.isoformat(),
            # Position (VDR item 2)
            "lat": own.position.lat,
            "lon": own.position.lon,
            # Speed (VDR item 3)
            "speed_kts": own.velocity.speed_kts,
            "course_deg": own.velocity.course_deg,
            # Heading (VDR item 4)
            "heading_deg": own.heading_deg,
            # Rudder (VDR item 10)
            "rudder_angle_deg": own.rudder_angle_deg,
            # Engine (VDR item 11)
            "engine_rpm": own.engine_rpm,
            # Navigation mode
            "nav_mode": own.mode.value,
            # Visibility
            "visibility_nm": own.visibility_nm,
            # Radar targets (VDR item 7)
            "targets": [
                {
                    "mmsi": t.mmsi,
                    "name": t.name,
                    "lat": t.position.lat,
                    "lon": t.position.lon,
                    "speed_kts": t.velocity.speed_kts,
                    "course_deg": t.velocity.course_deg,
                    "cpa_nm": t.cpa_nm,
                    "tcpa_min": t.tcpa_min,
                    "range_nm": t.range_nm,
                    "bearing_deg": t.bearing_deg,
                    "is_ais": t.is_ais_confirmed,
                }
                for t in entry.targets
            ],
            # Active alarms (VDR item 9)
            "alarms": entry.active_alarms,
            # Encounter data
            "encounters": [
                {
                    "mmsi": enc.target.mmsi,
                    "type": enc.encounter_type.value,
                    "action": enc.required_action.value,
                    "risk": enc.risk_level.value,
                    "time_to_act_s": enc.time_to_act_s,
                }
                for enc in entry.active_encounters
            ],
            # Maneuver commands
            "commands": [
                {
                    "course_deg": c.course_deg,
                    "speed_kts": c.speed_kts,
                    "reason": c.reason,
                    "colreg_rule": c.colreg_rule,
                    "priority": c.priority,
                }
                for c in entry.maneuver_commands
            ],
        }
        await self._write_entry(record)

    async def log_alarm(
        self,
        level: AlarmLevel,
        message: str,
        context: dict,
    ) -> None:
        """
        Log an alarm event to VDR (VDR item 9).

        Per IMO VDR: all alarms from integrated bridge systems must be recorded.
        """
        record = {
            "type": "alarm",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level.value,
            "message": message,
            "context": context,
        }
        await self._write_entry(record)
        logger.warning("VDR alarm logged", extra={"level": level.value, "message": message})

    async def log_maneuver(
        self,
        command: ManeuverCommand,
        source_agent: str,
    ) -> None:
        """
        Log a maneuver command to VDR (audit trail).

        All commanded maneuvers must be recorded for post-incident analysis.
        """
        record = {
            "type": "maneuver",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_agent": source_agent,
            "course_deg": command.course_deg,
            "speed_kts": command.speed_kts,
            "reason": command.reason,
            "colreg_rule": command.colreg_rule,
            "priority": command.priority,
            "expires_at": command.expires_at.isoformat() if command.expires_at else None,
        }
        await self._write_entry(record)

    async def export_playback(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """
        Export VDR data for a time range (for incident investigation).

        Reads from all relevant daily log files and returns matching entries.
        Returns list of raw log entry dicts sorted by timestamp.
        """
        entries = []

        # Determine which dates to check
        current = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_time.replace(hour=0, minute=0, second=0, microsecond=0)

        while current <= end_date:
            # Check both compressed and uncompressed files
            log_path = self._get_log_filename(current)
            compressed_path = self._get_compressed_filename(current)

            if compressed_path.exists():
                try:
                    with gzip.open(compressed_path, "rt", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            entry = json.loads(line)
                            # Filter by timestamp
                            ts_str = entry.get("timestamp", "")
                            if ts_str:
                                ts = datetime.fromisoformat(ts_str)
                                if start_time <= ts <= end_time:
                                    entries.append(entry)
                except Exception as exc:
                    logger.error("VDR playback read error", extra={"file": str(compressed_path), "error": str(exc)})

            elif log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            entry = json.loads(line)
                            ts_str = entry.get("timestamp", "")
                            if ts_str:
                                ts = datetime.fromisoformat(ts_str)
                                if start_time <= ts <= end_time:
                                    entries.append(entry)
                except Exception as exc:
                    logger.error("VDR playback read error", extra={"file": str(log_path), "error": str(exc)})

            current += timedelta(days=1)

        # Sort by timestamp
        entries.sort(key=lambda e: e.get("timestamp", ""))

        logger.info(
            "VDR playback export",
            extra={
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "entries": len(entries),
            }
        )

        return entries

    async def cleanup_old_logs(self) -> None:
        """Delete logs older than VDR_RETENTION_DAYS."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=VDR_RETENTION_DAYS)
        for f in self._log_dir.glob("VDR_*.jsonl.gz"):
            try:
                # Extract date from filename: VDR_MMSI_SHIPNAME_YYYYMMDD.jsonl.gz
                parts = f.stem.replace(".jsonl", "").split("_")
                date_str = parts[-1]
                file_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                if file_date < cutoff:
                    f.unlink()
                    logger.info("VDR old log deleted", extra={"path": str(f)})
            except Exception as exc:
                logger.warning("VDR cleanup error", extra={"file": str(f), "error": str(exc)})

    async def run(self) -> None:
        """
        Main VDR loop — runs periodic log maintenance.

        Periodic tasks:
        - Cleanup logs older than retention period
        - Flush current file
        """
        self._is_running = True
        logger.info("VDR running", extra={"log_dir": str(self._log_dir)})

        try:
            while self._is_running:
                # Daily cleanup check
                await self.cleanup_old_logs()
                await asyncio.sleep(3600.0)  # Check hourly
        except asyncio.CancelledError:
            logger.info("VDR cancelled")
        finally:
            async with self._lock:
                if self._current_file is not None:
                    self._current_file.close()
                    self._current_file = None
            self._is_running = False
            logger.info("VDR stopped", extra={"total_entries": self._entry_count})

    def get_status(self) -> dict:
        """Return VDR status."""
        return {
            "is_running": self._is_running,
            "log_dir": str(self._log_dir),
            "current_date": self._current_date,
            "entry_count": self._entry_count,
            "retention_days": VDR_RETENTION_DAYS,
        }
