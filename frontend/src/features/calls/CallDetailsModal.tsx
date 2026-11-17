import { Icon } from '@/components/Icon'
import { Modal } from '@/components/Modal'
import { Avatar, Badge, CopyField, Dot } from '@/components/ui'
import type { CallSession } from '@/lib/api'
import { publicText } from '@/lib/colors'
import { duration, formatDate, inr, latencyTone, ms, parseDate } from '@/lib/format'
import { LatencyBars } from './LatencyBars'
import { CHANNEL_LABEL, STATUS_TONE, type AgentRef } from './useCalls'

/** Everything about one call in a dialog: summary, transcript, latency, usage and identifiers. */
export function CallDetailsModal({
  call: c,
  agent,
  position,
  onPrev,
  onNext,
  onOpenAgent,
  onClose,
}: {
  call: CallSession
  agent?: AgentRef
  position?: { index: number; total: number }
  onPrev?: () => void
  onNext?: () => void
  onOpenAgent?: (ref: AgentRef) => void
  onClose: () => void
}) {
  const started = parseDate(c.started_at)
  const tone = latencyTone(c.latency_avg_ms, 1000, 1400)
  const channel = CHANNEL_LABEL[c.channel] ?? c.channel
  const isPhone = c.channel !== 'browser' && c.channel !== 'chat'

  const stats: [string, string, ReturnType<typeof latencyTone>?][] = [
    ['Duration', duration(c.duration_secs)],
    ['Turns', String(c.turns)],
    ['Avg response', ms(c.latency_avg_ms), tone],
    ['p95 response', ms(c.latency_p95_ms), latencyTone(c.latency_p95_ms, 1200, 1700)],
    ['Cost', inr(c.cost_inr, 3)],
  ]

  const usage: [string, string][] = [
    ['Speech recognised', `${c.stt_seconds.toLocaleString()} s`],
    ['Voice characters', c.tts_chars.toLocaleString()],
    ['AI tokens in', c.llm_prompt_tokens.toLocaleString()],
    ...(c.llm_cached_tokens ? ([['  of which cached', c.llm_cached_tokens.toLocaleString()]] as [string, string][]) : []),
    ['AI tokens out', c.llm_completion_tokens.toLocaleString()],
  ]

  const info: [string, string][] = [
    ['Channel', channel],
    ['Direction', c.direction === 'outbound' ? 'Outbound' : 'Inbound'],
    ...(c.phone_number ? ([['Phone number', c.phone_number]] as [string, string][]) : []),
    ['Started', formatDate(c.started_at, true)],
    ...(c.ended_at ? ([['Ended', formatDate(c.ended_at, true)]] as [string, string][]) : []),
    ['Agent version', `v${c.agent_version}`],
  ]

  return (
    <Modal
      title={agent ? agent.agentName : 'Call details'}
      subtitle={`${agent ? `${agent.clientName} · ` : ''}${started.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}, ${started.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`}
      leading={agent ? <Avatar name={agent.agentName} seed={agent.agentId} square /> : undefined}
      onClose={onClose}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft' && onPrev) onPrev()
        if (e.key === 'ArrowRight' && onNext) onNext()
      }}
      actions={
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <Badge tone="gray" icon={isPhone ? 'phone' : c.channel === 'chat' ? 'chat' : 'mic'}>
            {channel}
          </Badge>
          <Badge tone={STATUS_TONE[c.status] ?? 'gray'} dot>
            {c.status}
          </Badge>
        </div>
      }
      footer={
        <>
          <span className="row modal-hint">
            {position && (
              <>
                Call {position.index + 1} of {position.total} · <span className="kbd">←</span>
                <span className="kbd">→</span> to move · <span className="kbd">Esc</span> to close
              </>
            )}
          </span>
          <span className="row" style={{ flexWrap: 'nowrap' }}>
            {agent && onOpenAgent && (
              <button className="btn btn-ghost btn-sm" onClick={() => onOpenAgent(agent)}>
                Open agent <Icon name="arrowRight" size={14} />
              </button>
            )}
            <button className="btn btn-secondary btn-sm" onClick={onPrev} disabled={!onPrev}>
              <Icon name="back" size={14} /> Newer
            </button>
            <button className="btn btn-secondary btn-sm" onClick={onNext} disabled={!onNext}>
              Older <Icon name="arrowRight" size={14} />
            </button>
          </span>
        </>
      }
    >
      <div className="detail-stats">
        {stats.map(([label, value, t]) => (
          <div className="detail-stat" key={label}>
            <span className="label">{label}</span>
            <span className="value">
              {t && <Dot tone={t} />}
              {value}
            </span>
          </div>
        ))}
      </div>

      <div className="detail-grid">
        <section className="detail-main">
          {c.error && (
            <div className="banner tone-red">
              <Icon name="alert" /> <span className="grow">{publicText(c.error)}</span>
            </div>
          )}
          <div className="detail-section-title">
            <span>Transcript</span>
            <span className="small" style={{ textTransform: 'none', letterSpacing: 0, fontWeight: 500 }}>
              {c.transcript.filter((l) => l.role !== 'event').length} messages
            </span>
          </div>
          <div className="bubbles compact">
            {c.transcript.length === 0 && <p className="muted small">No transcript was recorded for this call.</p>}
            {c.transcript.map((l, i) => (
              <div key={i} className={`bubble ${l.role}`}>
                {l.role === 'event' ? publicText(l.text) : l.text}
              </div>
            ))}
          </div>
        </section>

        <aside className="detail-side">
          <section>
            <div className="detail-section-title">Response time per turn</div>
            <LatencyBars turns={c.latency_turns} emptyText="No voice turns were measured for this call." />
          </section>
          <section>
            <div className="detail-section-title">Usage</div>
            <dl className="kv">
              {usage.map(([k, v]) => (
                <Row key={k} k={k} v={v} />
              ))}
            </dl>
          </section>
          <section>
            <div className="detail-section-title">Call info</div>
            <dl className="kv">
              {info.map(([k, v]) => (
                <Row key={k} k={k} v={v} />
              ))}
            </dl>
          </section>
          <section>
            <div className="detail-section-title">Call ID</div>
            <CopyField value={c.id} />
          </section>
        </aside>
      </div>
    </Modal>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt>{k.trim()}</dt>
      <dd>{v}</dd>
    </>
  )
}
