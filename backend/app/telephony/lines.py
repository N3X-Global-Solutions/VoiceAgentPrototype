"""Clients' own phone numbers (bring your own Exotel or Plivo account).

Each PhoneLine keeps the client's account settings, with the API key/token encrypted. Checking a
line confirms the credentials work and the number is on that account. For Plivo we also connect
the number to us: an "application" in their account whose answer URL points here. Exotel has no
API for that, so the client pastes our Voicebot URL into their call flow by hand.
"""

import json
import re
from datetime import UTC, datetime

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from app.core import config
from app.core.db import PhoneLine

PROVIDERS = ("exotel", "plivo")
EXOTEL_HOSTS = ("api.exotel.com", "api.in.exotel.com")  # Singapore, Mumbai
PLIVO_API = "https://api.plivo.com/v1/Account"

# Per provider: settings stored as-is, and secrets stored encrypted.
SETTINGS = {"exotel": ("account_sid", "subdomain", "flow_app_id"), "plivo": ("auth_id",)}
SECRETS = {"exotel": ("api_key", "api_token"), "plivo": ("auth_token",)}
REQUIRED = {
    "exotel": ("account_sid", "subdomain", "api_key", "api_token"),
    "plivo": ("auth_id", "auth_token"),
}


# ---------------------------------------------------------------- encryption


def _fernet() -> Fernet:
    key = config.CREDENTIALS_KEY
    if not key:
        path = config.DATA_DIR / ".credentials_key"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(Fernet.generate_key().decode())
            path.chmod(0o600)
        key = path.read_text().strip()
    return Fernet(key.encode())


def encrypt(values: dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(values).encode()).decode() if values else ""


def decrypt(token: str) -> dict[str, str]:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken:
        # The key changed (or the data dir was restored without it): ask for the credentials again.
        return {}


def secrets_of(line: PhoneLine) -> dict[str, str]:
    return decrypt(line.secrets)


def mask(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) > 4 else "••••" if value else ""


# ---------------------------------------------------------------- input


def digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def same_number(a: str, b: str) -> bool:
    """Compare on the last 10 digits, so 080..., +9180... and 9180... match."""
    da, db = digits(a), digits(b)
    return bool(da) and bool(db) and da[-10:] == db[-10:]


def clean_settings(provider: str, settings: dict[str, str], secrets: dict[str, str], existing: dict[str, str]) -> tuple[dict, dict]:
    """Validated (settings, secrets) for a line. Blank secrets keep the stored ones."""
    s = {k: str(settings.get(k, "")).strip() for k in SETTINGS[provider]}
    sec = {k: str(secrets.get(k, "")).strip() or existing.get(k, "") for k in SECRETS[provider]}
    if provider == "exotel":
        s["subdomain"] = s["subdomain"] or EXOTEL_HOSTS[0]
        if s["subdomain"] not in EXOTEL_HOSTS:
            raise HTTPException(422, f"Exotel region must be one of: {', '.join(EXOTEL_HOSTS)}")
    missing = [k for k in REQUIRED[provider] if not (s.get(k) or sec.get(k))]
    if missing:
        raise HTTPException(422, f"Missing: {', '.join(k.replace('_', ' ') for k in missing)}")
    for k in ("account_sid", "auth_id", "flow_app_id"):
        if s.get(k) and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", s[k]):
            raise HTTPException(422, f"{k.replace('_', ' ')} looks wrong: letters and numbers only")
    return s, sec


def line_out(line: PhoneLine) -> dict:
    """A line for the browser: settings, with secrets masked."""
    data = line.model_dump(exclude={"secrets"})
    data["secrets"] = {k: mask(v) for k, v in secrets_of(line).items()}
    data["urls"] = urls(line)
    return data


def urls(line: PhoneLine) -> dict[str, str]:
    """What the client pastes into their provider (Exotel), or what we set for them (Plivo)."""
    base = config.PUBLIC_BASE_URL
    if not base.startswith("https://"):
        return {}
    wss = "wss://" + base.removeprefix("https://")
    if line.provider == "exotel":
        return {"voicebot": f"{wss}/ws/telephony/line/{line.id}"}
    return {"answer": f"{base}/telephony/plivo/{line.id}/answer"}


