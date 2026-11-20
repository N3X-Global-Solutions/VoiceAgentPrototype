"""Environment-driven settings. Secrets come only from .env / the environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR.parent / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def env_float(name: str, default: float) -> float:
    return _float(name, default)


# Voice AI providers. Each agent picks one per part (speech recognition, AI model, voice);
# a provider is usable once its key is set. See app/providers/catalog.py.
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
# Navana (Bodhi) keys from platform.navana.ai (bd_...). A legacy bodhi.navana.ai account also
# needs NAVANA_CUSTOMER_ID and NAVANA_STT_URL=wss://bodhi.navana.ai.
NAVANA_API_KEY = os.getenv("NAVANA_API_KEY", "")
NAVANA_CUSTOMER_ID = os.getenv("NAVANA_CUSTOMER_ID", "")
NAVANA_STT_URL = os.getenv("NAVANA_STT_URL", "wss://stt.navana.ai")
NAVANA_TTS_URL = os.getenv("NAVANA_TTS_URL", "https://tts.navana.ai/tts/bytes")
# Gnani (Vachana) key from app.gnani.ai. Its AI model (Evon) needs early access.
GNANI_API_KEY = os.getenv("GNANI_API_KEY", "")


def provider_api_key(provider: str) -> str:
    return {"sarvam": SARVAM_API_KEY, "navana": NAVANA_API_KEY, "gnani": GNANI_API_KEY}.get(provider, "")

# Public https base URL of this backend (ngrok / AWS). Needed only for phone calls,
# because the telephony provider must reach our WebSocket from the internet.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# SQLite database and the generated session secret live here (a Docker volume in production).
DATA_DIR = Path(os.getenv("DATA_DIR", BACKEND_DIR / "data"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

# Admin sign-in. Override both in .env on the server.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@n3xglobalsolutions.com").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "n3xadminpassword")
# Signs the session cookie. If empty, one is generated and stored in DATA_DIR.
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "72"))

# Credit guards: every call is hard-capped, whatever the agent config says.
MAX_CALL_SECONDS_CAP = int(os.getenv("MAX_CALL_SECONDS_CAP", "300"))
# Voice AI cost cap per call (phone line not included). ~Rs 2.8/min at current rates, so Rs 10 ~ 3.5 min.
MAX_COST_PER_CALL_INR = _float("MAX_COST_PER_CALL_INR", 10.0)

# Phone calls: the greeting waits for the caller's first "Hello?" (or this many seconds), so it
# isn't spoken into a line that isn't playing audio yet and lost.
GREETING_WAIT_OUTBOUND_SECS = _float("GREETING_WAIT_OUTBOUND_SECS", 2.5)
GREETING_WAIT_INBOUND_SECS = _float("GREETING_WAIT_INBOUND_SECS", 1.0)

# Telephony: Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

# Telephony: Exotel
EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY", "")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN", "")
EXOTEL_ACCOUNT_SID = os.getenv("EXOTEL_ACCOUNT_SID", "")
EXOTEL_SUBDOMAIN = os.getenv("EXOTEL_SUBDOMAIN", "api.exotel.com")  # api.in.exotel.com for Mumbai
EXOTEL_CALLER_ID = os.getenv("EXOTEL_CALLER_ID", "")  # your ExoPhone
EXOTEL_FLOW_APP_ID = os.getenv("EXOTEL_FLOW_APP_ID", "")  # flow containing the Voicebot applet

# Voice AI prices (INR, ex-GST) are per provider: see app/providers/catalog.py for every
# PRICE_* variable and its default.

# Phone line prices in INR per minute, billed in whole pulses from when the call is
# answered. Exotel and Twilio quote rates per account: copy yours from your invoice/plan.
PRICE_EXOTEL_PER_MIN = _float("PRICE_EXOTEL_PER_MIN", 1.00)
EXOTEL_PULSE_SECS = int(os.getenv("EXOTEL_PULSE_SECS", "60"))
PRICE_TWILIO_PER_MIN = _float("PRICE_TWILIO_PER_MIN", 0.0)
TWILIO_PULSE_SECS = int(os.getenv("TWILIO_PULSE_SECS", "60"))


def telephony_rate(channel: str) -> tuple[float, int]:
    """(INR per minute, pulse seconds) for a call channel; browser/chat calls have no line cost."""
    if channel == "exotel":
        return PRICE_EXOTEL_PER_MIN, EXOTEL_PULSE_SECS
    if channel == "twilio":
        return PRICE_TWILIO_PER_MIN, TWILIO_PULSE_SECS
    return 0.0, 0


def twilio_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER)


def exotel_configured() -> bool:
    return bool(
        EXOTEL_API_KEY
        and EXOTEL_API_TOKEN
        and EXOTEL_ACCOUNT_SID
        and EXOTEL_CALLER_ID
        and EXOTEL_FLOW_APP_ID
    )
