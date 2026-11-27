"""Which voice AI provider does what: languages, voices, models and prices.

An agent picks one provider per part of the pipeline (speech recognition, AI model,
voice). Plivo offers a voice only. Everything provider-specific the rest of the app needs lives here, so adding a
provider means one entry in PROVIDERS plus its Pipecat services in app/providers/.

Prices are INR, before GST, and every one can be overridden in .env. "source" says
where each default came from, so the UI can flag the ones you should confirm:
  published - the provider's docs or launch pricing
  quoted    - the figure you gave us for your account
  estimate  - no public price; set it from your provider console
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.core import config

Kind = str  # "stt" | "tts" | "llm"

# Every language an agent can use. Each provider supports a subset (see PROVIDERS).
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
    "ml-IN": "Malayalam",
    "or-IN": "Odia",
}

# How each language is written, so replies come out in the script the voice expects.
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
    "or-IN": "Odia script",
}

_TEN = ["en-IN", "hi-IN", "ta-IN", "te-IN", "kn-IN", "mr-IN", "gu-IN", "bn-IN", "pa-IN", "ml-IN"]

# A voice whose "language" is ALL speaks every language its provider supports.
ALL = "*"


# ---------------------------------------------------------------- voices


@cache
def _sarvam_voices() -> list[dict]:
    """Bulbul v4 Flash personas, parsed from Sarvam's voice catalog."""
    raw = json.loads((Path(__file__).resolve().parents[1] / "agents" / "voices.json").read_text())
    return [{**v, "provider": "sarvam"} for v in raw]


# Navana Bodhi TTS: every named voice speaks all ten of its languages (docs.navana.ai/text-to-speech/voices).
# Gender isn't documented, so it isn't shown.
_NAVANA_NAMED = (
    "achu ammu anirban ann arasi ayesha basava basheer bhavana bijay bimla champa chhotu elango faizal "
    "falguni flavia gurdeep harleen imran ipsita jayita jessy kannan kayal kishan mahadevi malar maria merin "
    "mukta murugan nasrin nayeema netra nila ponni porkavi rukhiya rukhsana savio selvi shabnam sharon shikha "
    "shivanna srinu sulaiman tanaji temjen vanaja vetri xavier yasmin zoya"
).split()


@cache
def _navana_voices() -> list[dict]:
    voices = [
        {"id": "default_female", "name": "Default", "style": "female", "language": ALL, "group": "Standard"},
        {"id": "default_male", "name": "Default", "style": "male", "language": ALL, "group": "Standard"},
    ]
    voices += [{"id": n, "name": n.capitalize(), "style": "all languages", "language": ALL, "group": "Named"} for n in _NAVANA_NAMED]
    return [{**v, "provider": "navana"} for v in voices]


