import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db, AsyncSessionLocal
from .core.message_bus import message_bus
from .channels.telegram_bot import telegram_channel
from .api import agents, workflows, executions, channels as channels_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _make_telegram_handler():
    from sqlalchemy import select
    from .models import Agent, Execution, Message
    from .core.agent_runtime import run_agent

    async def handle(text: str, chat_id: str, channel: str) -> str:
        agent_id = telegram_channel._default_agent_id

        async with AsyncSessionLocal() as db:
            if not agent_id:
                result = await db.execute(select(Agent).where(Agent.is_active == True).limit(1))
                a = result.scalar_one_or_none()
                agent_id = a.id if a else None

            if not agent_id:
                return "No agent configured yet."

            result = await db.execute(select(Agent).where(Agent.id == agent_id))
            agent = result.scalar_one_or_none()
            if not agent:
                return "Agent not found."

            exec_id = str(uuid.uuid4())
            ex = Execution(
                id=exec_id,
                agent_id=agent_id,
                input_data={"message": text, "channel": channel},
                status="running",
                started_at=datetime.utcnow(),
            )
            db.add(ex)
            await db.commit()

            res = await run_agent(
                agent_config={
                    "id": agent.id, "name": agent.name, "role": agent.role,
                    "system_prompt": agent.system_prompt, "model": agent.model,
                    "tools": agent.tools or [], "memory_config": agent.memory_config or {},
                    "guardrails": agent.guardrails or {},
                },
                messages=[{"role": "user", "content": text}],
                execution_id=exec_id,
            )

            msg = Message(
                id=str(uuid.uuid4()), execution_id=exec_id,
                from_agent_id=agent_id, from_agent_name=agent.name,
                to_agent_name=f"telegram:{chat_id}",
                content=res.get("output", ""), message_type="ai_response",
                channel="telegram", tokens_used=res.get("tokens", 0),
            )
            db.add(msg)
            ex.status = "completed"
            ex.completed_at = datetime.utcnow()
            ex.output_data = {"output": res.get("output", "")}
            ex.total_tokens = res.get("tokens", 0)
            await db.commit()

            return res.get("output", "I couldn't generate a response.")

    return handle


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    bus_task = asyncio.create_task(message_bus.start())

    tg_task = None
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        handler = await _make_telegram_handler()
        telegram_channel.set_agent_handler(handler)
        tg_task = asyncio.create_task(telegram_channel.start())

    yield

    message_bus.stop()
    await telegram_channel.stop()
    bus_task.cancel()
    if tg_task:
        tg_task.cancel()


app = FastAPI(
    title="AI Agent Orchestration Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api")
app.include_router(workflows.router, prefix="/api")
app.include_router(executions.router, prefix="/api")
app.include_router(channels_api.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await message_bus.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        message_bus.disconnect(websocket)
