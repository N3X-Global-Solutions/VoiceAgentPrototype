"""Spend per provider and the credits left with each (see app/providers/usage.py)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.db import CreditEntry, get_session, set_setting
from app.providers import usage

router = APIRouter(tags=["usage"])


class CreditIn(BaseModel):
    provider: str
    kind: Literal["balance", "topup"]
    amount_inr: float = Field(ge=0, le=10_000_000)
    note: str = Field(default="", max_length=200)


class AlertIn(BaseModel):
    below_inr: float | None = Field(default=None, ge=0, le=10_000_000)


def _known(provider: str) -> None:
    if provider not in {a["id"] for a in usage.accounts()}:
        raise HTTPException(404, f"Unknown provider {provider}")


@router.get("/api/usage")
def get_usage(days: int = 30, tz: int = 0, db: Session = Depends(get_session)):
    return usage.usage_report(db, max(0, min(days, 3650)), max(-840, min(tz, 840)))


@router.post("/api/usage/credits", status_code=201)
def add_credit(body: CreditIn, db: Session = Depends(get_session)):
    _known(body.provider)
    if body.kind == "topup" and body.amount_inr <= 0:
        raise HTTPException(422, "A top-up must be more than ₹0.")
    entry = CreditEntry(provider=body.provider, kind=body.kind, amount_inr=body.amount_inr, note=body.note.strip())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/api/usage/credits/{entry_id}", status_code=204)
def delete_credit(entry_id: str, db: Session = Depends(get_session)):
    entry = db.get(CreditEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Credit entry not found")
    db.delete(entry)
    db.commit()


@router.put("/api/usage/alerts/{provider}")
def set_alert(provider: str, body: AlertIn, db: Session = Depends(get_session)):
    _known(provider)
    set_setting(db, usage.alert_key(provider), "" if body.below_inr is None else str(body.below_inr))
    db.commit()
    return {"provider": provider, "below_inr": body.below_inr}
