# Sarvam Voice Agents: Analysis, Key Findings & Prototype Plan

_Research date: 30 Oct 2026. Sources: docs.sarvam.ai (Voice Agents section), the published `sarvam-conv-ai-sdk` npm package (v0.0.42), and the Sarvam MCP server docs._

Each statement is labelled with how sure we are:

- ✅ **Verified**: stated in the official docs or read directly from SDK source.
- ⚠️ **Unverified**: inferred or not documented publicly. Confirm it in the Phase 0 spike.

> **Update (Part B, §10–§15):** Two follow-ups were researched: a full re-check of every Sarvam API endpoint for agent creation, and a cost comparison for **building our own agent runtime** on Sarvam's STT + LLM + TTS APIs.
> **Outcome:** There is still no public REST endpoint to create an agent. The build-it-yourself (DIY) route costs about **₹0.70–2.40/min (typically ~₹1.20)** versus **₹3.50/min** for managed Voice Agents. It also removes the need for any Sarvam agent-creation API, because an "agent" becomes just a config row in our DB. **We now recommend the DIY runtime for this prototype.** See §15.

---

## 1. What we're building

A prototype web app where we:

1. **Create clients**. Creating a client also creates that client's **agent record (data model)** in our DB. The same form configures the agent: prompt, greeting, instructions, language, voice, variables and settings.
2. **Provision the agent in Sarvam at the same time.** The client is saved right away and the Sarvam agent is created in the background, with a live status.
3. **Edit and version** the agent's configuration and commit versions.
4. **Test the agent** from inside our app, using text chat, browser voice, and Sarvam's simulated test suites.

---

## 2. Sarvam Voice Agents: what it is

| Item | Detail |
|---|---|
| Product | Sarvam **Voice Agents**, internally called **Samvaad** (formerly "Conversations"). ✅ |
| Dashboard | `https://indus.sarvam.ai/samvaad` ✅ |
| Languages | 11 Indian languages + English, code-mixed speech supported. ✅ |
| Models | ASR **Saaras v4**, TTS **Bulbul v3 / v4**, LLM routed automatically (`sarvam-105b-conversations` + open-weight fine-tunes). ✅ |
| **LLM choice** | **None. There is no model picker and you cannot bring your own model.** Only the **temperature** (0.1–0.9, default 0.3) can be tuned. ✅ |
| Data residency | All models self-hosted by Sarvam in India. ✅ |

> **Implication:** In our app, "create a model" means our **data model / DB entity** for the agent. It does not mean choosing an LLM, because Sarvam doesn't allow that.

### 2.1 Anatomy of an agent ✅

| Part | What it holds |
|---|---|
| **Greeting** | First message the agent speaks. Supports variables. |
| **Instructions** | Free text, usually in sections: Persona, Objective, Context, Guardrails, Steps/Workflow. |
| **Variables** | **Sarvam variables** (read-only: `current_date`, `current_time`, `current_datetime`, `current_day`, `start_datetime`, `language_name`) and **Agent variables** (yours). An agent variable can be an **Input** (name + default value; filled from telephony, on-start hook, campaign CSV, or SDK `agent_variables`), an **Output** (String or Enum; extracted by the LLM after the call via an extraction prompt), or both. |
| **Call goal** | `Successful when <variable> <op> <value>`. Drives success analytics. |
| **Voice** | TTS model (Bulbul V3/V4), speaker, speed (0.5–2.0x), pitch, volume (0.7–2.0), per-language voices, pronunciation dictionary (JSON ≤5 MB). |
| **Language** | Starting language, allowed languages, switch during call, auto-detect switch, Indic numerals. |
| **Conversation settings** | Temperature, interruptions (sensitivity, eagerness), background sound, nudges for quiet callers, hang up after nudges, max call length (≤60 min), voicemail, call transfer. |
| **Tools** | HTTP/API tools, data validation, call transfer, KB query tool, code tools (enterprise). |
| **Hooks** | On-start (fetch context before the call) and on-end (push results after the call). |
| **Knowledge base** | Named + described group of files (PDF, DOCX, CSV, TSV, TXT, MD). Ingestion is async. Attaching a KB auto-adds the query tool. |
| **States** | Single-state by default. Converting to multi-state is **one-way**. |

> ⚠️ **Bulbul V3 reaches end of life for Voice Agents on 10 Nov 2026** (11 days from now). **Always create agents on Bulbul V4.** V4 voice names differ, for example `Shubh` becomes `Shubh - Hinglish Ad Voice`.

### 2.2 Versioning ✅

- **Draft**: mutable, in-progress edits.
- **Committed version**: immutable snapshot with an integer version number. **Committing is irreversible.**
- **Deployed**: the version serving live traffic.
- **Deployments, campaigns, test-suite runs, and SDK sessions always use a committed version, never the draft.** The SDK uses the latest committed version if `version` is omitted. **The connection fails if the agent has no committed version.**
- Draft updates **merge** nested objects key by key, but **lists are replaced whole**. Always resend the full list (variables, voices, and so on), or the other items are silently dropped. (From the MCP docs.)

---

## 3. Ways to integrate programmatically

### 3.1 The four integration surfaces

| Surface | Auth | What it can do | Good for our app? |
|---|---|---|---|
| **A. Public REST API** (`apps.sarvam.ai/api/...`) | `X-API-Key` header | Deployments, campaigns, instant outbound, analytics, boards, **tests (evals)**. ✅ | **Yes**, for testing and analytics. **Does not include agent create/configure** in the public reference. ✅ |
| **B. Agent-authoring "API recipes"** (dashboard → **Deploy with Code**) | `X-API-Key` | Docs say: "Create or update an agent configuration… set up agents programmatically" (marked **preview**). ✅ The exact endpoints are only shown **inside the logged-in dashboard**. ⚠️ | **Best option if it works.** Confirm in Phase 0. |
| **C. MCP server** `https://mcp.sarvam.ai/voice-agents` | OAuth 2.1 via Sarvam SSO, **24 h token, no refresh** | Full authoring: `configure_agent` (create/update/clone), `agents` commit, `run_eval`, KB, telephony, and more. ✅ | **Fallback.** Fine for a single-operator prototype. Not suitable for unattended production because of the daily re-login. |
| **D. Realtime SDK / WebSocket** (`sarvam-conv-ai-sdk`) | `X-API-Key` (server-side) | Live **voice (`call`)** or **text (`chat`)** sessions with a committed agent. ✅ | **Yes**, for the test playground. |

### 3.2 REST base URLs ✅

| Service | Base URL | Path shape |
|---|---|---|
| Deployments (app authoring) | `https://apps.sarvam.ai/api/app-authoring` | `/v1/orgs/{org_id}/workspaces/{workspace_id}/deployments` |
| Campaigns & Cohorts | `https://apps.sarvam.ai/api/scheduling` | `/v1/orgs/{org_id}/workspaces/{workspace_id}/...` |
| Instant Outbound | `https://apps.sarvam.ai/api/outbounds` | `/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds` |
| Analytics & Boards | `https://apps.sarvam.ai/api/analytics` | `/v1/{org_id}/{workspace_id}/{app_id}/interactions` |
| Tests (evals) | `https://apps.sarvam.ai/api/evals` | `/v1/{org_id}/{workspace_id}/test-suites` |
| **Runtime (SDK sessions)** | `https://apps.sarvam.ai/api/app-runtime/` | `orgs/{org_id}/workspaces/{workspace_id}/apps/{app_id}/url` → `{ url, reference_id }` (signed, **single-use** WebSocket URL). Read from SDK source ✅ |

- `org_id` and `workspace_id` come from the dashboard URL or **Settings**. The API key comes from **Settings → API Key**.
- An agent is identified by **`app_id`** plus an integer **`app_version`**.
- ⚠️ The agent CRUD endpoints probably live under `app-authoring` (for example `.../apps`). Copy them from the dashboard recipes; don't guess.

### 3.3 Realtime SDK details ✅

- npm: `sarvam-conv-ai-sdk` (browser entry `sarvam-conv-ai-sdk/browser`, class `ConversationAgent`). Python: `sarvam-conv-ai-sdk` (`AsyncSamvaadAgent`).
- `interaction_type`: **`call`** (voice, needs `BrowserAudioInterface`) or **`chat`** (text; `agent.sendText(text)`).
- Config: `org_id`, `workspace_id`, `app_id`, `user_identifier`, `user_identifier_type`, `input_sample_rate` (8000/16000), `output_sample_rate` (16000/22050), optional `version`, `agent_variables`, `initial_language_name`, `initial_bot_message`.
- Callbacks: `transcriptCallback`, `stateCallback` (IDLE / CONNECTING / CONNECTED / LISTENING / SPEAKING / ERROR), `audioLevelCallback`, `eventCallback`, `endCallback`.
- **Never put the API key in the browser.** Set `apiKey: ""` and `baseUrl: "/api/sarvam/"` so the SDK calls **our backend proxy**, which adds `X-API-Key` and forwards to `app-runtime`.
- There is no reconnect. If a session drops, create a new agent instance. Start sessions from a click, because browsers require a user gesture before playing audio. The microphone needs HTTPS (localhost is fine).

