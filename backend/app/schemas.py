from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class AgentCreate(BaseModel):
    name: str
    role: str = "assistant"
    system_prompt: str = "You are a helpful AI assistant."
    model: str = "gpt-4o-mini"
    tools: List[str] = []
    channels: List[Dict[str, Any]] = []
    memory_config: Dict[str, Any] = {"type": "buffer", "window_size": 10}
    schedule: Optional[str] = None
    guardrails: Dict[str, Any] = {"max_tokens": 2000, "max_iterations": 10, "timeout": 60}
    skills: List[str] = []
    interaction_rules: List[str] = []


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    tools: Optional[List[str]] = None
    channels: Optional[List[Dict[str, Any]]] = None
    memory_config: Optional[Dict[str, Any]] = None
    schedule: Optional[str] = None
    guardrails: Optional[Dict[str, Any]] = None
    skills: Optional[List[str]] = None
    interaction_rules: Optional[List[str]] = None
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    id: str
    name: str
    role: str
    system_prompt: str
    model: str
    tools: List[str]
    channels: List[Dict[str, Any]]
    memory_config: Dict[str, Any]
    schedule: Optional[str]
    guardrails: Dict[str, Any]
    skills: List[str]
    interaction_rules: List[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowNode(BaseModel):
    id: str
    agent_id: Optional[str] = None
    label: str = ""
    position: Dict[str, float] = {"x": 0, "y": 0}
    config: Dict[str, Any] = {}


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    condition: Optional[str] = None
    label: Optional[str] = None


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    nodes: List[WorkflowNode] = []
    edges: List[WorkflowEdge] = []
    template_id: Optional[str] = None


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[WorkflowNode]] = None
    edges: Optional[List[WorkflowEdge]] = None
    status: Optional[str] = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    status: str
    template_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExecutionCreate(BaseModel):
    workflow_id: Optional[str] = None
    agent_id: Optional[str] = None
    input_data: Dict[str, Any] = {}


class ExecutionResponse(BaseModel):
    id: str
    workflow_id: Optional[str]
    agent_id: Optional[str]
    status: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    error: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_tokens: int
    total_cost: float
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: str
    execution_id: Optional[str]
    from_agent_name: str
    to_agent_name: str
    content: str
    message_type: str
    channel: str
    tokens_used: int
    cost: float
    created_at: datetime

    model_config = {"from_attributes": True}
