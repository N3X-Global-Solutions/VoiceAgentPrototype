"""Session tokens and the API guard. The login routes that issue tokens are in app.api.auth.

The cookie holds "<email>|<expiry>|<signature>", HMAC-SHA256-signed with SESSION_SECRET, so no
session table is needed. It is HttpOnly (JavaScript can't read it) and SameSite=Lax, and it is
marked Secure when the request came in over HTTPS (via the reverse proxy).
"""

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import config

COOKIE_NAME = "vas_session"

# /api paths that work without a session. Everything else under /api needs one.
# - health/login/logout/me: the login page needs them before anyone is signed in.
# - demo/order-status: the agent itself calls this mock tool over HTTP during calls.
# Telephony webhooks (/telephony/*, /ws/telephony*) are outside /api, so they stay
# reachable by Twilio and Exotel.
PUBLIC_API_PATHS = {
    "/api/healthz",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/demo/order-status",
}


def _secret() -> bytes:
    """SESSION_SECRET from the environment, else one generated once and kept in the data dir."""
    if config.SESSION_SECRET:
        return config.SESSION_SECRET.encode()
    path = config.DATA_DIR / ".session_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48))
        path.chmod(0o600)
    return path.read_text().strip().encode()


# The admin password is part of the key, so changing it signs out every existing session.
SIGNING_KEY = hashlib.sha256(_secret() + b"\0" + config.ADMIN_PASSWORD.encode()).digest()


def _sign(payload: str) -> str:
    mac = hmac.new(SIGNING_KEY, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def make_token(email: str) -> str:
    expires = int(time.time()) + config.SESSION_TTL_HOURS * 3600
    payload = f"{email}|{expires}"
    return f"{payload}|{_sign(payload)}"


def read_token(token: str | None) -> str | None:
    """The signed-in email, or None if the token is missing, tampered with or expired."""
    if not token or token.count("|") != 2:
        return None
    email, expires, signature = token.split("|")
    if not hmac.compare_digest(signature, _sign(f"{email}|{expires}")):
        return None
    if not expires.isdigit() or int(expires) < time.time():
        return None
    if email.lower() != config.ADMIN_EMAIL.lower():  # admin email changed since login
        return None
    return email


def current_user(request: Request) -> str | None:
    return read_token(request.cookies.get(COOKIE_NAME))


class AuthMiddleware:
    """Plain ASGI middleware (not BaseHTTPMiddleware), so it never wraps the response stream:
    a browser call runs as a background task of its /offer request for the whole call."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope["path"]
            if path.startswith("/api/") and path not in PUBLIC_API_PATHS and scope["method"] != "OPTIONS":
                if not read_token(Request(scope).cookies.get(COOKIE_NAME)):
                    await JSONResponse({"detail": "Not signed in"}, status_code=401)(scope, receive, send)
                    return
        await self.app(scope, receive, send)
