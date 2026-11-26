# Sarvam Voice Agents prototype

Create clients. Each client gets its own voice agent, created in the same step: prompt, greeting, language, voice, tools and limits are all stored in **our** database. No Sarvam dashboard setup is needed.
Each call runs a [Pipecat](https://github.com/pipecat-ai/pipecat) pipeline: **Sarvam Saaras v4 realtime STT → `sarvam-105b-conversations` → Bulbul v4 Flash TTS**. You can test in the browser, by text chat, or with real phone calls (Twilio / Exotel). Latency and cost are measured on every turn.

```
backend/                 FastAPI + Pipecat, managed with uv
  app/main.py            app wiring: middleware, routers, serves the built UI
  app/api/               HTTP/WebSocket routes, one module per area
                         (auth, meta, clients, testing, live calls, call history)
  app/core/              settings (.env), database models, session security
  app/agents/            agent config model, voice catalog, HTTP tools
  app/voice/             the call pipeline (STT → LLM → TTS), metrics, text shaping
  app/telephony/         Twilio / Exotel / Plivo dialing, call matching, clients' own numbers
  scripts/e2e_test.py    end-to-end test that plays the caller
frontend/                React + Vite + TypeScript (imports use the @/ alias for src/)
  src/app/               auth gate, app shell (sidebar, top bar), hash routes
  src/components/        shared UI: icons, badges, tabs, fields, theme toggle
  src/features/          one folder per area: auth, overview, agents (+ config tabs),
                         clients, calls, testing (voice / chat / phone playground), settings
  src/lib/               API client, formatting, colour tones
  src/styles/            tokens → base → components → layout → pages
deploy/nginx-site.conf   Nginx site for voicepilot.n3xglobalsolutions.com (HTTPS via certbot)
deploy/Caddyfile         optional bundled HTTPS proxy, for a server without Nginx
Dockerfile, docker-compose.yml
docs/                    deployment guides, research and costs, design references
```

## 1. Run it locally (browser calls)

Needs Python 3.12 + [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
cp .env.example .env          # then put your SARVAM_API_KEY in .env

# terminal 1: backend on :7860
cd backend
uv sync
uv run uvicorn app.main:app --port 7860

# terminal 2: frontend on :5173 (proxies /api to :7860)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in with the admin account (`ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`; the defaults are in `.env.example`). Then: **Create agent** (sidebar) → fill in the client + agent → **Create agent** → in the **Playground** panel, press the call button (allow the microphone).

All `/api` routes need a signed-in session, except the telephony webhooks (`/telephony/*`, `/ws/telephony*`) and the demo tool (`/api/demo/order-status`).

Single-server alternative: `cd frontend && npm run build`. The backend then serves the UI at http://localhost:7860.

## 2. Credit guards (you have limited free credits)

| Guard | Default | Where |
|---|---|---|
| Hard max call length (all calls) | 300 s | `MAX_CALL_SECONDS_CAP` in `.env` |
| Per-agent max call length | 180 s | agent form |
| Voice AI cost cap per call (phone line not included) | ₹10 | `MAX_COST_PER_CALL_INR` in `.env` |
| Silence → "Are you still there?" → hang up | 12 s | agent form |
| Bad key / no credits → call ends with an error (no silent retry loop) | — | `app/voice/bot.py` |

Every call's cost is calculated from the rates in `.env` (Settings → Cost rates shows the active values). Defaults are Sarvam's pay-as-you-go prices as billed in Nov 2026: voice ₹2 per 1,000 characters, speech recognition ₹0.49 per minute of caller speech, AI model ₹10 / ₹0.25 cached / ₹25 per 1M tokens. Phone calls add the line rate (`PRICE_EXOTEL_PER_MIN`, default ₹1/min in 60 s pulses; set yours from your Exotel invoice).
Voice output is ~95% of the voice AI cost, so typical cost is about ₹2.8/min plus the phone line. Compare a day's total with the Sarvam dashboard's usage breakdown to confirm.

## 3. Full test (no telephony account needed)

### 3a. Automated end-to-end test (about ₹2–3 of Sarvam credits)

With the backend running and `SARVAM_API_KEY` in `.env`:

```bash
cd backend
uv run python scripts/e2e_test.py
```

The script plays the caller. It generates three caller lines with Sarvam TTS and talks to a real agent twice:

1. **Browser call** over WebRTC (the same path as the UI's "Start browser call").
2. **Phone call** over the telephony WebSocket in Exotel's 8 kHz wire format. The script acts as the phone provider, so this tests the exact code path a real phone call uses, with no Twilio/Exotel account.

It also runs a 2-turn **text chat**. The agent it creates has an HTTP tool (`check_order_status`, served by a mock inside the script) and `end_call`.

It prints per-turn latency, both server-measured and as heard by the caller (which includes Sarvam's end-of-speech wait), plus the transcript and cost. It finishes with PASS/FAIL checks:

- client + agent created together
- text chat replies
- greeting heard
- ≥2 turns measured
- tool called with the right order number
- agent hung up via `end_call`
- call saved without error

The test client stays in the UI so you can inspect it. Add `--cleanup` to delete it, or `--skip-chat` / `--skip-browser` / `--skip-phone` to run parts.

### 3b. Manual checklist (your own voice, ~₹10)

| # | Test | How | Expect |
|---|---|---|---|
| 1 | Create | New client with your own prompt | Agent appears under the client, v1 |
| 2 | Prompt | Text chat tab: ask in-scope and out-of-scope questions | Follows instructions and guardrails |
| 3 | Greeting + basic call | Start browser call, ask 2–3 questions | Greeting plays at once; replies mostly green (< 1 s) |
| 4 | Barge-in | Talk over the agent mid-sentence | Agent stops and listens |
| 5 | Language | Enable auto-detect, switch to Hindi/Hinglish | Agent follows your language |
| 6 | Silence | Stay silent | "Are you still there?" after the idle timeout, then goodbye + hang-up |
| 7 | Tools | Add an HTTP tool pointing at any API you have | Agent calls it and speaks the result |
| 8 | End call | Say "that's all, bye" | Goodbye message, call ends by itself |
| 9 | Limits | Set max call length to 30 s | Call ends at 30 s |
| 10 | Versioning | Edit the prompt, save, call again | Version bumps; Call history shows the new version |
| 11 | History | Open a call in Call history | Transcript, latency avg/p95, cost |
| 12 | Mobile | `npm run build`, `ngrok http 7860`, open the ngrok URL on your phone (mobile data) | Works on a real mobile network |

After the first calls, compare the app's cost estimate with the drop in your Sarvam credit balance.

## 4. Real phone calls

The phone provider must reach your backend over the internet, so expose port 7860 with ngrok:

```bash
ngrok http 7860
# put the https URL in .env:  PUBLIC_BASE_URL=https://xxxx.ngrok-free.app
# restart the backend
```

Running the built UI on :7860 (see above) also makes the app itself reachable at the ngrok URL.

### Twilio (fastest to start: trial account, ~$15 credit)

1. Sign up at twilio.com, get a phone number, and **verify your own mobile number** (trial accounts can only call verified numbers; calls are capped at 10 min).
2. Console → Voice → **Geographic permissions**: enable **India** (or your country).
3. `.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` (E.164, e.g. `+1415…`).
4. **Outbound:** Test lab → Phone call → Twilio → your mobile number → **Call this number**.
5. **Inbound:** in Twilio, set the number's *A call comes in* webhook to
   `POST https://xxxx.ngrok-free.app/telephony/twilio/incoming`, then click **Use this agent for inbound calls** on the agent you want.

Trial accounts play a short Twilio notice before connecting.

### Exotel (Indian numbers; needs KYC)

1. Exotel account + KYC + an ExoPhone. Ask Exotel support to **enable voice streaming (Voicebot applet)** if you don't see it.
2. App Bazaar: create a flow **Call Start → Voicebot → Hangup**, and set the Voicebot URL to
   `wss://xxxx.ngrok-free.app/ws/telephony`. Note the flow's **App ID**.
3. `.env`: `EXOTEL_API_KEY`, `EXOTEL_API_TOKEN`, `EXOTEL_ACCOUNT_SID`, `EXOTEL_SUBDOMAIN` (`api.exotel.com`, or `api.in.exotel.com` for Mumbai accounts), `EXOTEL_CALLER_ID` (your ExoPhone), `EXOTEL_FLOW_APP_ID`.
4. **Outbound:** Test lab → Phone call → Exotel. The backend matches the incoming stream to the agent that dialed it.
5. **Inbound:** point your ExoPhone at the same flow, and click **Use this agent for inbound calls**.

### Clients' own numbers (Exotel or Plivo)

The setup above is the **workspace number**, shared by every client. A client that already has an Exotel or Plivo account can use its own number instead: **Clients → Phone numbers → Add number**. Their API credentials are stored encrypted (`CREDENTIALS_KEY`), calls are billed to their account, and each number picks the agent that answers it. In an agent's Phone playground, **Call from** lists the client's numbers.

- **Exotel:** enter the ExoPhone, account SID, region, API key/token and the flow's App ID. After saving, copy the number's own **Voicebot applet URL** (`wss://…/ws/telephony/line/<id>`) into the client's flow and attach the flow to the ExoPhone. Exotel has no API for this step.
- **Plivo:** enter the number (with country code), Auth ID and Auth Token. Saving creates an application in the client's Plivo account and links the number to it, so inbound calls reach the agent with no manual setup. Removing the number gives back the application it had before.

**Check** re-tests the credentials (and re-connects a Plivo number). `PUBLIC_BASE_URL` must be https.

> Sarvam's own ₹59/month numbers only work with Sarvam's managed Voice Agents, so they can't be connected to this app.

## 5. What the latency numbers mean

Each turn is measured on the server from **Sarvam's end-of-speech signal** to **the first agent audio sent**:

- **STT**: final transcript ready
- **LLM 1st text**: first token from the LLM
- **TTS 1st audio**: first synthesized audio
- **Total**: agent starts speaking (green < 1 s, amber < 1.5 s, red above)

Not included: the pause before the turn is declared over, and the network/phone leg back to the caller (typically +100–300 ms on phone calls).
The **You heard** column in the browser call measures the full wait in your browser: your mic goes quiet → agent audio starts. That is the number to optimize.

### Making replies faster (agent form → "Response speed & recognition")

| Setting | Caller waits (measured, phone path) | Notes |
|---|---|---|
| Turn detection **Sarvam VAD** (default) | ~2.3–2.6 s | Sarvam's server decides you stopped; most robust on noisy lines |
| Turn detection **Fast (local VAD)**, pause 300 ms | **~1.2–1.4 s** | Our server decides after a 300 ms pause and tells Sarvam to finalize at once; first words kept via a 1 s pre-roll |

- Lower pause = faster, but slow speakers who pause mid-sentence may get cut off (their words still reach the agent as one turn more often than not).
- **Important words** (names, brands, product terms) improve speech recognition of those words.
- Compare settings yourself: `uv run python scripts/e2e_test.py --compare` (3 phone-path calls, about ₹2–2.5).
Each call's avg / p50 / p95 / max latency, transcript, token/char/second usage and cost are saved in **Call history**.

## 6. Agent configuration

| Setting | Effect |
|---|---|
| Greeting | Spoken immediately on connect (no LLM wait) |
| Prompt / instructions | System prompt. Voice rules are appended automatically (short replies, no markdown, language rule, end-call rule) |
| Language / auto-detect | STT language and reply language (`auto` lets the caller choose) |
| Voice / pace | Bulbul v4 Flash persona (222 voices, filtered by language) |
| Temperature | Lower = more predictable |
| Tools | `end_call` (agent can hang up) plus your own HTTP tools: name, description, URL, method, JSON-schema parameters, headers. The agent calls them mid-conversation and speaks the result |
| Limits | Max call length, silence nudge timeout, goodbye message |

Saving an agent bumps its version. Each call records which version it used.

## 7. Deploying to a VPS (Hostinger, Docker)

See **[docs/deploy-vps.md](docs/deploy-vps.md)**: frontend and backend ship in **one container** (`Dockerfile` + `docker-compose.yml`), behind the server's Nginx at https://voicepilot.n3xglobalsolutions.com. In short: add the Cloudflare DNS record, fill in `.env`, run `docker compose up -d --build`, then add the Nginx site and certificate.

## 8. Deploying later (AWS)

See Part C of [docs/research-and-costs.md](docs/research-and-costs.md) and [docs/deployment-and-scaling.md](docs/deployment-and-scaling.md). The API endpoints can move to Lambda. Live calls need a long-running container (ECS Fargate) because calls are persistent WebSocket/WebRTC streams.
