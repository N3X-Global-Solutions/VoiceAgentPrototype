"""Health checks and the catalog (languages, voices, default agent config)."""

from fastapi import APIRouter

from app.agents.models import AgentConfig, voices, LANGUAGES
from app.core import config
from app.core.db import get_setting

router = APIRouter(tags=["meta"])


@router.get("/api/healthz")
def healthz():
    """Unauthenticated liveness check for Docker / uptime monitors. Reveals nothing."""
    return {"ok": True}


@router.get("/api/health")
def health():
    return {
        "sarvam_key_set": bool(config.SARVAM_API_KEY),
        "public_base_url": config.PUBLIC_BASE_URL,
        "twilio_configured": config.twilio_configured(),
        "exotel_configured": config.exotel_configured(),
        "inbound_agent_id": get_setting("inbound_agent_id"),
        "max_call_seconds_cap": config.MAX_CALL_SECONDS_CAP,
        "max_cost_per_call_inr": config.MAX_COST_PER_CALL_INR,
    }


@router.get("/api/catalog")
def catalog():
    return {"languages": LANGUAGES, "voices": voices(), "defaults": AgentConfig().model_dump()}
