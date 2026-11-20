"""The voice agent runtime: one Pipecat pipeline per call, built from an agent's config.

STT -> LLM -> TTS, each from the provider the agent picked (Sarvam, Navana or Gnani;
see app/providers/). Sarvam speech recognition can let its server-side VAD drive turns
("robust"); every other setup uses local Silero VAD ("fast").
"""

import asyncio
from datetime import UTC, datetime

import numpy as np

from loguru import logger
from sqlmodel import Session

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    EndFrame,
    EndWorkerFrame,
    Frame,
    FunctionCallResultProperties,
    InputAudioRawFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import (
    MuteUntilFirstBotCompleteUserMuteStrategy,
)
from pipecat.workers.runner import WorkerRunner

from app.core import config
from app.agents.models import AgentConfig, HttpTool
from app.voice.call_metrics import CallMetricsObserver
from app.core.db import Agent, CallSession, engine
from app.core.errors import public_error
from app.agents.tools import END_CALL_DESCRIPTION, run_http_tool
from app.providers import catalog, factory

def _tool_schema(tool: HttpTool) -> FunctionSchema:
    return FunctionSchema(
        name=tool.name,
        description=tool.description,
        properties=tool.parameters,
        required=tool.required,
    )


def _http_tool_handler(tool: HttpTool):
    async def handler(params: FunctionCallParams):
        await params.result_callback(await run_http_tool(tool, dict(params.arguments or {})))

    return handler


# Words that show the caller is closing the call: English, romanised and native-script Indic.
# Matched anywhere in the caller's last message.
_CLOSING_PHRASES = (
    "bye", "thank", "that's all", "that is all", "thats all", "nothing else", "no more", "hang up",
    "end the call", "cut the call", "disconnect", "talk later", "call later", "call you later",
    "not interested", "dhanyavad", "dhanyawad", "shukriya", "alvida", "nandri", "dhanyavadalu",
    "dhanyavaada", "nanni", "abhar",
    "धन्यवाद", "शुक्रिया", "अलविदा", "बाय", "आभार", "நன்றி", "ధన్యవాదాలు", "ಧನ್ಯವಾದ", "നന്ദി",
    "ধন্যবাদ", "ધન્યવાદ", "આભાર", "ਧੰਨਵਾਦ",
)
# A short "no" (answering "anything else?") also counts.
_SHORT_NO = {
    "no", "nope", "nah", "nahi", "nahin", "illa", "illai", "ledu", "nako", "bas", "venda", "beda",
    "नहीं", "नही", "बस", "இல்லை", "வேண்டாம்", "లేదు", "వద్దు", "ಇಲ್ಲ", "ಬೇಡ", "ഇല്ല", "വേണ്ട",
    "नाही", "नको", "না", "ના", "ਨਹੀਂ",
}


def caller_is_closing(text: str) -> bool:
    """True if the caller's words look like a goodbye or a "no, nothing else"."""
    lowered = text.lower()
    if any(p in lowered for p in _CLOSING_PHRASES):
        return True
    words = [w.strip(".,!?।|'\"") for w in lowered.split()]
    return 0 < len(words) <= 3 and any(w in _SHORT_NO for w in words)


def _last_text(messages: list, role: str) -> str | None:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == role and isinstance(m.get("content"), str) and m["content"].strip():
            return m["content"].strip()
    return None


def premature_end_call(messages: list) -> bool:
    """The agent asked a question and the caller answered it without saying goodbye.

    Hanging up there is almost always a model mistake (seen on a real call: the caller answered
    "what will you use it for?" and the agent hung up).
    """
    user = _last_text(messages, "user")
    if user is None or caller_is_closing(user):
        return False
    # The agent's last spoken line before the caller's reply.
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, dict) and m.get("role") == "user":
            agent_line = _last_text(messages[:i], "assistant")
            return bool(agent_line and agent_line.rstrip().endswith("?"))
    return False


class CallerSpeechGate(FrameProcessor):
    """Passes all frames through and notes when the caller first speaks and then pauses.

    Phone calls greet after the caller's "Hello?", because audio sent the moment the line opens
    can be lost before the caller's phone starts playing it.
    """

    def __init__(self, threshold: int = 500):
        super().__init__()
        self.done = asyncio.Event()
        self._threshold = threshold
        self._voiced = 0.0
        self._quiet = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if not self.done.is_set() and isinstance(frame, InputAudioRawFrame) and frame.audio:
            pcm = np.frombuffer(frame.audio, dtype=np.int16)
            secs = len(pcm) / max(frame.sample_rate, 1)
            if np.sqrt(np.mean(pcm.astype(np.float32) ** 2)) > self._threshold:
                self._voiced += secs
                self._quiet = 0.0
            elif self._voiced >= 0.2:
                self._quiet += secs
                if self._quiet >= 0.4:
                    self.done.set()
        await self.push_frame(frame, direction)


