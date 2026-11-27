"""The agent definition we own. One row per client agent; no Sarvam-side agent exists."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.providers import catalog
from app.providers.catalog import LANGUAGES, SCRIPTS  # noqa: F401  (re-exported)


class HttpTool(BaseModel):
    """A tool the agent can call mid-conversation: we call your HTTP endpoint."""

    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=1000)
    method: Literal["GET", "POST"] = "POST"
    url: str = Field(pattern=r"^https?://")
    headers: dict[str, str] = Field(default_factory=dict)
    # JSON Schema "properties" for the arguments the LLM must fill in.
    parameters: dict[str, dict] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    timeout_secs: float = Field(default=8.0, ge=1, le=30)


class AgentConfig(BaseModel):
    greeting: str = "Hello! How can I help you today?"
    instructions: str = (
        "You are a friendly, helpful voice assistant. Keep replies short and conversational."
    )
    # One provider per part of the pipeline (see app/providers/catalog.py).
    stt_provider: Literal["sarvam", "navana", "gnani"] = "sarvam"
    llm_provider: Literal["sarvam", "gnani"] = "sarvam"
    tts_provider: Literal["sarvam", "navana", "gnani", "plivo"] = "sarvam"
    language: str = "en-IN"
    auto_detect_language: bool = False
    voice: str = "simran_enhi_customer"  # an id from the TTS provider's voice list
    pace: float = Field(default=1.0, ge=0.5, le=2.0)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    max_call_seconds: int = Field(default=180, ge=30, le=1800)
    idle_timeout_secs: float = Field(default=12.0, ge=4.0, le=60.0)
    end_call_enabled: bool = True
    goodbye_message: str = "Thank you for calling. Goodbye!"
    nudge_message: str = "Are you still there?"  # said after the caller is silent for idle_timeout_secs
    repeat_message: str = "Sorry, could you say that again?"  # said if the LLM fails on a turn
    tools: list[HttpTool] = Field(default_factory=list)
    # Turn detection: "sarvam" = Sarvam's server-side VAD decides when the caller stopped
    # (Sarvam's recommendation for noisy lines); "fast" = local Silero VAD decides after a
    # short pause and tells Sarvam to finalize at once (measured ~0.9-1.1 s quicker to answer).
    # Other speech recognition providers always use "fast".
    turn_detection: Literal["sarvam", "fast"] = "fast"
    # Silence that ends the caller's turn. None = Sarvam's default (sarvam mode) / 300 ms (fast).
    end_of_speech_ms: int | None = Field(default=None, ge=150, le=2000)
    # Names/brands/terms the speech recognizer should favour (Saaras v4 keyterms).
    important_words: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("important_words")
    @classmethod
    def _clean_words(cls, words: list[str]) -> list[str]:
        cleaned = [w.strip()[:64] for w in words if w.strip()]
        return list(dict.fromkeys(cleaned))

    @field_validator("language")
    @classmethod
    def _known_language(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError(f"Unsupported language {v!r}")
        return v

    @model_validator(mode="after")
    def _fits_providers(self) -> "AgentConfig":
        """The language must work with both speech providers, and the voice must be the TTS provider's."""
        if self.language not in catalog.call_languages(self.stt_provider, self.tts_provider):
            stt = catalog.providers()[self.stt_provider]["name"]
            tts = catalog.providers()[self.tts_provider]["name"]
            raise ValueError(f"{LANGUAGES[self.language]} isn't supported by {stt} speech recognition with {tts} voices")
        voice = catalog.find_voice(self.tts_provider, self.voice)
        if voice is None:
            raise ValueError(f"Unknown voice {self.voice!r} for {catalog.providers()[self.tts_provider]['name']}")
        if not catalog.voice_fits(voice, self.language):
            raise ValueError(f"The voice {voice['name']} doesn't speak {LANGUAGES[self.language]}")
        return self

    @field_validator("tools")
    @classmethod
    def _unique_tool_names(cls, tools: list[HttpTool]) -> list[HttpTool]:
        names = [t.name for t in tools]
        if len(names) != len(set(names)) or "end_call" in names:
            raise ValueError("Tool names must be unique and must not be 'end_call'")
        return tools

    def language_rule(self) -> str:
        name = LANGUAGES[self.language]
        if self.auto_detect_language:
            return (
                "Reply in the same language the caller is speaking, written in that language's own script; "
                f"code-mixed speech like Hinglish is fine. If unsure, use {name}."
            )
        if self.language == "en-IN":
            return "Always reply in English."
        return (
            f"Always reply in {name}, written in {SCRIPTS[self.language]}, even if the caller speaks "
            "English or these instructions are in English. Keep names and brand names as they are, "
            f"and use common English words the way {name} speakers naturally do."
        )

    def number_rule(self) -> str:
        """Numbers as spoken words, so the voice says "fourteen thousand", never reads "14000"."""
        rule = (
            "Never write digits for amounts, prices or quantities. Write them as spoken words, the way a person "
            "says them aloud, using the Indian system of thousand, lakh and crore."
        )
        english = "write 'fourteen thousand rupees', not '14000 rupees' or 'Rs. 14,000'"
        hindi = "in Hindi write 'चौदह हज़ार रुपये', not '14000 रुपये'"
        if self.auto_detect_language:
            return f"{rule} Use the words of the language you are replying in: {english}; {hindi}."
        if self.language == "en-IN":
            return f"{rule} For example, {english}, and 'one lakh fifty thousand', not '150000'."
        example = f" For example, {hindi}." if self.language == "hi-IN" else ""
        return f"{rule} Write the number words in {LANGUAGES[self.language]}, in {SCRIPTS[self.language]}.{example}"

    def system_prompt(self) -> str:
        """Instructions plus the voice-specific rules from Sarvam's production guide."""
        language_rule = self.language_rule()
        rules = [
            "You are speaking on a live voice call.",
            "Respond in natural spoken language. Never use markdown, bullet points, lists or emoji.",
            "Keep replies to one or two short sentences.",
            language_rule,
            # Everything below is read aloud by the voice, so write it the way it is spoken.
            "Sound warm and expressive, like a real person. Punctuation shapes your tone of voice: use an "
            "exclamation mark for genuine warmth or excitement (a greeting, good news, thanks), but not on "
            "every sentence, or you will sound over-excited.",
            self.number_rule(),
            "Read phone numbers, OTPs, PINs, account numbers and other codes one digit at a time, written "
            "as words, with a short pause (a comma) between groups of digits.",
            "Write times and dates as spoken words, like 'ten thirty in the morning' or 'fifth of March', "
            "and spell out abbreviations and symbols, like 'doctor' for 'Dr.' and 'percent' for '%'.",
        ]
        if self.end_call_enabled:
            rules.append(
                "Call the end_call tool only after the caller clearly says goodbye, asks to end the call, "
                "or confirms they need nothing else. Never call it right after the caller answers your "
                "question or gives you information; reply to them instead."
            )
        # The language rule goes first as well: the instructions are often written in English.
        return (
            f"LANGUAGE: {language_rule}\n\n"
            + self.instructions.strip()
            + "\n\nVoice rules:\n"
            + "\n".join(f"- {r}" for r in rules)
        )
