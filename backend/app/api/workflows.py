import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Workflow
from ..schemas import WorkflowCreate, WorkflowResponse, WorkflowUpdate

router = APIRouter(prefix="/workflows", tags=["workflows"])

TEMPLATES = [
    {
        "id": "customer_support",
        "name": "Customer Support Pipeline",
        "description": "Triage agent classifies the issue; specialist agent resolves it.",
        "nodes": [
            {"id": "triage", "label": "Triage Agent", "agent_id": None,
             "position": {"x": 100, "y": 200}, "config": {"role": "triage"}},
            {"id": "specialist", "label": "Specialist Agent", "agent_id": None,
             "position": {"x": 420, "y": 200}, "config": {"role": "specialist"}},
        ],
        "edges": [
            {"id": "e1", "source": "triage", "target": "specialist",
             "condition": "always", "label": "Forward to specialist"},
        ],
    },
    {
        "id": "research_summarizer",
        "name": "Research & Summarizer",
        "description": "Research agent gathers information; summarizer agent condenses it.",
        "nodes": [
            {"id": "researcher", "label": "Research Agent", "agent_id": None,
             "position": {"x": 100, "y": 200}, "config": {"role": "researcher"}},
            {"id": "summarizer", "label": "Summarizer Agent", "agent_id": None,
             "position": {"x": 420, "y": 200}, "config": {"role": "summarizer"}},
        ],
        "edges": [
            {"id": "e1", "source": "researcher", "target": "summarizer",
             "condition": "always", "label": "Summarize research"},
        ],
    },
    {
        "id": "code_review",
        "name": "Code Review Pipeline",
        "description": "Analyzer checks code quality; reviewer provides feedback; reporter generates summary.",
        "nodes": [
            {"id": "analyzer", "label": "Code Analyzer", "agent_id": None,
             "position": {"x": 100, "y": 200}, "config": {"role": "analyzer"}},
            {"id": "reviewer", "label": "Code Reviewer", "agent_id": None,
             "position": {"x": 420, "y": 200}, "config": {"role": "reviewer"}},
            {"id": "reporter", "label": "Report Generator", "agent_id": None,
             "position": {"x": 740, "y": 200}, "config": {"role": "reporter"}},
        ],
        "edges": [
            {"id": "e1", "source": "analyzer", "target": "reviewer",
             "condition": "always", "label": "Review"},
            {"id": "e2", "source": "reviewer", "target": "reporter",
             "condition": "always", "label": "Report"},
        ],
    },
]


@router.get("/templates")
async def list_templates():
    return TEMPLATES


@router.get("/", response_model=List[WorkflowResponse])
async def list_workflows(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).order_by(Workflow.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=WorkflowResponse)
async def create_workflow(data: WorkflowCreate, db: AsyncSession = Depends(get_db)):
    workflow = Workflow(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        nodes=[n.model_dump() for n in data.nodes],
        edges=[e.model_dump() for e in data.edges],
        template_id=data.template_id,
    )
    db.add(workflow)
    await db.commit()
    await db.refresh(workflow)
    return workflow


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return wf


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(workflow_id: str, data: WorkflowUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(404, "Workflow not found")

    update = data.model_dump(exclude_none=True)
    if "nodes" in update:
        update["nodes"] = [
            n.model_dump() if hasattr(n, "model_dump") else n for n in update["nodes"]
        ]
    if "edges" in update:
        update["edges"] = [
            e.model_dump() if hasattr(e, "model_dump") else e for e in update["edges"]
        ]
    for k, v in update.items():
        setattr(wf, k, v)
    wf.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(wf)
    return wf


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    wf = result.scalar_one_or_none()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    await db.delete(wf)
    await db.commit()
    return {"success": True}
