"""Clients and their agents. Creating a client creates its first agent in the same step."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlmodel import Session, select

from app.agents.models import AgentConfig
from app.api.deps import agent_or_404, agent_out, client_payload
from app.core.db import Agent, CallSession, Client, get_session, set_setting

router = APIRouter(tags=["clients & agents"])


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    industry: str = ""
    contact_name: str = ""
    contact_phone: str = ""
    notes: str = ""


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config: AgentConfig = Field(default_factory=AgentConfig)


class CreateClientIn(BaseModel):
    client: ClientIn
    agent: AgentIn


@router.get("/api/clients")
def list_clients(db: Session = Depends(get_session)):
    clients = db.exec(select(Client).order_by(Client.created_at.desc())).all()
    return [client_payload(db, c) for c in clients]


@router.post("/api/clients", status_code=201)
def create_client(body: CreateClientIn, db: Session = Depends(get_session)):
    """Creating a client creates its agent in the same transaction: no Sarvam-side setup."""
    client = Client(**body.client.model_dump())
    db.add(client)
    db.flush()
    agent = Agent(client_id=client.id, name=body.agent.name, config=body.agent.config.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(client)
    return client_payload(db, client)


@router.get("/api/clients/{client_id}")
def get_client(client_id: str, db: Session = Depends(get_session)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return client_payload(db, client)


@router.put("/api/clients/{client_id}")
def update_client(client_id: str, body: ClientIn, db: Session = Depends(get_session)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    for k, v in body.model_dump().items():
        setattr(client, k, v)
    db.add(client)
    db.commit()
    return client_payload(db, client)


@router.delete("/api/clients/{client_id}", status_code=204)
def delete_client(client_id: str, db: Session = Depends(get_session)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    agent_ids = db.exec(select(Agent.id).where(Agent.client_id == client_id)).all()
    if agent_ids:
        db.exec(delete(CallSession).where(CallSession.agent_id.in_(agent_ids)))
        db.exec(delete(Agent).where(Agent.id.in_(agent_ids)))
    db.delete(client)
    db.commit()


@router.post("/api/clients/{client_id}/agents", status_code=201)
def add_agent(client_id: str, body: AgentIn, db: Session = Depends(get_session)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "Client not found")
    agent = Agent(client_id=client_id, name=body.name, config=body.config.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, db: Session = Depends(get_session)):
    return agent_out(agent_or_404(db, agent_id))


@router.put("/api/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentIn, db: Session = Depends(get_session)):
    agent = agent_or_404(db, agent_id)
    agent.name = body.name
    agent.config = body.config.model_dump()
    agent.version += 1
    agent.updated_at = datetime.now(UTC)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.put("/api/agents/{agent_id}/inbound")
def set_inbound_agent(agent_id: str, db: Session = Depends(get_session)):
    """The agent that answers calls to your phone number."""
    agent_or_404(db, agent_id)
    set_setting(db, "inbound_agent_id", agent_id)
    db.commit()
    return {"inbound_agent_id": agent_id}
