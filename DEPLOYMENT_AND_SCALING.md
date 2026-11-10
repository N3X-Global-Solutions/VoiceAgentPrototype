# Sarvam Voice Agent: Deployment, Cost, Scaling and Key Findings

_Written 3 Nov 2026. Covers the decisions and findings from the deployment and scaling discussion. Research and the original plan are in `SARVAM_VOICE_AGENTS_ANALYSIS.md`._

Prices are in INR and exclude 18% GST unless stated. AWS prices are for Mumbai (ap-south-1), converted at ₹88 = $1. Each number is marked **measured** (from our own calls or tests), **official** (from Sarvam or AWS docs) or **estimate** (needs confirming).

---

## 1. Key findings

| # | Finding |
|---|---|
| 1 | **Lambda can't run live calls.** A call needs one two-way audio connection held open for the whole call. Lambda runs the dashboard and API; EC2 or Fargate runs the calls. |
| 2 | **Measured Sarvam cost is ₹1.08/min (phone) to ₹1.38/min (browser)**, across 31 real calls (28.6 min). The voice (TTS) is the biggest part: about ₹0.79/min. |
| 3 | **Production cost is about ₹2/min for incoming calls and ₹2.5/min for outgoing calls** at 20,000–50,000 min/month, all-in (Sarvam + Exotel + AWS). |
| 4 | **One 2 GB server handles about 8–12 calls at once.** CPU runs out before memory: the app is one Python process, which uses only one core. More RAM alone doesn't help; more cores with one app copy per core does. **Production server: c7g.2xlarge (8 vCPU / 16 GB), ~60–80 calls each, about 6 servers for 300 calls at once** (section 11). |
| 5 | **Sarvam's plan limits are the main bottleneck for scaling, not AWS.** The best self-serve plan (Growth) allows about 60 calls at once. 100 or 300 calls at once need a **Sarvam Enterprise** agreement. |
| 6 | **AWS server cost is tiny at scale** (about ₹0.005 per call-minute at 300 calls at once). Sarvam and Exotel are almost the whole bill, so those are the prices to negotiate. |
| 7 | **The app is built for one server today.** About 1.5–2 weeks of work is needed before it can run across many servers (section 14). |
| 8 | **Every provider needs a limit increase at 300 calls at once, not just Sarvam.** Sarvam is still the cheapest and best for Indian languages. The AI model is the easiest part to swap if Sarvam's limits block you (section 13). |

---

## 2. Tech stack

### Prototype (what runs today)

| Layer | Technology | Where in the code |
|---|---|---|
| **Frontend** | React 19 + TypeScript 7, built with Vite 8, linted with oxlint | [frontend/src/](frontend/src/) |
| Frontend voice client | `@pipecat-ai/client-js` + `@pipecat-ai/small-webrtc-transport` (browser mic ↔ backend over WebRTC, Google STUN server) | [TestLab.tsx](frontend/src/TestLab.tsx) |
| **Backend API** | Python 3.12, **FastAPI**, served by **uvicorn** on port 7860, managed with **uv** | [backend/app/main.py](backend/app/main.py) |
| **Voice pipeline** | **Pipecat 1.15** (`pipecat-ai[sarvam,silero,webrtc,websocket]`) | [backend/app/bot.py](backend/app/bot.py) |
| Speech-to-text | **Sarvam Saaras v4** (`saaras:v4`), live streaming, with a pre-roll buffer so the first words aren't lost | [bot.py](backend/app/bot.py), [stt_preroll.py](backend/app/stt_preroll.py) |
| AI model | **Sarvam `sarvam-105b-conversations`**, thinking off for speed, with tool calling | [bot.py](backend/app/bot.py), [tools.py](backend/app/tools.py) |
| Voice (TTS) | **Sarvam Bulbul v4 Flash** (`bulbul:v4-flash`), 222 voices | [bot.py](backend/app/bot.py), [voices.json](backend/app/voices.json) |
| Turn detection | **Silero VAD** on the server ("fast" mode, default 300 ms pause) or Sarvam's server-side detection ("sarvam" mode) | [bot.py](backend/app/bot.py) |
| Browser calls | **SmallWebRTC** (aiortc): 16 kHz in, 24 kHz out | [main.py](backend/app/main.py) |
| Phone calls | **Exotel** (Voicebot applet) and **Twilio** (Media Streams) over WebSocket | [telephony.py](backend/app/telephony.py) |
| Database | **SQLite** via **SQLModel** (`backend/data/app.db`); tables `client`, `agent`, `callsession`, `setting` | [backend/app/db.py](backend/app/db.py) |
| Cost and latency metering | A Pipecat observer that counts speech-to-text seconds, voice characters and AI tokens, and measures latency every turn | [call_metrics.py](backend/app/call_metrics.py) |
| Settings and secrets | `.env` file (Sarvam key, telephony keys, prices, call caps) | [config.py](backend/app/config.py) |
| Hosting (test) | One **EC2 t4g.small** (Mumbai) + **Caddy** (HTTPS, password) + **systemd** | Section 6 |

### Production (planned)

| Layer | Technology |
|---|---|
| Dashboard | React build on **S3 + CloudFront** |
| API | **AWS Lambda** (Python 3, Arm) + **API Gateway** (HTTP API) |
| Live calls | Pipecat container on **ECS Fargate** (Graviton/Arm) behind an **Application Load Balancer**, scaled by active calls |
| Database | **DynamoDB** (on-demand) |
| Call queue and dialler | **SQS** + Lambda |
| Storage | **S3** for recordings and transcripts |
| Secrets | **AWS Secrets Manager** |
| Monitoring | **CloudWatch** logs, metrics and alarms; per-call usage table |
| Infrastructure as code | **AWS CDK** or SST |
| Region | **ap-south-1 (Mumbai)**: close to Sarvam and Indian callers, keeps data in India |
| Speech, AI, voice | **Sarvam** (Enterprise at scale); optional backup provider for speech-to-text and AI (section 13) |
| Phone | **Exotel** (India) |

---

## 3. Application flow

### What a user does in the app

