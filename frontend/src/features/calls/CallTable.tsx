import { Fragment, useState } from 'react'
import { Icon } from '@/components/Icon'
import { Avatar, Badge, Dot } from '@/components/ui'
import type { CallSession } from '@/lib/api'
import { duration, formatDate, inr, latencyTone, ms, parseDate } from '@/lib/format'
import { CHANNEL_LABEL, STATUS_TONE, type AgentRef } from './useCalls'

/** Calls table; click a row for usage details and the transcript. Pass `agents` to show an Agent column. */
export function CallTable({
  calls,
  agents,
  onOpenAgent,
  compact,
}: {
  calls: CallSession[]
  agents?: Map<string, AgentRef>
  onOpenAgent?: (ref: AgentRef) => void
  compact?: boolean
}) {
  const [open, setOpen] = useState<string | null>(null)
  const showAgent = Boolean(agents)
  // In a narrow card: no p95, and no turns column when the agent column is shown.
  const showTurns = !(compact && showAgent)
  const cols = 6 + Number(showAgent) + Number(showTurns)

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
            <th className="num">{compact ? 'Latency' : 'Latency avg / p95'}</th>
            <th className="num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => {
            const when = parseDate(c.started_at)
            const ref = agents?.get(c.agent_id)
            const isOpen = open === c.id
            const tone = latencyTone(c.latency_avg_ms, 1000, 1400)
            return (
              <Fragment key={c.id}>
                <tr className={`clickable${isOpen ? ' open' : ''}`} onClick={() => setOpen(isOpen ? null : c.id)} aria-expanded={isOpen}>
                  <td className="nowrap">
                    <span className="cell-title">{when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</span>{' '}
                    <span className="muted">{when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span>
                  </td>
                  {showAgent && (
                    <td>
                      {ref ? (
                        <button
                          className="row-link"
                          onClick={(e) => {
                            e.stopPropagation()
                            onOpenAgent?.(ref)
                          }}
                        >
                          <Avatar name={ref.agentName} seed={ref.agentId} size="sm" />
                          <span className="nowrap">
                            <span className="cell-title" style={{ display: 'block' }}>
                              {ref.agentName}
                            </span>
                            <span className="cell-sub">{ref.clientName}</span>
                          </span>
                        </button>
                      ) : (
                        <span className="muted">Deleted agent</span>
                      )}
                    </td>
                  )}
                  <td>
                    <span className="channel">
                      <Icon name={c.channel === 'browser' ? 'mic' : 'phone'} size={14} />
                      {CHANNEL_LABEL[c.channel] ?? c.channel}
                      {c.channel !== 'browser' && <Icon name={c.direction === 'outbound' ? 'outbound' : 'inbound'} size={12} />}
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
                  <td className="num" title={`avg ${ms(c.latency_avg_ms)} · p95 ${ms(c.latency_p95_ms)}`}>
                    <span className="row nowrap" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                      {tone && <Dot tone={tone} />}
                      {ms(c.latency_avg_ms)}
                      {!compact && <span className="muted">/ {ms(c.latency_p95_ms)}</span>}
                    </span>
                  </td>
                  <td className="num cell-title">{inr(c.cost_inr)}</td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={cols} className="detail-cell">
                      <CallDetail call={c} />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function CallDetail({ call: c }: { call: CallSession }) {
  const rows: [string, string][] = [
    ['Call ID', c.id],
    ['Agent version', `v${c.agent_version}`],
    ['Direction', c.direction],
    ['Started', formatDate(c.started_at, true)],
    ['Duration', duration(c.duration_secs)],
    ['Latency p50', ms(c.latency_p50_ms)],
    ['Latency max', ms(c.latency_max_ms)],
    ['STT audio', `${c.stt_seconds}s`],
    ['TTS characters', c.tts_chars.toLocaleString()],
    ['LLM tokens in / out', `${c.llm_prompt_tokens.toLocaleString()} / ${c.llm_completion_tokens.toLocaleString()}`],
    ['Cost', inr(c.cost_inr, 3)],
  ]
  return (
    <div className="call-detail">
      <div className="call-detail-meta">
        <span className="label-sm">Usage</span>
        <dl>
          {rows.map(([k, v]) => (
            <Fragment key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </Fragment>
          ))}
        </dl>
      </div>
      <div className="call-detail-transcript">
        {c.error && (
          <div className="banner tone-red">
            <Icon name="alert" /> <span className="grow">{c.error}</span>
          </div>
        )}
        <span className="label-sm">Transcript</span>
        <div className="bubbles compact">
          {c.transcript.length === 0 && <div className="muted small">No transcript recorded.</div>}
          {c.transcript.map((l, i) => (
            <div key={i} className={`bubble ${l.role}`}>
              {l.text}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
