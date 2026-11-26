"""Health checks and the catalog (languages, voices, default agent config)."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.agents.models import AgentConfig, LANGUAGES
from app.core import config
from app.core.db import get_session, get_setting
from app.providers import catalog as providers_catalog
from app.providers import usage

router = APIRouter(tags=["meta"])


@router.get("/api/healthz")
def healthz():
    """Unauthenticated liveness check for Docker / uptime monitors. Reveals nothing."""
    return {"ok": True}


@router.get("/api/health")
def health(db: Session = Depends(get_session)):
    return {
        # True when at least one voice AI provider has a key; per-provider status below.
        "provider_key_set": any(providers_catalog.configured(p) for p in providers_catalog.providers()),
        "providers": {p: providers_catalog.configured(p) for p in providers_catalog.providers()},
        "public_base_url": config.PUBLIC_BASE_URL,
        "twilio_configured": config.twilio_configured(),
        "exotel_configured": config.exotel_configured(),
        "inbound_agent_id": get_setting("inbound_agent_id"),
        # Credits left per provider (only providers with credit entries): {remaining, status}.
        "credits": {p: {"remaining": c["remaining"], "status": c["status"]} for p, c in usage.credit_status(db).items()},
        "max_call_seconds_cap": config.MAX_CALL_SECONDS_CAP,
        "max_cost_per_call_inr": config.MAX_COST_PER_CALL_INR,
        # Phone-line rates (INR, ex-GST); voice AI rates are per provider, in /api/catalog.
        "rates": {
            "exotel_per_min": config.PRICE_EXOTEL_PER_MIN,
            "exotel_pulse_secs": config.EXOTEL_PULSE_SECS,
            "twilio_per_min": config.PRICE_TWILIO_PER_MIN,
            "twilio_pulse_secs": config.TWILIO_PULSE_SECS,
            "plivo_per_min": config.PRICE_PLIVO_PER_MIN,
            "plivo_pulse_secs": config.PLIVO_PULSE_SECS,
        },
    }


@router.get("/api/catalog")
def catalog():
    return {
        "languages": LANGUAGES,
        "voices": providers_catalog.voices(),
        "providers": providers_catalog.public_catalog(),
        "defaults": AgentConfig().model_dump(),
    }