```
1. Create a client      →  name, industry, contact. An agent is created in the same step.
2. Configure the agent  →  greeting, instructions, language, voice, pace, turn detection,
                           important words, call limits, nudge/goodbye messages, HTTP tools.
                           Non-English: one click translates the fixed phrases.
3. Test the agent       →  Test Lab: text chat, browser voice call, or real phone call.
4. Review calls         →  Call history: transcript, latency per turn, usage and ₹ cost.
```

Every save bumps the agent's **version**, and each call records the version it used. **No setup is needed on Sarvam's side:** an agent is just a row in our database.

### What happens during a call (the voice pipeline)

```
Caller audio ─▶ transport in ─▶ Saaras v4 (speech-to-text) ─▶ user turn
              (WebRTC or                                           │
               phone WebSocket)                                    ▼
                                         sarvam-105b-conversations (AI reply, may call tools)
                                                                   │
Caller hears ◀─ transport out ◀─ Bulbul v4 Flash (voice) ◀─────────┘
                                   │
                         CallMetricsObserver: latency, speech-to-text seconds, voice characters,
                         AI tokens, ₹ cost (sent live to the browser, saved when the call ends)
```

Step by step:
1. **Call starts:** the server loads the agent's settings and builds the instructions: the agent's prompt, plus voice rules, the language rule (reply in the chosen language and script) and the end-call rule.
2. **Greeting:** the agent speaks the greeting.
3. **Caller speaks:** audio streams to Saaras v4. In "fast" mode, Silero VAD on the server notices the pause (300 ms by default) and tells Sarvam to finish the transcript at once. In "sarvam" mode, Sarvam decides when the caller has stopped.
4. **AI reply:** the transcript goes to sarvam-105b with the conversation so far. If it needs data, it calls an **HTTP tool** (8-second timeout, reply cut to 4,000 characters), then answers.
5. **Voice:** the reply streams to Bulbul v4 Flash, and audio plays as soon as the first part is ready. If the caller speaks over the agent, the agent stops (barge-in).
6. **Silence:** after `idle_timeout_secs` the agent says the nudge message. If the caller stays silent, the call ends.
7. **Call ends** when any of these happens:
   - the AI calls `end_call`
   - the caller hangs up
   - the call reaches `max_call_seconds` (capped by `MAX_CALL_SECONDS_CAP`, 300 s)
   - the call's cost reaches `MAX_COST_PER_CALL_INR` (₹5)
8. **Saved:** transcript, per-turn latency (average, p50, p95, max), usage and cost go into `callsession`.

### Call channels

| Channel | How audio arrives | Endpoint |
|---|---|---|
| Browser test | WebRTC from the browser mic (16 kHz in / 24 kHz out) | `POST /api/agents/{id}/offer` |
| Exotel outbound | `POST /api/agents/{id}/phone-call` → Exotel dials → Exotel's Voicebot opens a WebSocket (8 kHz). The call is matched to the agent by phone number | `wss://…/ws/telephony` |
| Exotel inbound | Customer calls the ExoPhone → Voicebot WebSocket → the agent set as the inbound agent | `wss://…/ws/telephony` or `/ws/telephony/{agent_id}` |
| Twilio | Webhook returns instructions to stream audio → Media Stream WebSocket | `POST /telephony/twilio/incoming`, `/ws/telephony/{agent_id}` |
| Text chat | No audio. Same instructions and tools, AI only | `POST /api/agents/{id}/chat` |

### Main API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health`, `GET /api/catalog` | Status; languages, voices and defaults |
| `GET/POST/PUT/DELETE /api/clients…` | Clients |
| `POST /api/clients/{id}/agents`, `GET/PUT /api/agents/{id}` | Agents |
| `PUT /api/agents/{id}/inbound` | Choose the agent for inbound calls |
| `POST /api/translate` | Translate the fixed phrases (greeting, goodbye and others) |
| `GET /api/calls`, `GET /api/calls/{id}` | Call history and details |
| `POST /api/demo/order-status` | Demo tool for trying tools |

---

## 4. Production architecture

### Who does what

| Part | Runs on | Handles |
|---|---|---|
| Dashboard (web pages) | **S3 + CloudFront** | The React app's files |
| Dashboard API | **Lambda** + API Gateway | Clients, agents, settings, call history, costs, tool setup, translation, text-chat testing, **starting** outbound calls |
| Live calls | **EC2 or ECS Fargate** | **Every call with live audio**: outbound, inbound and browser test calls |
| Database | **DynamoDB** (shared) | Lambda saves agent settings. Call servers read them when a call starts and save transcript, cost and latency when it ends |
| Campaign queue | **SQS** + dialler Lambda | Starts outbound calls only when there's free capacity |

### How an outbound call works

```
1. Dashboard / campaign  →  Lambda: "call +91 98xxxx for Agent A"
2. Lambda                →  Exotel API: "dial this number"         (~1 second; Lambda is done)
3. Customer answers      →  Exotel opens an audio connection (wss://) to a call server
4. Call server           →  Sarvam speech-to-text → AI reply → voice, for the whole call
5. Call ends             →  Call server saves transcript, cost and latency to DynamoDB
6. Dashboard             →  Lambda reads DynamoDB and shows the call
```

**Lambda starts the call; the call server runs it.**

### Why Lambda for production, and why not now

- **Why Lambda in production:** the team already runs on Lambda, there are no servers to manage for the API, it scales by itself, and dashboard traffic never slows down live calls.
- **Why not now:** the prototype is one program (web pages, API, calls and a SQLite database). Splitting it for Lambda takes about 3–5 days and **doesn't change the per-minute cost**, so measure first.
- Lambda isn't required for cost. Running everything on Fargate or EC2 costs about the same. Lambda is about fitting the team's way of working.

### EC2 or Fargate for the call servers?

- **Fargate** until volume is steady and high (about 50,000+ min/month). No servers to patch, and it scales by the number of active calls.
- **Server size:** c7g.2xlarge (8 vCPU / 16 GB) or Fargate tasks of the same size, running 8 app copies each. See section 11.
- After that, an **EC2 Auto Scaling group with a Savings Plan** is about 30–40% cheaper. At that volume AWS is only ₹0.10–0.15/min, so the saving is small.
- **Don't use t4g (burstable) servers in production.** They're designed for about 20% CPU per core over time and charge extra above that.

