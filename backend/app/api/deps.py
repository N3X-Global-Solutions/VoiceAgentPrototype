"""Helpers shared by the API routers."""

from fastapi import HTTPException
from sqlmodel import Session, select

from app.agents.models import AgentConfig
from app.core.db import Agent, Client


def agent_or_404(db: Session, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


def agent_out(agent: Agent) -> dict:
    """Agent with its config normalized, so agents saved before a new setting existed get its default."""
    return {**agent.model_dump(), "config": AgentConfig.model_validate(agent.config).model_dump()}


def client_payload(db: Session, client: Client) -> dict:
    agents = db.exec(select(Agent).where(Agent.client_id == client.id)).all()
    return {**client.model_dump(), "agents": [agent_out(a) for a in agents]}
