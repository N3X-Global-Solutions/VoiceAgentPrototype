"""Gnani (Vachana) speech recognition and voice, as Pipecat services. Its AI model (Evon) is
OpenAI-compatible and runs on Pipecat's OpenAI service (see factory.py).

Protocol: docs.gnani.ai (STT WebSocket, TTS inference).
- STT: wss://api.vachana.ai/stt/v3/stream. All settings are upgrade headers. Audio is raw
  16-bit mono PCM in frames of exactly 1,024 bytes at real-time pace. Only final
  transcripts (one per utterance); {"type": "commit"} closes the utterance at once, which
  we send when local VAD decides the caller stopped.
- TTS: POST https://api.vachana.ai/api/v1/tts/inference returns raw audio bytes.
"""

import json
from collections.abc import AsyncGenerator

import httpx
from loguru import logger
from websockets.protocol import State

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    StartFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import WebsocketSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from app.core import config
from app.providers.catalog import GNANI_TTS_V3, find_voice
from app.providers.navana import _pcm_chunks, rejection_text

STT_URL = "wss://api.vachana.ai/stt/v3/stream"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"
LLM_BASE_URL = "https://api.vachana.ai/v1"
STT_MODEL = "prisma-v3.0"
FRAME_BYTES = 1024  # Gnani's required frame size (512 samples)


class GnaniSTTService(WebsocketSTTService):
    def __init__(
        self,
        *,
        language: str,
        auto_detect: bool,
        sample_rate: int,
        keyterms: list[str] | None = None,
        **kwargs,
    ):
        kwargs.setdefault("ttfs_p99_latency", 0.7)  # commit -> transcript
        super().__init__(
            sample_rate=sample_rate,
            settings=STTSettings(model=STT_MODEL, language="indic-auto" if auto_detect else language),
            **kwargs,
        )
        self._keyterms = keyterms or []
        self._buffer = bytearray()
        self._ready = False
        self._receive_task = None

    def can_generate_metrics(self) -> bool:
        return True

    def _upgrade_headers(self) -> dict[str, str]:
        phone = self.sample_rate == 8000
        headers = {
            "x-api-key-id": config.GNANI_API_KEY,
            "model": STT_MODEL,
            "language_code": str(self._settings.language),
            "x-sample-rate": str(self.sample_rate),
            "format": "transcribe",
            # Our VAD commits each turn; Gnani's own pause only splits very long pauses.
            "x-min-silence-ms": "800",
            "x-min-speech-ms": "200" if phone else "100",
        }
        if self._keyterms:
            headers["keyterms"] = json.dumps(self._keyterms)  # ASCII-escaped, as headers require
        return headers

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await self._send_json({"type": "commit"})
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            await self._flush_buffer(pad=True)
            await self._send_json({"type": "commit"})

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if self._ready:
            self._buffer.extend(audio)
            await self._flush_buffer()
        yield None

    async def _flush_buffer(self, pad: bool = False):
        """Send whole 1,024-byte frames; with pad, zero-fill the remainder so it isn't held back."""
        if not (self._ready and self._websocket and self._websocket.state is State.OPEN):
            return
        if pad and self._buffer:
            self._buffer.extend(b"\x00" * (-len(self._buffer) % FRAME_BYTES))
        try:
            while len(self._buffer) >= FRAME_BYTES:
                await self._websocket.send(bytes(self._buffer[:FRAME_BYTES]))
                del self._buffer[:FRAME_BYTES]
        except Exception as e:
            logger.warning(f"{self}: send failed: {e}")

    async def _send_json(self, payload: dict):
        if self._websocket and self._websocket.state is State.OPEN:
            try:
                await self._websocket.send(json.dumps(payload))
            except Exception as e:
                logger.warning(f"{self}: could not send {payload}: {e}")

    async def _connect(self):
        await self._connect_websocket()
        await super()._connect()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        await super()._disconnect()
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    async def _connect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return
            self._ready = False
            self._buffer.clear()
            self._websocket = await self._websocket_connect(STT_URL, additional_headers=self._upgrade_headers())
            await self._call_event_handler("on_connected")
        except Exception as e:
            self._websocket = None
            await self.push_error(error_msg=f"Speech recognition connection failed: {rejection_text(e)}", exception=e)

    async def _disconnect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                await self._websocket.close()
        except Exception as e:
            logger.debug(f"{self}: error closing websocket: {e}")
        finally:
            self._websocket = None
            self._ready = False
            await self._call_event_handler("on_disconnected")

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Websocket not connected")

    async def _receive_messages(self):
        async for message in self._get_websocket():
            if isinstance(message, bytes):
                continue
            try:
                content = json.loads(message)
            except json.JSONDecodeError:
                continue
            kind = content.get("type")
            if kind == "connected":
                self._ready = True
            elif kind == "transcript":
                text = (content.get("text") or "").strip()
                if text:
                    await self.emit_stt_usage_metrics()
                    await self.push_frame(
                        TranscriptionFrame(text, self._user_id, time_now_iso8601(), None, result=content, finalized=True)
                    )
            elif kind == "error":
                await self.push_error(error_msg=f"Speech recognition error: {content.get('message', content)}")


def _speed(model: str, pace: float) -> float:
    if model == GNANI_TTS_V3:  # v3.0 takes only 0.8, 1.0 or 1.2
        return min((0.8, 1.0, 1.2), key=lambda s: abs(s - pace))
    return round(max(0.85, min(1.15, pace)), 2)


class GnaniTTSService(TTSService):
    """Timbre TTS over HTTP, one request per sentence, audio streamed as it downloads."""

    def __init__(self, *, voice: str, language: str, auto_detect: bool, pace: float, sample_rate: int, **kwargs):
        entry = find_voice("gnani", voice)
        if entry is None:
            raise ValueError(f"Unknown voice {voice!r}")
        super().__init__(
            sample_rate=sample_rate,
            push_stop_frames=True,
            push_start_frame=True,
            settings=TTSSettings(model=entry["model"], voice=entry["name"], language=language),
            **kwargs,
        )
        if entry.get("hinglish"):
            self._language = "hi-en"
        elif auto_detect and entry["model"] == GNANI_TTS_V3:
            self._language = "auto"
        else:
            self._language = language
        self._speed = _speed(entry["model"], pace)
        self._client: httpx.AsyncClient | None = None

    def can_generate_metrics(self) -> bool:
        return True

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._close()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._close()

    async def _close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
        payload = {
            "text": text,
            "voice": self._settings.voice,
            "model": self._settings.model,
            "language": self._language,
            "speed": self._speed,
            "audio_config": {
                "sample_rate": self.sample_rate,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "pcm_s16le",
                "container": "raw",
            },
        }
        headers = {"X-API-Key-ID": config.GNANI_API_KEY, "Content-Type": "application/json"}
        feed = _pcm_chunks()
        try:
            async with self._client.stream("POST", TTS_URL, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")[:300]
                    yield ErrorFrame(error=f"Voice provider error {resp.status_code}: {body}")
                    return
                await self.start_tts_usage_metrics(text)
                async for chunk in resp.aiter_bytes(4096):
                    pcm = feed(chunk)
                    if pcm:
                        yield TTSAudioRawFrame(audio=pcm, sample_rate=self.sample_rate, num_channels=1, context_id=context_id)
        except Exception as e:
            yield ErrorFrame(error=f"Voice generation failed: {e}", exception=e)
