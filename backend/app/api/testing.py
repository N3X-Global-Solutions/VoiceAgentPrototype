"""Cheap text-only testing: chat with an agent, translate its fixed phrases, and a demo tool."""

import asyncio
import json
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agents.models import LANGUAGES, SCRIPTS, AgentConfig
from app.agents.tools import openai_tools, run_http_tool
from app.api.deps import agent_or_404
from app.core.db import get_session
from app.core.errors import NO_LLM_KEY, public_error
from app.providers import catalog
from app.providers.factory import chat_request

router = APIRouter(tags=["testing"])


class ChatIn(BaseModel):
    messages: list[dict] = Field(default_factory=list)  # [{role, content}] excluding system


class TranslateIn(BaseModel):
    language: str
    texts: dict[str, str] = Field(max_length=10)


@router.post("/api/agents/{agent_id}/chat")
async def chat(agent_id: str, body: ChatIn, db: Session = Depends(get_session)):
    """Test the agent in text: same prompt and tools as a call, no audio (~Rs 0.01-0.05 per turn)."""
    agent = agent_or_404(db, agent_id)
    cfg = AgentConfig.model_validate(agent.config)
    provider = cfg.llm_provider
    if not catalog.configured(provider):
        raise HTTPException(400, f"This agent's AI model needs {catalog.providers()[provider]['key_env']} in the server's .env.")
    prices = catalog.part(provider, "llm")["prices"]
    history = [m for m in body.messages[-20:] if m.get("role") in ("user", "assistant")]
    messages: list[dict] = [
        {"role": "system", "content": cfg.system_prompt()},
        {"role": "assistant", "content": cfg.greeting},
        *history,
    ]
    tools = openai_tools(cfg)
    tools_by_name = {t.name: t for t in cfg.tools}
    tool_log: list[dict] = []
    cost = 0.0
    ended = False
    reply = ""
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(4):  # at most 3 tool rounds, then a final answer
            data = await _chat(client, provider, messages, cfg.temperature, tools)
            usage = data.get("usage") or {}
            cost += (usage.get("prompt_tokens", 0) / 1e6 * prices["input"].rate
                     + usage.get("completion_tokens", 0) / 1e6 * prices["output"].rate)
            message = data["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if not calls:
                reply = message.get("content") or ""
                break
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "end_call":
                    ended = True
                    result = {"status": "ending call"}
                elif name in tools_by_name:
                    result = await run_http_tool(tools_by_name[name], args)
                else:
                    result = {"error": f"Unknown tool {name}"}
                tool_log.append({"name": name, "arguments": args, "result": result})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
            if ended:
                reply = cfg.goodbye_message
                break

    return {
        "reply": reply,
        "tool_calls": tool_log,
        "ended": ended,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "cost_inr": round(cost, 4),
    }


async def _chat(client: httpx.AsyncClient, provider: str, messages: list[dict], temperature: float, tools: list[dict]) -> dict:
    url, headers, extra = chat_request(provider)
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 300,
        **extra,
    }
    if tools:
        payload["tools"] = tools
    for attempt in range(2):  # one retry for transient overload / rate limit
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code in (429, 503) and attempt == 0:
            await asyncio.sleep(1.0)
            continue
        break
    if resp.status_code == 402:
        raise HTTPException(402, public_error("insufficient credits"))
    if resp.status_code >= 300:
        raise HTTPException(502, public_error(f"AI provider error {resp.status_code}: {resp.text[:300]}"))
    return resp.json()


@router.post("/api/translate")
async def translate(body: TranslateIn):
    """Translate an agent's fixed phrases (greeting, goodbye...) into its language (~Rs 0.01)."""
    if body.language not in LANGUAGES:
        raise HTTPException(422, f"Unsupported language {body.language}")
    provider = catalog.default_llm_provider()
    if provider is None:
        raise HTTPException(400, NO_LLM_KEY)
    texts = {k: v for k, v in body.texts.items() if v.strip()}
    if not texts or body.language == "en-IN":
        return {"texts": body.texts}
    name, script = LANGUAGES[body.language], SCRIPTS[body.language]
    messages = [
        {
            "role": "system",
            "content": (
                f"You translate short phrases that a voice agent speaks on phone calls into {name} ({script}). "
                f"Use natural, polite, spoken {name}, the way a friendly call-centre agent talks. "
                "Keep person names, brand names and numbers unchanged. "
                "Reply with only a JSON object that has exactly the same keys as the input."
            ),
        },
        {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        data = await _chat(client, provider, messages, temperature=0.2, tools=[])
    content = (data["choices"][0]["message"].get("content") or "").strip()
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        translated = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(502, f"Could not parse translation: {content[:200]}")
    return {"texts": {k: str(translated.get(k) or v) for k, v in body.texts.items()}}


# ---------------------------------------------------------------- demo tool (for trying tools in the UI)


@router.post("/api/demo/order-status")
async def demo_order_status(body: dict):
    """Fake order lookup. Use http://localhost:7860/api/demo/order-status as a tool URL."""
    order_id = str(body.get("order_id", "")).strip()
    if not order_id:
        return {"error": "order_id is required"}
    statuses = ["processing", "packed", "out for delivery", "delivered"]
    status = statuses[sum(map(ord, order_id)) % len(statuses)]
    eta = "already delivered" if status == "delivered" else "today by 6 PM"
    return {"order_id": order_id, "status": status, "eta": eta}
