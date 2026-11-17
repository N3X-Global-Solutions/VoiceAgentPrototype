"""Outbound dialing through Twilio or Exotel. Their media streams come back to /ws/telephony."""

import asyncio
import time
from xml.sax.saxutils import quoteattr

import httpx
from fastapi import HTTPException

from app.core import config

# Exotel's Voicebot applet uses one fixed WebSocket URL per flow, so for outbound
# calls we remember which agent dialed which number and match it when the stream
# connects. Entries expire after 3 minutes.
_pending_exotel: dict[str, tuple[str, str, float]] = {}


def normalize_number(number: str) -> str:
    digits = "".join(ch for ch in number if ch.isdigit())
    return digits[-10:]  # compare on the last 10 digits (Indian mobile numbers)


def remember_exotel_call(to_number: str, agent_id: str, call_session_id: str) -> None:
    _pending_exotel[normalize_number(to_number)] = (agent_id, call_session_id, time.time())


def match_exotel_call(*numbers: str | None) -> tuple[str, str] | None:
    now = time.time()
    for key, (_, _, ts) in list(_pending_exotel.items()):
        if now - ts > 180:
            _pending_exotel.pop(key, None)
    for number in numbers:
        if number and (hit := _pending_exotel.pop(normalize_number(number), None)):
            return hit[0], hit[1]
    return None


def ws_url(path: str) -> str:
    if not config.PUBLIC_BASE_URL.startswith("https://"):
        raise HTTPException(
            400,
            "PUBLIC_BASE_URL must be set to a public https URL (for example your ngrok URL) "
            "so the phone provider can reach this server.",
        )
    return "wss://" + config.PUBLIC_BASE_URL.removeprefix("https://") + path


def twilio_stream_twiml(agent_id: str, call_session_id: str = "") -> str:
    url = ws_url(f"/ws/telephony/{agent_id}")
    param = (
        f'<Parameter name="call_session_id" value={quoteattr(call_session_id)} />'
        if call_session_id
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Connect><Stream url={quoteattr(url)}>{param}</Stream></Connect></Response>"
    )


async def dial_twilio(to_number: str, agent_id: str, call_session_id: str) -> str:
    if not config.twilio_configured():
        raise HTTPException(400, "Twilio is not configured. Set TWILIO_* values in .env")
    from twilio.rest import Client as TwilioClient

    twiml = twilio_stream_twiml(agent_id, call_session_id)

    def _create() -> str:
        client = TwilioClient(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        call = client.calls.create(
            to=to_number,
            from_=config.TWILIO_PHONE_NUMBER,
            twiml=twiml,
            time_limit=config.MAX_CALL_SECONDS_CAP,
        )
        return call.sid

    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        raise HTTPException(502, f"Twilio rejected the call: {e}") from e


async def dial_exotel(to_number: str, agent_id: str, call_session_id: str) -> str:
    if not config.exotel_configured():
        raise HTTPException(400, "Exotel is not configured. Set EXOTEL_* values in .env")
    url = (
        f"https://{config.EXOTEL_SUBDOMAIN}/v1/Accounts/{config.EXOTEL_ACCOUNT_SID}/Calls/connect.json"
    )
    flow_url = (
        f"http://my.exotel.com/{config.EXOTEL_ACCOUNT_SID}/exoml/start_voice/{config.EXOTEL_FLOW_APP_ID}"
    )
    remember_exotel_call(to_number, agent_id, call_session_id)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            auth=(config.EXOTEL_API_KEY, config.EXOTEL_API_TOKEN),
            data={
                "From": to_number,
                "CallerId": config.EXOTEL_CALLER_ID,
                "Url": flow_url,
                "TimeLimit": str(config.MAX_CALL_SECONDS_CAP),
                "CustomField": call_session_id,
            },
        )
    if resp.status_code >= 300:
        raise HTTPException(502, f"Exotel rejected the call ({resp.status_code}): {resp.text[:500]}")
    try:
        return resp.json().get("Call", {}).get("Sid", "")
    except ValueError:
        return ""
