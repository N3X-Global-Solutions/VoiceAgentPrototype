"""Provider-neutral error text for anything shown in the UI (the product is white-label).

Server logs keep the raw provider message; users see these generic versions instead.
"""

import re

_PROVIDER = re.compile(r"sarvam(ai)?|saaras|saarika|bulbul|navana|bodhi|gnani|vachana|prisma|timbre|evon", re.IGNORECASE)


def public_error(text: str) -> str:
    """Map a raw provider error to a message that doesn't name the provider."""
    lowered = text.lower()
    if any(k in lowered for k in ("invalid_subscription_key", "invalid api key", "401", "403", "unauthorized")):
        return "An AI provider rejected its API key. Check the provider keys in the server's .env."
    if any(k in lowered for k in ("insufficient", "quota", "402", "credits")):
        return "AI provider credits are exhausted. Top up the provider account, then try again."
    return _PROVIDER.sub("AI provider", text)


NO_PROVIDER_KEY = "The AI provider API key isn't configured on the server (.env)."
NO_LLM_KEY = "No AI model provider key is configured on the server (.env)."
