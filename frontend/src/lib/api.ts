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

export type AgentConfig = {
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
  turn_detection: 'sarvam' | 'fast'
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

export type Voice = { id: string; name: string; style: string; language: string; group: string }

export type Catalog = {
  languages: Record<string, string>
  voices: Voice[]
  defaults: AgentConfig
}

export type Health = {
  sarvam_key_set: boolean
  public_base_url: string
  twilio_configured: boolean
  exotel_configured: boolean
  inbound_agent_id: string
  max_call_seconds_cap: number
  max_cost_per_call_inr: number
}

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
  duration_secs: number
  turns: number
  latency_avg_ms: number | null
  latency_p50_ms: number | null
  latency_p95_ms: number | null
  latency_max_ms: number | null
  stt_seconds: number
  tts_chars: number
  llm_prompt_tokens: number
  llm_completion_tokens: number
  cost_inr: number
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
      message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
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
