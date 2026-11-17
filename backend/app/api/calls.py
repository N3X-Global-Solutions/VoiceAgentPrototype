"""Call history: every browser, chat and phone call with its transcript, latency and cost."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.db import CallSession, get_session

router = APIRouter(tags=["calls"])


@router.get("/api/calls")
def list_calls(agent_id: str | None = None, limit: int = 50, db: Session = Depends(get_session)):
    query = select(CallSession).order_by(CallSession.started_at.desc()).limit(min(limit, 200))
    if agent_id:
        query = query.where(CallSession.agent_id == agent_id)
    return db.exec(query).all()


@router.get("/api/calls/{call_id}")
def get_call(call_id: str, db: Session = Depends(get_session)):
    call = db.get(CallSession, call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    return call
