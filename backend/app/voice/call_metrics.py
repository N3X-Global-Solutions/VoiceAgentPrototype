"""Per-call latency + usage metering.

Latency per turn = time from the user's end of speech, as decided by Sarvam's
server-side VAD (ProposedUserStoppedSpeakingFrame), to the moment our transport
starts sending agent audio. It includes final transcription, LLM and TTS time. It
does not include the VAD silence window before Sarvam declares end of speech, nor
the network/telephony leg back to the caller.
"""

import statistics
import time
from collections.abc import Awaitable, Callable

from loguru import logger

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    LLMTextFrame,
    MetricsFrame,
    ProposedUserStartedSpeakingFrame,
    ProposedUserStoppedSpeakingFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import (
    LLMUsageMetricsData,
    STTUsageMetricsData,
    TTFBMetricsData,
    TTSUsageMetricsData,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from app.core import config

ServerMessageSender = Callable[[dict], Awaitable[None]]


def _service_kind(processor: str) -> str | None:
    name = processor.lower()
    for kind in ("stt", "llm", "tts"):
        if kind in name:
            return kind
    return None


class CallMetricsObserver(BaseObserver):
    def __init__(self, send: ServerMessageSender | None = None, pause_ms: int | None = None):
        super().__init__(observe_every_push=False)
        self._send = send
        # Configured silence the caller must leave before their turn ends (None = unknown
        # provider default). Shown next to each turn: it is waited before the clock starts.
        self._pause_ms = pause_ms
        self.started_at = time.time()

        # Usage
        self.stt_seconds = 0.0
        self.tts_chars = 0
        self.llm_prompt_tokens = 0
        self.llm_cached_tokens = 0
        self.llm_completion_tokens = 0

        # Transcript
        self.transcript: list[dict] = []
        self._bot_text: list[str] = []
        self.end_reason: str | None = None  # saved as the last transcript line

        # Latency
        self.turns: list[dict] = []
        self._pending: dict | None = None
        self._connected_at: float | None = None
        self.greeting_ms: int | None = None

    # -- cost -------------------------------------------------------------

    def cost_inr(self) -> float:
        uncached = max(self.llm_prompt_tokens - self.llm_cached_tokens, 0)
        return round(
            self.stt_seconds / 60 * config.PRICE_STT_PER_MIN
            + self.tts_chars / 1000 * config.PRICE_TTS_PER_1K_CHARS
            + uncached / 1e6 * config.PRICE_LLM_INPUT_PER_1M
            + self.llm_cached_tokens / 1e6 * config.PRICE_LLM_CACHED_PER_1M
            + self.llm_completion_tokens / 1e6 * config.PRICE_LLM_OUTPUT_PER_1M,
            4,
        )

    def usage(self) -> dict:
        return {
            "stt_seconds": round(self.stt_seconds, 2),
            "tts_chars": self.tts_chars,
            "llm_prompt_tokens": self.llm_prompt_tokens,
            "llm_cached_tokens": self.llm_cached_tokens,
            "llm_completion_tokens": self.llm_completion_tokens,
            "cost_inr": self.cost_inr(),
        }

    def latency_summary(self) -> dict:
        totals = [t["total_ms"] for t in self.turns]
        if not totals:
            return {"turns": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
        ordered = sorted(totals)
        p95_index = max(0, round(0.95 * (len(ordered) - 1)))
        return {
            "turns": len(totals),
            "avg_ms": round(statistics.fmean(totals)),
            "p50_ms": round(statistics.median(totals)),
            "p95_ms": round(ordered[p95_index]),
            "max_ms": round(ordered[-1]),
        }

    # -- frames -----------------------------------------------------------

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        now = time.time()

        if isinstance(
            frame, (ProposedUserStartedSpeakingFrame, VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)
        ):
            self._pending = None
        elif isinstance(frame, (ProposedUserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)):
            # Sarvam's VAD (sarvam mode) or local Silero (fast mode) decided the turn ended.
            self._pending = {"user_stopped_at": now, "ttfb": {}}
        elif isinstance(frame, UserStoppedSpeakingFrame):
            # Fallback anchor when the STT does not propose turn boundaries.
            if self._pending is None:
                self._pending = {"user_stopped_at": now, "ttfb": {}}
        elif isinstance(frame, TranscriptionFrame):
            self._flush_bot_text()
            self.transcript.append({"role": "user", "text": frame.text, "at": now})
            if self._pending is not None:
                self._pending.setdefault("transcript_ms", (now - self._pending["user_stopped_at"]) * 1000)
        elif isinstance(frame, LLMTextFrame):
            if self._pending is not None:
                self._pending.setdefault("llm_first_text_ms", (now - self._pending["user_stopped_at"]) * 1000)
        elif isinstance(frame, TTSTextFrame):
            self._bot_text.append(frame.text)
        elif isinstance(frame, TTSAudioRawFrame):
            if self._pending is not None:
                self._pending.setdefault("tts_first_audio_ms", (now - self._pending["user_stopped_at"]) * 1000)
        elif isinstance(frame, BotStartedSpeakingFrame):
            await self._close_turn(now)
        elif isinstance(frame, MetricsFrame):
            await self._on_metrics(frame)

    async def _on_metrics(self, frame: MetricsFrame):
        changed = False
        for item in frame.data:
            if isinstance(item, TTFBMetricsData) and self._pending is not None and item.value:
                kind = _service_kind(item.processor)
                if kind:
                    self._pending["ttfb"][kind] = round(item.value * 1000)
            elif isinstance(item, LLMUsageMetricsData):
                usage = item.value
                self.llm_prompt_tokens += usage.prompt_tokens or 0
                self.llm_cached_tokens += usage.cache_read_input_tokens or 0
                self.llm_completion_tokens += usage.completion_tokens or 0
                changed = True
            elif isinstance(item, TTSUsageMetricsData):
                self.tts_chars += item.value or 0
                changed = True
            elif isinstance(item, STTUsageMetricsData):
                self.stt_seconds += item.value.audio_seconds or 0
                changed = True
        if changed:
            await self._emit({"type": "usage", **self.usage()})

    def mark_connected(self) -> None:
        self._connected_at = time.time()

    async def _close_turn(self, now: float):
        if self.greeting_ms is None and self._connected_at is not None and not self.turns:
            self.greeting_ms = round((now - self._connected_at) * 1000)
            await self._emit({"type": "greeting_latency", "greeting_ms": self.greeting_ms})
        if self._pending is None:
            return
        turn = self._pending
        self._pending = None
        total_ms = (now - turn["user_stopped_at"]) * 1000
        record = {
            "turn": len(self.turns) + 1,
            "total_ms": round(total_ms),
            "transcript_ms": _round(turn.get("transcript_ms")),
            "llm_first_text_ms": _round(turn.get("llm_first_text_ms")),
            "tts_first_audio_ms": _round(turn.get("tts_first_audio_ms")),
            "ttfb_ms": turn["ttfb"],
            "pause_ms": self._pause_ms,
        }
        self.turns.append(record)
        logger.info(f"Turn latency: {record}")
        await self._emit({"type": "latency", **record, "summary": self.latency_summary()})

    def _flush_bot_text(self):
        if self._bot_text:
            text = " ".join(t.strip() for t in self._bot_text if t.strip())
            if text:
                self.transcript.append({"role": "agent", "text": text, "at": time.time()})
            self._bot_text = []

    def add_event(self, text: str) -> None:
        """A note in the transcript (not speech), e.g. why the call ended."""
        self._flush_bot_text()
        self.transcript.append({"role": "event", "text": text, "at": time.time()})

    def finish(self) -> None:
        self._flush_bot_text()
        if self.end_reason:
            self.transcript.append({"role": "event", "text": self.end_reason, "at": time.time()})

    async def _emit(self, payload: dict):
        if self._send:
            try:
                await self._send(payload)
            except Exception as e:  # never let UI updates break the call
                logger.debug(f"Could not send metrics to client: {e}")


def _round(value: float | None) -> int | None:
    return None if value is None else round(value)
