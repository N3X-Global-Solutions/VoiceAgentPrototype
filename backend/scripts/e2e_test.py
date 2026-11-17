"""End-to-end test of a real voice agent, driven by synthetic caller speech.

What it does (against a running backend, with a real SARVAM_API_KEY):
  1. Creates a test client + agent with an HTTP tool (served by a local mock) and end_call.
  2. Text chat: 2 turns through the LLM.
  3. Browser call over WebRTC: speaks 3 caller lines generated with Sarvam TTS.
  4. Phone call over the telephony WebSocket (Exotel wire format, 8 kHz): same 3 lines.
     No Twilio/Exotel account is needed: this script plays the phone provider.
  5. Prints per-turn latency (server-measured and caller-measured), cost and pass/fail checks.

Costs roughly Rs 2-3 of Sarvam credits.

Usage (backend running on :7860):
    cd backend && uv run python scripts/e2e_test.py
    options: --base URL  --skip-chat --skip-browser --skip-phone --cleanup --yes
"""

import argparse
import asyncio
import base64
import io
import json
import sys
import time
import wave
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import httpx
import numpy as np
import uvicorn
import websockets
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from av import AudioFrame
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core import config  # noqa: E402  (loads .env)

# Session cookie from signing in as the admin (the API needs it); set in main().
AUTH_COOKIES: dict[str, str] = {}

CALLER_LINES = [
    "Hi, can you tell me what you can help me with?",
    "I want to know the status of my order. The order number is one two three four.",
    "Great, thank you. That's all, bye.",
]
CALLER_VOICE = "dev_en_conversational"
SPEECH_RMS = 300  # int16 RMS above which audio counts as speech
TOOL_PORT = 7871

AGENT_CONFIG = {
    "greeting": "Hello, this is Riya from Acme Store. How can I help you today?",
    "instructions": (
        "You are Riya, a customer support agent for Acme Store, an online shop. "
        "You help callers with the status of their orders. "
        "When the caller gives an order number, call check_order_status with the digits only, "
        "then tell them the status and delivery time in one short sentence. "
        "If the caller says goodbye or has nothing else, call end_call."
    ),
    "language": "en-IN",
    "voice": "ishita_en_customer",
    "max_call_seconds": 120,
    "tools": [
        {
            "name": "check_order_status",
            "description": "Look up the delivery status of an order by its order number.",
            "method": "POST",
            "url": f"http://127.0.0.1:{TOOL_PORT}/order-status",
            "parameters": {"order_id": {"type": "string", "description": "Order number, digits only"}},
            "required": ["order_id"],
        }
    ],
}

tool_calls: list[dict] = []


# --------------------------------------------------------------------------- helpers


def ok(flag: bool) -> str:
    return "PASS" if flag else "FAIL"


def build_mock_tool_server() -> uvicorn.Server:
    app = FastAPI()

    @app.post("/order-status")
    async def order_status(body: dict):
        tool_calls.append(body)
        return {"order_id": body.get("order_id"), "status": "out for delivery", "eta": "today by 6 PM"}

    return uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=TOOL_PORT, log_level="warning"))


