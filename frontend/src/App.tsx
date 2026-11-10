import { useCallback, useEffect, useState } from 'react'
import { AgentConfigForm } from './AgentConfigForm'
import { api, type Agent, type AgentConfig, type Catalog, type Client, type ClientFields, type Health } from './api'
import { CallHistory, TestLab } from './TestLab'
import { Badge, Field, Icon, Section, ThemeToggle, initials } from './ui'

type View = { page: 'clients' } | { page: 'new' } | { page: 'agent'; clientId: string; agentId: string }

// The current page lives in the URL hash, so refresh and the back button work.
function viewFromHash(): View {
  const [page, clientId, agentId] = window.location.hash.replace(/^#\/?/, '').split('/')
  if (page === 'new') return { page: 'new' }
  if (page === 'agent' && clientId && agentId) return { page: 'agent', clientId, agentId }
  return { page: 'clients' }
}

function hashFor(view: View) {
  return view.page === 'agent' ? `#/agent/${view.clientId}/${view.agentId}` : view.page === 'new' ? '#/new' : '#/'
}

export default function App() {
  const [view, setViewState] = useState<View>(viewFromHash)
  const setView = useCallback((next: View) => {
    if (window.location.hash !== hashFor(next)) window.location.hash = hashFor(next)
    setViewState(next)
    window.scrollTo({ top: 0 })
  }, [])
  useEffect(() => {
    const onHash = () => setViewState(viewFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [clients, setClients] = useState<Client[]>([])
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [c, h] = await Promise.all([api.clients(), api.health()])
      setClients(c)
      setHealth(h)
      setError('')
    } catch (e) {
      setError(`Backend not reachable (${e instanceof Error ? e.message : e}). Is it running on port 7860?`)
    }
  }, [])

  useEffect(() => {
    void api.catalog().then(setCatalog).catch(() => {})
    void reload()
  }, [reload])

  const current =
    view.page === 'agent'
      ? (() => {
          const client = clients.find((c) => c.id === view.clientId)
          const agent = client?.agents.find((a) => a.id === view.agentId)
          return client && agent ? { client, agent } : null
        })()
      : null

  const telephony = health?.twilio_configured ? 'Twilio' : health?.exotel_configured ? 'Exotel' : null

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <button className="brand" onClick={() => setView({ page: 'clients' })}>
            <span className="brand-mark">
              <Icon name="wave" size={17} />
            </span>
            <span>
              Voice Agent Studio
              <small>Sarvam STT · LLM · TTS</small>
            </span>
          </button>
          <div className="status-chips">
            <Badge tone={health?.sarvam_key_set ? 'green' : 'red'}>
              <span className="dot" /> Sarvam {health?.sarvam_key_set ? 'connected' : 'key missing'}
            </Badge>
            <Badge tone={telephony ? 'green' : 'neutral'}>
              <Icon name="phone" size={12} /> {telephony ?? 'No telephony'}
            </Badge>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="page">
        {error && (
          <div className="banner banner-red">
            <Icon name="x" /> {error}
          </div>
        )}

        {view.page === 'clients' && (
          <ClientList
            clients={clients}
            catalog={catalog}
            onNew={() => setView({ page: 'new' })}
            onOpen={(c, a) => setView({ page: 'agent', clientId: c.id, agentId: a.id })}
            onDelete={async (c) => {
              if (confirm(`Delete ${c.name}, its agents and call history?`)) {
                await api.deleteClient(c.id)
                await reload()
              }
            }}
          />
        )}

        {view.page === 'new' && catalog && (
          <NewClient
            catalog={catalog}
            onCancel={() => setView({ page: 'clients' })}
            onCreated={async (c) => {
              await reload()
              setView({ page: 'agent', clientId: c.id, agentId: c.agents[0].id })
            }}
          />
        )}

        {current && catalog && (
          <AgentPage
            key={current.agent.id}
            client={current.client}
            agent={current.agent}
            catalog={catalog}
            health={health}
            onBack={() => setView({ page: 'clients' })}
            onSaved={reload}
          />
        )}
      </main>
    </>
  )
}