async def run_agent_call(
    *,
    transport: BaseTransport,
    agent: Agent,
    channel: str,
    in_sample_rate: int,
    out_sample_rate: int,
    direction: str = "inbound",
    phone_number: str = "",
    provider_call_id: str = "",
    call_session_id: str | None = None,
) -> str:
    """Run one call to completion and persist its transcript, latency and cost."""
    cfg = AgentConfig.model_validate(agent.config)
    browser = channel == "browser"

    with Session(engine) as db:
        call = db.get(CallSession, call_session_id) if call_session_id else None
        if call is None:
            call = CallSession(agent_id=agent.id, agent_version=agent.version, channel=channel)
        call.direction = direction
        call.phone_number = phone_number or call.phone_number
        call.provider_call_id = provider_call_id or call.provider_call_id
        call.providers = {"stt": cfg.stt_provider, "llm": cfg.llm_provider, "tts": cfg.tts_provider}
        call.status = "active"
        db.add(call)
        db.commit()
        db.refresh(call)
        call_id = call.id

    worker: PipelineWorker | None = None

    async def send_to_client(payload: dict):
        if browser and worker is not None:
            await worker.queue_frame(RTVIServerMessageFrame(data=payload))

    pricing = catalog.call_pricing(cfg.stt_provider, cfg.tts_provider, cfg.llm_provider)
    metrics = CallMetricsObserver(send=send_to_client, pause_ms=factory.pause_ms(cfg), channel=channel, pricing=pricing)

    stt, turn_params = factory.make_stt(cfg, in_sample_rate)
    tts = factory.make_tts(cfg, out_sample_rate)
    llm = factory.make_llm(cfg)

    functions: list[FunctionSchema] = []
    end_refused_at = -1
    if cfg.end_call_enabled:
        functions.append(
            FunctionSchema(
                name="end_call",
                description=END_CALL_DESCRIPTION,
                properties={},
                required=[],
            )
        )

        async def end_call(params: FunctionCallParams):
            nonlocal end_refused_at
            messages = context.get_messages()
            user_turns = sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "user")
            # Block a premature hang-up once per caller turn; if the model insists, let it end.
            if end_refused_at != user_turns and premature_end_call(messages):
                end_refused_at = user_turns
                logger.warning(f"[{call_id}] Blocked end_call: the caller answered a question and didn't say goodbye")
                metrics.add_event("The agent tried to hang up, but the caller hadn't said goodbye, so the call continued.")
                await params.result_callback(
                    {
                        "status": "not ended",
                        "reason": "The caller has not said goodbye. Do not hang up. Reply to what they just said.",
                    }
                )
                return
            metrics.end_reason = "Call ended by the agent (end_call tool)."
            await params.result_callback(
                {"status": "ending call"}, properties=FunctionCallResultProperties(run_llm=False)
            )
            await params.llm.push_frame(TTSSpeakFrame(cfg.goodbye_message))
            await params.llm.push_frame(EndWorkerFrame(reason="end_call tool"))

        llm.register_function("end_call", end_call)

    for tool in cfg.tools:
        functions.append(_tool_schema(tool))
        llm.register_function(tool.name, _http_tool_handler(tool))

    messages = [
        {"role": "system", "content": cfg.system_prompt()},
        {"role": "assistant", "content": cfg.greeting},
    ]
    context = LLMContext(messages, tools=ToolsSchema(standard_tools=functions) if functions else None)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            **turn_params,
            user_idle_timeout=cfg.idle_timeout_secs,
            user_turn_stop_timeout=3.0,
            # Phone: the caller's opening "Hello?" only triggers the greeting, not an extra reply.
            user_mute_strategies=[] if browser else [MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )
    speech_gate = None if browser else CallerSpeechGate()

    pipeline = Pipeline(
        [
            transport.input(),
            *([speech_gate] if speech_gate else []),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=in_sample_rate,
            audio_out_sample_rate=out_sample_rate,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[metrics],
        enable_rtvi=browser,
        idle_timeout_secs=max(60, cfg.idle_timeout_secs * 4),
    )

    call_error = ""
    ending = False

    @worker.event_handler("on_pipeline_error")
    async def on_pipeline_error(worker, frame):
        """End the call on errors that retrying can't fix (bad key, no credits)."""
        nonlocal call_error, ending
        text = str(getattr(frame, "error", frame))
        lowered = text.lower()
        speech_service = isinstance(getattr(frame, "processor", None), (TTSService, STTService))
        unrecoverable = (
            getattr(frame, "fatal", False)
            or any(k in lowered for k in ("invalid_subscription_key", "insufficient", "quota", "402", "401", "403"))
            # Config the API rejects, or a socket that keeps dropping: retrying won't fix it,
            # and without TTS/STT the caller would only hear silence.
            or (speech_service and any(k in lowered for k in ("validation error", "connection failed", "no longer")))
        )
        if ending:
            return
        if not unrecoverable:
            # e.g. a transient LLM 503: say so instead of leaving the caller in silence.
            if isinstance(getattr(frame, "processor", None), LLMService):
                logger.warning(f"[{call_id}] LLM error, asking caller to repeat: {text[:200]}")
                await worker.queue_frames([TTSSpeakFrame(cfg.repeat_message)])
            return
        ending = True
        call_error = public_error(text)[:500]  # shown in call logs; the log line below keeps the raw text
        metrics.end_reason = metrics.end_reason or "Call ended: unrecoverable error (see error)."
        logger.error(f"[{call_id}] Unrecoverable error, ending call: {text[:300]}")
        await send_to_client({"type": "error", "message": public_error(text)[:300]})
        await worker.cancel()

    idle_count = 0
    greet_task: asyncio.Task | None = None

    @user_aggregator.event_handler("on_user_turn_idle")
    async def on_user_turn_idle(aggregator):
        nonlocal idle_count
        idle_count += 1
        if idle_count == 1:
            await worker.queue_frames([TTSSpeakFrame(cfg.nudge_message)])
        else:
            logger.info("Caller silent after a nudge; ending call")
            metrics.end_reason = metrics.end_reason or "Call ended: the caller stayed silent after the nudge."
            await worker.queue_frames([TTSSpeakFrame(cfg.goodbye_message), EndFrame()])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"[{call_id}] {channel} client connected (agent {agent.id})")
        metrics.mark_connected()
        await send_to_client({"type": "session", "call_id": call_id})
        if speech_gate is None:
            await worker.queue_frames([TTSSpeakFrame(cfg.greeting)])
            return
        nonlocal greet_task
        wait = config.GREETING_WAIT_OUTBOUND_SECS if direction == "outbound" else config.GREETING_WAIT_INBOUND_SECS

        async def greet_when_ready():
            try:
                await asyncio.wait_for(speech_gate.done.wait(), wait)
                logger.info(f"[{call_id}] Caller spoke first; greeting now")
            except TimeoutError:
                logger.info(f"[{call_id}] No caller speech in {wait}s; greeting now")
            await worker.queue_frames([TTSSpeakFrame(cfg.greeting)])

        greet_task = asyncio.create_task(greet_when_ready())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"[{call_id}] client disconnected")
        metrics.end_reason = metrics.end_reason or "Call ended: the caller hung up."
        await worker.cancel()

    async def guard():
        """Hard caps so a stuck call can never drain the credits."""
        limit = min(cfg.max_call_seconds, config.MAX_CALL_SECONDS_CAP)
        loop = asyncio.get_running_loop()
        started = loop.time()
        while True:
            await asyncio.sleep(1)
            elapsed = loop.time() - started
            if elapsed >= limit:
                reason = f"max call length {limit}s reached"
            # The cap protects voice AI credits; phone-line time is bounded by `limit` above.
            elif metrics.ai_cost_inr() >= config.MAX_COST_PER_CALL_INR:
                reason = f"cost cap Rs {config.MAX_COST_PER_CALL_INR} reached"
            else:
                continue
            logger.warning(f"[{call_id}] Ending call: {reason}")
            metrics.end_reason = metrics.end_reason or f"Call ended: {reason}."
            await worker.queue_frames([TTSSpeakFrame(cfg.goodbye_message), EndFrame()])
            await asyncio.sleep(10)
            await worker.cancel()
            return

    guard_task = asyncio.create_task(guard())
    try:
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        await runner.run()
    except Exception as e:
        logger.exception(f"[{call_id}] call failed")
        call_error = call_error or public_error(str(e))
    finally:
        guard_task.cancel()
        if greet_task:
            greet_task.cancel()
        metrics.finish()
        _save_call(call_id, metrics, call_error, cfg)
    return call_id


