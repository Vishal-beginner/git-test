import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .database import Base


def gen_id():
    return str(uuid.uuid4())


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="assistant")
    system_prompt = Column(Text, nullable=False, default="You are a helpful AI assistant.")
    model = Column(String, nullable=False, default="gpt-4o-mini")
    tools = Column(JSON, default=list)
    channels = Column(JSON, default=list)
    memory_config = Column(JSON, default=dict)
    schedule = Column(String, nullable=True)
    guardrails = Column(JSON, default=dict)
    skills = Column(JSON, default=list)
    interaction_rules = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship("Message", back_populates="agent", foreign_keys="Message.from_agent_id")


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    nodes = Column(JSON, default=list)
    edges = Column(JSON, default=list)
    status = Column(String, default="draft")
    template_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    executions = relationship("Execution", back_populates="workflow")


class Execution(Base):
    __tablename__ = "executions"

    id = Column(String, primary_key=True, default=gen_id)
    workflow_id = Column(String, ForeignKey("workflows.id"), nullable=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    status = Column(String, default="pending")
    input_data = Column(JSON, default=dict)
    output_data = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    total_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    workflow = relationship("Workflow", back_populates="executions")
    messages = relationship("Message", back_populates="execution")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=gen_id)
    execution_id = Column(String, ForeignKey("executions.id"), nullable=True)
    from_agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    to_agent_id = Column(String, ForeignKey("agents.id"), nullable=True)
    from_agent_name = Column(String, default="user")
    to_agent_name = Column(String, default="agent")
    content = Column(Text, nullable=False)
    message_type = Column(String, default="message")
    channel = Column(String, default="internal")
    tokens_used = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    execution = relationship("Execution", back_populates="messages")
    agent = relationship("Agent", back_populates="messages", foreign_keys=[from_agent_id])