// ------------------------------------------------------------------ clients

function ClientList({
  clients,
  catalog,
  onNew,
  onOpen,
  onDelete,
}: {
  clients: Client[]
  catalog: Catalog | null
  onNew: () => void
  onOpen: (c: Client, a: Agent) => void
  onDelete: (c: Client) => void
}) {
  const [query, setQuery] = useState('')
  const q = query.trim().toLowerCase()
  const shown = clients.filter(
    (c) => !q || c.name.toLowerCase().includes(q) || c.industry.toLowerCase().includes(q) || c.agents.some((a) => a.name.toLowerCase().includes(q)),
  )
  const voiceName = (id: string) => catalog?.voices.find((v) => v.id === id)?.name ?? id

  if (clients.length === 0) {
    return (
      <div className="card empty-state">
        <div className="brand-mark">
          <Icon name="wave" size={24} />
        </div>
        <h2>Create your first client</h2>
        <p>Each client gets its own voice agent — prompt, language, voice and tools — ready to test in seconds.</p>
        <button className="btn btn-primary" onClick={onNew}>
          <Icon name="plus" /> New client
        </button>
      </div>
    )
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Clients</h1>
          <p>
            {clients.length} client{clients.length === 1 ? '' : 's'} · {clients.reduce((n, c) => n + c.agents.length, 0)} agents
          </p>
        </div>
        <div className="row">
          <div className="search">
            <Icon name="search" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search clients or agents" />
          </div>
          <button className="btn btn-primary" onClick={onNew}>
            <Icon name="plus" /> New client
          </button>
        </div>
      </div>

      <div className="client-grid">
        {shown.map((c) => (
          <div key={c.id} className="card client-card">
            <div className="client-top">
              <div className="avatar">{initials(c.name)}</div>
              <div className="grow">
                <h3>{c.name}</h3>
                <span className="muted small">
                  {c.industry || 'No industry'} · added {new Date(c.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
                </span>
              </div>
              <button className="btn btn-ghost btn-icon" onClick={() => onDelete(c)} title="Delete client">
                <Icon name="trash" />
              </button>
            </div>
            {c.agents.map((a) => (
              <button key={a.id} className="agent-tile" onClick={() => onOpen(c, a)}>
                <Icon name="mic" />
                <div className="grow">
                  <strong>{a.name}</strong>
                  <div className="meta">
                    <Badge>{catalog?.languages[a.config.language] ?? a.config.language}</Badge>
                    <Badge>{voiceName(a.config.voice)}</Badge>
                    {a.config.turn_detection === 'fast' && (
                      <Badge tone="blue">
                        <Icon name="zap" size={11} /> Fast
                      </Badge>
                    )}
                    {a.config.tools.length > 0 && (
                      <Badge>
                        <Icon name="wrench" size={11} /> {a.config.tools.length}
                      </Badge>
                    )}
                  </div>
                </div>
                <Badge tone="neutral">v{a.version}</Badge>
              </button>
            ))}
          </div>
        ))}
        {shown.length === 0 && <p className="muted">No clients match “{query}”.</p>}
      </div>
    </>
  )
}

// ------------------------------------------------------------------ new client

function NewClient({
  catalog,
  onCancel,
  onCreated,
}: {
  catalog: Catalog
  onCancel: () => void
  onCreated: (c: Client) => void
}) {
  const [client, setClient] = useState<ClientFields>({ name: '', industry: '', contact_name: '', contact_phone: '', notes: '' })
  const [agentName, setAgentName] = useState('Voice agent')
  const [config, setConfig] = useState<AgentConfig>(catalog.defaults)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      onCreated(await api.createClient(client, { name: agentName, config }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 860 }}>
      <button className="btn btn-ghost" onClick={onCancel} style={{ marginLeft: -10, marginBottom: 8 }}>
        <Icon name="back" /> Clients
      </button>
      <div className="page-head">
        <div>
          <h1>New client</h1>
          <p>The client's voice agent is created together with the client — no Sarvam dashboard setup.</p>
        </div>
      </div>

      <Section icon="building" title="Client" description="Who this agent works for.">
        <Field label="Client name *">
          <input value={client.name} autoFocus onChange={(e) => setClient({ ...client, name: e.target.value })} placeholder="Acme Store" />
        </Field>
        <Field label="Industry">
          <input value={client.industry} onChange={(e) => setClient({ ...client, industry: e.target.value })} placeholder="E-commerce" />
        </Field>
        <Field label="Contact name">
          <input value={client.contact_name} onChange={(e) => setClient({ ...client, contact_name: e.target.value })} />
        </Field>
        <Field label="Contact phone">
          <input value={client.contact_phone} onChange={(e) => setClient({ ...client, contact_phone: e.target.value })} />
        </Field>
        <Field label="Agent name" wide>
          <input value={agentName} onChange={(e) => setAgentName(e.target.value)} />
        </Field>
      </Section>

      <AgentConfigForm catalog={catalog} value={config} onChange={setConfig} />

      <div className="save-bar">
        <span className="grow">{error ? <span style={{ color: '#fda29b' }}>{error}</span> : 'Ready to create the client and its agent.'}</span>
        <button className="btn btn-secondary" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={submit} disabled={saving || !client.name.trim()}>
          {saving ? 'Creating…' : 'Create client + agent'}
        </button>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ agent workspace

function AgentPage({
  client,
  agent,
  catalog,
  health,
  onBack,
  onSaved,
}: {
  client: Client
  agent: Agent
  catalog: Catalog
  health: Health | null
  onBack: () => void
  onSaved: () => Promise<void>
}) {
  const [name, setName] = useState(agent.name)
  const [config, setConfig] = useState<AgentConfig>(agent.config)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [historyKey, setHistoryKey] = useState(0)
  const dirty = name !== agent.name || JSON.stringify(config) !== JSON.stringify(agent.config)
  const voice = catalog.voices.find((v) => v.id === agent.config.voice)

  const save = async () => {
    setSaving(true)
    setMessage('')
    try {
      const saved = await api.updateAgent(agent.id, name, config)
      setMessage(`Saved as v${saved.version}`)
      await onSaved()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <button className="btn btn-ghost" onClick={onBack} style={{ marginLeft: -10, marginBottom: 8 }}>
        <Icon name="back" /> Clients
      </button>
      <div className="agent-head">
        <div className="avatar">{initials(client.name)}</div>
        <div className="grow">
          <span className="muted small">{client.name}</span>
          <div>
            <input className="title-input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Agent name" />
          </div>
        </div>
        <div className="row">
          <Badge>v{agent.version}</Badge>
          <Badge>
            <Icon name="globe" size={11} /> {catalog.languages[agent.config.language]}
          </Badge>
          <Badge>
            <Icon name="mic" size={11} /> {voice ? `${voice.name} · ${voice.style}` : agent.config.voice}
          </Badge>
          <Badge tone={agent.config.turn_detection === 'fast' ? 'blue' : 'neutral'}>
            <Icon name="zap" size={11} /> {agent.config.turn_detection === 'fast' ? 'Fast' : 'Sarvam VAD'}
          </Badge>
        </div>
      </div>

      <div className="workspace">
        <div>
          <AgentConfigForm catalog={catalog} value={config} onChange={setConfig} />
          {(dirty || message) && (
            <div className="save-bar">
              <span className="grow">
                {dirty ? 'Unsaved changes — calls use the saved version.' : message}
              </span>
              {dirty && (
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    setName(agent.name)
                    setConfig(agent.config)
                  }}
                >
                  Discard
                </button>
              )}
              <button className="btn btn-primary" onClick={save} disabled={saving || !dirty}>
                {saving ? 'Saving…' : 'Save agent'}
              </button>
            </div>
          )}
        </div>
        <TestLab agent={agent} health={health} onCallEnded={() => setHistoryKey((k) => k + 1)} />
      </div>

      <CallHistory agentId={agent.id} refreshKey={historyKey} />
    </>
  )
}
