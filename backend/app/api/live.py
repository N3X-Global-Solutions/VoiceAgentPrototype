"""Live calls: browser calls over WebRTC, outbound phone calls, and the telephony webhooks/WebSockets."""

from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, WebSocket
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field, model_validator
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
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from app.api.deps import agent_or_404
from app.core.db import Agent, CallSession, PhoneLine, engine, get_session, get_setting
from app.telephony import lines
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
    """Dial from the workspace number in .env (provider), or from one of the client's numbers (line_id)."""

    to: str = Field(pattern=r"^\+?[0-9]{8,15}$")
    provider: str | None = Field(default=None, pattern=r"^(twilio|exotel)$")
    line_id: str | None = None

    @model_validator(mode="after")
    def _one_route(self):
        if bool(self.provider) == bool(self.line_id):
            raise ValueError("Choose the workspace number or one of the client's numbers to call from.")
        return self


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
    line = db.get(PhoneLine, body.line_id) if body.line_id else None
    if body.line_id and (line is None or line.client_id != agent.client_id):
        raise HTTPException(404, "That phone number doesn't belong to this agent's client.")
    call = CallSession(
        agent_id=agent.id,
        agent_version=agent.version,
        channel=line.provider if line else body.provider,
        direction="outbound",
        phone_number=body.to,
        line_id=line.id if line else "",
        status="dialing",
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    try:
        if line:
            sid = await telephony.dial_line(line, body.to, agent.id, call.id)
        elif body.provider == "twilio":
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


@router.api_route("/telephony/plivo/{line_id}/answer", methods=["GET", "POST"])
async def plivo_answer(line_id: str, request: Request):
    """Answer URL of the application we create in a client's Plivo account (see lines.connect_plivo).
    Outbound calls carry their agent and call record in the query; inbound calls use the line's agent."""
    form = parse_qs((await request.body()).decode(errors="ignore")) if request.method == "POST" else {}
    query = request.query_params
    agent_id, session_id, caller = query.get("agent", ""), query.get("session", ""), ""
    with Session(engine) as db:
        line = db.get(PhoneLine, line_id)
    try:
        if line is None or line.provider != "plivo":
            raise HTTPException(404, f"Unknown Plivo line {line_id}")
        if not agent_id:
            agent_id = line.inbound_agent_id
            caller = (form.get("From") or [""])[0]
        if not agent_id:
            raise HTTPException(400, f"No agent answers {line.number}")
        xml = telephony.plivo_stream_xml(line, agent_id, session_id, caller)
    except HTTPException as e:
        logger.error(f"Plivo call rejected: {e.detail}")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Speak>Sorry, this line is not configured yet.</Speak></Response>"
        )
    return Response(content=xml, media_type="application/xml")


def _line_transport(websocket: WebSocket, transport_type: str, call_data, line: PhoneLine) -> FastAPIWebsocketTransport:
    """Like pipecat's create_transport, but with the client's own credentials (it reads .env)."""
    if transport_type == "plivo":
        from pipecat.serializers.plivo import PlivoFrameSerializer

        serializer = PlivoFrameSerializer(
            stream_id=call_data["stream_id"],
            call_id=call_data["call_id"],
            auth_id=line.settings.get("auth_id", ""),
            auth_token=lines.secrets_of(line).get("auth_token", ""),
        )
    else:
        from pipecat.serializers.exotel import ExotelFrameSerializer

        serializer = ExotelFrameSerializer(stream_sid=call_data["stream_id"], call_sid=call_data["call_id"])
    params = FastAPIWebsocketParams(
        audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False, serializer=serializer
    )
    return FastAPIWebsocketTransport(websocket=websocket, params=params)


async def _run_telephony(websocket: WebSocket, agent_id: str | None, line_id: str | None = None):
    await websocket.accept()
    transport_type, call_data = await parse_telephony_websocket(websocket)
    body = call_data.body or {}
    call_session_id = body.get("call_session_id") or ""
    caller_hint = ""

    line = None
    if line_id:
        with Session(engine) as db:
            line = db.get(PhoneLine, line_id)
        if line is None or line.provider != transport_type:
            logger.error(f"{transport_type} stream for unknown line {line_id}")
            await websocket.close()
            return
        query = websocket.query_params  # Plivo: set by plivo_stream_xml
        agent_id = query.get("agent") or None
        call_session_id = query.get("session") or call_session_id
        caller_hint = query.get("caller", "")

    direction = "outbound" if call_session_id else "inbound"
    if transport_type == "exotel" and not agent_id:
        match = telephony.match_exotel_call(call_data.from_number, call_data.to_number, line_id=line_id or "")
        if match:
            agent_id, call_session_id = match
            direction = "outbound"
    agent_id = agent_id or (line.inbound_agent_id if line else get_setting("inbound_agent_id"))

    with Session(engine) as db:
        agent = db.get(Agent, agent_id) if agent_id else None
    if agent is None or (line and agent.client_id != line.client_id):
        logger.error(f"No agent for {transport_type} call {call_data.call_id}")
        await websocket.close()
        return

    if line:
        transport = _line_transport(websocket, transport_type, call_data, line)
    else:
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
    # Outbound calls already hold the dialled number. (Exotel's connect API dials the customer
    # as "From", so the stream's to/from can't be trusted for them.)
    caller = "" if call_session_id else (call_data.from_number or caller_hint)
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
        line_id=line.id if line else "",
        telephony_rate=lines.rate(line, transport_type),
    )


@router.websocket("/ws/telephony/line/{line_id}")
async def telephony_ws_for_line(websocket: WebSocket, line_id: str):
    """A client's own number: Exotel's Voicebot applet URL, or where our Plivo XML streams to."""
    await _run_telephony(websocket, None, line_id)


@router.websocket("/ws/telephony/{agent_id}")
async def telephony_ws_for_agent(websocket: WebSocket, agent_id: str):
    await _run_telephony(websocket, agent_id)


@router.websocket("/ws/telephony")
async def telephony_ws(websocket: WebSocket):
    """Exotel Voicebot applet URL: outbound calls are matched by number, inbound use the inbound agent."""
    await _run_telephony(websocket, None)