### 3.4 Tests API (simulated calls) ✅

- `POST /api/evals/v1/{org}/{ws}/test-suites` with `name`, `app_id?`, `variables[]`, `global_guardrails[]` (≤20), and `test_cases[]` (≤200; each has `name`, `category`, `user_scenario`, `expected_behaviors[{name, description}]`, `max_turns`).
- Run a suite: `POST .../test-suites/{id}/runs`. Run one case: `POST .../test-suites/{id}/test-cases/{case_id}/runs`, body `{ app_id, app_version, frequency, run_name }` → `202 { run_id }`.
- Poll `GET .../runs/{run_id}` until `completed` or `failed`, then read results (transcript + pass/fail per behavior).
- Limits: 60 req/min per key, **10 suite runs / 5 min**, 20 single-case runs/min. `402` means out of credits. There is **no delete and no cancel via the API**.

### 3.5 Instant outbound call ✅ (for later; needs telephony)

`POST /api/outbounds/v1/orgs/{org}/workspaces/{ws}/outbounds`, body `{ app_config: { app_id, app_version, connection_config: { connection_id, agent_phone_number }, agent_variables, app_overrides: { initial_bot_message, initial_language_name, initial_state_name } }, user_config: { user_phone_number } }`.

---

## 4. Pricing, credits & limits ✅

| Item | Cost |
|---|---|
| Agent conversation (pay as you go) | **₹3.50 per minute**, rounded **up** per 60 s (a 45 s call costs 1 min, a 61 s call costs 2 min) |
| **Simulated test run** | **₹2 per run** |
| Sarvam telephony (Vobiz) | ₹0.20 per 30 s |
| Phone number rental | **₹59 per 30 days** |
| Unanswered or busy calls | Free |
| Pay-as-you-go limits | **4 concurrent calls**, 20 calls started per minute (org-wide) |

**Your 79 free credits.** On paid plans, 1 credit = ₹1. ⚠️ We assume free credits work the same way. That gives roughly:

- **~22 minutes** of voice conversation, **or**
- **~39** simulated test runs, **or** a mix.
- **Don't rent a phone number** for this prototype. ₹59 would use about 75% of the credits.
- ⚠️ Unknown: whether **text `chat` sessions** and the dashboard's **Test agent** panel are billed per minute. Check by running one session and reading the balance before and after.
- ⚠️ Unknown: whether authoring calls (create, update, commit) cost anything. They're expected to be free.

---

## 5. Proposed architecture

### 5.1 Stack (recommended)

- **Next.js (App Router) + TypeScript**: a single codebase for the UI and the API routes. The Sarvam web SDK is TypeScript, so it fits naturally.
- **Prisma + SQLite** for the prototype; switch to Postgres later without code changes.
- **Zod** for validating agent configs, mirroring Sarvam's `agent-config` JSON schema.
- **In-process job runner** (a simple queue with retries) for provisioning. BullMQ/Redis can replace it later.
- All Sarvam secrets live in `.env` and are used **server-side only**.

### 5.2 High-level diagram

```
┌──────────────────────── Browser (our app UI) ─────────────────────────┐
│  Clients list │ Create Client + Agent form │ Agent editor │ Test Lab  │
│                                                   │                    │
│                       sarvam-conv-ai-sdk/browser (baseUrl=/api/sarvam/)│
└─────────────┬───────────────────────────────────────────┬─────────────┘
              │ REST (our API)                            │ signed-URL fetch
              ▼                                           ▼
┌──────────────────────── Next.js server ───────────────────────────────┐
│  /api/clients        /api/agents/:id   /api/agents/:id/commit         │
│  /api/agents/:id/tests  /api/sarvam/* (runtime proxy, adds X-API-Key) │
│                                                                       │
│  ProvisioningService ──► Job queue (retry, idempotent)                │
│        │                                                              │
│        ▼                                                              │
│  SarvamAuthoringProvider  (interface)                                 │
│     ├─ RestAuthoringAdapter   (dashboard "API recipes", X-API-Key)    │
│     ├─ McpAuthoringAdapter    (mcp.sarvam.ai, OAuth token)            │
│     └─ ManualAdapter          (paste app_id from dashboard)           │
│  SarvamEvalsClient  SarvamAnalyticsClient                             │
│                                                                       │
│  Prisma ──► SQLite / Postgres                                         │
└─────────────┬─────────────────────────────────────────────────────────┘
              ▼
   apps.sarvam.ai: app-authoring │ app-runtime (WS) │ evals │ analytics
```

**Key design choice:** the rest of the app depends only on the `SarvamAuthoringProvider` interface. Whichever authoring path Phase 0 confirms (REST recipe or MCP) plugs in without touching the UI or DB.

```ts
interface SarvamAuthoringProvider {
  createAgent(cfg: AgentConfig): Promise<{ appId: string }>;
  updateDraft(appId: string, cfg: AgentConfig): Promise<void>; // send FULL lists
  commit(appId: string): Promise<{ version: number }>;
  getAgent(appId: string): Promise<RemoteAgent>;
  listVoices(): Promise<Voice[]>;
}
```

### 5.3 Data model (DB)

```
Client
  id, name, slug, industry, contactName, contactEmail, contactPhone,
  notes, createdAt, updatedAt

Agent                          (1 client : N agents; the UI starts with 1)
  id, clientId → Client
  name                         e.g. "<client-slug> – Support Agent"
  sarvamAppId?                 filled after provisioning
  syncStatus                   PENDING | PROVISIONING | READY | FAILED | OUT_OF_SYNC
  syncError?, lastSyncedAt?
  draftConfig  (JSON)          our canonical AgentConfig (below)
  latestVersion? (int)         last committed Sarvam app_version
  createdAt, updatedAt

AgentVersion
  id, agentId → Agent, version (Sarvam app_version), configSnapshot (JSON),
  note, committedAt

TestSession                    (playground chat / voice runs)
  id, agentId, version, mode (CHAT | VOICE), interactionId,
  transcript (JSON), startedAt, endedAt, durationSec, estCostInr

TestSuite / TestRun            (Sarvam evals mirror)
  sarvamSuiteId, sarvamRunId, status, results (JSON), costInr

SyncEvent                      (audit log of every Sarvam call)
  id, agentId, action, requestSummary, responseStatus, error, createdAt
```

