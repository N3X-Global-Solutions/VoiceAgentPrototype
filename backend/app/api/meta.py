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
        "provider_key_set": bool(config.SARVAM_API_KEY),
        "public_base_url": config.PUBLIC_BASE_URL,
        "twilio_configured": config.twilio_configured(),
        "exotel_configured": config.exotel_configured(),
        "inbound_agent_id": get_setting("inbound_agent_id"),
        "max_call_seconds_cap": config.MAX_CALL_SECONDS_CAP,
        "max_cost_per_call_inr": config.MAX_COST_PER_CALL_INR,
        # Rates the cost meter uses (INR, ex-GST); set in .env.
        "rates": {
            "stt_per_min": config.PRICE_STT_PER_MIN,
            "tts_per_1k_chars": config.PRICE_TTS_PER_1K_CHARS,
            "llm_input_per_1m": config.PRICE_LLM_INPUT_PER_1M,
            "llm_cached_per_1m": config.PRICE_LLM_CACHED_PER_1M,
            "llm_output_per_1m": config.PRICE_LLM_OUTPUT_PER_1M,
            "exotel_per_min": config.PRICE_EXOTEL_PER_MIN,
            "exotel_pulse_secs": config.EXOTEL_PULSE_SECS,
            "twilio_per_min": config.PRICE_TWILIO_PER_MIN,
            "twilio_pulse_secs": config.TWILIO_PULSE_SECS,
        },
    }


@router.get("/api/catalog")
def catalog():
    return {"languages": LANGUAGES, "voices": voices(), "defaults": AgentConfig().model_dump()}