---

## 5. Does an EC2 test give the same cost as production?

**About 95% of it, yes.**

| Cost | Same on the EC2 test and in production? |
|---|---|
| Sarvam (speech-to-text, AI, voice) | ✅ Identical: same API calls, same prices |
| Phone (Exotel / Twilio) | ✅ Identical: billed by the provider |
| Lambda part | ≈ ₹0.005/min, too small to matter |
| Server cost (EC2 vs Fargate) | ❌ Different: fixed monthly cost ÷ minutes, so it depends on volume |

So the EC2 test measures the **real Sarvam and phone cost** plus **how many calls one server handles**. The production server cost is calculated from those.

---

## 6. Prototype deployment on EC2 (step by step)

### Step 0: Before you start
1. Top up Sarvam if the balance is low (about ₹100), and note the exact balance.
2. Note the Exotel balance.
3. In AWS, switch to **Mumbai (ap-south-1)**. Billing → Budgets → monthly budget of **$10 with an email alert**.

### Step 1: Code fix for browser calls (⚠️ not applied yet)
The browser is given a STUN server, but the backend isn't. On EC2 the server only knows its private address, so browser calls may fail on mobile data or office Wi-Fi. Change [backend/app/main.py:57](backend/app/main.py#L57) to:
```python
webrtc_handler = SmallWebRTCRequestHandler(ice_servers=["stun:stun.l.google.com:19302"])
```
Phone calls work without this.

### Step 2: Build the frontend on your Mac
```bash
cd ~/Desktop/SarvamVoiceAgent/frontend && npm run build
```
The backend serves `frontend/dist` itself, so the server doesn't need Node.

### Step 3: Launch the EC2 server

| Setting | Value |
|---|---|
| Name | `sarvam-voice-test` |
| OS image | Ubuntu 24.04 LTS, 64-bit (Arm) |
| Instance type | **t4g.small** (2 vCPU, 2 GB), or **c7g.large** (2 vCPU, 4 GB, ~₹4.30/hour) for a cleaner load test: it has no CPU-credit limits (section 11) |
| Key pair | Create one and download the `.pem` file |
| Storage | 20 GB gp3 |
| Tags | `Project = sarvam-voice`, applied to the instance **and** the volume |
| Firewall (security group) | SSH 22 from *My IP*; 80 and 443 from anywhere; **UDP 1024–65535** from anywhere (browser-call audio) |

Then **Elastic IPs → Allocate**, tag it `Project = sarvam-voice`, and attach it to the server.

**Domain:** you don't need to buy one. For IP `13.233.10.20`, use `13-233-10-20.sslip.io`. HTTPS is required because browsers only allow the microphone on HTTPS pages, and Exotel only connects to `wss://`.

### Step 4: Copy the app (from your Mac)
```bash
chmod 400 ~/Downloads/sarvam.pem
cd ~/Desktop/SarvamVoiceAgent
rsync -av -e "ssh -i ~/Downloads/sarvam.pem" \
  --exclude .venv --exclude node_modules --exclude __pycache__ --exclude .DS_Store \
  ./ ubuntu@13.233.10.20:~/app/
```
This also copies `.env` (keys) and `backend/data/app.db` (clients and agents).

### Step 5: Install and start the app (on the server)
```bash
ssh -i ~/Downloads/sarvam.pem ubuntu@13.233.10.20
sudo apt update && sudo apt install -y caddy sqlite3 htop
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
cd ~/app/backend && uv sync
chmod 600 ~/app/.env
```
In `~/app/.env`, set `PUBLIC_BASE_URL=https://13-233-10-20.sslip.io`.

Make the app start automatically and restart if it crashes:
```bash
sudo tee /etc/systemd/system/voice.service >/dev/null <<'EOF'
[Unit]
Description=Sarvam voice agent
After=network.target
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/app/backend
ExecStart=/home/ubuntu/.local/bin/uv run uvicorn app.main:app --host 127.0.0.1 --port 7860
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now voice
```

### Step 6: HTTPS and a password
**The app has no login.** Without a password, anyone who finds the address can use up your Sarvam credits. The phone-provider paths stay open, because Exotel and Twilio can't send a password.
```bash
caddy hash-password        # type a password and copy the output
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
13-233-10-20.sslip.io {
    @private not path /telephony/* /ws/telephony*
    basicauth @private {
        admin PASTE_HASH_HERE
    }
    reverse_proxy 127.0.0.1:7860
}
EOF
sudo systemctl restart caddy
```

### Step 7: Check that it works (about ₹3)
1. Open `https://13-233-10-20.sslip.io` and log in.
2. Test Lab → **text chat**. This checks the Sarvam key without using voice credits.
3. One **30-second browser call**. Logs: `sudo journalctl -u voice -f`.
4. Change the Exotel Voicebot applet URL to `wss://13-233-10-20.sslip.io/ws/telephony` and make one 30-second phone call.

### Step 8: Clean up afterwards
- **Pausing:** *stop* the server. The Elastic IP and disk still cost about ₹15/day.
- **Finished:** *terminate* the server **and release the Elastic IP**.

---

## 7. How to measure the real cost per minute

```
Total ₹/min = Sarvam (speech-to-text + AI + voice) + phone provider (Exotel/Twilio) + AWS (fixed + per-call)
```

### Test plan (about 50 minutes of calls)
Note the Sarvam and Exotel balances and the start time, then make about 20 calls:

| Calls | Channel | Language | Length |
|---|---|---|---|
| 6 | Browser | English | 2–3 min |
| 4 | Browser | Tamil / Telugu | 2–3 min |
| 6 | Exotel phone | English / Hindi | 2–3 min |
| 4 | Exotel phone | Tamil | 2–3 min |

Every call is capped by `MAX_CALL_SECONDS_CAP` (300 s) and `MAX_COST_PER_CALL_INR` (₹5) in `.env`.