def _save_call(call_id: str, metrics: CallMetricsObserver, error: str, cfg: AgentConfig) -> None:
    summary = metrics.latency_summary()
    usage = metrics.usage()
    with Session(engine) as db:
        call = db.get(CallSession, call_id)
        if call is None:
            return
        call.ended_at = datetime.now(UTC)
        started = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=UTC)
        call.duration_secs = round((call.ended_at - started).total_seconds(), 1)
        call.status = "failed" if error else "completed"
        call.error = error[:500]
        call.turns = summary["turns"]
        call.latency_avg_ms = summary["avg_ms"]
        call.latency_p50_ms = summary["p50_ms"]
        call.latency_p95_ms = summary["p95_ms"]
        call.latency_max_ms = summary["max_ms"]
        call.stt_seconds = usage["stt_seconds"]
        call.tts_chars = usage["tts_chars"]
        call.llm_prompt_tokens = usage["llm_prompt_tokens"]
        call.llm_cached_tokens = usage["llm_cached_tokens"]
        call.llm_completion_tokens = usage["llm_completion_tokens"]
        call.cost_inr = usage["cost_inr"]
        call.cost_breakdown = usage["cost_breakdown"]
        call.providers = {"stt": cfg.stt_provider, "llm": cfg.llm_provider, "tts": cfg.tts_provider}
        call.transcript = metrics.transcript
        call.latency_turns = metrics.turns
        db.add(call)
        db.commit()
    logger.info(f"[{call_id}] saved: {summary} cost Rs {usage['cost_inr']}")
