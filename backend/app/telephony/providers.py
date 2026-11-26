"""Outbound dialing through Twilio, Exotel or Plivo. Their media streams come back to /ws/telephony.

Twilio and the workspace Exotel number use the .env account. A client's own number (PhoneLine)
dials with that client's credentials: see app.telephony.lines.
"""

import asyncio
import time
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

import httpx
from fastapi import HTTPException

from app.core import config
from app.core.db import PhoneLine
from app.telephony import lines

# Exotel's Voicebot applet uses one fixed WebSocket URL per flow, so for outbound calls we
# remember which agent dialed which number (per line; "" = the workspace number) and match it
# when the stream connects. Entries expire after 3 minutes.
_pending_exotel: dict[tuple[str, str], tuple[str, str, float]] = {}


def normalize_number(number: str) -> str:
    digits = "".join(ch for ch in number if ch.isdigit())
    return digits[-10:]  # compare on the last 10 digits (Indian mobile numbers)


def remember_exotel_call(to_number: str, agent_id: str, call_session_id: str, line_id: str = "") -> None:
    _pending_exotel[(line_id, normalize_number(to_number))] = (agent_id, call_session_id, time.time())


def match_exotel_call(*numbers: str | None, line_id: str = "") -> tuple[str, str] | None:
    now = time.time()
    for key, (_, _, ts) in list(_pending_exotel.items()):
        if now - ts > 180:
            _pending_exotel.pop(key, None)
    for number in numbers:
        if number and (hit := _pending_exotel.pop((line_id, normalize_number(number)), None)):
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
    """Dial from the workspace ExoPhone in .env."""
    if not config.exotel_configured():
        raise HTTPException(400, "Exotel is not configured. Set EXOTEL_* values in .env")
    return await _exotel_connect(
        host=config.EXOTEL_SUBDOMAIN,
        account_sid=config.EXOTEL_ACCOUNT_SID,
        auth=(config.EXOTEL_API_KEY, config.EXOTEL_API_TOKEN),
        caller_id=config.EXOTEL_CALLER_ID,
        flow_app_id=config.EXOTEL_FLOW_APP_ID,
        to_number=to_number,
        call_session_id=call_session_id,
        remember=lambda: remember_exotel_call(to_number, agent_id, call_session_id),
    )


async def dial_line(line: PhoneLine, to_number: str, agent_id: str, call_session_id: str) -> str:
    """Dial from a client's own number, with their account's credentials."""
    secrets = lines.secrets_of(line)
    if line.provider == "exotel":
        s = line.settings
        if not s.get("flow_app_id"):
            raise HTTPException(400, "Add the Exotel flow (app) ID to this number to place outbound calls.")
        if not secrets.get("api_key") or not secrets.get("api_token"):
            raise HTTPException(400, "This number's API key/token are missing. Enter them again.")
        return await _exotel_connect(
            host=s["subdomain"],
            account_sid=s["account_sid"],
            auth=(secrets["api_key"], secrets["api_token"]),
            caller_id=line.number,
            flow_app_id=s["flow_app_id"],
            to_number=to_number,
            call_session_id=call_session_id,
            remember=lambda: remember_exotel_call(to_number, agent_id, call_session_id, line.id),
        )
    return await _plivo_call(line, secrets, to_number, agent_id, call_session_id)


async def _exotel_connect(
    *, host, account_sid, auth, caller_id, flow_app_id, to_number, call_session_id, remember
) -> str:
    url = f"https://{host}/v1/Accounts/{account_sid}/Calls/connect.json"
    flow_url = f"http://my.exotel.com/{account_sid}/exoml/start_voice/{flow_app_id}"
    remember()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            url,
            auth=auth,
            data={
                "From": to_number,
                "CallerId": caller_id,
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


# ---------------------------------------------------------------- Plivo


def plivo_answer_url(line: PhoneLine, agent_id: str, call_session_id: str) -> str:
    base = lines.urls(line).get("answer")
    if not base:
        ws_url("")  # raises the PUBLIC_BASE_URL error
    return f"{base}?{urlencode({'agent': agent_id, 'session': call_session_id})}"


def plivo_stream_xml(line: PhoneLine, agent_id: str, call_session_id: str = "", caller: str = "") -> str:
    """Plivo XML that streams the call's audio to our WebSocket, both ways. Plivo's stream doesn't
    carry the call's details, so the agent, call record and caller ride in the URL."""
    query = {k: v for k, v in {"agent": agent_id, "session": call_session_id, "caller": caller}.items() if v}
    url = ws_url(f"/ws/telephony/line/{line.id}") + "?" + urlencode(query)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        '<Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">'
        f"{escape(url)}</Stream></Response>"
    )


async def _plivo_call(line: PhoneLine, secrets: dict, to_number: str, agent_id: str, call_session_id: str) -> str:
    auth_id, auth_token = line.settings.get("auth_id", ""), secrets.get("auth_token", "")
    if not auth_id or not auth_token:
        raise HTTPException(400, "This number's Plivo Auth ID/Token are missing. Enter them again.")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{lines.PLIVO_API}/{auth_id}/Call/",
            auth=(auth_id, auth_token),
            json={
                "from": lines.digits(line.number),
                "to": lines.digits(to_number),
                "answer_url": plivo_answer_url(line, agent_id, call_session_id),
                "answer_method": "POST",
                "time_limit": config.MAX_CALL_SECONDS_CAP,
            },
        )
    if resp.status_code >= 300:
        raise HTTPException(502, f"Plivo rejected the call ({resp.status_code}): {resp.text[:500]}")
    try:
        uuid = resp.json().get("request_uuid", "")
        return uuid[0] if isinstance(uuid, list) and uuid else str(uuid)
    except ValueError:
        return ""