**`AgentConfig` (our canonical shape; map it to Sarvam's schema in the adapter):**

```ts
{
  greeting: string,
  instructions: { persona, objective, context, guardrails, steps },  // joined into one prompt
  language: { starting: "English", allowed: ["English","Hindi"], switchDuringCall: true },
  voice: { ttsModel: "bulbul-v4", speaker: "Shubh - Hinglish Ad Voice", speed: 1.0, pitch: 0, volume: 1.0 },
  temperature: 0.3,
  inputVariables:  [{ name, defaultValue, sendToLlm: true }],
  outputVariables: [{ name, type: "string"|"enum", enumValues?, extractionPrompt }],
  callGoal?: { variable, operator: "=", value },
  settings: { allowInterrupt: true, maxCallMinutes: 10, nudges: [...], voicemail?: {...} },
  knowledgeBaseIds: []
}
```

### 5.4 Flow: "Create client → agent provisioned in parallel"

```
User submits "New Client" form (client fields + agent config)
   │
   ▼
POST /api/clients
   1. Validate with Zod.
   2. DB transaction: insert Client + Agent(syncStatus=PENDING, draftConfig).
   3. Enqueue job provisionAgent(agentId).
   4. Return 201 { clientId, agentId } immediately.  ◄── the UI isn't blocked
   │
   ▼  (background, at the same time)
provisionAgent job
   a. syncStatus = PROVISIONING
   b. provider.createAgent(draftConfig)      → sarvamAppId   (saved immediately)
   c. provider.commit(sarvamAppId)            → version 1     (required before any test)
   d. insert AgentVersion(v1), syncStatus = READY
   on error → syncStatus = FAILED, syncError = message, show a "Retry" button
   │
   ▼
UI polls GET /api/agents/:id (or listens over SSE) → badge goes Pending → Provisioning → Ready
```

- **Why local-first:** our DB is the source of truth, and Sarvam is synced to it. If Sarvam fails, nothing is lost and we retry.
- **Idempotency:** store `sarvamAppId` as soon as it's returned. On retry, if `sarvamAppId` is set, skip creation. Agent names include the client slug, so duplicates are easy to detect.
- **Parallel across clients:** jobs run concurrently but are throttled to stay under rate limits.
- **Committing is irreversible,** so auto-committing v1 on creation is a setting you can turn off (default on, because testing requires a committed version).

### 5.5 Flow: Edit → Commit → Test

1. Edit the agent in our editor. Save writes `draftConfig` locally, then calls `provider.updateDraft` with the **full** config (lists are replaced whole).
2. The **Commit** button creates a new immutable Sarvam version and stores an `AgentVersion` snapshot.
3. **Test Lab** with three modes:
   - **Chat test** (`interaction_type: "chat"`): type and get text replies. Cheapest and fastest for checking prompt logic.
   - **Voice test** (`interaction_type: "call"`): browser mic and speaker through our `/api/sarvam/*` proxy, with live transcript, state indicator, mute, and stop.
   - **Simulated tests** (Evals API): define scenarios and expected behaviors, run them against a version, and view pass/fail with transcripts.
4. Every session stores its transcript and an estimated cost (duration × ₹3.50) in `TestSession`.

### 5.6 Multi-tenancy reality check ✅

The API key, MCP connection, and our app all point at **one Sarvam org and workspace**. Every client's agents therefore live in **the same Sarvam workspace**. "Clients" are a concept in **our app only**. We keep them apart through naming (`<client-slug> – <agent>`) and our DB mapping. True per-client isolation would need separate Sarvam workspaces, which is out of scope for the prototype.

---

## 6. Implementation plan

### Phase 0: Discovery spike (½–1 day, ~₹5–10 of credits)

Goal: confirm the unknowns before writing app code.

1. Collect **`org_id`, `workspace_id`**, and create an **API key** (Settings → API Key).
2. Open **Dashboard → Deploy with Code → API recipes**. Copy the exact **create/update agent** and **commit** requests. ⚠️ This is the main unknown.
3. Add the MCP server to Claude Code (run in a terminal, then `/mcp` → Authenticate):
   `claude mcp add --transport http sarvam-voice-agents https://mcp.sarvam.ai/voice-agents`
   Then read `sarvam://schemas/agent-config`, `sarvam://examples/agent-config` and `sarvam://playbooks/agents`. These give us the **exact config JSON** for our Zod schema.
4. Create one throwaway agent through the recipe (or MCP), commit it, and note `app_id` and the version.
5. Run a ~30-line Node script: a **chat** session with the SDK, then check the **credit balance**, to learn whether chat is billed.
6. Run **one** 1-minute voice session and **one** simulated test run to confirm costs.
7. **Decide** which adapter to use: REST recipe (preferred), MCP (fallback), or Manual (last resort).

### Phase 1: Foundation (1 day)

- Scaffold Next.js + TS + Tailwind + Prisma (SQLite). Add `.env` with `SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`.
- Prisma schema from §5.3, plus the Zod `AgentConfig` schema.
- A `lib/sarvam/` module: the provider interface, the chosen adapter, an evals client, the runtime proxy route, a retry/backoff helper that honours `Retry-After`, and `SyncEvent` logging.

### Phase 2: Clients + agent provisioning (1–2 days)

- Clients list and detail pages.
- **Create Client** wizard: Client info → Agent basics (name, greeting, persona/objective/guardrails) → Language & Voice (voice list from Sarvam, Bulbul V4 only) → Variables & Goal → Review & Create.
- Background `provisionAgent` job, a status badge, and Retry.

### Phase 3: Agent editor + versioning (1–2 days)

- Tabbed editor: Instructions, Variables, Voice & Language, Settings.
- "Unsaved changes" vs "Draft synced" vs "Committed vN" indicators.
- Version history with a config diff (local snapshots).

### Phase 4: Test Lab (2 days)

- Chat test panel.
- Voice test panel (mic permission handling, transcript, state, mute, stop, `finally` cleanup).
- Choose which version to test, and pass `agent_variables` for personalised runs.
- Simulated tests: suite builder, run, polling, results view.
- A **credit guard**: show estimated spend per session, ask for confirmation before voice or suite runs, and auto-stop voice sessions at N minutes (default 2).

### Phase 5: Polish (optional, 1 day)

- Pull call transcripts and outputs from the Analytics API onto the agent page.
- Error toasts, empty states, seed data.
- Later: knowledge-base upload, telephony, campaigns (needs a number, so skip while on free credits).

### Credit budget for the whole prototype (79 credits)

| Activity | Est. spend |
|---|---|
| Phase 0 spike (1 voice min + 1 sim run + chat check) | ~₹6–10 |
| Dev testing: ~8 short voice sessions (≤1 min each) | ~₹28 |
| ~5 simulated test runs | ~₹10 |
| **Buffer** | **~₹30** |

Rules: keep voice tests under 60 s (billing rounds up per minute), test logic in **chat** first, and **never rent a number** on free credits.

---

## 7. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Agent-authoring REST is **preview / undocumented publicly** | Endpoints may change | Provider interface with REST, MCP and Manual adapters; log every call in `SyncEvent` |
| MCP token expires every **24 h, no refresh** | Daily re-login if MCP is the authoring path | Acceptable for a single-operator prototype; show a "Reconnect Sarvam" banner |
| Lists replace whole on update | Silent loss of variables or voices | Always send the full config from our DB (never partial lists) |
| Sessions need a **committed** version | Tests fail on new agents | Auto-commit v1 on provisioning; disable test buttons until `latestVersion` exists |
| Commit is irreversible | Version clutter | Commit only on explicit click (after v1) |
| API key leakage | Account abuse | Key only on the server; browser SDK goes through the `/api/sarvam/*` proxy |
| Small credit balance | Can't finish testing | Credit guard, chat-first testing, auto-stop timer |
| **Bulbul V3 EOL 10 Nov 2026** | Agents on V3 break | Enforce Bulbul V4 in validation |
| Pay-as-you-go limits: 4 concurrent calls, 10 suite runs / 5 min | 429s during demos | Queue and throttle; honour `Retry-After` |
| All clients share one Sarvam workspace | No hard isolation | Naming convention + DB mapping; separate workspaces later if needed |

---

## 8. Open questions (answer during Phase 0)

1. What exactly are the create/update/commit agent endpoints and payloads in the dashboard's API recipes?
2. Are text **chat** sessions and the dashboard **Test agent** billed, and at what rate?
3. Does the 79-credit free balance map 1:1 to ₹ (that is, ~22 voice minutes)?
4. Is there a per-workspace limit on the number of agents?
5. Can an agent be **deleted** through the API? Genie can't delete agents, so cleanup may have to happen in the dashboard.

---

## 9. Useful links

- Docs index: https://docs.sarvam.ai/voice-agents/llms.txt (append `.md` to any page for raw Markdown)
- API intro: https://docs.sarvam.ai/voice-agents/api/introduction
- Web SDK: https://docs.sarvam.ai/voice-agents/deploy/sdks/web
- Python SDK: https://docs.sarvam.ai/voice-agents/deploy/sdks/python
- Tests API: https://docs.sarvam.ai/voice-agents/api/tests/overview
- Deploy with Code: https://docs.sarvam.ai/voice-agents/deploy/deploy-with-code. Recipes: https://indus.sarvam.ai/samvaad/deploy/with-code
- MCP server: https://docs.sarvam.ai/voice-agents/mcp
- Pricing: https://docs.sarvam.ai/voice-agents/pricing
- Voice & language (V3→V4 names): https://docs.sarvam.ai/voice-agents/build/voice-language
- Docs MCP (for coding assistants): https://docs.sarvam.ai/_mcp/server

---
---

# Part B: Agent-creation API re-check & the "build our own agent" option

## 10. Is there an API to create Sarvam agents? (full re-check)

We searched the **entire** Sarvam API reference (`docs.sarvam.ai/api-reference/llms.txt`, ~150 endpoints) and the Voice Agents docs index.

| Area in the API reference | Endpoints exist? |
|---|---|
| Deployments (put an agent on a number) | ✅ create / get / list / update / delete / status |
| Campaigns, cohorts, webhooks | ✅ |
| Instant outbound call | ✅ |
| Analytics, boards, recordings, transcripts | ✅ |
| Tests (evals) | ✅ |
| STT, TTS, chat/LLM, translate, voice cloning, pronunciation dictionary | ✅ |
| **Create / update / commit an agent (app)** | ❌ **Not in the public reference** |

So the only ways to create a *managed* Sarvam agent from code are:

1. **Dashboard → Deploy with Code → "API recipes"**: the docs say this includes "Create or update an agent configuration" (preview). It's visible only when logged in. ⚠️ Still to be checked by you.
2. **MCP server** (`configure_agent` + `agents` commit): documented and works, but the OAuth token lasts **24 h with no refresh**, so a person must log in again every day. OK for a demo; fragile for an always-on backend.

There's a third option that needs **no agent API at all**: build our own agent on Sarvam's individual services.

---

## 11. The DIY option: our own agent on Sarvam STT + LLM + TTS

Sarvam itself documents this path ("When to use the APIs instead": "if you already run your own orchestration, for example **LiveKit** or **Pipecat**"). Both frameworks ship official Sarvam plugins.

```
Caller audio ─► Saaras v4 STT (WebSocket streaming, VAD turn detection)
                      │ text
                      ▼
              sarvam-105b-conversations (LLM, streaming, reasoning OFF)
                      │ text (sentence by sentence)
                      ▼
              Bulbul v4 Flash TTS (WebSocket streaming) ─► agent audio back
Orchestrator (Pipecat / LiveKit Agents): turn-taking, barge-in, tool calls, transcript
```

Example (Sarvam's LiveKit guide; Pipecat is equivalent):
`stt=sarvam.STT(model="saaras:v4")`, `llm=sarvam.LLM(model="sarvam-105b-conversations")`, `tts=sarvam.TTS(model="bulbul:v4-flash", speaker="simran_en_customer")`.

### 11.1 Per-service prices (Sarvam API, pay as you go, ex-GST) ✅

| Service | Price | Billing unit |
|---|---|---|
| **STT** Saaras v4 (real-time / streaming / batch) | **₹0.49 per min** (Pro ₹0.45, Growth ₹0.41) | **Billed per second** |
| **TTS** Bulbul **v4 Flash** | **₹1.00 per 1,000 characters** (Pro ₹0.925, Growth ₹0.85) | Per character |
| TTS Bulbul v3 (avoid) | ₹3.00 per 1,000 chars | Per character |
| **LLM** `sarvam-105b-conversations` | **₹15 / 1M input**, ₹5 / 1M cached input, **₹60 / 1M output** | Per token, same on all plans |
| LLM cheaper alternative `mimo-v2.6-flash` (beta) | ₹12.5 in / ₹25 out per 1M | Per token |
| Free credits | ₹100 per verified user, usable on any API, never expire ⚠️ (likely the same wallet as your 79 credits) | — |

**Important LLM gotcha:** `sarvam-105b` models have **thinking ON by default** (reasoning tokens bill as output and add latency). For voice, call with `reasoning_effort: null`.

### 11.2 Cost per minute of conversation (our estimate)

Assumptions for one minute of a typical support or sales call:

- STT streams for the whole call (needed to detect barge-in).
- The agent speaks 35–55% of the time at about 14 characters per second, plus 15–40% extra for text synthesized but cut off by interruptions.
- The LLM runs about 4 turns a minute with ~2.5k input tokens per turn (prompt + history) and ~60 output tokens per turn.

| Component | Low | **Typical** | High | Notes |
|---|---:|---:|---:|---|
| STT (Saaras v4) | ₹0.30 | **₹0.49** | ₹0.49 | Low = only send audio when local VAD hears speech |
| TTS (Bulbul v4 Flash) | ₹0.30 | **₹0.45** | ₹0.65 | ~300 / 435 / 650 chars per min |
| LLM (`sarvam-105b-conversations`) | ₹0.08 | **₹0.17** | ₹0.35 | Low = prefix cache hits; High = 4k context + reasoning on + post-call extraction |
| Orchestration hosting | ₹0.00 | **₹0.10** | ₹0.90 | Low = Pipecat on a local machine; Typical = small VPS amortized; High = LiveKit Cloud overage (~$0.01/min after 1,000 free min/month) |
| **Total per minute** | **≈ ₹0.70** | **≈ ₹1.20** | **≈ ₹2.40** | |
| Managed Sarvam Voice Agents | ₹3.50 | ₹3.50 | ₹3.50 | Pay-as-you-go plan |

**Telephony** (Exotel, Plivo, Twilio, Vobiz and so on) costs the same either way, so it's left out. On managed, Sarvam bills telephony on top as well.

### 11.3 The rounding effect makes DIY cheaper still

Managed bills **whole minutes, rounded up**. DIY STT bills **per second**.

| Call length | Managed (₹3.50, rounded up) | DIY typical (₹1.20, per second) |
|---|---:|---:|
| 20 s | ₹3.50 | ₹0.40 |
| 61 s | ₹7.00 | ₹1.22 |
| 1 min 40 s | ₹7.00 | ₹2.00 |
| 5 min | ₹17.50 | ₹6.00 |

### 11.4 Monthly view

| Minutes / month | Managed (best plan) | DIY typical (₹1.20) | DIY high (₹2.40) |
|---:|---:|---:|---:|
| 1,000 | ₹3,500 | ₹1,200 | ₹2,400 |
| 10,000 | ₹32,500 (Pro) | ₹12,000 | ₹24,000 |
| 50,000 | ₹1,57,500 (Growth) | ₹60,000 | ₹1,20,000 |

Add a fixed ~₹1,500–5,000/month for servers, and the engineering time described in §12.

### 11.5 For your 79 credits

| | Managed | DIY |
|---|---|---|
| Voice testing minutes | ~22 min | **~60+ min** |
| Text-only chat test (LLM only) | Unknown | **~₹0.01–0.04 per turn** (500–2,500-token prompt at ₹15/1M) _(corrected in Part D)_ |
| Simulated test (LLM plays the caller) | ₹2 per run | **~₹0.30–0.70 per run** (10 exchanges: agent + simulated caller + judge, text mode) _(corrected in Part D)_ |

---

## 12. What managed gives you that DIY makes you build

| Capability | Managed Voice Agents | DIY effort |
|---|---|---|
| Turn-taking, barge-in, endpointing tuning | Included and tuned | Medium. Pipecat/LiveKit handle the basics; tuning for Indic phone audio takes iteration |
| Latency target (<1 s response) | Tuned by Sarvam | Medium. Stream everything, sentence-chunk TTS, reasoning off |
| Language switching mid-call | Included | Medium. Language detection + switch TTS voice/language |
| Voicemail detection, call transfer, nudges, max call length | Included | Medium per feature |
| Telephony (Exotel, Plivo, Twilio, SIP) | Click to connect | Medium. Pipecat/LiveKit have telephony serializers or SIP |
| Simulated tests + AI judge | ₹2 per run | Low–medium. LLM-vs-LLM in text mode |
| Analytics, call logs, recordings | Included | Medium. We store transcripts, usage, and recordings ourselves |
| Outbound campaigns / dialer | Included | High. Scheduling, retries, DND, concurrency |
| LLM choice | None (fixed) | **Any Sarvam Token Factory model** |
| Per-client agent creation via API | ❌ No public API | ✅ **Trivial. It's a DB row** |
| Exact cost per call | Per-minute only | ✅ **We meter STT seconds, TTS chars, and LLM tokens per call** |

**Rate limits on pay as you go (DIY):** STT 20 concurrent WebSockets, TTS 60 concurrent, and `sarvam-105b` **60 requests/min**. At ~4 LLM turns per minute per call, that's **~15 concurrent calls max**, which is the real ceiling. Managed pay as you go allows **4 concurrent calls**.

---

## 13. Revised architecture: our own agent runtime (recommended for the prototype)

```
┌──────────────── Browser (Next.js UI) ─────────────────┐
│ Clients │ New Client + Agent form │ Agent editor      │
│ Test Lab: Chat test │ Voice test (WebRTC mic) │ Sims  │
└───────────┬───────────────────────────────┬───────────┘
            │ REST                          │ WebRTC audio
            ▼                               ▼
┌──────────── Next.js API ────────┐   ┌────── Agent Runtime (Python) ──────┐
│ /api/clients  /api/agents       │   │ FastAPI + Pipecat                    │
│ /api/agents/:id/versions        │   │ POST /sessions {agentId, version}    │
│ /api/test/chat (LLM only)       │──►│  1. load AgentVersion config         │
│ /api/test/simulate              │   │  2. build pipeline:                  │
│ Usage & cost reports            │   │     Saaras v4 → sarvam-105b-conv     │
└───────────┬─────────────────────┘   │     → Bulbul v4 Flash                │
            │ Prisma                  │  3. meter STT s / TTS chars / tokens │
            ▼                         │  4. on end: transcript + post-call   │
      Postgres / SQLite ◄─────────────┤     extraction → save CallSession    │
                                      └──────────────┬───────────────────────┘
                                                     ▼
                                   api.sarvam.ai (STT WS, TTS WS, chat completions)
```

### 13.1 "Create client → agent created at the same time" (DIY)

```
POST /api/clients { client, agentConfig }
  1. Validate (Zod).
  2. ONE DB transaction: insert Client + Agent + AgentVersion v1 (config snapshot).
  3. Return 201. The agent is usable immediately; there's no external provisioning.
  4. Background (in parallel, non-blocking, optional):
       • generate a greeting audio preview with Bulbul (≈₹0.10)
       • run a quick text smoke test (LLM only, ≈₹0.04)
       → mark agent "Verified"
```

### 13.2 Data model changes vs §5.3

- `Agent.sarvamAppId` and `syncStatus` are **no longer needed** (keep them optional if we later add "Publish to Sarvam managed").
- `AgentVersion.config` now also holds `llm: { model: "sarvam-105b-conversations", temperature, reasoning: "off", maxTokens }`, `stt: { model: "saaras:v4", languageCode }`, and `tts: { model: "bulbul:v4-flash", speaker, pace, sampleRate }`.
- New **`CallSession`**: `agentId, version, channel (web|chat|phone|sim), startedAt, endedAt, transcript, outputVariables, sttSeconds, ttsChars, llmInputTokens, llmCachedTokens, llmOutputTokens, costInr`. This gives an exact per-call cost.

### 13.3 Keep the door open to managed

Keep an `AgentRuntime` interface with a `SelfHostedRuntime` (DIY, built now) and, later, a `SarvamManagedRuntime` that publishes the same config through the MCP server or the dashboard recipe. Client configs stay identical, so we can compare both on cost and quality.

---

## 14. Revised implementation plan (DIY)

| Phase | Work | Time | Credits |
|---|---|---|---|
| 0. Spike | Sarvam API key → a ~40-line Pipecat script (Saaras v4 + `sarvam-105b-conversations` with reasoning off + Bulbul v4 Flash) talking in the browser; measure latency and **check the credit drop after 2 minutes** | ½ day | ~₹3 |
| 1. Foundation | Next.js + Prisma (Client, Agent, AgentVersion, CallSession); Python runtime service skeleton | 1 day | 0 |
| 2. Clients + agents | New Client wizard (prompt, greeting, language, voice, variables, LLM settings); versioning | 1–2 days | ~₹1 |
| 3. Runtime | Load config per session, streaming pipeline, barge-in, usage metering, transcript save, post-call extraction | 2–3 days | ~₹15 |
| 4. Test Lab | Chat test (LLM only), voice test (WebRTC), LLM-vs-LLM simulations with a judge; cost per session shown | 2 days | ~₹10 |
| 5. Later | Telephony (Exotel or Plivo via Pipecat serializer), language switching, voicemail, tools/HTTP, dashboards | — | — |

---

## 15. Recommendation

1. **For this prototype, build our own runtime (Pipecat + Sarvam STT/LLM/TTS).**
   - It fully solves "create a client → its agent is created automatically," with no dependency on an undocumented API.
   - It costs about **₹1.20/min typical (₹0.70–2.40)** vs **₹3.50/min**, billed per second instead of rounded-up minutes.
   - Your 79 credits stretch roughly **3× further** for testing.
   - We can pick and tune the LLM, and we get exact per-call cost metering.
2. **Trade-off:** we own call quality. That means turn-taking, latency, language switching, telephony, campaigns and analytics. Sarvam's managed platform includes these, tuned. If the product needs outbound campaigns or heavy telephony soon, revisit managed (via MCP or the dashboard recipe), using the `AgentRuntime` abstraction to swap.
3. **Use Pipecat** for the prototype: open source, runs locally with a browser WebRTC transport, and needs no third-party media infra. **LiveKit Agents** is the alternative if we want its hosted SIP/telephony and scaling (1,000 free agent minutes a month, then ~$0.01/min).
4. **Validate in the Phase 0 spike:** real latency, voice quality, and the actual credit drop per minute. Then lock in the cost model.

**Sources for Part B:** [API pricing](https://docs.sarvam.ai/api/getting-started/pricing) · [Build vs buy](https://docs.sarvam.ai/voice-agents/why-voice-agents) · [LiveKit guide](https://docs.sarvam.ai/api/integration/build-voice-agent-with-live-kit) · [Pipecat guide](https://docs.sarvam.ai/api/integration/build-voice-agent-with-pipecat) · [Chat completions](https://docs.sarvam.ai/api/token-factory/chat-completions) · [API reference index](https://docs.sarvam.ai/api-reference/llms.txt) · [LiveKit pricing](https://livekit.com/pricing)

---
---

# Part C: Running it on AWS (Lambda-first), hosting cost per minute, and language choice

_All AWS prices are **Mumbai (ap-south-1), on-demand, from AWS's official Price List API, pulled 30 Oct 2026**, unless marked ⚠️. Converted at **₹88 = $1** (assumption). Sarvam prices are from §11._

## 16. Can the voice agent run on AWS Lambda?

**Short answer: Lambda is great for everything *around* the call, but it can't host a live, real-time voice call.**

| Requirement of a live voice call | Lambda | Why it matters |
|---|---|---|
| Hold one long, two-way audio stream for the whole call | ❌ Lambda can't accept an inbound WebSocket or WebRTC (UDP) connection. Function URL streaming is **one-way** | The caller's audio has to land on a server that stays connected |
| Keep Sarvam STT/TTS WebSockets open across the call | ❌ With API Gateway WebSocket, **every audio frame is a separate, stateless Lambda invocation** | You can't keep the STT stream, VAD state or LLM context in memory |
| Phone providers (Exotel, Plivo, Twilio) stream media to *your* WebSocket server | ❌ Same problem | Phone calls are impossible on Lambda alone |
| Calls up to 15 min | ⚠️ Lambda's hard limit is 15 min | Long calls would be cut off |
| Barge-in / sub-second latency | ❌ Cold starts plus per-frame invocations add latency | Poor call experience |

What it would cost if forced through API Gateway WebSocket + Lambda per audio frame (~50 frames/s): about 3,000 messages + 3,000 invocations per minute ≈ **₹0.35/min**, *and it still wouldn't work* because the pipeline needs in-memory state. **Not recommended.**

### Three ways to deploy on AWS

| Option | How it works | AWS cost/min | Voice quality | Phone calls |
|---|---|---:|---|---|
| **A. Lambda-only, turn-based** ("walkie-talkie") | The browser detects when you stop talking and uploads that clip → Lambda: STT REST → LLM → TTS → streams audio back | **≈ ₹0.01** | 2–4 s per reply, no real barge-in | ❌ Web only |
| **B. Hybrid (recommended)** | **Lambda** = APIs, client/agent CRUD, jobs, post-call processing. **ECS Fargate** container = live voice runtime (Pipecat) | **≈ ₹0.05 + fixed** (see §17) | Real-time, <1 s target, barge-in | ✅ |
| C. Fargate/EC2 for everything | Same as B but the APIs also run in containers | Similar to B | Same as B | ✅ |

Option A is a fine **first demo** (no servers at all). Its STT is also cheaper, because only your speech clips are billed (≈₹0.20 instead of ₹0.49 per minute). The real product needs **Option B**.

---

## 17. AWS cost for Option B (Lambda + Fargate), per minute

### 17.1 AWS unit prices used (Mumbai) ✅

| Item | Price |
|---|---|
| Lambda (ARM/Graviton) | $0.0000133334 per GB-second, $0.20 per 1M requests (free tier: 1M requests + 400k GB-s per month) |
| API Gateway HTTP API | $1.05 per 1M requests |
| API Gateway WebSocket | $1.00 per 1M messages + $0.25 per 1M connection-minutes |
| **Fargate ARM** | **$0.02383 per vCPU-hour, $0.00261 per GB-hour** (x86: $0.04256 / $0.004655) |
| EC2 t4g.small / t4g.medium / c7g.large | $0.0112 / $0.0224 / $0.0491 per hour |
| Application Load Balancer | $0.0239 per hour + $0.008 per LCU-hour |
| Public IPv4 address | $0.005 per hour (~₹320/month) |
| Data transfer out to internet | First 100 GB/month free, then $0.1093/GB |
| CloudWatch Logs | $0.67/GB ingested, $0.03/GB-month stored |
| NAT Gateway ⚠️ | ~$0.056 per hour + $0.056/GB (older sources). **Avoid; use public subnets for the runtime** |

### 17.2 Per-call variable cost (Python Pipecat runtime)

Assumptions: each live call uses ~0.25 vCPU + 0.5 GB (⚠️ estimate; load-test it), average fleet utilization is 35% (spare headroom for peaks), and audio egress is ~2.3 MB/min (16 kHz PCM up to Sarvam STT, plus audio to the caller).

| Item | ₹ per call-minute |
|---|---:|
| Fargate compute (incl. idle headroom) | ₹0.030 |
| Data egress | ₹0.00 under ~40,000 min/month (inside the free 100 GB), then ₹0.02 |
| Logs | ₹0.003 |
| Lambda + API Gateway + DynamoDB + S3 (control plane, transcripts) | ₹0.005 |
| **Variable AWS total** | **≈ ₹0.04–0.06** |

### 17.3 Fixed monthly AWS cost

| Setup | What's in it | Fixed ₹/month |
|---|---|---:|
| **Prototype** | 1 × EC2 t4g.small running Pipecat (+ Caddy for HTTPS) + 1 public IP; Lambda/DynamoDB/S3 within free tier | **≈ ₹1,050** |
| **Production-lite** | ALB (~₹2,050) + 1 always-warm Fargate task, 1 vCPU / 2 GB ARM (~₹1,870) + public IP (~₹320) + Secrets Manager, Route 53, CloudWatch alarms (~₹380) | **≈ ₹4,600** |

### 17.4 All-in cost per minute = Sarvam APIs + AWS

Sarvam APIs ≈ **₹1.10/min** (STT ₹0.49 + TTS ₹0.45 + LLM ₹0.17). This replaces the generic "orchestration hosting" line in §11.2.

| Minutes / month | AWS per min (production-lite) | **All-in DIY per min** | Managed Sarvam per min |
|---:|---:|---:|---:|
| 1,000 | ₹4.65 | **₹5.75** ❌ | ₹3.50 |
| 2,500 | ₹1.89 | **₹2.99** | ₹3.50 |
| 5,000 | ₹0.97 | **₹2.07** | ₹3.50 |
| 10,000 | ₹0.51 | **₹1.61** | ₹3.25 (Pro) |
| 50,000 | ₹0.15 | **≈ ₹1.20** | ₹3.15 (Growth) |
| 1,00,000 | ₹0.11 | **≈ ₹1.15** | ₹3.00 (Business) |

- **Break-even vs managed: ~2,000 minutes a month** for production-lite (~450 minutes a month for the ₹1,050 prototype setup). Below that, the fixed AWS cost makes DIY *more* expensive per minute.
- Above ~10,000 minutes a month, AWS adds only **₹0.10–0.50 per minute**. The Sarvam API usage (~₹1.10) dominates.
- Managed rounds every call up to whole minutes, so real-world savings are larger than this table shows (§11.3).
- **Engineering and maintenance time isn't included.** That's the biggest hidden cost of DIY (§12).

### 17.5 Prototype tip: scale to zero

For testing, a Lambda can call `ecs:RunTask` to start a Fargate voice task only when you click "Test voice", and stop it after. **Idle cost is ₹0**, but the first call waits ~30–60 s for the task to start. That's fine for testing, not for inbound phone calls.

---

## 18. Backend language: cost and complexity

**Key point:** in a voice agent, >95% of the time the process is *waiting* on Sarvam (STT/LLM/TTS). Language speed changes only the tiny AWS compute slice (₹0.01–0.03 of the ~₹1.15–1.60 all-in). **The language choice is about engineering complexity, not running cost.**

| Language | Voice framework with Sarvam support | Runtime compute ₹/min (est.) ⚠️ | Lambda cold start (control plane) | Complexity | Time to a working real-time agent |
|---|---|---:|---|---|---|
| **Python** | ✅ **Pipecat** and ✅ **LiveKit Agents** (official Sarvam plugins, Saaras v4 realtime STT, Sarvam docs examples) | ~₹0.03 | ~0.3–0.8 s | **Low–Medium** | **1–3 days** |
| **TypeScript / Node.js** | ✅ LiveKit Agents JS (`@livekit/agents-plugin-sarvam`). But the newer realtime STT is **Python-only**; Node uses the legacy STT (default `saaras:v3`). No Pipecat | ~₹0.015 | ~0.15–0.4 s | **Medium** | ~1 week |
| **Go** | ❌ None. Write the pipeline yourself: WebSockets, VAD, turn-taking, barge-in, WebRTC (pion) | ~₹0.005 | ~0.05–0.1 s | **High** | 3–5 weeks |
| **Java / Kotlin** | ❌ None. Same as Go, heavier runtime | ~₹0.01 | 1–3 s (SnapStart helps) | **High** | 4–6 weeks |
| **Rust** | ❌ None | ~₹0.004 | ~0.02–0.05 s | **Very high** | 5–8 weeks |

- **Most you can save by switching from Python to Go:** ~₹0.025/min, about ₹2,500 a month at 1 lakh minutes. That's far less than the extra weeks of engineering and the risk of hand-building turn-taking and barge-in.
- On Lambda (control plane), the language cost difference is a few rupees a month. Prefer Python or TS for speed of development.

---

## 19. Recommended AWS tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js (TypeScript)** on AWS Amplify Hosting (or S3 + CloudFront) | Rich agent editor + Test Lab UI |
| Control-plane API | **AWS Lambda (Python 3, ARM)** + API Gateway HTTP API | Your team already runs on Lambda; scales to zero; near-free at prototype volume |
| Agent config models | **Pydantic** models shared by the Lambdas and the voice runtime | One definition of `AgentConfig` everywhere |
| Database | **DynamoDB (on-demand)**: Clients, Agents, AgentVersions, CallSessions | Serverless and pay-per-request; fits Lambda. Use Aurora Serverless/RDS only if you need SQL reporting |
| Async jobs | **SQS + Lambda** | "Create client → set up agent in parallel", post-call extraction, cost metering |
| **Live voice runtime** | **Python + Pipecat** container on **ECS Fargate (ARM/Graviton), ap-south-1**, behind an ALB, using a **WebSocket transport** | Real-time calls; WebSocket works for both browser and phone providers (no TURN server needed); autoscale on active calls |
| Prototype runtime | Single **EC2 t4g.small** (or scale-to-zero Fargate via `RunTask`) | ~₹1,050/month or ₹0 idle |
| Storage | **S3** (recordings, transcripts), **Secrets Manager** (Sarvam API key) | Keys never reach the browser |
| Observability | CloudWatch logs + metrics, per-call usage table (STT seconds, TTS chars, LLM tokens, AWS share) | Exact cost per call and per client |
| Infrastructure as code | **AWS CDK** (Python or TypeScript) or SST | Repeatable environments |
| Region | **ap-south-1 (Mumbai)** | Low latency to Sarvam and Indian callers, India data residency |

**Bottom line:** keep Lambda for the backend you already know. Add **one Fargate service** only for the live voice runtime (Python/Pipecat). All-in, that's about **₹1.6/min at 10k minutes a month and ~₹1.2/min at 50k+**, vs ₹3.00–3.50 managed. For the prototype, it's about ₹1,050/month of AWS plus the Sarvam usage.

**Sources for Part C:** AWS Price List API, ap-south-1 offer files for [AWSLambda](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSLambda/current/ap-south-1/index.json), [AmazonECS (Fargate)](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/ap-south-1/index.json), [AWSELB](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSELB/current/ap-south-1/index.json), [AmazonApiGateway](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonApiGateway/current/ap-south-1/index.json), [AWSDataTransfer](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSDataTransfer/current/ap-south-1/index.json), [AmazonVPC](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/ap-south-1/index.json), [AmazonCloudWatch](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/ap-south-1/index.json); AWS EC2 on-demand Mumbai price file · [Pipecat Cloud sizing](https://docs.pipecat.ai/deployment/pipecat-cloud/fundamentals/deploy) · [LiveKit Sarvam plugin docs](https://docs.livekit.io/agents/models/stt/plugins/sarvam/) · [@livekit/agents-plugin-sarvam](https://www.pkgstats.com/pkg:@livekit/agents-plugin-sarvam) · NAT price (older sources): [Cloudkeeper](https://www.cloudkeeper.com/insights/blog/aws-cloud-cost-optimization-nat-gateway)

---
---

# Part D: What Sarvam gives us for a DIY end-to-end system, what's missing, and a 76-credit prototype

## 20. The big telephony finding

**The ₹59/month Sarvam number and Sarvam telephony work only with Sarvam's managed Voice Agents, not with an agent we build ourselves.** ✅

- "Rent from Sarvam" numbers live on a **Sarvam-managed Vobiz account**. You get **no credentials** ("Credentials: none needed").
- The only routing options are **Inbound deployment → a Sarvam agent** or **group → a Sarvam campaign**.
- There's no option to point the number at *our* WebSocket server.
- Even with "Bring your own telephony", the provider's answer URL points to **Sarvam's runtime** (`apps.sarvam.ai/api/app-runtime/v1/channels/...`), not to us.

**For our own agent, we need our own telephony account** whose numbers can stream call audio to our server over WebSocket. Sarvam's own build-it-yourself guides do exactly this.

| Provider (direct account) | Our agent connects via | Sarvam/Pipecat guide | Notes |
|---|---|---|---|
| **Exotel** | Voicebot Applet → our `wss://` URL; 8 kHz default (16/24 kHz via `?sample-rate=`) | ✅ [Official Sarvam + Pipecat + Exotel guide](https://docs.sarvam.ai/api/integration/build-voice-agent-with-exotel) | Indian provider; "voice streaming" may need enabling by Exotel support; KYC needed. ⚠️ Rates aren't public: reseller blogs quote ~₹0.30–0.50/min inbound, ~₹0.80–1.50/min outbound |
| **Twilio** | Media Streams (TwiML `<Stream>`) | ✅ [Official Sarvam + Pipecat + Twilio guide](https://docs.sarvam.ai/api/integration/build-voice-agent-with-twilio) (also WhatsApp) | Indian numbers need a regulatory bundle; usually pricier for India |
| **Plivo** | Audio streaming | Pipecat has a Plivo serializer | Indian numbers need KYC |
| **Vobiz** (your own account, not Sarvam's) | Audio stream over WebSocket | ⚠️ Community package `pipecat-vobiz` (unofficial, v0.0.3) | The same carrier Sarvam uses; check its pricing |

All Indian virtual numbers need **KYC**: individual or business documents. Budget a few days for approval.

---

## 21. Full building blocks: what Sarvam gives vs what we add

### 21.1 From Sarvam (APIs, paid from the same credits) ✅

| Need | Sarvam service | Price |
|---|---|---|
| Ears: live speech-to-text | **Saaras v4** streaming WebSocket (VAD turn detection, 8/16 kHz, mulaw/PCM, 22 languages, code-mix) | ₹0.49/min, per second |
| Brain: conversation + **tool calling** | **`sarvam-105b-conversations`** (OpenAI-style chat completions, `tools` / `tool_choice` supported) | ₹15 / ₹60 per 1M tokens in / out |
| Voice | **Bulbul v4 Flash** streaming TTS (many voices, pace, 8–24 kHz) | ₹1 per 1k chars |
| Brand pronunciations | **Pronunciation dictionary API** (create/list/update/delete) | — |
| Custom brand voice | **Instant voice cloning API** | ₹2 per 1k chars |
| Multilingual helpers | Translate, transliterate, language ID | ₹0.35–2 per 1k chars |
| Post-call analytics | **Batch STT with diarization** (who said what, from recordings) | ₹0.59/min |
| Knowledge-base file parsing | **Document Intelligence** (PDF → text) | ₹0.50–1 per page |

### 21.2 Not from Sarvam: we must add these

| Need | Recommended choice | Cost |
|---|---|---|
| **Telephony + numbers** for our own agent | **Exotel** (official Sarvam guide) or Plivo / your own Vobiz | Per-minute + number rental + KYC |
| Real-time orchestration (turn-taking, barge-in, tool loop) | **Pipecat** (open source) | Free |
| Hosting | **AWS**: Lambda (APIs) + Fargate (live calls); see Part C | ~₹1,050–4,600/month fixed |
| Database / storage | DynamoDB + S3 (recordings, transcripts) | Near-free at prototype scale |
| **Embeddings + vector search** for knowledge bases | ❌ **Sarvam has no embeddings API.** Use Amazon Bedrock Titan embeddings, an open-source embedding model, or plain keyword search for small KBs | Low |
| App login / users | Cognito (or Clerk/Auth0) | Free tier |
| Test harness (simulated callers + judge) | Build it (LLM-vs-LLM, text mode) | ~₹0.30–0.70 per run |
| Analytics dashboards, call logs | Build in our app (CloudWatch for infra) | — |
| Outbound campaigns: scheduler, retries, number rotation | Build it (SQS + EventBridge Scheduler) | — |
| **Compliance (India)** ⚠️ | Consent capture, **DND/NCPR scrubbing**, calling-hour limits, **TRAI/DLT rules for commercial calls** (registered number series for promotional vs service calls), call-recording disclosure, **DPDP Act 2023** for personal data. Confirm with your telephony provider and legal | — |

**In short:** Sarvam supplies everything the agent hears, thinks and says, plus extras like pronunciations, voice cloning and recording analytics. We supply the phone line, the real-time "glue" (Pipecat), hosting, storage, KB search, the dashboard, campaigns and compliance.

> Only on managed Voice Agents (₹3.50/min) can we use Sarvam's ₹59 numbers, its campaigns, its test runs and its analytics directly. A **hybrid** is possible: run some clients on managed and some on DIY behind the same `AgentRuntime` interface (§13.3).

---

## 22. Can we build the prototype with the current 76 free credits? Yes, browser-only

**Scope that fits:** create clients and their agents, edit the config, **text chat test**, **real-time voice test in the browser**, transcripts, per-call cost meter, a few simulated tests.
**Out of scope on free credits:** phone calls. They need an Exotel/Plivo/Twilio account and KYC, and Sarvam's ₹59 number won't connect to our agent.

**No AWS needed for the prototype.** Run everything on your Mac: Next.js + SQLite + a Python Pipecat runtime, with the browser talking to `localhost` (the mic works on localhost without HTTPS). AWS cost: ₹0.

### 22.1 Credit budget (76 credits ≈ ₹76) ⚠️ assumes 1 credit = ₹1 and one wallet shared across APIs

| Activity | Unit cost | Qty | ₹ |
|---|---|---:|---:|
| Text chat turns while developing (keep the dev prompt short) | ~₹0.02–0.04 per turn | 200 | ~6 |
| Voice previews for the agent form (Bulbul v4 Flash, ~150 chars) | ~₹0.15 each | 20 | ~3 |
| **Real-time voice tests in the browser** (STT + LLM + TTS) | ~₹1.10 per min | **40 min** | ~44 |
| Simulated text tests (agent + fake caller + judge) | ~₹0.50 per run | 10 | ~5 |
| **Buffer** for bugs, retries, mistakes | | | ~18 |
| **Total** | | | **≈ ₹76** |

That's about **40 minutes of real voice conversations**, plus plenty of text testing. That's enough to build and demo the prototype (managed Voice Agents would give ~21 minutes).

### 22.2 Credit-safety rules (important)

1. **STT bills per second of audio streamed, even silence.** Auto-hang-up after **3 minutes max** and after **20 s of silence**, and close the STT WebSocket on every exit path (`finally`).
2. **Turn off LLM "thinking":** `reasoning_effort: null` on `sarvam-105b-conversations`. Otherwise every reply pays for hidden reasoning tokens.
3. **Use Bulbul v4 Flash, never v3** (v3 is 3× the price and is being retired).
4. **Develop logic in text chat first**, then voice. Keep dev prompts short.
5. **Show a live cost meter** (STT seconds, TTS chars, LLM tokens → ₹) in the Test Lab, and stop at a per-session cap (for example ₹3).
6. After the first 2-minute test, **check the balance on the Sarvam Billing page** to confirm the real cost per minute and that API usage draws from these credits.
7. A `402` response means credits are exhausted. The app should show "Out of credits" rather than retrying.

### 22.3 Prototype build order

| Step | What | Credits |
|---|---|---:|
| 1 | Sarvam API key in `.env`; a ~80-line Pipecat script (browser ↔ Saaras v4 ↔ `sarvam-105b-conversations` ↔ Bulbul v4 Flash); 2-minute test; check the balance | ~3 |
| 2 | Next.js app: Clients + Agents (+ versions) in SQLite; New Client wizard creates the agent config in one step | 0 |
| 3 | Runtime loads an agent's config per session (prompt, greeting, language, voice, temperature) | ~2 |
| 4 | Test Lab: text chat, browser voice with transcript and cost meter, session caps | ~25 |
| 5 | Post-call extraction (output variables), simulated tests | ~10 |
| 6 | Demo runs with 2–3 sample clients | ~15 |
| — | Buffer | ~20 |

**After the prototype** (paid, not free credits): an Exotel (or Plivo) account + KYC + number → phone calls through the same runtime → move to AWS (Part C).

**Sources for Part D:** [Rent from Sarvam](https://docs.sarvam.ai/voice-agents/deploy/telephony/rent-from-sarvam) · [Bring your own telephony](https://docs.sarvam.ai/voice-agents/deploy/telephony/bring-your-own) · [Vobiz on Voice Agents](https://docs.sarvam.ai/voice-agents/deploy/telephony/vobiz) · [Sarvam + Exotel + Pipecat](https://docs.sarvam.ai/api/integration/build-voice-agent-with-exotel) · [Sarvam + Twilio + Pipecat](https://docs.sarvam.ai/api/integration/build-voice-agent-with-twilio) · [Chat completions / tool calling](https://docs.sarvam.ai/api/token-factory/chat-completions) · [API pricing](https://docs.sarvam.ai/api/getting-started/pricing) · [pipecat-vobiz (PyPI)](https://pypi.org/project/pipecat-vobiz/) · Exotel rates (reseller estimates): [Edesy guide](https://edesy.in/blog/exotel-ai-voice-agent-setup-guide-2026.md), [Twilio vs Exotel 2026](https://edesy.in/blog/twilio-vs-exotel-india-cost-comparison-2026.md)

---

## 23. Prototype checklist: what we need from other providers

**Paid outside providers needed for the browser prototype: none.** Everything except Sarvam is free and runs on your Mac.

| # | Need | Provider | Cost | Required? |
|---|---|---|---|---|
| 1 | STT + LLM + TTS | **Sarvam** API key (Dashboard → API keys) | Your 76 credits | ✅ Yes |
| 2 | Real-time voice pipeline (turn-taking, barge-in) | **Pipecat** (`pip install "pipecat-ai[sarvam,webrtc]"`) with its built-in browser WebRTC transport | Free, open source | ✅ Yes |
| 3 | App UI + API | **Next.js** (Node.js 20+) | Free | ✅ Yes |
| 4 | Database | **SQLite** via Prisma (a local file) | Free | ✅ Yes |
| 5 | Runtime language | **Python 3.10+** (+ `uv` or `pip`) | Free | ✅ Yes |
| 6 | Mic + speaker | Chrome on your Mac (`localhost` works without HTTPS) | Free | ✅ Yes |
| — | Phone calls | Exotel / Plivo / Twilio + KYC + number | Paid | ❌ Later |
| — | Cloud hosting | AWS (Lambda + Fargate) | Paid | ❌ Later |
| — | Public URL to demo remotely | ngrok or Cloudflare Tunnel (free tiers) | Free | ⚪ Optional |
| — | Knowledge-base embeddings | Bedrock / open-source model | Low | ❌ Later (skip the KB in the prototype) |
| — | Login | Cognito / Clerk | Free tier | ❌ Later |
| — | Media server (LiveKit Cloud, Daily) | Not needed. Pipecat's WebRTC runs directly between browser and Mac | — | ❌ No |

⚠️ When demoing over a public tunnel, some networks block direct WebRTC. If audio fails remotely, switch Pipecat to its WebSocket transport (works through tunnels) or deploy to one small EC2 server.

---
---

# Part E: From prototype to production

_Based on the current code in `backend/` and `frontend/` (30 Oct 2026). P0 = before the first real customer call, P1 = before scaling up, P2 = product maturity._

## 24. Security (P0)

| Gap in the prototype | Risk | Change |
|---|---|---|
| **No authentication** on any of the 22 API/WebSocket endpoints | Anyone who finds the URL can create/delete clients, read transcripts, and place calls on your credits | Add login (Cognito/Clerk/Auth0) and require a token on every `/api/*` route; add roles (admin, operator, viewer) |
| **Telephony endpoints accept any caller** (`/ws/telephony`, `/telephony/twilio/incoming`) | Anyone can open a WebSocket and burn Sarvam credits | Validate Twilio's `X-Twilio-Signature`; put a signed, expiring token in the stream URL or custom parameters; allow-list Exotel/Twilio IPs at the load balancer |
| **HTTP tools can call any URL** (SSRF) | An agent tool pointed at `169.254.169.254` or internal services could leak AWS credentials or internal data | Resolve the host and block private, loopback and link-local ranges; HTTPS-only in production; allow-list per tenant |
| Tool headers (customer API keys) stored **in plain text** in agent JSON and returned to the UI | Credential leak | Store them in Secrets Manager or encrypt with KMS; show them masked; never return them to the browser |
| Demo endpoint `/api/demo/order-status` | Noise and attack surface | Remove it, or enable it only in dev |
| CORS open to localhost; served over plain HTTP locally | — | HTTPS everywhere (ALB + ACM cert), strict CORS, security headers |
| No rate limits or per-tenant spend caps | Runaway costs | Per-tenant concurrent-call limits and daily ₹ budget; keep the per-call caps already in place |

## 25. Multi-tenancy & data (P0/P1)

- **Decide what a "client" is.** If your customers will log in, each client is a **tenant**: add `tenant_id` to every table and scope every query by it.
- **SQLite → Postgres (RDS/Aurora) or DynamoDB**, with migrations (Alembic). Today `create_all` builds tables once and can't evolve them.
- **Real agent versions.** Calls record `agent_version`, but the config of old versions isn't kept. Add an immutable `AgentVersion` table with **draft → publish → rollback**, and attach phone numbers to a *published* version, never the draft.
- **Phone-number routing table** (`number → agent`) instead of the single global "inbound agent" setting.
- **Recordings and transcripts:** store them in S3 (encrypted), with a retention policy and per-tenant access control. They contain personal data.

## 26. Scaling & reliability (P1)

| Area | Today | Production |
|---|---|---|
| Process layout | API and voice runtime in one FastAPI process | Split: **control-plane API** (Lambda or Fargate) and **voice runtime** (ECS Fargate, ARM, ap-south-1), autoscaling on active calls |
| In-memory state | WebRTC peer map (`webrtc_handler`) and Exotel outbound matching (`_pending_exotel`) live in one process's memory | Sticky routing for WebRTC (or the WebSocket transport); Redis for outbound-call matching |
| Browser calls | STUN only | A **TURN server** (coturn or managed) so calls work behind corporate/mobile NATs |
| Deploys | Restart drops live calls | Graceful drain: stop new calls, let active calls finish (≤ max call length), ECS deregistration delay |
| Sarvam limits (pay as you go) | STT 20 concurrent sockets, `sarvam-105b` **60 req/min (≈15 concurrent calls)** | Upgrade the Sarvam plan to match peak concurrency; a global concurrency limiter; tell callers "all agents busy" instead of failing |
| Failures | LLM error → "please repeat"; fatal STT/TTS → call ends | Add an LLM fallback model (Pipecat service switcher); reconnect handling; alert on error rate |
| Tools | 8 s timeout | Speak a filler ("one moment, let me check") while slow tools run; retries for idempotent calls |
| Dependencies | `uv.lock` pins versions | Keep pinned; upgrade Pipecat/Sarvam on purpose, and run `scripts/e2e_test.py` in CI before every upgrade (Sarvam's API changed `min_buffer_size` under us once already) |

## 27. Telephony & compliance in India (P0 for real calls)

- **Provider:** Exotel / Plivo / your own Vobiz account with Indian numbers (Twilio has no Indian numbers). Complete KYC.
- **TRAI rules:** use the right number series for promotional vs service/transactional calls (140 and 1600 series for regulated sectors). Scrub against **NCPR/DND**, respect calling hours, and keep consent records. Confirm the current rules with your provider.
- **DPDP Act 2023:** consent and purpose notice, data minimisation, retention limits, deletion requests, breach process. Keep data in India (ap-south-1 + Sarvam).
- **Disclosure:** tell callers they're speaking with an AI assistant, and that the call is recorded if it is.
- **Phone audio tuning:** test Fast vs Sarvam VAD on real noisy lines; raise the pause to 400–500 ms if callers get cut off. Detect voicemail on outbound (provider AMD), and add transfer-to-human.

## 28. Quality, testing & observability (P1)

- **Regression tests per agent:** turn `scripts/e2e_test.py` into scenario suites (simulated caller + LLM judge) that run before publishing a new version.
- **Monitoring:** structured JSON logs to CloudWatch; metrics for active calls, turn latency p50/p95, "you heard" latency, error rate per service, and cost per call and per tenant; alarms. Pipecat supports OpenTelemetry tracing (`enable_tracing=True`). Log Sarvam request IDs for support tickets.
- **Outcome tracking:** post-call extraction of results (did they agree, order id, sentiment) plus webhooks to the client's CRM.
- **Language:** in auto-detect mode, also switch the TTS language per turn (today TTS stays on the agent's language).

## 29. Product features usually needed (P2)

Outbound campaigns (scheduler, retries, calling windows, DND checks, concurrency), knowledge base (embeddings + search; Sarvam has no embeddings API), on-call-start CRM lookup for personalisation, call transfer, voicemail handling, a usage and billing dashboard per client, audit log, and team roles.

## 30. Suggested order

| Phase | Work | Rough effort |
|---|---|---|
| 1. Lock down (P0) | Auth + tenants, telephony signature checks, SSRF guard, secrets out of agent JSON, remove demo endpoint | 1–2 weeks |
| 2. Real phone line | Exotel/Plivo Indian number + KYC, number→agent routing, AI disclosure, recording consent, test Fast vs Sarvam VAD on real calls | 1 week (+ KYC wait) |
| 3. Deploy on AWS | Postgres, split API vs voice runtime on Fargate, TURN, HTTPS/ALB, graceful drain, CloudWatch metrics & alarms, CI with the e2e test | 2–3 weeks |
| 4. Scale & operate | Sarvam plan upgrade, concurrency limiter, LLM fallback, versions with publish/rollback, per-tenant budgets | 1–2 weeks |
| 5. Product | Campaigns, outcomes + CRM webhooks, knowledge base, transfer to human | ongoing |
