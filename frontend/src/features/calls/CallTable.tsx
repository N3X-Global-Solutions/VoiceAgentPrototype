import { useState } from 'react'
import { Icon } from '@/components/Icon'
import { Avatar, Badge, Dot } from '@/components/ui'
import type { CallSession } from '@/lib/api'
import { duration, inr, latencyTone, ms, parseDate } from '@/lib/format'
import { CallDetailsModal } from './CallDetailsModal'
import { CHANNEL_LABEL, STATUS_TONE, type AgentRef } from './useCalls'

/** Calls table. Clicking a row opens the call in a details dialog (with newer/older navigation). */
export function CallTable({
  calls,
  agents,
  agent,
  onOpenAgent,
  compact,
}: {
  calls: CallSession[]
  agents?: Map<string, AgentRef>
  /** The agent, when the table lists a single agent's calls (no Agent column). */
  agent?: AgentRef
  onOpenAgent?: (ref: AgentRef) => void
  compact?: boolean
}) {
  const [openId, setOpenId] = useState<string | null>(null)
  const showAgent = Boolean(agents)
  // In a narrow card: no p95, and no turns column when the agent column is shown.
  const showTurns = !(compact && showAgent)
  const openIndex = openId ? calls.findIndex((c) => c.id === openId) : -1
  const open = openIndex >= 0 ? calls[openIndex] : null

  return (
    <div className="table-wrap">
      <table className={compact ? 'compact' : undefined}>
        <thead>
          <tr>
            <th>Started</th>
            {showAgent && <th>Agent</th>}
            <th>Channel</th>
            <th>Status</th>
            <th className="num">Duration</th>
            {showTurns && <th className="num">Turns</th>}
            <th className="num">{compact ? 'Avg response' : 'Response avg / p95'}</th>
            <th className="num">Cost</th>
            <th aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => {
            const when = parseDate(c.started_at)
            const ref = agents?.get(c.agent_id)
            const tone = latencyTone(c.latency_avg_ms, 1000, 1400)
            return (
              <tr
                key={c.id}
                className="clickable"
                tabIndex={0}
                onClick={() => setOpenId(c.id)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), setOpenId(c.id))}
                aria-label={`Open call from ${when.toLocaleString()}`}
              >
                <td className="nowrap">
                  <span className="cell-title">{when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</span>{' '}
                  <span className="muted">{when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span>
                </td>
                {showAgent && (
                  <td>
                    {ref ? (
                      <span className="row nowrap" style={{ flexWrap: 'nowrap', gap: 10 }}>
                        <Avatar name={ref.agentName} seed={ref.agentId} size="sm" square />
                        <span>
                          <span className="cell-title" style={{ display: 'block' }}>
                            {ref.agentName}
                          </span>
                          <span className="cell-sub">{ref.clientName}</span>
                        </span>
                      </span>
                    ) : (
                      <span className="muted">Deleted agent</span>
                    )}
                  </td>
                )}
                <td>
                  <span className="channel">
                    <Icon name={c.channel === 'browser' ? 'mic' : c.channel === 'chat' ? 'chat' : 'phone'} size={14} />
                    {CHANNEL_LABEL[c.channel] ?? c.channel}
                    {!compact && c.phone_number && <span className="muted">{c.phone_number}</span>}
                  </span>
                </td>
                <td>
                  <Badge tone={STATUS_TONE[c.status] ?? 'gray'} dot>
                    {c.status}
                  </Badge>
                </td>
                <td className="num">{duration(c.duration_secs)}</td>
                {showTurns && <td className="num">{c.turns}</td>}
                <td className="num">
                  <span className="row nowrap" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                    {tone && <Dot tone={tone} />}
                    {ms(c.latency_avg_ms)}
                    {!compact && <span className="muted">/ {ms(c.latency_p95_ms)}</span>}
                  </span>
                </td>
                <td className="num cell-title">{inr(c.cost_inr)}</td>
                <td className="num faint" style={{ width: 36 }}>
                  <Icon name="chevronRight" size={16} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {open && (
        <CallDetailsModal
          call={open}
          agent={agents?.get(open.agent_id) ?? agent}
          position={{ index: openIndex, total: calls.length }}
          onPrev={openIndex > 0 ? () => setOpenId(calls[openIndex - 1].id) : undefined}
          onNext={openIndex < calls.length - 1 ? () => setOpenId(calls[openIndex + 1].id) : undefined}
          onOpenAgent={
            onOpenAgent
              ? (r) => {
                  setOpenId(null)
                  onOpenAgent(r)
                }
              : undefined
          }
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  )
}
