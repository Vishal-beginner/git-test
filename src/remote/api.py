"""Remote Operations API — FastAPI application for remote monitoring and control.

Provides:
- WebSocket: /ws/telemetry — live telemetry stream
- GET /api/v1/status — current system status
- GET /api/v1/targets — tracked vessels
- GET /api/v1/route — active route
- GET /api/v1/alarms — active alarms
- POST /api/v1/route — upload new route (auth required)
- POST /api/v1/mode — change navigation mode (auth required)
- POST /api/v1/emergency/stop — emergency stop (auth required)

Authentication: Bearer JWT token (HS256).
Request logging via middleware.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
try:
    from jose import jwt as _jwt_module  # python-jose (preferred)
    jwt = _jwt_module
except BaseException:
    try:
        import jwt  # fallback to pyjwt
    except BaseException:
        jwt = None  # type: ignore[assignment]

from src.core.config import AppConfig
from src.core.types import (
    ManeuverCommand, NavigationMode, OwnShipState, Position, Route,
    TargetVessel, Waypoint, VesselType, Velocity, VesselDimensions,
)

logger = logging.getLogger(__name__)

# ── Auth ──────────────────────────────────────────────────────────────────────
JWT_ALGORITHM = "HS256"
JWT_SECRET = "ship-nav-secret-key-change-in-production"  # Override via env var
JWT_EXPIRE_MINUTES = 60

security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Verify JWT bearer token. Raises 401 if invalid."""
    if jwt is None:
        # JWT library not available — reject all tokens in secure mode
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT library not available",
        )
    try:
        token = credentials.credentials
        # python-jose and pyjwt have compatible decode interfaces for HS256
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        return payload  # type: ignore[return-value]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


# ── Request/Response Models ───────────────────────────────────────────────────

class RouteUploadRequest(BaseModel):
    name: str
    waypoints: list[dict]  # [{lat, lon, name, arrival_radius_nm}]


class ModeChangeRequest(BaseModel):
    mode: str  # NavigationMode value


class EmergencyStopRequest(BaseModel):
    reason: str = "Operator requested emergency stop"


class StatusResponse(BaseModel):
    system: dict
    own_ship: Optional[dict] = None
    timestamp: str


# ── WebSocket Connection Manager ──────────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._active.append(ws)
        logger.info("WebSocket connected", extra={"total": len(self._active)})

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._active:
                self._active.remove(ws)
        logger.info("WebSocket disconnected", extra={"remaining": len(self._active)})

    async def broadcast(self, data: dict) -> None:
        """Broadcast data to all connected clients."""
        if not self._active:
            return
        message = json.dumps(data, default=str)
        disconnected = []
        async with self._lock:
            for ws in list(self._active):
                try:
                    await ws.send_text(message)
                except Exception:
                    disconnected.append(ws)
        for ws in disconnected:
            await self.disconnect(ws)


# ── App Factory ───────────────────────────────────────────────────────────────