# Gnani Timbre (docs.gnani.ai/api/TTS/available-voices). v2.5 voices each have one language;
# v3.0 voices speak all ten languages.
_GNANI_V25: dict[str, list[tuple[str, str]]] = {
    "en-IN": [("Kaveri", "F"), ("Trupti", "F"), ("Devika", "F"), ("Pranav", "M"), ("Shlok", "M"), ("Girish", "M")],
    "hi-IN": [
        ("Nalini", "F"), ("Bhavna", "F"), ("Yashvi", "F"), ("Urmila", "F"), ("Jwala", "F"), ("Chitra", "F"),
        ("Ambuja", "F"), ("Deepak", "M"), ("Roopesh", "M"), ("Vikrant", "M"), ("Hemraj", "M"), ("Jalaj", "M"),
        ("Omkar", "M"),
    ],
    "ta-IN": [("Asmita", "F"), ("Trisha", "F"), ("Brinda", "F"), ("Vedika", "F"), ("Noopur", "F")],
    "te-IN": [("Suhana", "F"), ("Lehara", "F"), ("Lavanya", "F"), ("Yukti", "F"), ("Varuni", "F")],
    "kn-IN": [("Saanvi", "F"), ("Kavin", "M")],
    "ml-IN": [("Reshma", "F"), ("Riyaan", "M")],
    "mr-IN": [("Zahira", "F"), ("Ishaan", "M")],
    "bn-IN": [("Kirra", "F"), ("Dhruva", "M")],
    "gu-IN": [("Falak", "F"), ("Veera", "M")],
    "pa-IN": [("Mehuli", "F"), ("Zayan", "M")],
}
_GNANI_V3_FEMALE = (
    "Anitasingh Chetana Kalpana Lakshmi Lakshmidevi Neelam Priyasharm Rajni Rekha Riyaa Shivani Shruthi Sneha "
    "Sohini Sunaina Swathi Tarika Vasudha"
).split()
_GNANI_V3_MALE = (
    "Arko Avinash Devansh Harshad Mahendra Manjunath Nitin Prakash Rahulmehta Rajeev Rakesh Santosh Shubham "
    "Vikramdasu Vinod Yashraj"
).split()
GNANI_TTS_V3 = "timbre-v3.0"
GNANI_TTS_V25 = "timbre-v2.5"


@cache
def _gnani_voices() -> list[dict]:
    gender = {"F": "female", "M": "male"}
    voices = [
        {"id": f"v3:{n}", "name": n, "style": f"{g} · all languages", "language": ALL, "group": "Expressive (v3)", "model": GNANI_TTS_V3}
        for g, names in (("female", _GNANI_V3_FEMALE), ("male", _GNANI_V3_MALE))
        for n in names
    ]
    voices += [
        {"id": f"v2:{n}", "name": n, "style": gender[g], "language": lang, "group": "Classic (v2.5)", "model": GNANI_TTS_V25}
        for lang, names in _GNANI_V25.items()
        for n, g in names
    ]
    voices.append(
        {"id": "v2:Poorvi", "name": "Poorvi", "style": "female · Hinglish", "language": "hi-IN", "group": "Classic (v2.5)", "model": GNANI_TTS_V25, "hinglish": True}
    )
    return [{**v, "provider": "gnani"} for v in voices]


