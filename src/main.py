"""Autonomous Ship Navigation System — Application Entry Point.

Starts the complete navigation system:
1. Load configuration
2. Initialize VDR (Voyage Data Recorder)
3. Initialize Safety Supervisor
4. Create Agent Orchestrator
5. Start FastAPI remote operations server
6. Run all components concurrently via asyncio.TaskGroup

Usage:
    python -m src.main
    python src/main.py

Environment variables:
    CONFIG_PATH: Path to ship.yaml config (default: config/ship.yaml)
    API_HOST: Override API host
    API_PORT: Override API port
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn

from src.core.config import load_config, AppConfig
from src.core.types import OwnShipState, Position, Velocity, VesselDimensions, VesselType, NavigationMode
from src.agents.orchestrator import AgentOrchestrator
from src.logging.vdr import VoyageDataRecorder
from src.remote.api import create_api
from src.safety.supervisor import SafetySupervisor

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main application entry point."""
    # Load config
    config_path = os.environ.get("CONFIG_PATH", "config/ship.yaml")
    logger.info("Loading configuration", extra={"path": config_path})

    try:
        config = load_config(config_path)
    except Exception as exc:
        logger.error("Failed to load configuration", extra={"error": str(exc), "path": config_path})
        sys.exit(1)

    logger.info(
        "Configuration loaded",
        extra={
            "ship_name": config.ship.name,
            "mmsi": config.ship.mmsi,
            "max_speed": config.ship.max_speed_kts,
        }
    )

    # Initialize VDR (must start first per IMO requirements)
    vdr_log_dir = Path("vdr_data") / config.ship.mmsi
    vdr = VoyageDataRecorder(config=config, log_dir=vdr_log_dir)
    logger.info("VDR initialized", extra={"log_dir": str(vdr_log_dir)})

    # Initialize Safety Supervisor (independent of agents)
    safety_supervisor = SafetySupervisor(config=config)
    logger.info("Safety Supervisor initialized")

    # Create Agent Orchestrator
    orchestrator = AgentOrchestrator(
        config=config,
        safety_supervisor=safety_supervisor,
        vdr=vdr,
    )
    logger.info("Agent Orchestrator created")

    # Create FastAPI application
    api = create_api(orchestrator=orchestrator, vdr=vdr, config=config)

    # Uvicorn server config
    api_host = os.environ.get("API_HOST", config.remote_ops.api_host)
    api_port = int(os.environ.get("API_PORT", config.remote_ops.api_port))

    uvicorn_config = uvicorn.Config(
        app=api,
        host=api_host,
        port=api_port,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(uvicorn_config)

    logger.info(
        "Starting autonomous ship navigation system",
        extra={
            "ship": config.ship.name,
            "mmsi": config.ship.mmsi,
            "api_host": api_host,
            "api_port": api_port,
        }
    )

    # Graceful shutdown handler
    shutdown_event = asyncio.Event()

    def handle_shutdown(signum, frame):
        logger.info("Shutdown signal received", extra={"signal": signum})
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Run all components concurrently
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(orchestrator.run(), name="orchestrator")
            tg.create_task(server.serve(), name="api_server")
            tg.create_task(vdr.run(), name="vdr")
            tg.create_task(safety_supervisor.run(), name="safety_supervisor")
            tg.create_task(_await_shutdown(shutdown_event, orchestrator, safety_supervisor), name="shutdown_watcher")
    except* asyncio.CancelledError:
        logger.info("System shutdown complete")
    except* Exception as eg:
        for exc in eg.exceptions:
            logger.error("Component failure", extra={"error": str(exc)}, exc_info=exc)
        sys.exit(1)

    logger.info("Autonomous ship navigation system stopped")


async def _await_shutdown(
    event: asyncio.Event,
    orchestrator: AgentOrchestrator,
    safety_supervisor: SafetySupervisor,
) -> None:
    """Wait for shutdown signal and gracefully stop components."""
    await event.wait()
    logger.info("Initiating graceful shutdown...")
    orchestrator.stop()
    safety_supervisor.stop()
    # Give components 5 seconds to clean up
    await asyncio.sleep(5.0)
    raise asyncio.CancelledError("Shutdown requested")


if __name__ == "__main__":
    asyncio.run(main())