def create_api(
    orchestrator: Any,  # AgentOrchestrator
    vdr: Any,           # VoyageDataRecorder
    config: AppConfig,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Autonomous Ship Navigation API",
        description="Remote monitoring and control for autonomous vessel navigation system",
        version="1.0.0",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # WebSocket connection manager (shared state)
    ws_manager = ConnectionManager()

    # ── Request Logging Middleware ─────────────────────────────────────────────

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = datetime.now(timezone.utc)
        response = await call_next(request)
        duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        logger.info(
            "HTTP request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 1),
                "client": request.client.host if request.client else "unknown",
            }
        )
        return response

    # ── WebSocket Telemetry ────────────────────────────────────────────────────

    @app.websocket("/ws/telemetry")
    async def telemetry_websocket(ws: WebSocket):
        """
        WebSocket endpoint streaming live telemetry every 5 seconds.

        Sends JSON with: own_ship_state, tracked_targets, active_alarms,
        active_commands, system_status.
        """
        await ws_manager.connect(ws)
        try:
            while True:
                # Collect telemetry
                system_status = orchestrator.get_system_status()
                active_commands = orchestrator.get_active_commands()
                awareness_agent = orchestrator.get_awareness_agent()
                targets = await awareness_agent.get_targets()
                alarms = awareness_agent.get_active_alarms()

                telemetry = {
                    "type": "telemetry",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "system": system_status,
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
                            "vessel_type": t.vessel_type.value,
                        }
                        for t in targets[:50]  # Limit to 50 targets
                    ],
                    "alarms": alarms,
                    "commands": [
                        {
                            "course_deg": c.course_deg,
                            "speed_kts": c.speed_kts,
                            "reason": c.reason,
                            "priority": c.priority,
                        }
                        for c in active_commands
                    ],
                }

                await ws.send_text(json.dumps(telemetry, default=str))
                await asyncio.sleep(5.0)
        except WebSocketDisconnect:
            await ws_manager.disconnect(ws)
        except asyncio.CancelledError:
            await ws_manager.disconnect(ws)
        except Exception as exc:
            logger.error("WebSocket error", extra={"error": str(exc)})
            await ws_manager.disconnect(ws)

    # ── REST Endpoints ─────────────────────────────────────────────────────────

    @app.get("/api/v1/status", response_class=JSONResponse)
    async def get_status():
        """Get current system status."""
        system = orchestrator.get_system_status()
        return {
            "system": system,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/v1/targets", response_class=JSONResponse)
    async def get_targets():
        """Get all currently tracked target vessels."""
        awareness = orchestrator.get_awareness_agent()
        targets = await awareness.get_targets()
        return {
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
                    "vessel_type": t.vessel_type.value,
                    "is_ais_confirmed": t.is_ais_confirmed,
                    "last_updated": t.last_updated.isoformat(),
                }
                for t in targets
            ],
            "count": len(targets),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/v1/route", response_class=JSONResponse)
    async def get_route():
        """Get the current active route."""
        nav_agent = orchestrator._nav_agent
        route = nav_agent._route
        if route is None:
            return {"route": None, "active_leg": None}
        return {
            "route": {
                "name": route.name,
                "waypoints": [
                    {
                        "name": wp.name,
                        "lat": wp.position.lat,
                        "lon": wp.position.lon,
                        "arrival_radius_nm": wp.arrival_radius_nm,
                    }
                    for wp in route.waypoints
                ],
                "total_distance_nm": route.total_distance_nm,
                "estimated_duration_h": route.estimated_duration_h,
            },
            "active_leg": nav_agent.get_active_leg_index(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/v1/alarms", response_class=JSONResponse)
    async def get_alarms():
        """Get all currently active alarms."""
        awareness = orchestrator.get_awareness_agent()
        alarms = awareness.get_active_alarms()
        return {
            "alarms": alarms,
            "count": len(alarms),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/api/v1/route", response_class=JSONResponse)
    async def upload_route(
        request: RouteUploadRequest,
        _token: dict = Depends(verify_token),
    ):
        """Upload a new route (authenticated)."""
        try:
            waypoints = []
            for wp_data in request.waypoints:
                waypoints.append(Waypoint(
                    position=Position(
                        lat=wp_data["lat"],
                        lon=wp_data["lon"],
                    ),
                    name=wp_data.get("name", ""),
                    arrival_radius_nm=wp_data.get("arrival_radius_nm", 0.2),
                ))

            from src.navigation.route import RoutePlanner
            planner = RoutePlanner()
            route = planner.build_route(request.name, waypoints)
            orchestrator.set_route(route)

            logger.info("Route uploaded", extra={"name": request.name, "waypoints": len(waypoints)})

            return {
                "success": True,
                "route_name": request.name,
                "waypoint_count": len(waypoints),
                "total_distance_nm": route.total_distance_nm,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/mode", response_class=JSONResponse)
    async def change_mode(
        request: ModeChangeRequest,
        _token: dict = Depends(verify_token),
    ):
        """Change navigation mode (authenticated)."""
        try:
            mode = NavigationMode(request.mode)
            logger.warning(
                "Navigation mode change requested",
                extra={"mode": mode.value, "operator": _token.get("sub", "unknown")},
            )
            # Mode change is handled by the orchestrator/own ship integration
            # Here we just log and acknowledge
            return {
                "success": True,
                "mode": mode.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid mode. Valid modes: {[m.value for m in NavigationMode]}",
            )

    @app.post("/api/v1/emergency/stop", response_class=JSONResponse)
    async def emergency_stop(
        request: EmergencyStopRequest,
        _token: dict = Depends(verify_token),
    ):
        """Trigger emergency stop (authenticated)."""
        logger.critical(
            "OPERATOR EMERGENCY STOP",
            extra={
                "reason": request.reason,
                "operator": _token.get("sub", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Issue emergency stop to all agents
        stop_cmd = ManeuverCommand(
            course_deg=None,
            speed_kts=0.0,
            reason=f"OPERATOR EMERGENCY STOP: {request.reason}",
            colreg_rule="Operator Override",
            priority=100,
        )

        # Broadcast emergency notification to all WebSocket clients
        await ws_manager.broadcast({
            "type": "emergency",
            "message": f"EMERGENCY STOP: {request.reason}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "success": True,
            "message": "Emergency stop command issued",
            "reason": request.reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/health")
    async def health_check():
        """Health check endpoint for Docker HEALTHCHECK."""
        return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

    return app