async def synthesize(text: str) -> bytes:
    """Caller speech as 16 kHz mono PCM16, via Sarvam TTS REST (~Rs 0.05 per line)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": config.SARVAM_API_KEY},
            json={
                "text": text,
                "language_code": "en-IN",
                "speaker": CALLER_VOICE,
                "model": "bulbul:v4-flash",
                "speech_sample_rate": 16000,
            },
        )
    resp.raise_for_status()
    wav_bytes = base64.b64decode("".join(resp.json()["audios"]))
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getframerate() == 16000 and w.getsampwidth() == 2, "unexpected TTS format"
        pcm = w.readframes(w.getnframes())
        if w.getnchannels() == 2:
            pcm = np.frombuffer(pcm, np.int16).reshape(-1, 2).mean(axis=1).astype(np.int16).tobytes()
    return pcm


def trim_silence(pcm16k: bytes, threshold: int = 300, pad_ms: int = 40) -> bytes:
    """Cut leading/trailing silence so 'caller-heard' latency starts at the real end of speech."""
    samples = np.frombuffer(pcm16k, np.int16)
    window = 160  # 10 ms
    levels = [rms(samples[i : i + window]) for i in range(0, len(samples), window)]
    loud = [i for i, lv in enumerate(levels) if lv > threshold]
    if not loud:
        return pcm16k
    pad = pad_ms // 10
    start = max(0, (loud[0] - pad) * window)
    end = min(len(samples), (loud[-1] + 1 + pad) * window)
    return samples[start:end].tobytes()


def to_8k(pcm16k: bytes) -> bytes:
    samples = np.frombuffer(pcm16k, np.int16)
    samples = samples[: len(samples) // 2 * 2].reshape(-1, 2).mean(axis=1)
    return samples.astype(np.int16).tobytes()


def rms(pcm: np.ndarray) -> float:
    return float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if pcm.size else 0.0


class CallerAudio:
    """Real-time caller audio: silence until a line is queued, then the line."""

    def __init__(self, sample_rate: int):
        self.rate = sample_rate
        self.chunk_bytes = sample_rate // 50 * 2  # 20 ms
        self._queue = bytearray()
        self.line_ended_at: float | None = None
        self.line_done = asyncio.Event()

    def say(self, pcm: bytes):
        self.line_done.clear()
        self.line_ended_at = None
        self._queue.extend(pcm)

    def next_chunk(self) -> bytes:
        had_audio = bool(self._queue)
        chunk = bytes(self._queue[: self.chunk_bytes])
        del self._queue[: self.chunk_bytes]
        if had_audio and not self._queue:
            self.line_ended_at = time.time()
            self.line_done.set()
        return chunk.ljust(self.chunk_bytes, b"\0")


class AgentListener:
    """Watches the agent's audio to find when it starts and stops talking."""

    def __init__(self):
        self.last_speech_at = 0.0
        self.onsets: list[float] = []
        self.closed = False

    def feed(self, level: float):
        now = time.time()
        if level > SPEECH_RMS:
            if now - self.last_speech_at > 0.4:
                self.onsets.append(now)
            self.last_speech_at = now

    async def wait_onset_after(self, t: float, timeout: float) -> float | None:
        deadline = time.time() + timeout
        while time.time() < deadline and not self.closed:
            for onset in self.onsets:
                if onset > t:
                    return onset
            await asyncio.sleep(0.02)
        return None

    async def wait_quiet(self, quiet_secs: float, timeout: float):
        deadline = time.time() + timeout
        while time.time() < deadline and not self.closed:
            if time.time() - self.last_speech_at > quiet_secs:
                return
            await asyncio.sleep(0.05)


async def converse(caller: CallerAudio, agent: AgentListener, lines_pcm: list[bytes]) -> dict:
    """Wait for the greeting, then speak each line once the agent goes quiet."""
    result = {"greeting_heard": False, "client_latency_ms": []}
    start = time.time()
    greeting = await agent.wait_onset_after(start, timeout=15)
    result["greeting_heard"] = greeting is not None
    await agent.wait_quiet(1.2, timeout=20)
    for pcm in lines_pcm:
        caller.say(pcm)
        await asyncio.wait_for(caller.line_done.wait(), timeout=30)
        ended = caller.line_ended_at or time.time()
        onset = await agent.wait_onset_after(ended, timeout=15)
        result["client_latency_ms"].append(round((onset - ended) * 1000) if onset else None)
        await agent.wait_quiet(1.5, timeout=25)
    return result


