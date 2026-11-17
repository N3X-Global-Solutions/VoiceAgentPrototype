"""Environment-driven settings. Secrets come only from .env / the environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR.parent / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")

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
MAX_COST_PER_CALL_INR = _float("MAX_COST_PER_CALL_INR", 5.0)

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

# Sarvam API prices in INR (pay as you go, ex-GST) -- used for the live cost meter.
PRICE_STT_PER_MIN = _float("PRICE_STT_PER_MIN", 0.49)
PRICE_TTS_PER_1K_CHARS = _float("PRICE_TTS_PER_1K_CHARS", 1.00)
PRICE_LLM_INPUT_PER_1M = _float("PRICE_LLM_INPUT_PER_1M", 15.0)
PRICE_LLM_CACHED_PER_1M = _float("PRICE_LLM_CACHED_PER_1M", 5.0)
PRICE_LLM_OUTPUT_PER_1M = _float("PRICE_LLM_OUTPUT_PER_1M", 60.0)


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
