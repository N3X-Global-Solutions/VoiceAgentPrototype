import { useMemo, useState } from 'react'
import { Icon } from '@/components/Icon'
import { EmptyState, PageHead } from '@/components/ui'
import type { Client } from '@/lib/api'
import { CallTable } from './CallTable'
import { CHANNEL_LABEL, agentIndex, useCalls, type AgentRef } from './useCalls'

/** Workspace-wide call logs with search and filters. */
export function CallLogsPage({ clients, onOpenAgent }: { clients: Client[]; onOpenAgent: (ref: AgentRef) => void }) {
  const calls = useCalls(undefined, 0, 200, 10000)
  const agents = useMemo(() => agentIndex(clients), [clients])
  const [query, setQuery] = useState('')
  const [channel, setChannel] = useState('')
  const [status, setStatus] = useState('')

  const q = query.trim().toLowerCase()
  const shown = (calls ?? []).filter((c) => {
    if (channel && c.channel !== channel) return false
    if (status && c.status !== status) return false
    if (!q) return true
    const ref = agents.get(c.agent_id)
    return [ref?.agentName, ref?.clientName, c.phone_number, c.id].some((v) => v?.toLowerCase().includes(q))
  })
  const channels = [...new Set((calls ?? []).map((c) => c.channel))]
  const statuses = [...new Set((calls ?? []).map((c) => c.status))]

  return (
    <>
      <PageHead eyebrow="Monitoring" title="Call logs" description="Every call across all agents, newest first (last 200), with transcripts, latency and cost." />
      <div className="card">
        <div className="table-toolbar">
          <div className="input-icon">
            <Icon name="search" size={15} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search agent, client or number" />
          </div>
          <select value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Channel">
            <option value="">All channels</option>
            {channels.map((c) => (
              <option key={c} value={c}>
                {CHANNEL_LABEL[c] ?? c}
              </option>
            ))}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">All statuses</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <span className="muted small" style={{ marginLeft: 'auto' }}>
            {shown.length} of {calls?.length ?? 0}
          </span>
        </div>
        {calls && calls.length === 0 ? (
          <EmptyState icon="headphones" title="No calls yet">
            Open an agent and start a test call. Every call is logged here with its transcript, latency and cost.
          </EmptyState>
        ) : calls && shown.length === 0 ? (
          <EmptyState icon="search" tone="gray" title="No matching calls">
            Try a different search or filter.
          </EmptyState>
        ) : (
          <CallTable calls={shown} agents={agents} onOpenAgent={onOpenAgent} />
        )}
      </div>
    </>
  )
}
