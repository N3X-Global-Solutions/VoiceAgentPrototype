// Types mirror the backend (app/agents/models.py, app/core/db.py). Same-origin calls: the Vite proxy in dev,
// the backend itself in production. The session cookie is HttpOnly, so it never touches JS.

export type HttpTool = {
  name: string
  description: string
  method: 'GET' | 'POST'
  url: string
  headers: Record<string, string>
  parameters: Record<string, Record<string, unknown>>
  required: string[]
  timeout_secs: number
}

export type ProviderId = 'sarvam' | 'navana' | 'gnani'
export type PartKind = 'stt' | 'llm' | 'tts'

export type AgentConfig = {
  stt_provider: ProviderId
  llm_provider: 'sarvam' | 'gnani'
  tts_provider: ProviderId
  greeting: string
  instructions: string
  language: string
  auto_detect_language: boolean
  voice: string
  pace: number
  temperature: number
  max_call_seconds: number
  idle_timeout_secs: number
  end_call_enabled: boolean
  goodbye_message: string
  nudge_message: string
  repeat_message: string
  tools: HttpTool[]
  turn_detection: 'sarvam' | 'fast' // stored value; shown as "Robust" / "Fast"
  end_of_speech_ms: number | null
  important_words: string[]
}

export type Agent = {
  id: string
  client_id: string
  name: string
  config: AgentConfig
  version: number
  created_at: string
  updated_at: string
}

export type Client = {
  id: string
  name: string
  industry: string
  contact_name: string
  contact_phone: string
  notes: string
  created_at: string
  agents: Agent[]
}

export type ClientFields = Omit<Client, 'id' | 'created_at' | 'agents'>

/** language "*" = the voice speaks every language its provider supports. */
export type Voice = { id: string; name: string; style: string; language: string; group: string; provider: ProviderId }

/** A rate the cost meter uses. source: published by the provider, quoted by you, or an estimate to confirm. */
export type Price = { rate: number; unit: 'min' | '1k_chars' | '1m_tokens'; source: 'published' | 'quoted' | 'estimate'; env: string; note: string }

export type ProviderPart = {
  model: string
  languages: string[]
  features: string[] // robust_turns | auto_language | keywords
  note: string
  billing: string // stt: "speech" (speech sent) | "connected" (whole call)
  prices: Record<string, Price> // stt: audio · tts: chars · llm: input, cached, output
}

export type Provider = {
  id: ProviderId
  name: string
  configured: boolean
  key_env: string
  stt: ProviderPart | null
  tts: ProviderPart | null
  llm: ProviderPart | null
}

export type Catalog = {
  languages: Record<string, string>
  voices: Voice[]
  providers: Provider[]
  defaults: AgentConfig
}

export type Health = {
  provider_key_set: boolean // at least one voice AI provider has a key
  providers: Record<ProviderId, boolean>
  public_base_url: string
  twilio_configured: boolean
  exotel_configured: boolean
  inbound_agent_id: string
  max_call_seconds_cap: number
  max_cost_per_call_inr: number
  rates: Rates
}

/** Phone-line rates (INR, ex-GST). Voice AI rates are per provider, in the catalog. */
export type Rates = {
  exotel_per_min: number
  exotel_pulse_secs: number
  twilio_per_min: number
  twilio_pulse_secs: number
}

/** Per-part cost of a call in INR. Empty for calls made before the breakdown existed. */
export type CostBreakdown = Partial<{
  stt: number
  tts: number
  llm: number
  telephony: number
  telephony_billed_secs: number
  rates: { stt_per_min: number; stt_billing: string; tts_per_1k_chars: number; llm_input_per_1m: number; llm_output_per_1m: number }
}>

export type LatencyTurn = {
  turn: number
  total_ms: number
  transcript_ms: number | null
  llm_first_text_ms: number | null
  tts_first_audio_ms: number | null
  ttfb_ms: Partial<Record<'stt' | 'llm' | 'tts', number>>
  pause_ms: number | null
}

export type CallSession = {
  id: string
  agent_id: string
  agent_version: number
  channel: string
  direction: string
  phone_number: string
  status: string
  started_at: string
  ended_at: string | null
  provider_call_id: string
  duration_secs: number
  turns: number
  latency_avg_ms: number | null
  latency_p50_ms: number | null
  latency_p95_ms: number | null
  latency_max_ms: number | null
  stt_seconds: number
  tts_chars: number
  llm_prompt_tokens: number
  llm_cached_tokens: number
  llm_completion_tokens: number
  cost_inr: number
  cost_breakdown: CostBreakdown | null
  providers: Partial<Record<PartKind, ProviderId>> | null // empty for calls before provider choice (all Sarvam)
  transcript: { role: 'user' | 'agent' | 'event'; text: string }[]
  latency_turns: LatencyTurn[]
  error: string
}

// Fired when the session expires mid-use, so the app can show the sign-in page.
export const UNAUTHORIZED_EVENT = 'vas:unauthorized'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      // FastAPI validation errors: [{msg: "Value error, …"}] -> readable sentences.
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg?: string }) => String(d.msg ?? '').replace(/^Value error, /, '')).join(' ')
      else message = JSON.stringify(body.detail ?? body)
    } catch {
      /* keep status text */
    }
    throw new ApiError(res.status, message)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  me: () => request<{ email: string }>('/api/auth/me'),
  login: (email: string, password: string) =>
    request<{ email: string }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  health: () => request<Health>('/api/health'),
  catalog: () => request<Catalog>('/api/catalog'),
  clients: () => request<Client[]>('/api/clients'),
  createClient: (client: ClientFields, agent: { name: string; config: AgentConfig }) =>
    request<Client>('/api/clients', { method: 'POST', body: JSON.stringify({ client, agent }) }),
  deleteClient: (id: string) => request<void>(`/api/clients/${id}`, { method: 'DELETE' }),
  addAgent: (clientId: string, name: string, config: AgentConfig) =>
    request<Agent>(`/api/clients/${clientId}/agents`, { method: 'POST', body: JSON.stringify({ name, config }) }),
  updateAgent: (id: string, name: string, config: AgentConfig) =>
    request<Agent>(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify({ name, config }) }),
  setInbound: (id: string) => request<{ inbound_agent_id: string }>(`/api/agents/${id}/inbound`, { method: 'PUT' }),
  chat: (id: string, messages: { role: string; content: string }[]) =>
    request<{
      reply: string
      latency_ms: number
      cost_inr: number
      ended: boolean
      tool_calls: { name: string; arguments: Record<string, unknown>; result: unknown }[]
    }>(`/api/agents/${id}/chat`, {
      method: 'POST',
      body: JSON.stringify({ messages }),
    }),
  phoneCall: (id: string, to: string, provider: 'twilio' | 'exotel') =>
    request<{ call_session_id: string }>(`/api/agents/${id}/phone-call`, {
      method: 'POST',
      body: JSON.stringify({ to, provider }),
    }),
  translate: (language: string, texts: Record<string, string>) =>
    request<{ texts: Record<string, string> }>('/api/translate', {
      method: 'POST',
      body: JSON.stringify({ language, texts }),
    }),
  calls: (agentId?: string, limit = 50) =>
    request<CallSession[]>(`/api/calls?limit=${limit}${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ''}`),
}