### Calls per server (optional, about ₹15)
Watch `htop` while running **3, then 5, then 8 calls at once**. Note CPU % and the slowest reply time (p95 latency) in Call history. The highest number of calls before p95 latency rises is **calls per server**.

### Compare with the real bills (next day)
The app's own estimate (change the date to the test start, in UTC):
```bash
sqlite3 -header -column ~/app/backend/data/app.db "
select channel, count(*) calls, round(sum(duration_secs)/60.0,1) minutes,
       round(sum(cost_inr),2) sarvam_inr,
       round(sum(cost_inr)/(sum(duration_secs)/60.0),2) inr_per_min
from callsession where started_at >= '2026-11-04 00:00' group by channel;"
```

| Cost | Where the real number comes from | Compare with |
|---|---|---|
| Sarvam | Dashboard: balance before minus after, or the usage page | Total `cost_inr` from the query above |
| Phone provider | Exotel call report, or Twilio's call log | Not recorded in the app yet |
| AWS | Cost Explorer, Region = ap-south-1 (or the `Project` tag once it's turned on), by day | Per-minute share of the server cost |

If the Sarvam numbers differ by more than about 5%, adjust the price settings in [backend/app/config.py:43-47](backend/app/config.py#L43-L47).

### Fill in your results
```
Sarvam ₹/min   = Sarvam spent ÷ total minutes
Exotel ₹/min   = Exotel spent ÷ phone minutes
AWS production ₹/min ≈ fixed monthly AWS ÷ monthly minutes
                     + (server ₹/hour ÷ calls per server ÷ 60)
TOTAL ₹/min    = Sarvam + Exotel + AWS production   (+18% GST)
```

### Expected cost of the test

| Item | Approx. |
|---|---|
| Sarvam (~55–60 min at ~₹1.26/min) | ₹70–80 |
| Exotel (~25 phone minutes) | ₹10–15 (estimate) |
| AWS (t4g.small + IP + disk, ~₹40/day × 2–3 days) | ₹80–120 |
| **Total** | **≈ ₹160–215** |

---

## 8. Load test with one script (planned, not built)

One script, run **from your Mac (not the EC2 server)**, can measure most of this automatically. It reuses the fake phone call in [backend/scripts/e2e_test.py](backend/scripts/e2e_test.py), which already pretends to be Exotel and plays scripted caller speech. The load test runs that call many times at once, in steps.

```
Your Mac (runs the script)                 EC2 server (the app)
Step 1:  1 call at once   ─── wss ──▶  agent talks to Sarvam
Step 2:  3 calls at once  ─── wss ──▶      ...
Step 3:  5 calls at once  ─── wss ──▶      ...
Step 4:  8 calls at once  ─── wss ──▶      ...
Step 5: 12 calls at once  ─── wss ──▶      ...
  ├─ each fake caller speaks 4–6 lines and measures reply time
  ├─ every 5 s reads server CPU %, memory and active calls (new /api/metrics endpoint)
  └─ afterwards reads each call's latency, Sarvam cost and errors from Call history
```

| Item | From the script? | How |
|---|---|---|
| Calls at once per server | ✅ | Steps up until reply time or failures get worse |
| Reply time (p50 / p95) | ✅ | Measured by the server and by the fake caller |
| Server CPU and memory | ✅ | New `/api/metrics` endpoint (about 15 lines) |
| Sarvam cost per minute | ✅ | From call usage × price list; check against the Sarvam dashboard |
| Sarvam rate-limit errors (429 / 1003) | ✅ | Counted per step |
| EC2 cost | ⚠️ Calculated | Instance type × hours. Real bill in Cost Explorer about 24 hours later |
| t4g extra CPU charges | ⚠️ Next day | CloudWatch `CPUSurplusCreditsCharged` |
| Exotel cost | ❌ | Fake calls skip Exotel. Make 3–5 real calls and read Exotel's report |

**Limits of the test:**
- On Sarvam pay-as-you-go, about 12 calls at once is the most Sarvam allows, which is about the same as one t4g.small.
- Scripted callers are simpler than real ones, so real cost per minute may be 5–10% higher.
- Run it in both "fast" and "sarvam" turn modes.
- Start calls about 1 second apart.

**Cost of one run:** about ₹55 (29 calls × ~1.5 min × ₹1.2, plus ~₹2 of EC2).
**Work to build:** about half a day (`backend/scripts/load_test.py` + `/api/metrics`).

---

## 9. Measured numbers so far

### Sarvam cost per channel (measured, 31 calls)

| Channel | Calls | Minutes | Sarvam ₹ | ₹/min | Share of call billed as speech-to-text |
|---|---|---|---|---|---|
| Browser | 19 | 17.0 | 23.47 | **1.38** | 88% |
| Exotel phone | 12 | 11.6 | 12.57 | **1.08** | 75% |
| **All** | 31 | 28.6 | – | **1.26** | – |

- The agent speaks about **793 characters a minute**, so the voice costs **₹0.79/min** at ₹1.00 per 1,000 characters.
- **3.4–4.7 AI requests per minute per call** (phone vs browser), about 1,500 tokens per turn.
- Speech-to-text is billed for the whole call, but the app counts only the seconds actually streamed. Confirm against the Sarvam bill.

### Server memory and CPU (measured on a Mac; estimated for AWS)

| Item | Result |
|---|---|
| App loaded and idle | **170 MB** (measured) |
| Voice detection model per call | **13 MB** (measured) |
| Voice detection CPU per call | 0.6% of a core on the Mac (measured); ~1–2% on Graviton (estimate) |
| Memory per call, all included | ~35–50 MB phone, ~50–70 MB browser (estimate) |
| Total CPU per call | ~5–10% of one core (estimate) |

---

## 10. Capacity: how many calls one server handles

**Agents don't limit capacity.** An agent is a saved row of settings (about 2 KB), so you could have thousands. The limit is **calls at the same time**.

| On a 2 GB t4g.small | Estimate |
|---|---|
| Calls that fit in memory | ~25–35 |
| Calls the CPU can handle (one Python process = one core) | **~8–12 phone calls**, or ~6–8 browser calls |
| Throughput at 10 calls at once, 3-minute calls | ~200 calls an hour, ~2,000 calls in a 10-hour day |

To use more than one core, run several copies of the app with routing that keeps each call on the same copy. That's production work (section 11).

---

## 11. Production server sizing

### More RAM alone doesn't add calls

The limit is the CPU: the app runs as **one Python process, which uses only one core**. What adds calls is **more cores, with one copy of the app per core**.

| On one server | 2 GB | 16 GB |
|---|---|---|
| Calls that fit in memory | ~25–35 | ~250+ |
| Calls the CPU handles **with the app as it is** (1 process = 1 core) | ~8–12 | **still ~8–12** |
| Calls with **one app copy per core** (8 cores) | – | **~60–80** |

At ~50 MB per call and ~10 calls per core, each core needs only 0.5–1 GB, so **about 2 GB per core is plenty**. That's the ratio of AWS's compute-optimised "c" servers.

### Recommended production server: c7g.2xlarge

| Spec | Value | Why |
|---|---|---|
| Type | **c7g.2xlarge** (Graviton, compute-optimised) | Calls are limited by CPU, and Graviton gives the best price for the performance. Use c8g instead if available in Mumbai |
| CPU / RAM | **8 vCPU / 16 GB** | 8 copies of the app; 16 GB is about 4× what they need |
| Calls per server | **~60–80** (estimate; confirm with the load test) | ~8–10 per core |
| Network | Up to 15 Gbps | 80 calls need well under 50 Mbps |
| Disk | 30 GB gp3 | OS + app + logs |
| Price (Mumbai, on-demand) | **~₹17/hour, ~₹12,600/month** (estimate) | About 30–40% less with a 1-year Savings Plan |
| AWS cost per call-minute | **~₹0.004–0.006** | Negligible |

**Why 8 vCPU:**
- **Smaller (2 vCPU):** many servers to look after.
- **Bigger (16–64 vCPU):** fewer servers, but one failure drops 140–500 calls at once, and updates take longer.
- **8 vCPU** is the middle ground: few servers, and one failure affects only about 20% of calls at 300 calls at once.
- **Don't use t4g (burstable) servers in production.** They're designed for about 20% CPU per core over time and charge extra above that.

### Comparison for 300 calls at once (one spare server included)

| Server | vCPU / RAM | Calls each | Servers | ~₹/month (24×7) | Calls lost if one fails |
|---|---|---|---|---|---|
| c7g.xlarge | 4 / 8 GB | ~35 | 9 + 1 = 10 | ~₹63,000 | ~35 (~12%) |
| **c7g.2xlarge** ✅ | **8 / 16 GB** | **~70** | **5 + 1 = 6** | **~₹76,000** | **~70 (~23%)** |
| c7g.4xlarge | 16 / 32 GB | ~140 | 3 + 1 = 4 | ~₹1,00,000 | ~140 (~47%) |

Prices are estimated from c7g.large at $0.0491/hour (other sizes cost proportionally more), converted at ₹88 = $1. Dropping to 2 servers outside business hours roughly halves the monthly cost.

### Setup for availability and reliability

```
                    ┌── Availability Zone A ──┐   ┌── Availability Zone B ──┐
Exotel ── wss ──▶ ALB ─▶ c7g.2xlarge (8 copies)     c7g.2xlarge (8 copies)
                    │    c7g.2xlarge (8 copies)     c7g.2xlarge (8 copies)
                    └────── Auto Scaling group: min 2, max 8 ──────┘
```

| Need | How |
|---|---|
| **Availability** | At least **2 servers in 2 Availability Zones** (Mumbai has 3). If one server or zone fails, the others keep taking calls |
| **Reliability** | The load balancer checks each server's health; the Auto Scaling group replaces a broken server automatically. Always keep one spare server's worth of capacity |
| **Scaling** | Scheduled: e.g. 6 servers from 9 am to 8 pm, 2 overnight. Automatic: add a server when active calls go above 70% of capacity. A new server takes about 2–4 minutes to start, so scheduled scaling covers sudden peaks |
| **Updates without dropping calls** | Before a server is removed or updated, it **stops taking new calls and waits for active calls to finish** (calls last at most 5 minutes). This uses the load balancer's deregistration delay and Auto Scaling lifecycle hooks |
| **Simple management** | Build the app as a **Docker image**. Servers start from a launch template, so there's no hand-built server. Change one setting to add servers |
| **Monitoring** | CloudWatch: active calls per server, CPU, p95 reply time, Sarvam errors. Alarm when calls exceed 80% of capacity |

**Simpler alternative: ECS with Fargate**, with the same size per task (8 vCPU / 16 GB; Fargate allows up to 16 vCPU). There's no operating system to patch, and scaling and safe updates are built in. It costs about 20–30% more than EC2. Choose it if ease of management matters most; choose an EC2 Auto Scaling group if cost matters more.

### App changes needed to use 8 cores

Running 8 copies on one server has the same requirements as running many servers (all already in section 14):

1. **Run several copies:** `uvicorn --workers 8`, or 8 separate services behind the load balancer.
2. **Move pending outbound calls out of memory** ([backend/app/telephony.py:15](backend/app/telephony.py#L15)). The copy that starts a call may not be the copy Exotel connects to.
3. **Shared database:** DynamoDB or Postgres instead of SQLite, which handles several copies writing at once poorly.
4. **Browser test calls (WebRTC)** need each call's requests to reach the same copy. Keep browser testing on one small separate server, or switch it to WebSocket.

### Recommendation by stage

| Stage | Server |
|---|---|
| **Cost and load test now** | **c7g.large** (2 vCPU / 4 GB, ~₹4.30/hour) instead of t4g.small. No CPU-credit limits, so the result scales cleanly: calls per core × 8 = calls per c7g.2xlarge |
| **Production** | **c7g.2xlarge** (8 vCPU / 16 GB) in an Auto Scaling group: **at least 2 servers in 2 zones**, 8 app copies per server, ~70 calls each. **About 6 servers for 300 calls at once** |
| **If ease of management matters most** | The same size as **Fargate tasks** (8 vCPU / 16 GB) |

---

## 12. Bottlenecks when scaling (100 and 300 calls at once)

### Sarvam plan limits (official)

| Limit | Pay-as-you-go (₹0) | Pro (₹9,999/mo) | Growth (₹49,999/mo) | Business (₹1,99,999/mo) | Enterprise |
|---|---|---|---|---|---|
| Speech-to-text connections at once | 20 | 100 | 100 | not published | custom |
| Voice connections at once | 60 | 200 | 1,000 | not published | custom |
| sarvam-105b AI requests per minute | 60 | 200 | 300 | not published | custom |
| **Calls at once possible** (AI limit ÷ 5) | **≈ 12** | **≈ 40** | **≈ 60** | ask Sarvam | negotiated |

- **The AI request limit is the bottleneck.** Each call makes about 5 requests a minute (more if tools are used).
- **Starting many calls at once can fail.** Sarvam rejects connections opened in a fast burst, even below the limit (close code `1003`). Start calls gradually and retry.
- Adding credits doesn't raise limits. Limits beyond Growth need an **Enterprise** agreement.
- On Growth, Sarvam's other AI models (gemma4 and others) allow 1,000 requests a minute. Test their quality on Indian-language calls before relying on them.

### What 100 and 300 calls at once need

| Requirement | 100 calls | 300 calls | Growth plan |
|---|---|---|---|
| Speech-to-text connections | 100 | 300 | 100 ❌ (no spare room at 100) |
| Voice connections | 100 | 300 | 1,000 ✅ |
| AI requests per minute | ~500 | ~1,500 | 300 ❌ |
| **Sarvam verdict** | **Enterprise** | **Enterprise** | |
| Call servers: c7g.2xlarge (8 vCPU / 16 GB, ~70 calls each, + 1 spare) | 3 | 6 | – |
| AWS cost at peak | ~₹30/hour | ~₹90/hour | – |
| Exotel channels to ask for | 150+ | 350+ | – |

### Bottleneck summary (from most to least limiting)

1. **Sarvam plan limits:** about 60 calls at once on Growth. Fix: Enterprise agreement.
2. **Exotel channels and dialling rate:** fix by asking Exotel for the numbers, in writing. Also check Indian rules (TRAI/DLT number series) for bulk outgoing calls.
3. **The app's single-server design:** fix with the changes in section 14.
4. **Server start-up time:** a new Fargate server takes 30–60 seconds to start, so sudden spikes can't be met by adding servers on demand. Fix: pre-scheduled capacity for business hours, scaling on active calls per server, and queueing outbound calls.
5. **One Python process uses one core:** about 10 calls per copy of the app. Fix: run one app copy per core on 8-vCPU servers (section 11).
6. **AWS cost and limits:** not a bottleneck.

---

## 13. Other providers compared with Sarvam

**No provider gives 300 calls at once by default.** Each one needs a quota request or a sales conversation. Azure's and Google's requests are free forms; Sarvam's is a commercial agreement. Your app can mix providers: speech-to-text, AI and voice can each come from a different company, and Pipecat supports all of those listed below.

### Speech-to-text

| Provider | Indian languages | Default limit | Raising it | ~Price/min |
|---|---|---|---|---|
| **Sarvam Saaras v4** | 22 + English, best with mixed Hindi-English speech | 20 / 100 / 100 at once (PAYG / Pro / Growth) | Enterprise agreement | **₹0.49** |
| Google Chirp 3 | Hindi, Tamil, Telugu, Kannada, Malayalam and more (some in preview) | 300 sessions per region (documented as per 5 minutes) | Quota request in the Cloud console | ~₹1.40 |
| Azure Speech | ~13 Indian languages | 100 at once | Free request form (needs a company email) | ~₹1.45 |
| Deepgram Nova-3 | English and Hindi; Tamil and Telugu not confirmed | 150 at once on pay-as-you-go | Sales | ~₹0.70 |

### Voice

| Provider | Indian voices | Default limit | ~Price per 1,000 characters |
|---|---|---|---|
| **Sarvam Bulbul v4 Flash** | 9 languages, 222 voices (3–4 in most non-Hindi languages) | 1,000 at once on Growth ✅ | **₹1.00** |
| Azure Neural TTS | ~13 languages, about 2 voices each | 30 requests/sec, raisable to 1,000 | ~₹1.30 |
| Google Chirp 3 HD | Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati | Raisable | ~₹2.60 |
| ElevenLabs | Flash v2.5: only Hindi and Tamil | Only 30 at once on Scale/Business | Higher |
| Cartesia Sonic-3 / Smallest.ai | 9 Indian languages each | Not published | – |

### AI model

| Provider | Requests/min | Notes |
|---|---|---|
| **Sarvam-105b** | 60 / 200 / 300 | Tuned for Indian-language conversations |
| Google Gemini Flash | ~150–300 (Tier 1), ~1,000+ (Tier 2, after $250 spend) | Third-party figures; verify in AI Studio |
| OpenAI / Azure OpenAI | Thousands at higher usage levels | Azure OpenAI can be hosted in India |

300 calls at once need about **1,500 AI requests a minute**.

### Options for 300 calls at once

| Option | Setup | Sarvam Enterprise needed? | ~₹/min (no phone) | Indian-language quality |
|---|---|---|---|---|
| **A. All Sarvam** (recommended first) | Sarvam for everything | ✅ | ~₹1.0–1.2 | Best |
| B. Mixed providers | Google or Azure speech-to-text + Gemini or OpenAI + Sarvam voice | ❌ | ~₹2.2–2.4 | Good |
| **C. Sarvam + overflow** | Sarvam up to its limit; extra calls automatically use B | ❌ at first | ~₹1.2–1.6 blended | Best for most calls |
| D. All Azure or Google | One company | ❌ | ~₹2.5–3.0 | Fewer voices |

**Recommendation:** negotiate Sarvam Enterprise first. At the same time, test a backup AI model (the biggest bottleneck and the easiest to swap) and set up a backup speech-to-text account for overflow and outages. Avoid ElevenLabs for this use, and don't open several Sarvam accounts to add up limits.

⚠️ **Not confirmed:** non-Sarvam prices are approximate list prices (₹88 = $1). Gemini limits are from third-party guides. Deepgram's Indian-language support is unconfirmed.

---

## 14. App changes needed before running on many servers

| # | Today | Problem at scale | Change needed |
|---|---|---|---|
| 1 | SQLite database file | Only one server can use it | DynamoDB, shared by Lambda and all call servers |
| 2 | Outbound calls matched to agents in memory ([backend/app/telephony.py:15](backend/app/telephony.py#L15)) | Exotel may connect the call to a different server from the one that dialled → wrong agent or failed call | Store pending calls in DynamoDB or Redis, or put the call ID in the WebSocket URL |
| 3 | Calls start directly, with no capacity check | Going over Sarvam or Exotel limits → failed calls | Dialler: SQS + Lambda, starting calls only within min(Sarvam limit, Exotel channels, free server slots) |
| 4 | No per-client call limit | One client's campaign takes all capacity | Per-client limit (e.g. 10 calls at once by default) |
| 5 | No retry on Sarvam connection rejections | Burst rejections (`1003`) drop calls | Retry with short delays; ≤10 new calls per second |
| 6 | Browser calls use WebRTC | Hard to run behind a load balancer | WebSocket or a TURN server, or keep browser testing on one small separate server |
| 7 | No plan for overload | Incoming call when everything is full → silence | "All lines busy" message + callback queue, or transfer to a human |
| 8 | No login on the app | Anyone with the URL can use your credits | User login before any public deployment |

Estimated work: **about 1.5–2 weeks** for #1–#5 and #8.

### Target architecture at 300 calls at once

```
1,000 clients ─▶ Dashboard (S3 + CloudFront) ─▶ Lambda API ─▶ DynamoDB
                                                   │
                 Campaigns / outbound ─▶ SQS ─▶ Dialler Lambda (checks capacity + per-client limit)
                                                   │ "dial"
                                                   ▼
Customers ◀──── Exotel (350 channels) ──── wss ───▶ ALB ─▶ ~6 × c7g.2xlarge call servers (8 app copies, ~70 calls each)
                                                              │
                                                              ▼
                                                   Sarvam Enterprise (speech-to-text / AI / voice)
```

---

## 15. Production cost per minute

### Assumptions
- **Sarvam:** ₹1.20/min on pay-as-you-go, falling to ~₹1.10 on Growth (measured ₹1.08–1.38).
- **Exotel:** ~₹0.40/min incoming, ~₹1.00/min outgoing. ⚠️ Reseller estimates, not official; Exotel's plan fee comes on top. **Get a written quote.**
- **AWS (production, with a backup server):** ~₹6,500/month fixed (load balancer ~₹2,050 + 2 Fargate servers at 1 vCPU / 2 GB ~₹3,740 + secrets, monitoring and DNS ~₹700) + ~₹0.05/min variable. Lambda, DynamoDB, S3 and CloudFront are under ₹300/month at this volume.

### All-in cost by volume

| Minutes / month | Sarvam | Exotel (in / out) | AWS | **Incoming ₹/min** | **Outgoing ₹/min** |
|---:|---:|---:|---:|---:|---:|
| 5,000 | 1.20 | 0.40 / 1.00 | 1.35 | **≈ 2.95** | **≈ 3.55** |
| 20,000 | 1.20 | 0.40 / 1.00 | 0.38 | **≈ 2.00** | **≈ 2.60** |
| 50,000 | 1.15 (Pro) | 0.40 / 1.00 | 0.18 | **≈ 1.75** | **≈ 2.35** |
| 1,00,000 | 1.10 (Growth) | 0.40 / 1.00 | 0.12 | **≈ 1.60** | **≈ 2.20** |
| 10–15 lakh (300 calls at once at peak) | ~1.00–1.10 (Enterprise) | 0.40 / 1.00 | ~0.03–0.06 | **≈ 1.45–1.55** | **≈ 2.05–2.15** |

Add **18% GST**.

### What drives the cost
- **Sarvam is about 60%**, mostly the voice. Shorter agent replies lower the cost directly.
- **Exotel is the biggest unknown.** Outgoing calls can cost almost as much as Sarvam.
- **AWS only matters below about 10,000 min/month**, where the fixed cost dominates.
- **Sarvam's managed Voice Agents** cost ₹3.00–3.50/min plus telephony. Building it ourselves saves about **₹1.2–1.5/min** from about 20,000 min/month.

---

## 16. Languages

| Use | Languages |
|---|---|
| **In the app now** | **10:** English, Hindi, Tamil, Telugu, Kannada, Marathi, Gujarati, Bengali, Punjabi, **Malayalam** |
| Full voice agent possible with Sarvam | 11 (the 10 above + Odia) |
| Understand and translate only (no voice) | 23 (adds Assamese, Urdu, Nepali, Konkani, Kashmiri, Sindhi, Sanskrit, Santali, Manipuri, Bodo, Maithili, Dogri) |

- **Malayalam was added on 3 Nov 2026.** Bulbul v4 Flash has no Malayalam voices, so it uses **Aparna · edtech** (an English voice) across languages. A test sentence was accepted by Sarvam (HTTP 200); quality still needs a listening check.
- **Odia** (and native-voice Malayalam) would need **Bulbul v3**: ₹3 per 1,000 characters instead of ₹1, about **+₹1.60/min**, and a bit slower.

---

## 17. Voices

### Voices per language (Bulbul v4 Flash, 222 in the app's list)

| Language | Voices |
|---|---|
| Hindi | 116 |
| English | 75 |
| Marathi | 9 |
| Tamil, Telugu, Kannada, Punjabi | 4 each |
| Gujarati, Bengali | 3 each |
| Malayalam, Odia | 0 |

- The small number of voices outside Hindi and English is **Sarvam's limit**, not the app's.
- Sarvam's API reference now lists about **290** v4 Flash voices, so the app's `voices.json` may be out of date. Refreshing it could add voices.

### Aparna · edtech in every language (built, testing)
- `aparna_en_edtech` is offered in **every language**, marked "(English voice, test)". The language's own voices are listed first.
- **Not officially supported by Sarvam.** Expect an accent. Check pronunciation (Tamil ழ/ற, Malayalam ഴ/ള) before using it with clients.
- To add or remove voices: `CROSS_LANGUAGE_VOICES` in [frontend/src/AgentConfigForm.tsx](frontend/src/AgentConfigForm.tsx).

### Your own voice (voice cloning; not built)
- Sarvam has an **Instant Voice Cloning API** (beta), available with the normal API key. It needs a 10–15 second clean recording.
- **Officially supports other languages:** an English recording can speak Tamil, Telugu and others.
- Up to 50 saved voices on pay-as-you-go. A consent checkbox is required; other people's voices need their written consent.
- **Price:** ₹2.00 per 1,000 characters (no plan discounts) → about **₹1.59/min** for the voice, so **≈ ₹2.05/min** total Sarvam (≈ ₹0.80/min more than now).
- **Work needed:** a custom voice connection for live calls (Pipecat 1.15 doesn't support the cloning API), a "My voices" screen, and a separate price for cloned-voice calls. About 1–2 days.
- **Risks:** beta API; latency not published (measure it); confirm with Sarvam that cloned voices are allowed for client use.

---

## 18. Tools and integrations

### How tools work today
An agent can call **any HTTP endpoint** during a call ([backend/app/tools.py](backend/app/tools.py)). The AI fills in the details, the backend sends them, and the reply goes back to the AI.

### Google Calendar
- **Prototype (no code changes):** a small Google Apps Script web app with `check_availability` and `book_appointment`, added as two tools. Alternatives: an n8n, Make or Zapier webhook, or Cal.com.
- **Gaps to fix first:**
  1. The agent isn't told today's date or time, so "tomorrow at 4" can't be turned into a date.
  2. Tool headers are fixed, so every client shares one login. Production needs a per-client "Connect Google" sign-in.
  3. The caller's number isn't passed to the AI.
  4. No "let me check" line while a tool runs.
  5. No after-call webhook.
- **Production:** per-client Google sign-in with stored logins, built-in book/reschedule/cancel tools, and timezone handling. Google must review calendar access before outside users can connect; this takes days to weeks.

### Tools to add later

| Category | Integrations |
|---|---|
| Scheduling | Google Calendar, Outlook / Microsoft 365, Cal.com |
| CRM | Zoho CRM, LeadSquared, HubSpot, Salesforce, Freshsales |
| Support | Freshdesk, Zendesk |
| Orders | Shopify, WooCommerce, Shiprocket |
| Payments | Razorpay, Cashfree payment links |
| Messaging | WhatsApp (Meta Cloud API, Gupshup, Interakt), SMS (MSG91, Twilio), email |
| Data | Google Sheets, Airtable |
| Automation | Zapier, Make, n8n |
| Call controls (need code) | Transfer to a human, voicemail detection |
| After the call (need code) | Post-call webhook with transcript and extracted details |
| Knowledge base (need code) | Answers from the client's uploaded documents |

**Suggested order:** add today's date and the caller's number to the AI's instructions → Google Calendar → post-call webhook → WhatsApp/SMS confirmations.

---

## 19. Next steps

1. **Apply the browser-call STUN fix** (section 6, Step 1).
2. **Deploy to one EC2 t4g.small (or c7g.large for a cleaner load test) and run the 50-minute cost test.** This gives the real Sarvam and Exotel cost per minute and the number of calls per server (about ₹160–215).
3. **Build and run the one-script load test** (section 8) to confirm calls per server (about half a day of work + ~₹55 per run).
4. **Before onboarding many clients:** contact **Sarvam about Enterprise** (state the expected peak: 100, then 300 calls at once, and monthly minutes). Ask **Exotel** for channels, dialling rate and a written price.
5. **Set up a backup provider:** test Gemini Flash or Azure OpenAI as the AI model on Tamil, Telugu and Hindi calls, and request a higher speech-to-text limit on Azure or Google for overflow (section 13).
6. **Build the production version:** section 14, changes #1–#5 and #8 (about 1.5–2 weeks).
7. **Load test** at 50 → 100 → 300 calls at once before going live.
8. **Move to the Sarvam Pro plan before going live,** both for the higher limits and the lower prices.

---

## Sources

- [Sarvam pricing, plans and rate limits](https://docs.sarvam.ai/api/getting-started/pricing/llms.txt)
- [Sarvam models and supported languages](https://docs.sarvam.ai/api/getting-started/models.md)
- [Bulbul v4 Flash best practice guide](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/best-practice-guide-for-bulbul-v-4-flash)
- [Sarvam text-to-speech API reference](https://docs.sarvam.ai/api-reference-docs/text-to-speech/convert)
- [Sarvam Voice Cloning API](https://docs.sarvam.ai/api/api-guides-tutorials/voice-cloning/overview)
- [Sarvam commercial licensing](https://docs.sarvam.ai/api/getting-started/commercial-licensing.md)
- AWS prices: Mumbai (ap-south-1) price list, as used in `SARVAM_VOICE_AGENTS_ANALYSIS.md` Part C
- [Azure Speech quotas and limits](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits)
- [Google Speech-to-Text v2 quotas](https://docs.cloud.google.com/speech-to-text/v2/quotas)
- [Google Chirp 3 speech-to-text model](https://cloud.google.com/speech-to-text/v2/docs/chirp_3-model)
- [Google Chirp 3 HD voices](https://cloud-dot-devsite-v2-prod.appspot.com/text-to-speech/docs/chirp3-hd)
- [Deepgram API rate limits](https://developers.deepgram.com/reference/api-rate-limits)
- [ElevenLabs concurrency limits](https://elevenlabs.io/docs/help-center/technical/how-many-text-to-speech-requests-can-i-make-and-can-i-increase-it.md)
- [ElevenLabs supported languages](https://elevenlabs.io/docs/help-center/other/what-languages-do-you-support)
- [Cartesia available models](https://docs.cartesia.ai/getting-started/available-models)
- [Smallest.ai models](https://docs.smallest.ai/models)
- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
