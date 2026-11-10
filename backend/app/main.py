"""HTTP + WebSocket API: clients/agents CRUD, browser calls (WebRTC), phone calls, call history."""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete
from sqlmodel import Session, select

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

from app import config, telephony
from app.agent_config import LANGUAGES, SCRIPTS, AgentConfig, voices
from app.bot import LLM_MODEL, run_agent_call
from app.db import Agent, CallSession, Client, Setting, engine, get_session, init_db
from app.tools import openai_tools, run_http_tool

FRONTEND_DIST = config.BACKEND_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not config.SARVAM_API_KEY:
        logger.warning("SARVAM_API_KEY is not set: calls will fail until you add it to .env")
    yield
    await webrtc_handler.close()


app = FastAPI(title="Sarvam Voice Agent Prototype", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
webrtc_handler = SmallWebRTCRequestHandler()


# ---------------------------------------------------------------- schemas


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    industry: str = ""
    contact_name: str = ""
    contact_phone: str = ""
    notes: str = ""


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config: AgentConfig = Field(default_factory=AgentConfig)


class CreateClientIn(BaseModel):
    client: ClientIn
    agent: AgentIn


class ChatIn(BaseModel):
    messages: list[dict] = Field(default_factory=list)  # [{role, content}] excluding system


class TranslateIn(BaseModel):
    language: str
    texts: dict[str, str] = Field(max_length=10)


class PhoneCallIn(BaseModel):
    to: str = Field(pattern=r"^\+?[0-9]{8,15}$")
    provider: str = Field(pattern=r"^(twilio|exotel)$")


# ---------------------------------------------------------------- helpers


def _agent_or_404(db: Session, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


def _agent_out(agent: Agent) -> dict:
    """Agent with its config normalized, so agents saved before a new setting existed get its default."""
    return {**agent.model_dump(), "config": AgentConfig.model_validate(agent.config).model_dump()}


def _client_payload(db: Session, client: Client) -> dict:
    agents = db.exec(select(Agent).where(Agent.client_id == client.id)).all()
    return {**client.model_dump(), "agents": [_agent_out(a) for a in agents]}


def _get_setting(key: str) -> str:
    with Session(engine) as db:
        row = db.get(Setting, key)
        return row.value if row else ""


# ---------------------------------------------------------------- meta


@app.get("/api/health")
def health():
    return {
        "sarvam_key_set": bool(config.SARVAM_API_KEY),
        "public_base_url": config.PUBLIC_BASE_URL,
        "twilio_configured": config.twilio_configured(),
        "exotel_configured": config.exotel_configured(),
        "inbound_agent_id": _get_setting("inbound_agent_id"),
        "max_call_seconds_cap": config.MAX_CALL_SECONDS_CAP,
        "max_cost_per_call_inr": config.MAX_COST_PER_CALL_INR,
    }


@app.get("/api/catalog")
def catalog():
    return {"languages": LANGUAGES, "voices": voices(), "defaults": AgentConfig().model_dump()}


# ---------------------------------------------------------------- clients & agents


@app.get("/api/clients")
def list_clients(db: Session = Depends(get_session)):
    clients = db.exec(select(Client).order_by(Client.created_at.desc())).all()
    return [_client_payload(db, c) for c in clients]


@app.post("/api/clients", status_code=201)
def create_client(body: CreateClientIn, db: Session = Depends(get_session)):
    """Creating a client creates its agent in the same transaction: no Sarvam-side setup."""
    client = Client(**body.client.model_dump())
    db.add(client)
    db.flush()
    agent = Agent(client_id=client.id, name=body.agent.name, config=body.agent.config.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(client)
    return _client_payload(db, client)


@app.get("/api/clients/{client_id}")
def get_client(client_id: str, db: Session = Depends(get_session)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    return _client_payload(db, client)


@app.put("/api/clients/{client_id}")
def update_client(client_id: str, body: ClientIn, db: Session = Depends(get_session)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    for k, v in body.model_dump().items():
        setattr(client, k, v)
    db.add(client)
    db.commit()
    return _client_payload(db, client)


@app.delete("/api/clients/{client_id}", status_code=204)
def delete_client(client_id: str, db: Session = Depends(get_session)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    agent_ids = db.exec(select(Agent.id).where(Agent.client_id == client_id)).all()
    if agent_ids:
        db.exec(delete(CallSession).where(CallSession.agent_id.in_(agent_ids)))
        db.exec(delete(Agent).where(Agent.id.in_(agent_ids)))
    db.delete(client)
    db.commit()


@app.post("/api/clients/{client_id}/agents", status_code=201)
def add_agent(client_id: str, body: AgentIn, db: Session = Depends(get_session)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "Client not found")
    agent = Agent(client_id=client_id, name=body.name, config=body.config.model_dump())
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: str, db: Session = Depends(get_session)):
    return _agent_out(_agent_or_404(db, agent_id))


@app.put("/api/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentIn, db: Session = Depends(get_session)):
    agent = _agent_or_404(db, agent_id)
    agent.name = body.name
    agent.config = body.config.model_dump()
    agent.version += 1
    agent.updated_at = datetime.now(UTC)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@app.put("/api/agents/{agent_id}/inbound")
def set_inbound_agent(agent_id: str, db: Session = Depends(get_session)):
    """The agent that answers calls to your phone number."""
    _agent_or_404(db, agent_id)
    row = db.get(Setting, "inbound_agent_id") or Setting(key="inbound_agent_id")
    row.value = agent_id
    db.add(row)
    db.commit()
    return {"inbound_agent_id": agent_id}


# ---------------------------------------------------------------- text chat test (cheap)


@app.post("/api/agents/{agent_id}/chat")
async def chat(agent_id: str, body: ChatIn, db: Session = Depends(get_session)):
    """Test the agent in text: same prompt and tools as a call, no audio (~Rs 0.01-0.05 per turn)."""
    if not config.SARVAM_API_KEY:
        raise HTTPException(400, "SARVAM_API_KEY is not set in .env")
    agent = _agent_or_404(db, agent_id)
    cfg = AgentConfig.model_validate(agent.config)
    history = [m for m in body.messages[-20:] if m.get("role") in ("user", "assistant")]
    messages: list[dict] = [
        {"role": "system", "content": cfg.system_prompt()},
        {"role": "assistant", "content": cfg.greeting},
        *history,
    ]
    tools = openai_tools(cfg)
    tools_by_name = {t.name: t for t in cfg.tools}
    tool_log: list[dict] = []
    cost = 0.0
    ended = False
    reply = ""
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(4):  # at most 3 tool rounds, then a final answer
            data = await _sarvam_chat(client, messages, cfg.temperature, tools)
            usage = data.get("usage") or {}
            cost += (usage.get("prompt_tokens", 0) / 1e6 * config.PRICE_LLM_INPUT_PER_1M
                     + usage.get("completion_tokens", 0) / 1e6 * config.PRICE_LLM_OUTPUT_PER_1M)
            message = data["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if not calls:
                reply = message.get("content") or ""
                break
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "end_call":
                    ended = True
                    result = {"status": "ending call"}
                elif name in tools_by_name:
                    result = await run_http_tool(tools_by_name[name], args)
                else:
                    result = {"error": f"Unknown tool {name}"}
                tool_log.append({"name": name, "arguments": args, "result": result})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
            if ended:
                reply = cfg.goodbye_message
                break

    return {
        "reply": reply,
        "tool_calls": tool_log,
        "ended": ended,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "cost_inr": round(cost, 4),
    }


async def _sarvam_chat(client: httpx.AsyncClient, messages: list[dict], temperature: float, tools: list[dict]) -> dict:
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 300,
        "reasoning_effort": None,
    }
    if tools:
        payload["tools"] = tools
    for attempt in range(2):  # one retry for transient overload / rate limit
        resp = await client.post(
            "https://api.sarvam.ai/v2/chat/completions",
            headers={
                "api-subscription-key": config.SARVAM_API_KEY,
                "Authorization": f"Bearer {config.SARVAM_API_KEY}",
            },
            json=payload,
        )
        if resp.status_code in (429, 503) and attempt == 0:
            await asyncio.sleep(1.0)
            continue
        break
    if resp.status_code == 402:
        raise HTTPException(402, "Sarvam credits exhausted")
    if resp.status_code >= 300:
        raise HTTPException(502, f"Sarvam error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


@app.post("/api/translate")
async def translate(body: TranslateIn):
    """Translate an agent's fixed phrases (greeting, goodbye...) into its language (~Rs 0.01)."""
    if body.language not in LANGUAGES:
        raise HTTPException(422, f"Unsupported language {body.language}")
    if not config.SARVAM_API_KEY:
        raise HTTPException(400, "SARVAM_API_KEY is not set in .env")
    texts = {k: v for k, v in body.texts.items() if v.strip()}
    if not texts or body.language == "en-IN":
        return {"texts": body.texts}
    name, script = LANGUAGES[body.language], SCRIPTS[body.language]
    messages = [
        {
            "role": "system",
            "content": (
                f"You translate short phrases that a voice agent speaks on phone calls into {name} ({script}). "
                f"Use natural, polite, spoken {name}, the way a friendly call-centre agent talks. "
                "Keep person names, brand names and numbers unchanged. "
                "Reply with only a JSON object that has exactly the same keys as the input."
            ),
        },
        {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        data = await _sarvam_chat(client, messages, temperature=0.2, tools=[])
    content = (data["choices"][0]["message"].get("content") or "").strip()
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        translated = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(502, f"Could not parse translation: {content[:200]}")
    return {"texts": {k: str(translated.get(k) or v) for k, v in body.texts.items()}}


# ---------------------------------------------------------------- browser calls (WebRTC)


@app.post("/api/agents/{agent_id}/offer")
async def webrtc_offer(agent_id: str, request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
    if not config.SARVAM_API_KEY:
        raise HTTPException(400, "SARVAM_API_KEY is not set in .env")
    with Session(engine) as db:
        agent = _agent_or_404(db, agent_id)

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


@app.patch("/api/agents/{agent_id}/offer")
async def webrtc_ice(agent_id: str, request: SmallWebRTCPatchRequest):
    await webrtc_handler.handle_patch_request(request)
    return {"status": "success"}


# ---------------------------------------------------------------- phone calls


@app.post("/api/agents/{agent_id}/phone-call")
async def phone_call(agent_id: str, body: PhoneCallIn, db: Session = Depends(get_session)):
    agent = _agent_or_404(db, agent_id)
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


@app.post("/telephony/twilio/incoming")
async def twilio_incoming():
    """Set this as your Twilio number's Voice webhook (HTTP POST) for inbound calls."""
    agent_id = _get_setting("inbound_agent_id")
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
    agent_id = agent_id or _get_setting("inbound_agent_id")

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


@app.websocket("/ws/telephony/{agent_id}")
async def telephony_ws_for_agent(websocket: WebSocket, agent_id: str):
    await _run_telephony(websocket, agent_id)


@app.websocket("/ws/telephony")
async def telephony_ws(websocket: WebSocket):
    """Exotel Voicebot applet URL: outbound calls are matched by number, inbound use the inbound agent."""
    await _run_telephony(websocket, None)


# ---------------------------------------------------------------- demo tool (for trying tools in the UI)


@app.post("/api/demo/order-status")
async def demo_order_status(body: dict):
    """Fake order lookup. Use http://localhost:7860/api/demo/order-status as a tool URL."""
    order_id = str(body.get("order_id", "")).strip()
    if not order_id:
        return {"error": "order_id is required"}
    statuses = ["processing", "packed", "out for delivery", "delivered"]
    status = statuses[sum(map(ord, order_id)) % len(statuses)]
    eta = "already delivered" if status == "delivered" else "today by 6 PM"
    return {"order_id": order_id, "status": status, "eta": eta}


# ---------------------------------------------------------------- call history


@app.get("/api/calls")
def list_calls(agent_id: str | None = None, limit: int = 50, db: Session = Depends(get_session)):
    query = select(CallSession).order_by(CallSession.started_at.desc()).limit(min(limit, 200))
    if agent_id:
        query = query.where(CallSession.agent_id == agent_id)
    return db.exec(query).all()


@app.get("/api/calls/{call_id}")
def get_call(call_id: str, db: Session = Depends(get_session)):
    call = db.get(CallSession, call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    return call


@app.exception_handler(ValidationError)
async def validation_error(_: Request, exc: ValidationError):
    return Response(status_code=422, content=exc.json(), media_type="application/json")


# ---------------------------------------------------------------- frontend (production build)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        file = FRONTEND_DIST / path
        if path and file.is_file() and Path(file).resolve().is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
