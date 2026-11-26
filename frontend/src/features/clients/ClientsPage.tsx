import { useState } from 'react'
import type { Navigate } from '@/app/routes'
import { Icon } from '@/components/Icon'
import { Avatar, Badge, Dot, EmptyState, PageHead } from '@/components/ui'
import type { Client, Health } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { LINE_STATUS } from '@/lib/phoneLines'
import { PhoneLinesModal } from './PhoneLinesModal'

/** Clients table: contact details, their agents, their own phone numbers, and delete. */
export function ClientsPage({
  clients,
  health,
  navigate,
  onDelete,
  onChanged,
}: {
  clients: Client[]
  health: Health | null
  navigate: Navigate
  onDelete: (client: Client) => void
  onChanged: () => Promise<void> | void
}) {
  const [query, setQuery] = useState('')
  const [numbersFor, setNumbersFor] = useState<{ clientId: string; lineId?: string } | null>(null)
  // Looked up on every render, so the modal shows the client as reloaded after each change.
  const numbersClient = numbersFor ? clients.find((c) => c.id === numbersFor.clientId) : undefined
  const q = query.trim().toLowerCase()
  const shown = clients.filter(
    (c) => !q || c.name.toLowerCase().includes(q) || c.industry.toLowerCase().includes(q) || c.contact_name.toLowerCase().includes(q),
  )

  return (
    <>
      <PageHead
        eyebrow="Workspace"
        title="Clients"
        description="The businesses your agents work for. Each client can have several agents."
        actions={
          <button className="btn btn-primary" onClick={() => navigate({ page: 'new' })}>
            <Icon name="plus" /> New client
          </button>
        }
      />
      <div className="card">
        {clients.length === 0 ? (
          <EmptyState
            icon="users"
            title="No clients yet"
            action={
              <button className="btn btn-primary" onClick={() => navigate({ page: 'new' })}>
                <Icon name="plus" /> New client
              </button>
            }
          >
            A client is created together with its first voice agent.
          </EmptyState>
        ) : (
          <>
            <div className="table-toolbar">
              <div className="input-icon">
                <Icon name="search" size={15} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search clients" />
              </div>
              <span className="muted small" style={{ marginLeft: 'auto' }}>
                {shown.length} of {clients.length}
              </span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Contact</th>
                    <th>Agents</th>
                    <th>Phone numbers</th>
                    <th>Created</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {shown.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <span className="row" style={{ flexWrap: 'nowrap', gap: 12 }}>
                          <Avatar name={c.name} seed={c.id} square />
                          <span>
                            <span className="cell-title" style={{ display: 'block' }}>
                              {c.name}
                            </span>
                            {c.industry ? <Badge tone="gray">{c.industry}</Badge> : <span className="cell-sub">No industry</span>}
                          </span>
                        </span>
                      </td>
                      <td>
                        {c.contact_name || c.contact_phone ? (
                          <>
                            <span style={{ display: 'block', fontWeight: 600 }}>{c.contact_name || '–'}</span>
                            <span className="cell-sub">{c.contact_phone}</span>
                          </>
                        ) : (
                          <span className="faint">–</span>
                        )}
                      </td>
                      <td>
                        <div className="chips">
                          {c.agents.map((a) => (
                            <button key={a.id} className="chip-link" onClick={() => navigate({ page: 'agent', clientId: c.id, agentId: a.id, tab: 'prompt' })}>
                              <Icon name="bot" size={12} /> {a.name}
                            </button>
                          ))}
                          <button className="chip-link add" onClick={() => navigate({ page: 'new', clientId: c.id })} title="Add an agent to this client">
                            <Icon name="plus" size={12} /> Add agent
                          </button>
                        </div>
                      </td>
                      <td>
                        <div className="chips">
                          {c.phone_lines.map((l) => (
                            <button
                              key={l.id}
                              className="chip-link"
                              onClick={() => setNumbersFor({ clientId: c.id, lineId: l.id })}
                              title={`${l.provider === 'exotel' ? 'Exotel' : 'Plivo'} · ${LINE_STATUS[l.status].label}${l.status_detail ? `: ${l.status_detail}` : ''}`}
                            >
                              <Dot tone={LINE_STATUS[l.status].tone} /> <span className="mono">{l.number}</span>
                            </button>
                          ))}
                          <button className="chip-link add" onClick={() => setNumbersFor({ clientId: c.id })} title="Manage this client's own phone numbers">
                            <Icon name={c.phone_lines.length ? 'settings' : 'plus'} size={12} /> {c.phone_lines.length ? 'Manage' : 'Add number'}
                          </button>
                        </div>
                      </td>
                      <td className="nowrap muted">{formatDate(c.created_at)}</td>
                      <td className="num">
                        <button className="btn btn-danger btn-sm btn-icon" onClick={() => onDelete(c)} title={`Delete ${c.name}`}>
                          <Icon name="trash" size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {shown.length === 0 && (
              <EmptyState icon="search" tone="gray" title="No matching clients">
                Try a different search.
              </EmptyState>
            )}
          </>
        )}
      </div>
      {numbersClient && (
        <PhoneLinesModal
          key={numbersClient.id}
          client={numbersClient}
          health={health}
          initialLineId={numbersFor?.lineId}
          onClose={() => setNumbersFor(null)}
          onChanged={onChanged}
        />
      )}
    </>
  )
}
