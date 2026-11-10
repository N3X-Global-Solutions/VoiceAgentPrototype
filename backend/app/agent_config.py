"""The agent definition we own. One row per client agent; no Sarvam-side agent exists."""

import json
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LANGUAGES: dict[str, str] = {
    "en-IN": "English",
    "hi-IN": "Hindi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "kn-IN": "Kannada",
    "mr-IN": "Marathi",
    "gu-IN": "Gujarati",
    "bn-IN": "Bengali",
    "pa-IN": "Punjabi",
    "ml-IN": "Malayalam",  # no Bulbul v4 Flash voices yet: uses Aparna (English) cross-language
}


# How each language is written, so replies come out in the script TTS expects.
SCRIPTS: dict[str, str] = {
    "en-IN": "English",
    "hi-IN": "Devanagari script",
    "ta-IN": "Tamil script",
    "te-IN": "Telugu script",
    "kn-IN": "Kannada script",
    "mr-IN": "Devanagari script",
    "gu-IN": "Gujarati script",
    "bn-IN": "Bengali script",
    "pa-IN": "Gurmukhi script",
    "ml-IN": "Malayalam script",
}


@cache
def voices() -> list[dict]:
    """Bulbul v4 Flash personas, parsed from Sarvam's voice catalog."""
    return json.loads((Path(__file__).parent / "voices.json").read_text())


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
    language: str = "en-IN"
    auto_detect_language: bool = False
    voice: str = "simran_enhi_customer"
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

    @field_validator("voice")
    @classmethod
    def _known_voice(cls, v: str) -> str:
        if v not in {voice["id"] for voice in voices()}:
            raise ValueError(f"Unknown Bulbul v4 Flash voice {v!r}")
        return v

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
            "English or these instructions are in English. Keep names, brand names and numbers as they are, "
            f"and use common English words the way {name} speakers naturally do."
        )

    def system_prompt(self) -> str:
        """Instructions plus the voice-specific rules from Sarvam's production guide."""
        language_rule = self.language_rule()
        rules = [
            "You are speaking on a live voice call.",
            "Respond in natural spoken language. Never use markdown, bullet points, lists or emoji.",
            "Keep replies to one or two short sentences.",
            language_rule,
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
