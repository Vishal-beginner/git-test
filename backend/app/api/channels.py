import os
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent
from ..channels.telegram_bot import telegram_channel

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("/status")
async def channel_status():
    return {
        "telegram": {
            "enabled": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "running": telegram_channel.running,
            "connected_agent": telegram_channel._default_agent_id,
        }
    }


@router.post("/telegram/connect-agent")
async def connect_telegram_agent(data: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    agent_id = data.get("agent_id")
    if not agent_id:
        raise HTTPException(400, "agent_id required")

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    telegram_channel.set_default_agent(agent_id)

    channels = list(agent.channels or [])
    if not any(c.get("type") == "telegram" for c in channels):
        channels.append({"type": "telegram", "enabled": True})
        agent.channels = channels
        await db.commit()

    return {"success": True, "message": f"Agent '{agent.name}' connected to Telegram"}
