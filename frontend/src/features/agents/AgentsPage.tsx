import { useState } from 'react'
import type { Navigate } from '@/app/routes'
import { Icon } from '@/components/Icon'
import { Avatar, Badge, EmptyState, IconChip, PageHead } from '@/components/ui'
import type { Catalog, Client, Health } from '@/lib/api'
import { timeAgo } from '@/lib/format'

/** All agents as cards, with search and a language filter. */
export function AgentsPage({ clients, catalog, health, navigate }: { clients: Client[]; catalog: Catalog | null; health: Health | null; navigate: Navigate }) {
  const [query, setQuery] = useState('')
  const [language, setLanguage] = useState('')
  const rows = clients.flatMap((client) => client.agents.map((agent) => ({ client, agent })))
  const q = query.trim().toLowerCase()
  const shown = rows.filter(
    ({ client, agent }) =>
      (!language || agent.config.language === language) &&
      (!q || agent.name.toLowerCase().includes(q) || client.name.toLowerCase().includes(q) || client.industry.toLowerCase().includes(q)),
  )
  const voice = (provider: string, id: string) => catalog?.voices.find((v) => v.provider === provider && v.id === id)
  const languagesInUse = [...new Set(rows.map((r) => r.agent.config.language))]

  return (
    <>
      <PageHead
        eyebrow="Build"
        title="Agents"
        description="Every voice agent in the workspace. Open one to edit its prompt, voice and tools, and test it live."
        actions={
          <button className="btn btn-primary" onClick={() => navigate({ page: 'new' })}>
            <Icon name="plus" /> Create agent
          </button>
        }
      />

      {rows.length === 0 ? (
        <div className="card">
          <EmptyState
            icon="bot"
            title="No agents yet"
            action={
              <button className="btn btn-primary" onClick={() => navigate({ page: 'new' })}>
                <Icon name="plus" /> Create agent
              </button>
            }
          >
            Create a client and its first voice agent in one step.
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="card" style={{ marginBottom: 18 }}>
            <div className="table-toolbar" style={{ borderBottom: 0 }}>
              <div className="input-icon">
                <Icon name="search" size={15} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search agents or clients" />
              </div>
              <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Language">
                <option value="">All languages</option>
                {languagesInUse.map((l) => (
                  <option key={l} value={l}>
                    {catalog?.languages[l] ?? l}
                  </option>
                ))}
              </select>
              <span className="muted small" style={{ marginLeft: 'auto' }}>
                {shown.length} of {rows.length} agents
              </span>
            </div>
          </div>

          {shown.length === 0 ? (
            <div className="card">
              <EmptyState icon="search" tone="gray" title="No matching agents">
                Try a different search or language.
              </EmptyState>
            </div>
          ) : (
            <div className="agent-grid">
              {shown.map(({ client, agent }) => {
                const v = voice(agent.config.tts_provider, agent.config.voice)
                return (
                  <button
                    key={agent.id}
                    className="agent-card"
                    onClick={() => navigate({ page: 'agent', clientId: client.id, agentId: agent.id, tab: 'prompt' })}
                  >
                    <div className="top">
                      <Avatar name={agent.name} seed={agent.id} size="lg" square />
                      <div className="grow">
                        <h3 className="truncate">{agent.name}</h3>
                        <span className="client">{client.name}</span>
                      </div>
                      {health?.inbound_agent_id === agent.id && (
                        <Badge tone="brand" icon="inbound" title="Answers inbound calls">
                          Inbound
                        </Badge>
                      )}
                    </div>
                    <p className="greeting">“{agent.config.greeting}”</p>
                    <div className="chips">
                      <Badge icon="globe">
                        {catalog?.languages[agent.config.language] ?? agent.config.language}
                      </Badge>
                      <Badge icon="headphones">
                        {v?.name ?? agent.config.voice}
                      </Badge>
                      <Badge icon="zap">
                        {agent.config.turn_detection === 'fast' ? 'Fast' : 'Robust'}
                      </Badge>
                      {agent.config.tools.length > 0 && (
                        <Badge icon="wrench">
                          {agent.config.tools.length} tool{agent.config.tools.length === 1 ? '' : 's'}
                        </Badge>
                      )}
                    </div>
                    <div className="foot">
                      <span>
                        v{agent.version} · updated {timeAgo(agent.updated_at)}
                      </span>
                      <span className="open">
                        Open <Icon name="arrowRight" size={14} />
                      </span>
                    </div>
                  </button>
                )
              })}
              <button className="agent-card new" onClick={() => navigate({ page: 'new' })}>
                <IconChip icon="plus" size="lg" />
                <strong>Create a new agent</strong>
                <span className="small">For a new or existing client</span>
              </button>
            </div>
          )}
        </>
      )}
    </>
  )
}
