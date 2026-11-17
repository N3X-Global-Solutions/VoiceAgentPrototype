"""Admin sign-in: one admin account (from config) and a signed, HttpOnly session cookie."""

import hmac
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core import config
from app.core.security import COOKIE_NAME, current_user, make_token

# ---------------------------------------------------------------- login throttle

# Per client IP: at most MAX_FAILURES failed logins per WINDOW_SECS. In memory, which is
# enough for the single-process server this app runs as.
MAX_FAILURES = 8
WINDOW_SECS = 15 * 60
_failures: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _recent_failures(ip: str) -> deque[float]:
    attempts = _failures[ip]
    while attempts and attempts[0] < time.time() - WINDOW_SECS:
        attempts.popleft()
    return attempts


# ---------------------------------------------------------------- routes

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


def _set_cookie(response: Response, request: Request, value: str, max_age: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = _client_ip(request)
    attempts = _recent_failures(ip)
    if len(attempts) >= MAX_FAILURES:
        raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")
    email_ok = hmac.compare_digest(body.email.strip().lower().encode(), config.ADMIN_EMAIL.lower().encode())
    password_ok = hmac.compare_digest(body.password.encode(), config.ADMIN_PASSWORD.encode())
    if not (email_ok and password_ok):
        attempts.append(time.time())
        raise HTTPException(401, "Incorrect email or password.")
    attempts.clear()
    _set_cookie(response, request, make_token(config.ADMIN_EMAIL), config.SESSION_TTL_HOURS * 3600)
    return {"email": config.ADMIN_EMAIL}


@router.post("/logout")
def logout(request: Request, response: Response):
    _set_cookie(response, request, "", 0)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    email = current_user(request)
    if not email:
        raise HTTPException(401, "Not signed in")
    return {"email": email}
