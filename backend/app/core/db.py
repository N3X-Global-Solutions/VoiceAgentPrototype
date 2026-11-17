"""SQLite (via SQLModel) for the prototype. Swap DATABASE_URL for Postgres later."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, Column
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


class CallSession(SQLModel, table=True):
    id: str = Field(default_factory=_id, primary_key=True)
    agent_id: str = Field(foreign_key="agent.id", index=True)
    agent_version: int
    channel: str  # browser | twilio | exotel | plivo | chat
    direction: str = "inbound"  # inbound | outbound
    phone_number: str = ""
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
    cost_inr: float = 0
    transcript: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    latency_turns: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    error: str = ""


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""


if DATABASE_URL.startswith("sqlite:///"):
    Path(DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


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
