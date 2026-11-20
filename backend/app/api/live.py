"""Live calls: browser calls over WebRTC, outbound phone calls, and the telephony webhooks/WebSockets."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlmodel import Session

from pipecat.runner.types import WebSocketRunnerArguments
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

from app.api.deps import agent_or_404
from app.core.db import Agent, CallSession, engine, get_session, get_setting
from app.telephony import providers as telephony
from app.agents.models import AgentConfig
from app.providers.factory import missing_keys_message
from app.voice.bot import run_agent_call


def _require_provider_keys(agent: Agent) -> None:
    """Refuse a call up front if the agent's providers have no API key, instead of a silent call."""
    message = missing_keys_message(AgentConfig.model_validate(agent.config))
    if message:
        raise HTTPException(400, message)

router = APIRouter(tags=["live calls"])
webrtc_handler = SmallWebRTCRequestHandler()


class PhoneCallIn(BaseModel):
    to: str = Field(pattern=r"^\+?[0-9]{8,15}$")
    provider: str = Field(pattern=r"^(twilio|exotel)$")


# ---------------------------------------------------------------- browser calls (WebRTC)


@router.post("/api/agents/{agent_id}/offer")
async def webrtc_offer(agent_id: str, request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
    with Session(engine) as db:
        agent = agent_or_404(db, agent_id)
    _require_provider_keys(agent)

    async def on_connection(connection: SmallWebRTCConnection):
        transport = SmallWebRTCTransport(
            webrtc_connection=connection,
            params=TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=16000,
                audio_out_sample_rate=24000,
            ),
        )
        background_tasks.add_task(
            run_agent_call,
            transport=transport,
            agent=agent,
            channel="browser",
            in_sample_rate=16000,
            out_sample_rate=24000,
        )

    return await webrtc_handler.handle_web_request(request=request, webrtc_connection_callback=on_connection)


@router.patch("/api/agents/{agent_id}/offer")
async def webrtc_ice(agent_id: str, request: SmallWebRTCPatchRequest):
    await webrtc_handler.handle_patch_request(request)
    return {"status": "success"}


# ---------------------------------------------------------------- phone calls


@router.post("/api/agents/{agent_id}/phone-call")
async def phone_call(agent_id: str, body: PhoneCallIn, db: Session = Depends(get_session)):
    agent = agent_or_404(db, agent_id)
    _require_provider_keys(agent)
    call = CallSession(
        agent_id=agent.id,
        agent_version=agent.version,
        channel=body.provider,
        direction="outbound",
        phone_number=body.to,
        status="dialing",
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    try:
        if body.provider == "twilio":
            sid = await telephony.dial_twilio(body.to, agent.id, call.id)
        else:
            sid = await telephony.dial_exotel(body.to, agent.id, call.id)
    except HTTPException as e:
        call.status, call.error = "failed", str(e.detail)
        db.add(call)
        db.commit()
        raise
    call.provider_call_id = sid
    db.add(call)
    db.commit()
    return {"call_session_id": call.id, "provider_call_id": sid}


@router.post("/telephony/twilio/incoming")
async def twilio_incoming():
    """Set this as your Twilio number's Voice webhook (HTTP POST) for inbound calls."""
    agent_id = get_setting("inbound_agent_id")
    try:
        if not agent_id:
            raise HTTPException(400, "No agent is configured for this number.")
        twiml = telephony.twilio_stream_twiml(agent_id)
    except HTTPException as e:
        logger.error(f"Inbound Twilio call rejected: {e.detail}")
        twiml = "<Response><Say>Sorry, this line is not configured yet.</Say></Response>"
    return Response(content=twiml, media_type="application/xml")


async def _run_telephony(websocket: WebSocket, agent_id: str | None):
    await websocket.accept()
    transport_type, call_data = await parse_telephony_websocket(websocket)
    body = call_data.body or {}
    call_session_id = body.get("call_session_id") or ""
    direction = "outbound" if call_session_id else "inbound"

    if transport_type == "exotel" and not agent_id:
        match = telephony.match_exotel_call(call_data.from_number, call_data.to_number)
        if match:
            agent_id, call_session_id = match
            direction = "outbound"
    agent_id = agent_id or get_setting("inbound_agent_id")

    with Session(engine) as db:
        agent = db.get(Agent, agent_id) if agent_id else None
    if agent is None:
        logger.error(f"No agent for {transport_type} call {call_data.call_id}")
        await websocket.close()
        return

    params = lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True)  # noqa: E731
    try:
        transport = await create_transport(
            WebSocketRunnerArguments(websocket=websocket),
            {"twilio": params, "exotel": params, "plivo": params, "telnyx": params},
        )
    except ValueError as e:
        # e.g. Twilio needs TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN to hang up calls.
        logger.error(f"Cannot start {transport_type} call: {e}")
        await websocket.close()
        return
    caller = call_data.to_number if direction == "outbound" else call_data.from_number
    await run_agent_call(
        transport=transport,
        agent=agent,
        channel=transport_type,
        in_sample_rate=8000,
        out_sample_rate=8000,
        direction=direction,
        phone_number=caller or "",
        provider_call_id=call_data.call_id or "",
        call_session_id=call_session_id or None,
    )


@router.websocket("/ws/telephony/{agent_id}")
async def telephony_ws_for_agent(websocket: WebSocket, agent_id: str):
    await _run_telephony(websocket, agent_id)


@router.websocket("/ws/telephony")
async def telephony_ws(websocket: WebSocket):
    """Exotel Voicebot applet URL: outbound calls are matched by number, inbound use the inbound agent."""
    await _run_telephony(websocket, None)
