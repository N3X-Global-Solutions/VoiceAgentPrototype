"""Navana (Bodhi) speech recognition and voice, as Pipecat services.

Protocol: docs.navana.ai (API reference: transcribe-streaming, synthesize).
- STT: wss://stt.navana.ai, header X-Api-Key. One JSON config frame, then raw 16-bit
  mono PCM. Frames with the same segment_id replace each other; "complete" ends a segment
  (Navana's own endpointing, after >= 0.44 s of silence). {"eof": 1} flushes at the end.
  Billed per second connected, so the whole call is billed.
- TTS: POST https://tts.navana.ai/tts/bytes, header X-API-Key, returns headerless PCM.
  Billed per character of input text.
"""

import json
import uuid
from collections.abc import AsyncGenerator

import httpx
from loguru import logger
from websockets.protocol import State

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import WebsocketSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from app.core import config

# Navana's models are per language; the banking v2 family is the documented default.
_STT_MODELS = {
    "en-IN": "en-banking-v2-8khz",
    "hi-IN": "hi-banking-v2-8khz",
    "ta-IN": "ta-banking-v2-8khz",
    "te-IN": "te-banking-v2-8khz",
    "kn-IN": "kn-banking-v2-8khz",
    "mr-IN": "mr-banking-v2-8khz",
    "gu-IN": "gu-banking-v2-8khz",
    "bn-IN": "bn-banking-v2-8khz",
    "ml-IN": "ml-banking-v2-8khz",
    "or-IN": "or-general-v3-8khz",
}
# Following the caller's language: Hindi/English agents get the Hinglish model; the other
# Indic models already handle English mixed in.
_HINGLISH_MODEL = "hi-en-banking-v2-8khz"


def stt_model(language: str, auto_detect: bool) -> str:
    if auto_detect and language in ("hi-IN", "en-IN"):
        return _HINGLISH_MODEL
    return _STT_MODELS[language]


def rejection_text(e: Exception) -> str:
    """The provider's own reason when it refuses the WebSocket upgrade (e.g. 403 product_not_enabled)."""
    response = getattr(e, "response", None)
    if response is None:
        return str(e)
    body = bytes(getattr(response, "body", b"") or b"").decode(errors="replace")
    try:
        data = json.loads(body)
        detail = data.get("detail", data) if isinstance(data, dict) else data
        if isinstance(detail, dict):
            reason = detail.get("message") or detail.get("error") or detail.get("error_code")
            code = detail.get("error") or detail.get("error_code")
            body = f"{reason} ({code})" if code and code != reason else str(reason)
    except (ValueError, AttributeError):
        pass
    return f"HTTP {response.status_code}: {body[:200]}" if body else f"HTTP {response.status_code}"


def _headers() -> dict[str, str]:
    headers = {"X-Api-Key": config.NAVANA_API_KEY}
    if config.NAVANA_CUSTOMER_ID:  # legacy bodhi.navana.ai accounts
        headers["x-customer-id"] = config.NAVANA_CUSTOMER_ID
    return headers


class NavanaSTTService(WebsocketSTTService):
    """Streaming Bodhi STT. Local VAD ends the turn; Bodhi's "complete" frame is the final text."""

    def __init__(
        self,
        *,
        model: str,
        language: str,
        sample_rate: int,
        hotwords: list[str] | None = None,
        **kwargs,
    ):
        kwargs.setdefault("ttfs_p99_latency", 0.9)  # endpointing waits >= 0.44 s of silence first
        super().__init__(
            sample_rate=sample_rate,
            settings=STTSettings(model=model, language=language),
            **kwargs,
        )
        self._hotwords = hotwords or []
        self._receive_task = None
        self._config_sent = False

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await self._send_json({"eof": 1})
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if self._config_sent and self._websocket and self._websocket.state is State.OPEN:
            try:
                await self._websocket.send(audio)
            except Exception as e:
                logger.warning(f"{self}: send failed: {e}")
        yield None

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
            self._config_sent = False
            self._websocket = await self._websocket_connect(config.NAVANA_STT_URL, additional_headers=_headers())
            cfg = {
                "sample_rate": self.sample_rate,
                "transaction_id": str(uuid.uuid4()),
                "model": self._settings.model,
                "channels": 1,
                "parse_number": False,
                "endpoint_silence_duration": 0.44,  # the minimum: finals as soon as Bodhi allows
            }
            if self._hotwords:
                cfg["hotwords"] = [{"phrase": w} for w in self._hotwords]
            await self._websocket.send(json.dumps({"config": cfg}))
            self._config_sent = True
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
            self._config_sent = False
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
            if content.get("error"):
                code = content.get("code") or ""
                await self.push_error(error_msg=f"Speech recognition error {code} {content['error']}: {content.get('message', '')}")
                continue
            text = (content.get("text") or "").strip()
            if not text:
                continue
            if content.get("type") == "complete":
                await self.emit_stt_usage_metrics()
                await self.push_frame(
                    TranscriptionFrame(text, self._user_id, time_now_iso8601(), None, result=content, finalized=True)
                )
            else:
                await self.push_frame(InterimTranscriptionFrame(text, self._user_id, time_now_iso8601(), None, result=content))


def _pcm_chunks():
    """Re-chunk a byte stream into whole 16-bit samples."""
    leftover = b""

    def feed(chunk: bytes) -> bytes:
        nonlocal leftover
        data = leftover + chunk
        cut = len(data) - (len(data) % 2)
        leftover = data[cut:]
        return data[:cut]

    return feed


class NavanaTTSService(TTSService):
    """Bodhi TTS over HTTP, one request per sentence, audio streamed as it downloads."""

    def __init__(self, *, voice: str, language: str, pace: float, sample_rate: int, **kwargs):
        super().__init__(
            sample_rate=sample_rate,
            push_stop_frames=True,
            push_start_frame=True,
            settings=TTSSettings(model="bodhi-tts", voice=voice, language=language),
            **kwargs,
        )
        self._lang = language.split("-")[0]  # Bodhi takes bare codes: hi, ta, or…
        self._speed = max(0.25, min(4.0, pace))
        self._client: httpx.AsyncClient | None = None

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))

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
            "lang": self._lang,
            "voice": self._settings.voice,
            "output_format": f"{self.sample_rate}:pcm16",
            "speed": self._speed,
        }
        headers = {"X-API-Key": config.NAVANA_API_KEY, "Content-Type": "application/json"}
        feed = _pcm_chunks()
        try:
            async with self._client.stream("POST", config.NAVANA_TTS_URL, json=payload, headers=headers) as resp:
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
