"""Plivo voice (Koyal text-to-speech), as a Pipecat service.

Protocol: plivo.com/docs/models/text-to-speech/api/batch
- POST https://api.plivo.com/v1/Account/{auth_id}/TTS/ with HTTP Basic auth (Auth ID and Auth
  Token), a JSON body, and raw 16-bit PCM back, streamed as it is generated.
- Errors are JSON: {"error": "...", "code": "voice_not_found", "number": 2080, "param": "voice_id"}.
  A full account is "insufficient_balance" (HTTP 400); 429/502/503 are retryable.
- Plivo bills characters: its launch price is per "minute", counted as 1,000 characters.

This is Plivo's AI voice only. Clients' Plivo phone numbers are separate (app/telephony/), and
those use each client's own account; this uses the workspace account from .env.
"""

import asyncio
import json
from collections.abc import AsyncGenerator

import httpx
from loguru import logger

from pipecat.frames.frames import CancelFrame, EndFrame, ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

from app.core import config
from app.providers.catalog import PLIVO_TTS_MODEL, find_voice
from app.providers.navana import _pcm_chunks

API = "https://api.plivo.com/v1/Account"
PACE_RANGE = (0.7, 1.2)  # Plivo rejects other values
_RETRYABLE = {429, 502, 503}
# Errors that every later sentence would hit too (bad voice, unsupported setting). Their text
# says "validation error", which makes the call runtime end the call instead of going silent.
_CONFIG_ERRORS = {"voice_not_found", "model_not_found", "language_not_supported", "unsupported_format", "invalid_request"}


def tts_url() -> str:
    return f"{API}/{config.PLIVO_AUTH_ID}/TTS/"


def error_text(status: int, body: bytes) -> str:
    """Plivo's own reason, worded so bot.on_pipeline_error knows whether retrying can help."""
    code, reason = "", body.decode(errors="replace")[:300]
    try:
        data = json.loads(body)
        code, reason = str(data.get("code") or ""), str(data.get("error") or reason)
    except (ValueError, AttributeError):
        pass
    kind = "validation error" if code in _CONFIG_ERRORS else "error"
    detail = f"{code}: {reason}" if code else reason
    return f"Voice provider {kind} {status} ({detail})"


class PlivoTTSService(TTSService):
    """Koyal TTS over HTTP, one request per sentence, audio streamed as it downloads."""

    def __init__(self, *, voice: str, language: str, auto_detect: bool, pace: float, sample_rate: int, **kwargs):
        entry = find_voice("plivo", voice)
        if entry is None:
            raise ValueError(f"Unknown voice {voice!r}")
        super().__init__(
            sample_rate=sample_rate,
            push_stop_frames=True,
            push_start_frame=True,
            settings=TTSSettings(model=PLIVO_TTS_MODEL, voice=voice, language=language),
            **kwargs,
        )
        # Following the caller's language: let Plivo read each sentence in the language it is
        # written in. Otherwise the voice's own language code (en-IN, hi, ta...).
        self._language = "auto" if auto_detect else entry["api_language"]
        self._pace = round(max(PACE_RANGE[0], min(PACE_RANGE[1], pace)), 2)
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
            "voice_id": self._settings.voice,
            "text": text,
            "model_id": PLIVO_TTS_MODEL,
            "language": self._language,
            "pace": self._pace,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": self.sample_rate},
        }
        auth = (config.PLIVO_AUTH_ID, config.PLIVO_AUTH_TOKEN)
        feed = _pcm_chunks()
        try:
            for attempt in range(2):  # one retry when Plivo is busy (it sends Retry-After: 1)
                async with self._client.stream("POST", tts_url(), json=payload, auth=auth) as resp:
                    if resp.status_code in _RETRYABLE and attempt == 0:
                        await resp.aread()
                        await asyncio.sleep(min(float(resp.headers.get("retry-after") or 1), 1.0))
                        continue
                    if resp.status_code != 200:
                        body = await resp.aread()
                        if b"empty_text" in body:  # e.g. a sentence that was only punctuation
                            logger.debug(f"{self}: nothing to say in {text!r}")
                            return
                        yield ErrorFrame(error=error_text(resp.status_code, body))
                        return
                    await self.start_tts_usage_metrics(text)
                    async for chunk in resp.aiter_bytes(4096):
                        pcm = feed(chunk)
                        if pcm:
                            yield TTSAudioRawFrame(audio=pcm, sample_rate=self.sample_rate, num_channels=1, context_id=context_id)
                    return
        except Exception as e:
            yield ErrorFrame(error=f"Voice generation failed: {e}", exception=e)