# ---------------------------------------------------------------- checking and connecting


def _exotel_auth(line: PhoneLine) -> tuple[str, str]:
    sec = secrets_of(line)
    return sec.get("api_key", ""), sec.get("api_token", "")


def _plivo_auth(line: PhoneLine) -> tuple[str, str]:
    return line.settings.get("auth_id", ""), secrets_of(line).get("auth_token", "")


def _plivo_number(line: PhoneLine) -> str:
    return digits(line.number)  # Plivo wants E.164 without the "+", e.g. 918031234567


def _reason(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        text = body.get("error") or body.get("message") or body.get("RestException", {}).get("Message") or resp.text
    except ValueError:
        text = resp.text
    return str(text)[:300]


async def check(line: PhoneLine) -> tuple[str, str]:
    """(status, detail): do the credentials work, and is the number on this account?"""
    if line.provider == "exotel":
        return await _check_exotel(line)
    return await _check_plivo(line)


async def _check_exotel(line: PhoneLine) -> tuple[str, str]:
    """Exotel answers 401 (not 404) when the account lives in the other region, which looks just
    like a wrong key/token. So on a refusal, try the other region and switch to it if it works."""
    s = dict(line.settings)
    chosen = s["subdomain"]
    hosts = [chosen, *(h for h in EXOTEL_HOSTS if h != chosen)]
    try:
        async with httpx.AsyncClient(timeout=15, auth=_exotel_auth(line)) as client:
            for host in hosts:
                resp = await client.get(f"https://{host}/v2_beta/Accounts/{s['account_sid']}/IncomingPhoneNumbers")
                if resp.status_code not in (401, 403, 404):
                    break
            if resp.status_code >= 300:
                if resp.status_code in (401, 403, 404):
                    return "error", (
                        "Exotel refused these credentials in both regions. Check the account SID, API key "
                        f"and API token on Exotel's API settings page. Exotel said: {_reason(resp)}"
                    )
                return "error", f"Exotel answered {resp.status_code}: {_reason(resp)}"
            # Numbers Exotel allocated by hand may be missing from this list, so a number the
            # account has recently called from counts too.
            found = _has_number(resp.text, line.number)
            if not found:
                calls = await client.get(f"https://{host}/v1/Accounts/{s['account_sid']}/Calls.json?PageSize=50")
                found = calls.status_code < 300 and _has_number(calls.text, line.number)
    except httpx.HTTPError as e:
        return "error", f"Could not reach Exotel: {e}"

    notes = []
    if host != chosen:
        s["subdomain"] = host
        line.settings = s  # reassign so the JSON column is saved
        notes.append(f"Region switched to {host}: this account lives there.")
    warnings = []
    if not found:
        warnings.append("Credentials work, but this ExoPhone isn't on the account's number list or in its recent calls.")
    if not s.get("flow_app_id"):
        warnings.append("Add the flow (app) ID to place outbound calls.")
    if warnings:
        return "warning", " ".join(notes + warnings)
    return "ok", " ".join(["Credentials work and the ExoPhone is on this account.", *notes])


def _has_number(text: str, number: str) -> bool:
    return digits(number)[-10:] in digits(text)


async def _check_plivo(line: PhoneLine) -> tuple[str, str]:
    auth_id, _ = auth = _plivo_auth(line)
    try:
        async with httpx.AsyncClient(timeout=15, auth=auth) as client:
            resp = await client.get(f"{PLIVO_API}/{auth_id}/Number/{_plivo_number(line)}/")
    except httpx.HTTPError as e:
        return "error", f"Could not reach Plivo: {e}"
    if resp.status_code == 401:
        return "error", "Plivo refused the Auth ID / Auth Token."
    if resp.status_code == 404:
        return "error", "This number isn't on that Plivo account. Use the full number with country code."
    if resp.status_code >= 300:
        return "error", f"Plivo answered {resp.status_code}: {_reason(resp)}"
    return "ok", "Credentials work and the number is on this account."


async def connect_plivo(line: PhoneLine) -> tuple[str, str]:
    """Point the client's Plivo number at us: create (or update) our application in their account
    and link the number to it. The number's previous application is remembered for disconnect."""
    answer_url = urls(line).get("answer")
    if not answer_url:
        return "warning", "Credentials work. Set PUBLIC_BASE_URL to an https URL so inbound calls can be connected."
    auth_id, _ = auth = _plivo_auth(line)
    base = f"{PLIVO_API}/{auth_id}"
    settings = dict(line.settings)
    app_body = {"answer_url": answer_url, "answer_method": "POST"}
    try:
        async with httpx.AsyncClient(timeout=15, auth=auth) as client:
            number = await client.get(f"{base}/Number/{_plivo_number(line)}/")
            current = _app_id_from(number.json().get("application")) if number.status_code < 300 else ""

            app_id = settings.get("app_id", "")
            if app_id:
                resp = await client.post(f"{base}/Application/{app_id}/", json=app_body)
                if resp.status_code == 404:
                    app_id = ""  # deleted in their console: make a new one
                elif resp.status_code >= 300:
                    return "error", f"Plivo refused to update our application: {_reason(resp)}"
            if not app_id:
                resp = await client.post(f"{base}/Application/", json={"app_name": f"voicepilot-{line.id}", **app_body})
                if resp.status_code >= 300:
                    return "error", f"Plivo refused to create an application: {_reason(resp)}"
                app_id = str(resp.json().get("app_id", ""))

            if current and current != app_id and not settings.get("previous_app_id"):
                settings["previous_app_id"] = current
            settings["app_id"] = app_id
            line.settings = settings  # reassign so the JSON column is saved

            if current != app_id:
                resp = await client.post(f"{base}/Number/{_plivo_number(line)}/", json={"app_id": app_id})
                if resp.status_code >= 300:
                    return "error", f"Plivo refused to link the number to our application: {_reason(resp)}"
    except (httpx.HTTPError, ValueError) as e:
        return "error", f"Could not reach Plivo: {e}"
    return "ok", "Connected: calls to this number now reach its inbound agent."


async def disconnect_plivo(line: PhoneLine) -> str:
    """Undo connect_plivo: give the number back its previous application and delete ours.
    Best effort: returns a warning to show, or ""."""
    app_id = line.settings.get("app_id")
    if not app_id:
        return ""
    auth_id, _ = auth = _plivo_auth(line)
    base = f"{PLIVO_API}/{auth_id}"
    try:
        async with httpx.AsyncClient(timeout=15, auth=auth) as client:
            previous = line.settings.get("previous_app_id", "")
            await client.post(f"{base}/Number/{_plivo_number(line)}/", json={"app_id": previous})
            resp = await client.delete(f"{base}/Application/{app_id}/")
            if resp.status_code >= 300 and resp.status_code != 404:
                return f"Remove the application voicepilot-{line.id} in the Plivo console: {_reason(resp)}"
    except httpx.HTTPError as e:
        return f"Could not reach Plivo to disconnect the number: {e}"
    return ""


def _app_id_from(application: str | None) -> str:
    """Plivo returns the linked application as a path: /v1/Account/MA.../Application/12345/."""
    if not application:
        return ""
    parts = [p for p in str(application).split("/") if p]
    return parts[-1] if parts else ""


async def check_and_connect(line: PhoneLine) -> None:
    """Check a line and, for Plivo, connect it. Updates the line's status in place."""
    status, detail = await check(line)
    if status != "error" and line.provider == "plivo":
        status, detail = await connect_plivo(line)
    line.status, line.status_detail = status, detail
    line.checked_at = datetime.now(UTC)


def rate(line: PhoneLine | None, channel: str) -> tuple[float, int]:
    """(INR per minute, pulse seconds) for a call: the line's own rate, else the provider default."""
    default_rate, default_pulse = config.telephony_rate(channel)
    if line is None:
        return default_rate, default_pulse
    return (
        line.price_per_min if line.price_per_min is not None else default_rate,
        line.pulse_secs or default_pulse,
    )
