"""Sarvam realtime STT for fast (local VAD) turn detection, without losing first words.

With endpointing="manual", Sarvam only transcribes audio between `speech_start` and
`speech_end`. Local VAD confirms speech ~0.2-0.3 s after it actually begins (and the
VAD frame reaches the STT later still, from downstream), so audio streamed before
`speech_start` was ignored and callers lost their first word. Here audio is held in a
rolling pre-roll while nobody is speaking and sent right after `speech_start`.
Only speech is streamed, so only speech is billed (and counted, see
_record_stt_audio_usage); Sarvam's ping keeps the socket alive in between.
"""

from collections.abc import AsyncGenerator

from pipecat.frames.frames import Frame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService

PREROLL_SECS = 1.0


class PrerollSarvamRealtimeSTTService(SarvamRealtimeSTTService):
    def __init__(self, **kwargs):
        kwargs.setdefault("keepalive_timeout", 5.0)
        super().__init__(endpointing="manual", **kwargs)
        self._preroll = bytearray()
        self._in_turn = False

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if not self._in_turn:
            self._preroll.extend(audio)
            excess = len(self._preroll) - int(self._bytes_per_second() * PREROLL_SECS)
            if excess > 0:
                del self._preroll[: excess + (excess % 2)]  # keep 16-bit sample alignment
            yield None
            return
        async for frame in super().run_stt(audio):
            yield frame

    def _record_stt_audio_usage(self, audio: bytes | bytearray):
        """Count only audio that is actually sent to Sarvam (what it bills).

        The base class counts every incoming frame, but between turns frames only feed
        the pre-roll buffer and are never sent. Counting them would bill silence and the
        time the agent is talking.
        """
        if getattr(self, "_in_turn", False):
            super()._record_stt_audio_usage(audio)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, VADUserStartedSpeakingFrame) and not self._in_turn:
            self._in_turn = True
            await super().process_frame(frame, direction)  # sends speech_start
            # Replay the speech that arrived before VAD confirmed it, right away, in the
            # service's normal chunk size (Sarvam caps a single frame at 8000 bytes).
            preroll = bytes(self._preroll)
            self._preroll.clear()
            super()._record_stt_audio_usage(preroll)  # sent below, so it is billed
            chunk = self._chunk_size_bytes()
            for i in range(0, len(preroll), chunk):
                await self._send_audio_chunk(preroll[i : i + chunk])
            return
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            await super().process_frame(frame, direction)  # flushes audio, sends speech_end
            self._in_turn = False
            return
        await super().process_frame(frame, direction)
