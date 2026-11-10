"""The voice agent runtime: one Pipecat pipeline per call, built from an agent's config.

Sarvam realtime STT (saaras:v4) -> sarvam-105b-conversations -> Bulbul v4 Flash TTS,
tuned per Sarvam's Pipecat production guide: Sarvam's server-side VAD drives turns
(no Silero), External turn strategies, small TTS buffer, reasoning off.
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
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.transports.base_transport import BaseTransport
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.turns.user_start import ExternalUserTurnStartStrategy, VADUserTurnStartStrategy
from pipecat.turns.user_stop import ExternalUserTurnStopStrategy, SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_mute.mute_until_first_bot_complete_user_mute_strategy import (
    MuteUntilFirstBotCompleteUserMuteStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from app import config
from app.agent_config import AgentConfig, HttpTool
from app.call_metrics import CallMetricsObserver
from app.db import Agent, CallSession, engine
from app.stt_preroll import PrerollSarvamRealtimeSTTService
from app.tools import END_CALL_DESCRIPTION, run_http_tool

LLM_MODEL = "sarvam-105b-conversations"
TTS_MODEL = "bulbul:v4-flash"
STT_MODEL = "saaras:v4"


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


FAST_DEFAULT_END_OF_SPEECH_MS = 300

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


def _speech_input(cfg: AgentConfig, sample_rate: int) -> tuple[SarvamRealtimeSTTService, dict]:
    """STT service plus the user-turn settings that match the agent's turn detection mode."""
    settings = SarvamRealtimeSTTService.Settings(
        model=STT_MODEL,
        language=None if cfg.auto_detect_language else cfg.language,
        mode="transcribe",
        stream_type="fast",
    )
    keyterms = cfg.important_words or None

    if cfg.turn_detection == "fast":
        # Local Silero VAD ends the turn after a short pause; the STT then flushes its
        # buffered audio and sends speech_end, so Sarvam finalizes without waiting for
        # its own server-side silence window. The pre-roll STT keeps the first words
        # that are spoken before VAD confirms speech.
        stop_secs = (cfg.end_of_speech_ms or FAST_DEFAULT_END_OF_SPEECH_MS) / 1000
        stt = PrerollSarvamRealtimeSTTService(
            api_key=config.SARVAM_API_KEY,
            sample_rate=sample_rate,
            keyterms=keyterms,
            ttfs_p99_latency=0.4,  # measured: realtime finals arrive ~150-260 ms after speech_end
            settings=settings,
        )
        return stt, {
            "vad_analyzer": SileroVADAnalyzer(params=VADParams(stop_secs=stop_secs)),
            "user_turn_strategies": UserTurnStrategies(
                start=[VADUserTurnStartStrategy()],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)],
            ),
        }

    if cfg.end_of_speech_ms:
        settings.silence_duration_ms = cfg.end_of_speech_ms
    stt = SarvamRealtimeSTTService(
        api_key=config.SARVAM_API_KEY,
        sample_rate=sample_rate,
        keyterms=keyterms,
        settings=settings,
    )
    return stt, {
        "user_turn_strategies": UserTurnStrategies(
            start=[ExternalUserTurnStartStrategy(enable_interruptions=True)],
            stop=[ExternalUserTurnStopStrategy(timeout=0.1, wait_for_transcript=True)],
        ),
    }


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
        call.status = "active"
        db.add(call)
        db.commit()
        db.refresh(call)
        call_id = call.id

    worker: PipelineWorker | None = None

    async def send_to_client(payload: dict):
        if browser and worker is not None:
            await worker.queue_frame(RTVIServerMessageFrame(data=payload))

    pause_ms = cfg.end_of_speech_ms or (FAST_DEFAULT_END_OF_SPEECH_MS if cfg.turn_detection == "fast" else None)
    metrics = CallMetricsObserver(send=send_to_client, pause_ms=pause_ms)

    stt, turn_params = _speech_input(cfg, in_sample_rate)
    tts = SarvamTTSService(
        api_key=config.SARVAM_API_KEY,
        sample_rate=out_sample_rate,
        settings=SarvamTTSService.Settings(
            model=TTS_MODEL,
            voice=cfg.voice,
            language=cfg.language,
            pace=cfg.pace,
            min_buffer_size=30,  # Sarvam's API minimum (its Pipecat guide's 15-25 is now rejected)
        ),
    )
    llm = SarvamLLMService(
        api_key=config.SARVAM_API_KEY,
        settings=SarvamLLMService.Settings(
            model=LLM_MODEL,
            temperature=cfg.temperature,
            reasoning_effort=None,  # thinking off: lower latency, no hidden token cost
            max_tokens=300,
        ),
    )

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
        speech_service = isinstance(
            getattr(frame, "processor", None), (SarvamTTSService, SarvamRealtimeSTTService)
        )
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
            if isinstance(getattr(frame, "processor", None), SarvamLLMService):
                logger.warning(f"[{call_id}] LLM error, asking caller to repeat: {text[:200]}")
                await worker.queue_frames([TTSSpeakFrame(cfg.repeat_message)])
            return
        ending = True
        call_error = text[:500]
        metrics.end_reason = metrics.end_reason or "Call ended: unrecoverable error (see error)."
        logger.error(f"[{call_id}] Unrecoverable error, ending call: {text[:300]}")
        await send_to_client({"type": "error", "message": text[:300]})
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
            elif metrics.cost_inr() >= config.MAX_COST_PER_CALL_INR:
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
        call_error = call_error or str(e)
    finally:
        guard_task.cancel()
        if greet_task:
            greet_task.cancel()
        metrics.finish()
        _save_call(call_id, metrics, call_error)
    return call_id


def _save_call(call_id: str, metrics: CallMetricsObserver, error: str) -> None:
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
        call.transcript = metrics.transcript
        call.latency_turns = metrics.turns
        db.add(call)
        db.commit()
    logger.info(f"[{call_id}] saved: {summary} cost Rs {usage['cost_inr']}")
