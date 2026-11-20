"""Build a call's speech recognition, AI model and voice from the agent's chosen providers."""

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.services.llm_service import LLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.turns.user_start import ExternalUserTurnStartStrategy, VADUserTurnStartStrategy
from pipecat.turns.user_stop import ExternalUserTurnStopStrategy, SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from app.agents.models import AgentConfig
from app.core import config
from app.providers import catalog
from app.providers.gnani import LLM_BASE_URL as GNANI_LLM_BASE_URL
from app.providers.gnani import GnaniSTTService, GnaniTTSService
from app.providers.navana import NavanaSTTService, NavanaTTSService, stt_model
from app.voice.stt_preroll import PrerollSarvamRealtimeSTTService
from app.voice.tts_text import tts_text_transform

FAST_DEFAULT_END_OF_SPEECH_MS = 300


def missing_keys(cfg: AgentConfig) -> list[str]:
    """Env vars an agent's providers need that aren't set, e.g. ["NAVANA_API_KEY"]."""
    needed = dict.fromkeys([cfg.stt_provider, cfg.llm_provider, cfg.tts_provider])
    return [catalog.providers()[p]["key_env"] for p in needed if not catalog.configured(p)]


def missing_keys_message(cfg: AgentConfig) -> str | None:
    missing = missing_keys(cfg)
    if not missing:
        return None
    return f"This agent's providers need {' and '.join(missing)} in the server's .env."


def uses_fast_turns(cfg: AgentConfig) -> bool:
    """Local VAD decides turns: always, except Sarvam speech recognition in "robust" mode."""
    return cfg.stt_provider != "sarvam" or cfg.turn_detection == "fast"


def pause_ms(cfg: AgentConfig) -> int | None:
    return cfg.end_of_speech_ms or (FAST_DEFAULT_END_OF_SPEECH_MS if uses_fast_turns(cfg) else None)


def _fast_turn_params(cfg: AgentConfig) -> dict:
    stop_secs = (cfg.end_of_speech_ms or FAST_DEFAULT_END_OF_SPEECH_MS) / 1000
    return {
        "vad_analyzer": SileroVADAnalyzer(params=VADParams(stop_secs=stop_secs)),
        "user_turn_strategies": UserTurnStrategies(
            start=[VADUserTurnStartStrategy()],
            stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.05)],
        ),
    }


def make_stt(cfg: AgentConfig, sample_rate: int) -> tuple[STTService, dict]:
    """STT service plus the user-turn settings that match the provider and turn detection mode."""
    words = cfg.important_words or None

    if cfg.stt_provider == "navana":
        stt = NavanaSTTService(
            model=stt_model(cfg.language, cfg.auto_detect_language),
            language=cfg.language,
            sample_rate=sample_rate,
            hotwords=words,
        )
        return stt, _fast_turn_params(cfg)

    if cfg.stt_provider == "gnani":
        stt = GnaniSTTService(
            language=cfg.language,
            auto_detect=cfg.auto_detect_language,
            sample_rate=sample_rate,
            keyterms=words,
        )
        return stt, _fast_turn_params(cfg)

    settings = SarvamRealtimeSTTService.Settings(
        model=catalog.part("sarvam", "stt")["model"],
        language=None if cfg.auto_detect_language else cfg.language,
        mode="transcribe",
        stream_type="fast",
    )
    if uses_fast_turns(cfg):
        # Local Silero VAD ends the turn after a short pause; the STT then flushes its
        # buffered audio and sends speech_end, so Sarvam finalizes without waiting for
        # its own server-side silence window. The pre-roll STT keeps the first words
        # that are spoken before VAD confirms speech.
        stt = PrerollSarvamRealtimeSTTService(
            api_key=config.SARVAM_API_KEY,
            sample_rate=sample_rate,
            keyterms=words,
            ttfs_p99_latency=0.4,  # measured: realtime finals arrive ~150-260 ms after speech_end
            settings=settings,
        )
        return stt, _fast_turn_params(cfg)

    if cfg.end_of_speech_ms:
        settings.silence_duration_ms = cfg.end_of_speech_ms
    stt = SarvamRealtimeSTTService(api_key=config.SARVAM_API_KEY, sample_rate=sample_rate, keyterms=words, settings=settings)
    return stt, {
        "user_turn_strategies": UserTurnStrategies(
            start=[ExternalUserTurnStartStrategy(enable_interruptions=True)],
            stop=[ExternalUserTurnStopStrategy(timeout=0.1, wait_for_transcript=True)],
        ),
    }


def make_tts(cfg: AgentConfig, sample_rate: int) -> TTSService:
    # Digits the LLM still writes become spoken words ("14000" -> "fourteen thousand").
    transforms = [("*", tts_text_transform)]
    if cfg.tts_provider == "navana":
        return NavanaTTSService(voice=cfg.voice, language=cfg.language, pace=cfg.pace, sample_rate=sample_rate, text_transforms=transforms)
    if cfg.tts_provider == "gnani":
        return GnaniTTSService(
            voice=cfg.voice,
            language=cfg.language,
            auto_detect=cfg.auto_detect_language,
            pace=cfg.pace,
            sample_rate=sample_rate,
            text_transforms=transforms,
        )
    return SarvamTTSService(
        api_key=config.SARVAM_API_KEY,
        sample_rate=sample_rate,
        settings=SarvamTTSService.Settings(
            model=catalog.part("sarvam", "tts")["model"],
            voice=cfg.voice,
            language=cfg.language,
            pace=cfg.pace,
            min_buffer_size=30,  # Sarvam's API minimum (its Pipecat guide's 15-25 is now rejected)
        ),
        text_transforms=transforms,
    )


def make_llm(cfg: AgentConfig) -> LLMService:
    model = catalog.part(cfg.llm_provider, "llm")["model"]
    if cfg.llm_provider == "gnani":
        return OpenAILLMService(
            api_key=config.GNANI_API_KEY or "unset",  # calls without a key are refused before this
            base_url=GNANI_LLM_BASE_URL,
            settings=OpenAILLMService.Settings(
                model=model,
                temperature=cfg.temperature,
                max_tokens=300,
                extra={"reasoning_effort": "none"},  # Evon thinks by default: slow, and billed as output
            ),
        )
    return SarvamLLMService(
        api_key=config.SARVAM_API_KEY,
        settings=SarvamLLMService.Settings(
            model=model,
            temperature=cfg.temperature,
            reasoning_effort=None,  # thinking off: lower latency, no hidden token cost
            max_tokens=300,
        ),
    )


def chat_request(provider: str) -> tuple[str, dict, dict]:
    """(URL, headers, extra payload) for one OpenAI-style chat completion, used by text tests."""
    model = catalog.part(provider, "llm")["model"]
    if provider == "gnani":
        return (
            f"{GNANI_LLM_BASE_URL}/chat/completions",
            {"Authorization": f"Bearer {config.GNANI_API_KEY}"},
            {"model": model, "reasoning_effort": "none"},
        )
    return (
        "https://api.sarvam.ai/v2/chat/completions",
        {"api-subscription-key": config.SARVAM_API_KEY, "Authorization": f"Bearer {config.SARVAM_API_KEY}"},
        {"model": model, "reasoning_effort": None},
    )