# Plivo Koyal TTS (plivo.com/docs/models/text-to-speech/concepts/voices, Nov 2026). Each voice
# speaks one language; "api_language" is the code Plivo's API takes for it. Plivo's Voices API
# (GET /v1/Account/{auth_id}/TTS/Voices/) lists the current set if voices are added.
PLIVO_TTS_MODEL = "koyal-v1"
_PLIVO: dict[str, list[tuple[str, str, str, str]]] = {  # language -> (name, voice_id, gender, api_language)
    "en-IN": [
        ("Nisha", "H25SvwivznBqsIx1R7hX", "female", "en-IN"),
        ("Prerna", "3gVUACYdS3ibtu8qPruB", "female", "en-IN"),
        ("Aarav", "vGOW5Fzss7kzS9IxCObo", "male", "en-IN"),
        ("Karan", "34AUgJTl9p1TLO99Mc7E", "male", "en-IN"),
        ("Allison", "GhXTeeZNT1zacg9RUbXa", "female", "en-US"),
        ("Hailey", "lC7qzMoRE7SSjaNCVeff", "female", "en-US"),
        ("Garrett", "P2WNP5RVUP1t6dK9PY52", "male", "en-US"),
        ("Terrell", "ieA6hQ563LgXTiOgy6kz", "male", "en-US"),
        ("Travis", "Ak70ycoSdDYbeq5sAXsc", "male", "en-US"),
        ("Eleanor", "Ic0DJ4TLN1ELIYmzwi6H", "female", "en-GB"),
        ("Poppy", "0isEP1KMeZPsGSP5qj2A", "female", "en-GB"),
        ("Archie", "zYmyWxqLSdlQ0MA4AQEV", "male", "en-GB"),
        ("Tahlia", "S4OkXYkfzKK9f6wzmQ0X", "female", "en-AU"),
    ],
    "hi-IN": [
        ("Meera", "6uWzc4xFj31t4jNJUaED", "female", "hi"),
        ("Ritika", "Hiqcy02wuf8a4sCMcdNO", "female", "hi"),
        ("Aman", "OmziUEKO4d83QuGMo3bP", "male", "hi"),
        ("Ishaan", "nzWUWk5ShuIYGSosxESk", "male", "hi"),
    ],
    "bn-IN": [
        ("Debasmita", "cZncSKHriH32h4IKwAF1", "female", "bn"),
        ("Ishani", "GKrPm1RIxbJRv4yYqAxX", "female", "bn"),
        ("Subhankar", "vxMrWeHTjRflUziEla6E", "male", "bn"),
    ],
    "ta-IN": [
        ("Nandhini", "wDPugzmr5HSlFv9MaXk0", "female", "ta"),
        ("Kathir", "4YwYWODqig98puWmLYRz", "male", "ta"),
    ],
    "te-IN": [
        ("Abhiram", "v2jq1LG20JPbAVrlTWmZ", "male", "te"),
        ("Pavan", "cXEjlQTYG6DCOlWVjGe9", "male", "te"),
    ],
    "mr-IN": [
        ("Sanika", "KCWPtNGDMOQ5bI9SiaIm", "female", "mr"),
        ("Shravani", "WqKlYdzJonf6PWElzV6a", "female", "mr"),
        ("Akshay", "KYAauPOeeH6Xkcy9YBA7", "male", "mr"),
        ("Mandar", "nBMKcKglpeBGawQWLrOa", "male", "mr"),
    ],
    "gu-IN": [
        ("Hiren", "xHCIssLpg7mFHuxJAl5D", "male", "gu"),
        ("Nirav", "9ZCJ1Lca7nXQprCrubMG", "male", "gu"),
    ],
    "kn-IN": [
        ("Bhavana", "iNhbJlZPe4LFctxRtJPD", "female", "kn"),
        ("Spoorthi", "Ba1rbMwhlf3aXyxKB99Q", "female", "kn"),
        ("Pradeep", "JlZpUKXSnAs3C1qmfJR8", "male", "kn"),
    ],
}
# English voices are grouped by accent; every other language has one group.
_PLIVO_ACCENT = {"en-IN": "Indian accent", "en-US": "American accent", "en-GB": "British accent", "en-AU": "Australian accent"}


@cache
def _plivo_voices() -> list[dict]:
    return [
        {
            "id": voice_id,
            "name": name,
            "style": gender,
            "language": lang,
            "group": _PLIVO_ACCENT.get(api_lang, LANGUAGES[lang]),
            "api_language": api_lang,
            "provider": "plivo",
        }
        for lang, entries in _PLIVO.items()
        for name, voice_id, gender, api_lang in entries
    ]


# ---------------------------------------------------------------- providers


@dataclass(frozen=True)
class Price:
    rate: float
    unit: str  # "min" | "1k_chars" | "1m_tokens"
    source: str  # "published" | "quoted" | "estimate"
    env: str
    note: str = ""


def _price(env: str, default: float, unit: str, source: str, note: str = "") -> Price:
    return Price(rate=config.env_float(env, default), unit=unit, source=source, env=env, note=note)


def _sarvam_tts_languages() -> list[str]:
    # Malayalam has no Bulbul v4 Flash voice of its own; the Aparna (English) voice reads it.
    return sorted({v["language"] for v in _sarvam_voices()} | {"ml-IN"})


