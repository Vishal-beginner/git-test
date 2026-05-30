import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal, get_db
from ..models import Agent, Execution, Message, Workflow
from ..schemas import ExecutionCreate, ExecutionResponse, MessageResponse
from ..core.agent_runtime import run_agent
from ..core.workflow_engine import workflow_engine

router = APIRouter(prefix="/executions", tags=["executions"])


def _agent_dict(agent: Agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "role": agent.role,
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "tools": agent.tools or [],
        "memory_config": agent.memory_config or {},
        "guardrails": agent.guardrails or {},
    }


async def _run_workflow(execution_id: str, workflow_id: str, input_data: dict):
    async with AsyncSessionLocal() as db:
        wf = (await db.execute(select(Workflow).where(Workflow.id == workflow_id))).scalar_one_or_none()
        if not wf:
            return

        agent_ids = [n.get("agent_id") for n in (wf.nodes or []) if n.get("agent_id")]
        agents = {}
        for aid in agent_ids:
            a = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
            if a:
                agents[aid] = _agent_dict(a)

        ex = (await db.execute(select(Execution).where(Execution.id == execution_id))).scalar_one_or_none()
        if ex:
            ex.status = "running"
            ex.started_at = datetime.utcnow()
            await db.commit()

        try:
            res = await workflow_engine.execute_workflow(
                workflow={"id": wf.id, "name": wf.name, "nodes": wf.nodes or [], "edges": wf.edges or []},
                agents=agents,
                execution_id=execution_id,
                input_data=input_data,
            )
            if ex:
                ex.status = "completed"
                ex.completed_at = datetime.utcnow()
                ex.output_data = {"output": res.get("output", "")}
                ex.total_tokens = res.get("total_tokens", 0)
                ex.total_cost = res.get("cost", 0.0)
                await db.commit()
        except Exception as e:
            if ex:
                ex.status = "failed"
                ex.error = str(e)
                ex.completed_at = datetime.utcnow()
                await db.commit()


async def _run_single_agent(execution_id: str, agent_id: str, input_data: dict):
    async with AsyncSessionLocal() as db:
        agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if not agent:
            return

        ex = (await db.execute(select(Execution).where(Execution.id == execution_id))).scalar_one_or_none()
        if ex:
            ex.status = "running"
            ex.started_at = datetime.utcnow()
            await db.commit()

        try:
            res = await run_agent(
                agent_config=_agent_dict(agent),
                messages=[{"role": "user", "content": input_data.get("message", "Hello")}],
                execution_id=execution_id,
            )
            msg = Message(
                id=str(uuid.uuid4()),
                execution_id=execution_id,
                from_agent_id=agent_id,
                from_agent_name=agent.name,
                to_agent_name="user",
                content=res.get("output", ""),
                message_type="ai_response",
                tokens_used=res.get("tokens", 0),
                cost=res.get("tokens", 0) * 0.000002,
            )
            db.add(msg)
            if ex:
                ex.status = "completed"
                ex.completed_at = datetime.utcnow()
                ex.output_data = {"output": res.get("output", "")}
                ex.total_tokens = res.get("tokens", 0)
                ex.total_cost = res.get("tokens", 0) * 0.000002
            await db.commit()
        except Exception as e:
            if ex:
                ex.status = "failed"
                ex.error = str(e)
                ex.completed_at = datetime.utcnow()
                await db.commit()


@router.post("/", response_model=ExecutionResponse)
async def create_execution(
    data: ExecutionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    ex = Execution(
        id=str(uuid.uuid4()),
        workflow_id=data.workflow_id,
        agent_id=data.agent_id,
        input_data=data.input_data,
        status="pending",
    )
    db.add(ex)
    await db.commit()
    await db.refresh(ex)

    if data.workflow_id:
        background_tasks.add_task(_run_workflow, ex.id, data.workflow_id, data.input_data)
    elif data.agent_id:
        background_tasks.add_task(_run_single_agent, ex.id, data.agent_id, data.input_data)

    return ex


@router.get("/", response_model=List[ExecutionResponse])
async def list_executions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Execution).order_by(Execution.created_at.desc()).limit(50))
    return result.scalars().all()


@router.get("/messages/all", response_model=List[MessageResponse])
async def get_all_messages(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Message).order_by(Message.created_at.desc()).limit(100))
    return result.scalars().all()


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(execution_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Execution).where(Execution.id == execution_id))
    ex = result.scalar_one_or_none()
    if not ex:
        raise HTTPException(404, "Execution not found")
    return ex


@router.get("/{execution_id}/messages", response_model=List[MessageResponse])
async def get_execution_messages(execution_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message).where(Message.execution_id == execution_id).order_by(Message.created_at)
    )
    return result.scalars().all()
