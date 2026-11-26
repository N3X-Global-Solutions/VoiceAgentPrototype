"""SQLite (via SQLModel) for the prototype. Swap DATABASE_URL for Postgres later."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, Column, inspect, text
from sqlmodel import Field, Session, SQLModel, create_engine

from app.core.config import DATABASE_URL


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return uuid4().hex[:12]


class Client(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    name: str
    industry: str = ""
    contact_name: str = ""
    contact_phone: str = ""
    notes: str = ""
    created_at: datetime = Field(default_factory=_now)


class Agent(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    client_id: str = Field(foreign_key="client.id", index=True)
    name: str
    config: dict = Field(sa_column=Column(JSON, nullable=False))
    version: int = 1
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PhoneLine(SQLModel, table=True):
    """A client's own phone number on their own Exotel or Plivo account (bring your own number)."""

    id: str = Field(default_factory=_id, primary_key=True)
    client_id: str = Field(foreign_key="client.id", index=True)
    provider: str  # exotel | plivo
    label: str = ""
    number: str  # the number customers call, and the caller ID for outbound calls
    inbound_agent_id: str = ""  # the agent that answers calls to this number
    # Non-secret account settings: exotel {account_sid, subdomain, flow_app_id};
    # plivo {auth_id, app_id, previous_app_id}. The app ids are set by us when we connect the number.
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # API key/token, encrypted (app.telephony.lines). Never sent to the browser.
    secrets: str = ""
    # Phone-line rate for this number's calls; None = the provider default from .env.
    price_per_min: float | None = None
    pulse_secs: int | None = None
    status: str = "unchecked"  # unchecked | ok | warning | error
    status_detail: str = ""
    checked_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class CallSession(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    agent_version: int
    channel: str  # browser | twilio | exotel | plivo | chat
    direction: str = "inbound"  # inbound | outbound
    phone_number: str = ""
    line_id: str = ""  # the client's PhoneLine the call used; "" = the workspace number from .env
    provider_call_id: str = ""
    status: str = "active"  # active | completed | failed
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    duration_secs: float = 0
    turns: int = 0
    latency_avg_ms: float | None = None
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_max_ms: float | None = None
    stt_seconds: float = 0
    tts_chars: int = 0
    llm_prompt_tokens: int = 0
    llm_cached_tokens: int = 0
    llm_completion_tokens: int = 0
    cost_inr: float = 0  # total: voice AI + phone line
    # Per-part cost in INR: {stt, tts, llm, telephony, telephony_billed_secs}. Empty for older calls.
    cost_breakdown: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=True))
    # Provider per part: {stt, llm, tts}. Empty for calls made before provider choice existed (all Sarvam).
    providers: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=True))
    transcript: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    latency_turns: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    error: str = ""


class UsageCharge(SQLModel, table=True):
    """Provider spend outside calls: text chat tests and phrase translation (AI model tokens)."""

    id: str = Field(default_factory=_id, primary_key=True)
    at: datetime = Field(default_factory=_now, index=True)
    provider: str = Field(index=True)
    part: str = "llm"
    source: str = "chat"  # chat | translate
    agent_id: str = ""
    amount_inr: float = 0
    input_tokens: int = 0
    output_tokens: int = 0


class CreditEntry(SQLModel, table=True):
    """Credits you hold with a provider. "balance" = the balance its dashboard showed at that time;
    "topup" = credits added. Remaining = latest balance + later top-ups - spend since."""

    id: str = Field(default_factory=_id, primary_key=True)
    provider: str = Field(index=True)
    kind: str  # balance | topup
    amount_inr: float
    note: str = ""
    at: datetime = Field(default_factory=_now)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""


if DATABASE_URL.startswith("sqlite:///"):
    Path(DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all() never alters existing tables, so add columns introduced since (SQLite-safe)."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing:
                    kind = column.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'))


def get_session():
    with Session(engine) as session:
        yield session


def get_setting(key: str) -> str:
    """A workspace-wide setting (e.g. inbound_agent_id), or "" if unset."""
    with Session(engine) as db:
        row = db.get(Setting, key)
        return row.value if row else ""


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key) or Setting(key=key)
    row.value = value
    db.add(row)
