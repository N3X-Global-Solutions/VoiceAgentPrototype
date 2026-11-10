"""Agent tools, shared by the voice pipeline and the text-chat test."""

import json

import httpx
from loguru import logger

from app.agent_config import AgentConfig, HttpTool

END_CALL_DESCRIPTION = (
    "Hang up the call. Use it only after the caller clearly says goodbye, asks to end the call, "
    "or confirms they need nothing else. Never use it right after the caller answers your question "
    "or shares information: reply to them instead."
)


def openai_tools(cfg: AgentConfig) -> list[dict]:
    """Tool definitions in OpenAI chat-completions format."""
    tools = []
    if cfg.end_call_enabled:
        tools.append(_openai_tool("end_call", END_CALL_DESCRIPTION, {}, []))
    for tool in cfg.tools:
        tools.append(_openai_tool(tool.name, tool.description, tool.parameters, tool.required))
    return tools


def _openai_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


async def run_http_tool(tool: HttpTool, args: dict) -> dict:
    """Call the tool's endpoint. Results stay small: they are re-sent to the LLM every turn."""
    logger.info(f"Tool {tool.name} called with {args}")
    try:
        async with httpx.AsyncClient(timeout=tool.timeout_secs) as client:
            if tool.method == "GET":
                resp = await client.get(tool.url, params=args, headers=tool.headers)
            else:
                resp = await client.post(tool.url, json=args, headers=tool.headers)
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:2000]
        result = {"status_code": resp.status_code, "response": body}
    except Exception as e:
        logger.warning(f"Tool {tool.name} failed: {e}")
        return {"error": f"The {tool.name} service is unavailable right now."}
    text = json.dumps(result, ensure_ascii=False)
    if len(text) > 4000:
        return {"truncated": True, "response": text[:4000]}
    return result