async def wait_for_call_record(client: httpx.AsyncClient, base: str, agent_id: str, channel: str, after: float, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        calls = (await client.get(f"{base}/api/calls", params={"agent_id": agent_id})).json()
        for c in calls:
            if c["channel"] == channel and c["status"] != "active":
                return c
        await asyncio.sleep(1)
    return None


async def wait_for_call_record_since(client: httpx.AsyncClient, base: str, agent_id: str, after: float, timeout=30):
    """The newest finished call that started after `after` (UTC)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for c in (await client.get(f"{base}/api/calls", params={"agent_id": agent_id})).json():
            started = datetime.fromisoformat(c["started_at"])
            started = started if started.tzinfo else started.replace(tzinfo=UTC)
            if started.timestamp() >= after - 1 and c["status"] != "active":
                return c
        await asyncio.sleep(1)
    return None


# --------------------------------------------------------------------------- tests


async def browser_call(base: str, agent_id: str, lines: list[bytes]) -> dict:
    caller = CallerAudio(16000)
    agent = AgentListener()

    class CallerTrack(MediaStreamTrack):
        kind = "audio"

        def __init__(self):
            super().__init__()
            self._pts = 0
            self._t0: float | None = None

        async def recv(self):
            if self._t0 is None:
                self._t0 = time.time()
            delay = self._t0 + self._pts / 16000 - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            samples = np.frombuffer(caller.next_chunk(), np.int16).reshape(1, -1)
            frame = AudioFrame.from_ndarray(samples, format="s16", layout="mono")
            frame.sample_rate = 16000
            frame.pts = self._pts
            frame.time_base = Fraction(1, 16000)
            self._pts += samples.shape[1]
            return frame

    pc = RTCPeerConnection()
    pc.addTrack(CallerTrack())
    pc.createDataChannel("chat")

    @pc.on("track")
    def on_track(track):
        async def consume():
            try:
                while True:
                    frame = await track.recv()
                    agent.feed(rms(frame.to_ndarray()))
            except MediaStreamError:
                agent.closed = True

        asyncio.ensure_future(consume())

    @pc.on("connectionstatechange")
    async def on_state():
        if pc.connectionState in ("closed", "failed"):
            agent.closed = True

    await pc.setLocalDescription(await pc.createOffer())
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.05)
    async with httpx.AsyncClient(timeout=30, cookies=AUTH_COOKIES) as client:
        resp = await client.post(
            f"{base}/api/agents/{agent_id}/offer",
            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        )
    resp.raise_for_status()
    answer = resp.json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

    result = await converse(caller, agent, lines)
    # Give the agent time to say goodbye and hang up via end_call.
    for _ in range(100):
        if agent.closed:
            break
        await asyncio.sleep(0.2)
    result["ended_by_agent"] = agent.closed
    result["hung_up_at"] = time.time()
    await pc.close()
    return result


async def phone_call(base: str, agent_id: str, lines_16k: list[bytes]) -> dict:
    caller = CallerAudio(8000)
    agent = AgentListener()
    ws_url = base.replace("http", "ws", 1) + f"/ws/telephony/{agent_id}"
    stream_sid = f"e2e{int(time.time())}"
    async with websockets.connect(ws_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "event": "start",
                    "sequence_number": 1,
                    "stream_sid": stream_sid,
                    "start": {
                        "stream_sid": stream_sid,
                        "call_sid": f"call-{stream_sid}",
                        "account_sid": "e2e-test",
                        "from": "+919800000001",
                        "to": "+918000000000",
                        "media_format": {"encoding": "base64", "sample_rate": "8000", "bit_rate": "128kbps"},
                    },
                }
            )
        )

        async def send_audio():
            seq, t0 = 2, time.time()
            try:
                while True:
                    delay = t0 + (seq - 2) * 0.02 - time.time()
                    if delay > 0:
                        await asyncio.sleep(delay)
                    payload = base64.b64encode(caller.next_chunk()).decode()
                    await ws.send(json.dumps({
                        "event": "media",
                        "sequence_number": seq,
                        "stream_sid": stream_sid,
                        "media": {"chunk": seq, "timestamp": str((seq - 2) * 20), "payload": payload},
                    }))
                    seq += 1
            except websockets.ConnectionClosed:
                agent.closed = True

        async def receive_audio():
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("event") == "media":
                        pcm = np.frombuffer(base64.b64decode(msg["media"]["payload"]), np.int16)
                        agent.feed(rms(pcm))
            except websockets.ConnectionClosed:
                pass
            agent.closed = True

        sender = asyncio.create_task(send_audio())
        receiver = asyncio.create_task(receive_audio())
        result = await converse(caller, agent, [to_8k(p) for p in lines_16k])
        for _ in range(100):
            if agent.closed:
                break
            await asyncio.sleep(0.2)
        result["ended_by_agent"] = agent.closed
        result["hung_up_at"] = time.time()
        sender.cancel()
        receiver.cancel()
    return result


def print_call_report(name: str, call: dict | None, client_side: dict):
    print(f"\n=== {name} ===")
    if not call:
        print("  FAIL  no call record saved")
        return
    print(f"  status={call['status']} duration={call['duration_secs']}s turns={call['turns']} cost=Rs {call['cost_inr']:.2f}")
    if call["error"]:
        print(f"  error: {call['error'][:200]}")
    print("  turn | total | STT | LLM 1st text | TTS 1st audio  (server, ms)   | caller-heard (ms)")
    heard = client_side.get("client_latency_ms", [])
    for i, t in enumerate(call["latency_turns"]):
        c = heard[i] if i < len(heard) else None
        print(
            f"  {t['turn']:>4} | {t['total_ms']:>5} | {t['transcript_ms'] or '-':>3} | "
            f"{t['llm_first_text_ms'] or '-':>12} | {t['tts_first_audio_ms'] or '-':>13} | {c if c is not None else '-':>17}"
        )
    print(f"  server avg/p50/p95: {call['latency_avg_ms']}/{call['latency_p50_ms']}/{call['latency_p95_ms']} ms")
    valid = [h for h in heard if h is not None]
    if valid:
        print(f"  caller-heard avg: {round(sum(valid) / len(valid))} ms  (includes Sarvam's end-of-speech wait)")
    print("  transcript:")
    for line in call["transcript"]:
        print(f"    {line['role']:>5}: {line['text']}")


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:7860")
    parser.add_argument("--skip-chat", action="store_true")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--skip-phone", action="store_true")
    parser.add_argument("--cleanup", action="store_true", help="delete the test client afterwards")
    parser.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    parser.add_argument("--turn-detection", choices=["sarvam", "fast"], default="sarvam")
    parser.add_argument("--end-of-speech-ms", type=int, default=None, help="pause that ends the caller's turn")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="phone-path call for each latency setting (sarvam default, sarvam 400 ms, fast 300 ms) + summary table",
    )
    args = parser.parse_args()
    if args.compare:
        args.skip_chat = args.skip_browser = args.skip_phone = True
    AGENT_CONFIG["turn_detection"] = args.turn_detection
    AGENT_CONFIG["end_of_speech_ms"] = args.end_of_speech_ms

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            login = await client.post(
                f"{args.base}/api/auth/login",
                json={"email": config.ADMIN_EMAIL, "password": config.ADMIN_PASSWORD},
            )
        except httpx.HTTPError:
            sys.exit(f"Backend not reachable at {args.base}. Start it: uv run uvicorn app.main:app --port 7860")
        if login.status_code != 200:
            sys.exit(f"Admin sign-in failed ({login.status_code}): check ADMIN_EMAIL / ADMIN_PASSWORD in .env")
        AUTH_COOKIES.update(client.cookies)
        health = (await client.get(f"{args.base}/api/health")).json()
        if not health["sarvam_key_set"] or not config.SARVAM_API_KEY:
            sys.exit("SARVAM_API_KEY is missing in .env (both the backend and this script read it).")

        if not args.yes:
            cost = "Rs 2-3" if not args.compare else "Rs 2-2.5"
            answer = input(f"This test spends about {cost} of Sarvam credits. Continue? [y/N] ")
            if answer.strip().lower() != "y":
                sys.exit("Cancelled.")

        tool_server = build_mock_tool_server()
        tool_task = asyncio.create_task(tool_server.serve())
        while not tool_server.started:
            await asyncio.sleep(0.05)

        created = (
            await client.post(
                f"{args.base}/api/clients",
                json={
                    "client": {"name": f"E2E test {time.strftime('%H:%M:%S')}", "industry": "test"},
                    "agent": {"name": "Support (E2E)", "config": AGENT_CONFIG},
                },
            )
        ).json()
        agent_id = created["agents"][0]["id"]
        print(f"Created client {created['id']} with agent {agent_id}")

        checks: list[tuple[str, bool]] = [("client + agent created together", bool(agent_id))]
        total_cost = 0.0

        if not args.skip_chat:
            history: list[dict] = []
            chat_tools: list[dict] = []
            chat_ok = True
            print("\n=== Text chat ===")
            for text in CALLER_LINES[:2]:
                history.append({"role": "user", "content": text})
                r = await client.post(f"{args.base}/api/agents/{agent_id}/chat", json={"messages": history})
                if r.status_code >= 300:
                    print(f"  FAILED ({r.status_code}): {r.text[:300]}")
                    chat_ok = False
                    break
                data = r.json()
                history.append({"role": "assistant", "content": data["reply"]})
                chat_tools += data.get("tool_calls", [])
                total_cost += data["cost_inr"]
                print(f"  you: {text}")
                for t in data.get("tool_calls", []):
                    print(f"    [tool] {t['name']}({json.dumps(t['arguments'])}) -> {json.dumps(t['result'])[:120]}")
                print(f"  agent ({data['latency_ms']} ms): {data['reply']}")
            checks.append(("chat: replies", chat_ok and all(m["content"] for m in history if m["role"] == "assistant")))
            checks.append(("chat: tool called with order 1234", any("1234" in json.dumps(t["arguments"]) for t in chat_tools)))

        need_audio = args.compare or not (args.skip_browser and args.skip_phone)
        lines = []
        if need_audio:
            print("\nGenerating caller speech with Sarvam TTS…")
            try:
                lines = [trim_silence(await synthesize(t)) for t in CALLER_LINES]
            except httpx.HTTPStatusError as e:
                print(f"  Sarvam TTS failed ({e.response.status_code}): {e.response.text[:300]}")
                checks.append(("caller speech generated", False))
                args.skip_browser = args.skip_phone = True
            total_cost += sum(len(t) for t in CALLER_LINES) / 1000 * config.PRICE_TTS_PER_1K_CHARS

        if args.compare and lines:
            variants = [("sarvam", None), ("sarvam", 400), ("fast", 300)]
            rows = []
            for mode, pause in variants:
                label = f"{mode} / pause {pause or 'default'}"
                cfg = {**AGENT_CONFIG, "turn_detection": mode, "end_of_speech_ms": pause}
                await client.put(f"{args.base}/api/agents/{agent_id}", json={"name": "Support (E2E)", "config": cfg})
                print(f"\nRunning phone call with {label}…")
                started = time.time()
                try:
                    side = await phone_call(args.base, agent_id, lines)
                except Exception as e:
                    print(f"  failed: {e!r}")
                    checks.append((f"{label}: call ran", False))
                    continue
                call = await wait_for_call_record_since(client, args.base, agent_id, started)
                print_call_report(f"Phone call ({label})", call, side)
                if call:
                    total_cost += call["cost_inr"]
                heard = [h for h in side["client_latency_ms"] if h is not None]
                rows.append((label, call and call["latency_avg_ms"], round(sum(heard) / len(heard)) if heard else None,
                             len(heard), call and call["turns"]))
                checks.append((f"{label}: ≥2 turns measured", bool(call and call["turns"] >= 2)))
            print("\n=== Latency comparison (phone path, 8 kHz) ===")
            print(f"  {'setting':<24} {'server avg':>11} {'caller heard avg':>17} {'turns':>6}")
            for label, server, heard_avg, n, turns in rows:
                print(f"  {label:<24} {str(server) + ' ms':>11} {str(heard_avg) + ' ms':>17} {str(turns):>6}")
            print("  (caller heard = end of caller speech -> first agent audio, includes the pause)")

        for channel, enabled, runner in (
            ("browser", not args.skip_browser, browser_call),
            ("exotel", not args.skip_phone, phone_call),
        ):
            if not enabled:
                continue
            label = "Browser call (WebRTC)" if channel == "browser" else "Phone call (telephony WebSocket, 8 kHz)"
            print(f"\nRunning {label}…")
            before_tools = len(tool_calls)
            started = time.time()
            try:
                side = await runner(args.base, agent_id, lines)
            except Exception as e:
                print(f"  {label} failed to run: {e!r}")
                checks.append((f"{channel}: call ran", False))
                continue
            call = await wait_for_call_record(client, args.base, agent_id, channel, started)
            print_call_report(label, call, side)
            if call:
                total_cost += call["cost_inr"]
            new_tool_calls = tool_calls[before_tools:]
            if call and call.get("ended_at") and not side["ended_by_agent"]:
                # The call record closing before we hung up also means the agent ended it.
                ended = datetime.fromisoformat(call["ended_at"])
                ended = ended if ended.tzinfo else ended.replace(tzinfo=UTC)
                side["ended_by_agent"] = ended.timestamp() < side["hung_up_at"]
            checks += [
                (f"{channel}: greeting heard", side["greeting_heard"]),
                (f"{channel}: ≥2 turns measured", bool(call and call["turns"] >= 2)),
                (f"{channel}: tool called with order 1234", any("1234" in json.dumps(c) for c in new_tool_calls)),
                (f"{channel}: agent hung up via end_call", side["ended_by_agent"]),
                (f"{channel}: call saved without error", bool(call and call["status"] == "completed")),
            ]

        tool_server.should_exit = True
        await tool_task

        if args.cleanup:
            await client.delete(f"{args.base}/api/clients/{created['id']}")

    print("\n=== Checks ===")
    for name, passed in checks:
        print(f"  {ok(passed)}  {name}")
    print(f"\nEstimated Sarvam spend for this run: Rs {total_cost:.2f}")
    if not args.cleanup:
        print("The test client is kept so you can open it in the UI (use --cleanup to delete).")
    sys.exit(0 if all(p for _, p in checks) else 1)


if __name__ == "__main__":
    asyncio.run(main())