@cache
def providers() -> dict[str, dict]:
    """Provider id -> {name, key_env, stt?, tts?, llm?}. Each part lists languages, model and prices."""
    return {
        "sarvam": {
            "name": "Sarvam",
            "key_env": "SARVAM_API_KEY",
            "stt": {
                "model": "saaras:v4",
                "languages": _TEN,
                # Fast mode streams only speech, so only speech is billed.
                "billing": "speech",
                "prices": {"audio": _price("PRICE_STT_PER_MIN", 0.49, "min", "published", "per second of speech sent")},
                "features": ["robust_turns", "auto_language", "keywords"],
            },
            "tts": {
                "model": "bulbul:v4-flash",
                "languages": _sarvam_tts_languages(),
                "prices": {"chars": _price("PRICE_TTS_PER_1K_CHARS", 2.00, "1k_chars", "published")},
            },
            "llm": {
                "model": "sarvam-105b-conversations",
                "prices": {
                    "input": _price("PRICE_LLM_INPUT_PER_1M", 10.0, "1m_tokens", "published"),
                    "cached": _price("PRICE_LLM_CACHED_PER_1M", 0.25, "1m_tokens", "published"),
                    "output": _price("PRICE_LLM_OUTPUT_PER_1M", 25.0, "1m_tokens", "published"),
                },
            },
        },
        "navana": {
            "name": "Navana",
            "key_env": "NAVANA_API_KEY",
            "stt": {
                "model": "Bodhi (banking v2, 8 kHz)",
                "languages": ["en-IN", "hi-IN", "ta-IN", "te-IN", "kn-IN", "mr-IN", "gu-IN", "bn-IN", "ml-IN", "or-IN"],
                # Streaming is billed on seconds connected, silence included.
                "billing": "connected",
                "prices": {
                    "audio": _price(
                        "PRICE_NAVANA_STT_PER_MIN", 0.50, "min", "estimate",
                        "billed per second connected; copy the rate from platform.navana.ai → Plans",
                    )
                },
                "features": ["keywords"],
            },
            "tts": {
                "model": "Bodhi TTS",
                "languages": ["en-IN", "hi-IN", "ta-IN", "te-IN", "kn-IN", "mr-IN", "gu-IN", "bn-IN", "ml-IN", "or-IN"],
                "prices": {"chars": _price("PRICE_NAVANA_TTS_PER_1K_CHARS", 1.20, "1k_chars", "published", "₹12 per 10,000 characters")},
            },
        },
        "gnani": {
            "name": "Gnani",
            "key_env": "GNANI_API_KEY",
            "stt": {
                "model": "prisma-v3.0",
                "languages": _TEN,
                # Billed on audio duration; the whole call is streamed.
                "billing": "connected",
                "prices": {
                    "audio": _price(
                        "PRICE_GNANI_STT_PER_MIN", 0.45, "min", "estimate",
                        "no public price (third-party listing: ₹27/hour); confirm in app.gnani.ai",
                    )
                },
                "features": ["auto_language", "keywords"],
            },
            "tts": {
                "model": "timbre",
                "languages": _TEN,
                "prices": {"chars": _price("PRICE_GNANI_TTS_PER_1K_CHARS", 1.80, "1k_chars", "quoted", "your quoted rate; not published")},
            },
            "llm": {
                "model": "evon-v3.5",
                "note": "Early access only. Free plan: 1 request at a time, 100K tokens a day.",
                "prices": {
                    "input": _price("PRICE_GNANI_LLM_INPUT_PER_1M", 0.0, "1m_tokens", "estimate", "free plan; set if you pay"),
                    "cached": _price("PRICE_GNANI_LLM_CACHED_PER_1M", 0.0, "1m_tokens", "estimate"),
                    "output": _price("PRICE_GNANI_LLM_OUTPUT_PER_1M", 0.0, "1m_tokens", "estimate", "free plan; set if you pay"),
                },
            },
        },
        "plivo": {
            "name": "Plivo",
            # Two values: both must be set (see config.provider_api_key).
            "key_env": "PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN",
            "tts": {
                "model": PLIVO_TTS_MODEL,
                "languages": list(_PLIVO),
                "prices": {
                    "chars": _price(
                        "PRICE_PLIVO_TTS_PER_1K_CHARS", 0.65, "1k_chars", "published",
                        "launch price ₹0.65 per minute of speech; Plivo counts 1,000 characters as a minute",
                    )
                },
            },
        },
    }


