"""Spend per provider (voice AI and phone lines) and the credits left with each.

Spend comes from what we already record: each call's cost breakdown (split by the provider
that handled each part) plus UsageCharge rows for text tests and translation. Providers
don't offer a balance API, so credits are entered by hand: a "balance" entry copies the
figure from the provider's dashboard, "topup" entries add credits after it, and
remaining = balance + later top-ups - spend since the balance was entered.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.core import config
from app.core.db import CallSession, CreditEntry, UsageCharge, get_setting
from app.providers import catalog

PHONE_LINES = {"exotel": "Exotel", "twilio": "Twilio"}
PARTS = ("stt", "tts", "llm", "telephony", "other")
BURN_DAYS = 7  # "days left" uses the average daily spend over this many days
DEFAULT_ALERT_SHARE = 0.2  # without an alert set, warn when 20% of the funded credits are left


def alert_key(provider: str) -> str:
    return f"credit_alert:{provider}"


def accounts() -> list[dict]:
    """Every provider that can cost money: voice AI providers, then phone lines."""
    ai = [
        {"id": p, "name": info["name"], "kind": "voice_ai", "configured": catalog.configured(p)}
        for p, info in catalog.providers().items()
    ]
    phone = [
        {"id": "exotel", "name": "Exotel", "kind": "phone", "configured": config.exotel_configured()},
        {"id": "twilio", "name": "Twilio", "kind": "phone", "configured": config.twilio_configured()},
    ]
    return ai + phone


def _utc(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes; everything here is compared as aware UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


@dataclass
class Spend:
    at: datetime
    provider: str
    part: str
    inr: float
    source: str  # call | chat | translate
    ref: str  # call id, or charge id
    units: dict = field(default_factory=dict)


def _call_spend(c: CallSession) -> Iterable[Spend]:
    at = _utc(c.started_at)
    prov = {"stt": "sarvam", "llm": "sarvam", "tts": "sarvam", **(c.providers or {})}
    b = c.cost_breakdown or {}
    if not any(k in b for k in ("stt", "tts", "llm")):
        # Calls from before the per-part breakdown: all Sarvam, cost not split.
        if c.cost_inr:
            yield Spend(at, "sarvam", "other", c.cost_inr, "call", c.id)
        return
    rates = b.get("rates") or {}
    stt_secs = c.duration_secs if rates.get("stt_billing") == "connected" else c.stt_seconds
    yield Spend(at, prov["stt"], "stt", b.get("stt", 0), "call", c.id, {"stt_secs": stt_secs})
    yield Spend(at, prov["tts"], "tts", b.get("tts", 0), "call", c.id, {"tts_chars": c.tts_chars})
    yield Spend(
        at,
        prov["llm"],
        "llm",
        b.get("llm", 0),
        "call",
        c.id,
        {"input_tokens": c.llm_prompt_tokens, "output_tokens": c.llm_completion_tokens},
    )
    # A client's own number (line_id) is billed to the client's account, not to your credits.
    if c.channel in PHONE_LINES and not c.line_id and (b.get("telephony") or b.get("telephony_billed_secs")):
        yield Spend(at, c.channel, "telephony", b.get("telephony", 0), "call", c.id, {"phone_secs": b.get("telephony_billed_secs", 0)})


def spend_since(db: Session, since: datetime | None) -> list[Spend]:
    calls = select(CallSession)
    charges = select(UsageCharge)
    if since is not None:
        calls = calls.where(CallSession.started_at >= since)
        charges = charges.where(UsageCharge.at >= since)
    out = [s for c in db.exec(calls) for s in _call_spend(c)]
    out += [
        Spend(_utc(u.at), u.provider, u.part, u.amount_inr, u.source, u.id, {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens})
        for u in db.exec(charges)
    ]
    return out


def _alert(provider: str) -> float | None:
    raw = get_setting(alert_key(provider))
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def credit_status(db: Session, spend: list[Spend] | None = None) -> dict[str, dict]:
    """Remaining credits for each provider that has credit entries. `spend` must reach back
    to the oldest anchor (pass None to query it)."""
    entries = db.exec(select(CreditEntry).order_by(CreditEntry.at)).all()
    by_provider: dict[str, list[CreditEntry]] = defaultdict(list)
    for e in entries:
        by_provider[e.provider].append(e)
    if not by_provider:
        return {}

    anchors: dict[str, tuple[datetime, float, float]] = {}  # provider -> (since, balance, top-ups)
    for p, items in by_provider.items():
        balances = [e for e in items if e.kind == "balance"]
        if balances:
            last = balances[-1]
            since = _utc(last.at)
            topups = sum(e.amount_inr for e in items if e.kind == "topup" and _utc(e.at) > since)
            anchors[p] = (since, last.amount_inr, topups)
        else:
            anchors[p] = (_utc(items[0].at), 0.0, sum(e.amount_inr for e in items))

    if spend is None:
        spend = spend_since(db, min(a[0] for a in anchors.values()))
    now = datetime.now(UTC)
    recent = now - timedelta(days=BURN_DAYS)

    out: dict[str, dict] = {}
    for p, (since, balance, topups) in anchors.items():
        used = sum(s.inr for s in spend if s.provider == p and s.at >= since)
        burned = sum(s.inr for s in spend if s.provider == p and s.at >= max(since, recent))
        days_tracked = max((now - max(since, recent)).total_seconds() / 86400, 1)
        per_day = burned / days_tracked
        funded = balance + topups
        remaining = funded - used
        alert = _alert(p)
        threshold = alert if alert is not None else funded * DEFAULT_ALERT_SHARE
        status = "empty" if remaining <= 0 else "low" if remaining < threshold else "ok"
        out[p] = {
            "since": since.isoformat(),
            "balance_at_since": round(balance, 2),
            "topups": round(topups, 2),
            "funded": round(funded, 2),
            "used": round(used, 4),
            "remaining": round(remaining, 2),
            "per_day": round(per_day, 4),
            "days_left": round(remaining / per_day, 1) if per_day > 0 and remaining > 0 else None,
            "alert_below": alert,
            "alert_threshold": round(threshold, 2),
            "status": status,
        }
    return out


def usage_report(db: Session, days: int, tz_offset_min: int = 0) -> dict:
    """Spend per provider over the last `days` days (0 = all time), a daily series, and credits.
    tz_offset_min is the browser's getTimezoneOffset(), so days split at local midnight."""
    now = datetime.now(UTC)
    local = timedelta(minutes=-tz_offset_min)
    since = None
    if days > 0:
        start_local = (now + local).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        since = start_local - local

    entries = db.exec(select(CreditEntry).order_by(CreditEntry.at.desc())).all()
    oldest_anchor = min((_utc(e.at) for e in entries), default=None)
    prev_since = since - timedelta(days=days) if since is not None else None
    reach = prev_since if prev_since is None or oldest_anchor is None else min(prev_since, oldest_anchor)
    spend = spend_since(db, reach)
    credits = credit_status(db, spend)
    in_period = [s for s in spend if since is None or s.at >= since]
    prev_total = sum(s.inr for s in spend if prev_since is not None and prev_since <= s.at < since) if since else None

    calls = select(CallSession.duration_secs).where(CallSession.channel != "chat")
    if since is not None:
        calls = calls.where(CallSession.started_at >= since)
    durations = db.exec(calls).all()

    totals: dict[str, dict] = {}
    for a in accounts():
        totals[a["id"]] = {
            **a,
            "spent": 0.0,
            "by_part": dict.fromkeys(PARTS, 0.0),
            "units": {"stt_secs": 0.0, "tts_chars": 0, "input_tokens": 0, "output_tokens": 0, "phone_secs": 0},
            "calls": set(),
            "tests": 0,
        }
    daily: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for s in in_period:
        t = totals.get(s.provider)
        if t is None:
            continue
        t["spent"] += s.inr
        t["by_part"][s.part] += s.inr
        for k, v in s.units.items():
            t["units"][k] += v or 0
        if s.source == "call":
            t["calls"].add(s.ref)
        else:
            t["tests"] += 1
        daily[(s.at + local).date().isoformat()][s.provider] += s.inr

    providers = []
    for p, t in totals.items():
        providers.append(
            {
                **{k: v for k, v in t.items() if k not in ("calls", "spent", "by_part")},
                "spent": round(t["spent"], 4),
                "by_part": {k: round(v, 4) for k, v in t["by_part"].items() if v},
                "calls": len(t["calls"]),
                "credit": credits.get(p),
                "entries": [
                    {"id": e.id, "kind": e.kind, "amount_inr": e.amount_inr, "note": e.note, "at": _utc(e.at).isoformat()}
                    for e in entries
                    if e.provider == p
                ][:20],
            }
        )

    first_day = (since + local).date() if since else (min((s.at for s in in_period), default=now) + local).date()
    last_day = (now + local).date()
    series = []
    d = first_day
    while d <= last_day:
        key = d.isoformat()
        series.append({"date": key, "by_provider": {p: round(v, 4) for p, v in daily.get(key, {}).items()}})
        d += timedelta(days=1)

    return {
        "since": since.isoformat() if since else None,
        "days": days,
        "total": round(sum(p["spent"] for p in providers), 4),
        "prev_total": round(prev_total, 4) if prev_total is not None else None,  # the period before, same length
        "calls": len(durations),
        "call_minutes": round(sum(d or 0 for d in durations) / 60, 2),
        "providers": providers,
        "daily": series,
    }
