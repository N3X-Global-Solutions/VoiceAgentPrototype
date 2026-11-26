"""A client's own phone numbers (bring your own Exotel or Plivo account). See app.telephony.lines."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.db import Agent, Client, PhoneLine, get_session
from app.telephony import lines

router = APIRouter(tags=["phone numbers"])


class PhoneLineIn(BaseModel):
    provider: Literal["exotel", "plivo"]
    label: str = Field(default="", max_length=80)
    number: str = Field(pattern=r"^\+?[0-9][0-9 ()-]{6,20}$")
    inbound_agent_id: str = ""
    settings: dict[str, str] = Field(default_factory=dict)
    # Blank values keep the stored ones, so the browser never needs to see them.
    secrets: dict[str, str] = Field(default_factory=dict)
    price_per_min: float | None = Field(default=None, ge=0, le=100)
    pulse_secs: int | None = Field(default=None, ge=1, le=600)


def _line_or_404(db: Session, line_id: str) -> PhoneLine:
    line = db.get(PhoneLine, line_id)
    if not line:
        raise HTTPException(404, "Phone number not found")
    return line


def _apply(db: Session, line: PhoneLine, body: PhoneLineIn) -> None:
    if body.inbound_agent_id:
        agent = db.get(Agent, body.inbound_agent_id)
        if not agent or agent.client_id != line.client_id:
            raise HTTPException(422, "The answering agent must belong to this client.")
    number = ("+" if body.number.strip().startswith("+") else "") + lines.digits(body.number)
    others = db.exec(select(PhoneLine).where(PhoneLine.provider == body.provider, PhoneLine.id != line.id)).all()
    if any(lines.same_number(o.number, number) for o in others):
        raise HTTPException(409, f"{number} is already added on {body.provider.title()}.")
    settings, secrets = lines.clean_settings(body.provider, body.settings, body.secrets, lines.secrets_of(line))
    # Keep what we set ourselves when connecting (Plivo application ids).
    kept = {k: v for k, v in line.settings.items() if k in ("app_id", "previous_app_id")}
    line.provider = body.provider
    line.label = body.label.strip()
    line.number = number
    line.inbound_agent_id = body.inbound_agent_id
    line.settings = {**settings, **kept}
    line.secrets = lines.encrypt(secrets)
    line.price_per_min = body.price_per_min
    line.pulse_secs = body.pulse_secs


@router.post("/api/clients/{client_id}/phone-lines", status_code=201)
async def add_line(client_id: str, body: PhoneLineIn, db: Session = Depends(get_session)):
    """Save the number, then check it (and connect it, for Plivo). It is saved even if the check
    fails, so the status can say what to fix."""
    if not db.get(Client, client_id):
        raise HTTPException(404, "Client not found")
    line = PhoneLine(client_id=client_id, provider=body.provider, number="")
    _apply(db, line, body)
    await lines.check_and_connect(line)
    db.add(line)
    db.commit()
    db.refresh(line)
    return lines.line_out(line)


@router.put("/api/phone-lines/{line_id}")
async def update_line(line_id: str, body: PhoneLineIn, db: Session = Depends(get_session)):
    line = _line_or_404(db, line_id)
    if body.provider != line.provider:
        raise HTTPException(422, "A number can't change provider. Remove it and add it again.")
    before = line.model_copy()
    _apply(db, line, body)
    warning = ""
    moved = not lines.same_number(before.number, line.number) or before.settings.get("auth_id") != line.settings.get("auth_id")
    if line.provider == "plivo" and moved and before.settings.get("app_id"):
        # The old number/account still points at us: give it back before connecting the new one.
        warning = await lines.disconnect_plivo(before)
        line.settings = {k: v for k, v in line.settings.items() if k not in ("app_id", "previous_app_id")}
    await lines.check_and_connect(line)
    if warning:
        line.status_detail = f"{line.status_detail} Previous number: {warning}"
    db.add(line)
    db.commit()
    db.refresh(line)
    return lines.line_out(line)


@router.post("/api/phone-lines/{line_id}/check")
async def check_line(line_id: str, db: Session = Depends(get_session)):
    line = _line_or_404(db, line_id)
    await lines.check_and_connect(line)
    db.add(line)
    db.commit()
    db.refresh(line)
    return lines.line_out(line)


@router.delete("/api/phone-lines/{line_id}")
async def delete_line(line_id: str, db: Session = Depends(get_session)):
    """Remove the number. For Plivo, give the number back its previous application first."""
    line = _line_or_404(db, line_id)
    warning = await lines.disconnect_plivo(line) if line.provider == "plivo" else ""
    db.delete(line)
    db.commit()
    return {"warning": warning}