def provider_key(provider: str) -> str:
    return config.provider_api_key(provider)


def configured(provider: str) -> bool:
    return bool(provider_key(provider))


def providers_for(kind: Kind) -> list[str]:
    return [p for p, info in providers().items() if kind in info]


def part(provider: str, kind: Kind) -> dict | None:
    return providers().get(provider, {}).get(kind)


def voices(provider: str | None = None) -> list[dict]:
    all_voices = _sarvam_voices() + _navana_voices() + _gnani_voices() + _plivo_voices()
    return [v for v in all_voices if provider is None or v["provider"] == provider]


def find_voice(provider: str, voice_id: str) -> dict | None:
    return next((v for v in voices(provider) if v["id"] == voice_id), None)


def voice_fits(voice: dict, language: str) -> bool:
    """Whether a voice can speak this language (mirrors the UI's filter)."""
    if voice["language"] in (ALL, language):
        return True
    if voice["provider"] == "sarvam":
        return (voice.get("group") == "Hindi-English Code-Mixed" and language in ("en-IN", "hi-IN")) or voice["id"] == "aparna_en_edtech"
    return False


def default_voice(provider: str, language: str) -> str | None:
    own = [v for v in voices(provider) if v["language"] == language]
    fits = own or [v for v in voices(provider) if voice_fits(v, language)]
    return fits[0]["id"] if fits else None


def call_languages(stt: str, tts: str) -> list[str]:
    """Languages an agent can use with this speech recognition + voice pair."""
    stt_part, tts_part = part(stt, "stt"), part(tts, "tts")
    if not stt_part or not tts_part:
        return []
    both = set(stt_part["languages"]) & set(tts_part["languages"])
    return [code for code in LANGUAGES if code in both]


def default_llm_provider() -> str | None:
    """The AI model used for utility jobs (translating phrases): the first one with a key."""
    return next((p for p in providers_for("llm") if configured(p)), None)


@dataclass(frozen=True)
class CallPricing:
    """The rates one call is metered at, for its chosen providers."""

    stt_per_min: float
    stt_billing: str  # "speech" = seconds of speech sent; "connected" = whole call
    tts_per_1k_chars: float
    llm_input_per_1m: float
    llm_cached_per_1m: float
    llm_output_per_1m: float


def call_pricing(stt: str, tts: str, llm: str) -> CallPricing:
    s, t, l = part(stt, "stt"), part(tts, "tts"), part(llm, "llm")
    return CallPricing(
        stt_per_min=s["prices"]["audio"].rate,
        stt_billing=s["billing"],
        tts_per_1k_chars=t["prices"]["chars"].rate,
        llm_input_per_1m=l["prices"]["input"].rate,
        llm_cached_per_1m=l["prices"]["cached"].rate,
        llm_output_per_1m=l["prices"]["output"].rate,
    )


def public_catalog() -> list[dict]:
    """Providers for the UI: what each does, its languages, voices, prices, and whether its key is set."""
    out = []
    for pid, info in providers().items():
        entry: dict = {"id": pid, "name": info["name"], "configured": configured(pid), "key_env": info["key_env"]}
        for kind in ("stt", "tts", "llm"):
            p = info.get(kind)
            if not p:
                entry[kind] = None
                continue
            entry[kind] = {
                "model": p["model"],
                "languages": p.get("languages", []),
                "features": p.get("features", []),
                "note": p.get("note", ""),
                "billing": p.get("billing", ""),
                "prices": {k: {"rate": v.rate, "unit": v.unit, "source": v.source, "env": v.env, "note": v.note} for k, v in p["prices"].items()},
            }
        out.append(entry)
    return out
