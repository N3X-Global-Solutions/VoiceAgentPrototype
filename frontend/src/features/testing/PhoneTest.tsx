import { useState } from 'react'
import { Icon } from '@/components/Icon'
import { PROVIDER_NAME } from '@/lib/phoneLines'
import { api, type Agent, type CallRoute, type Health, type PhoneLine } from '@/lib/api'

type From = { key: string; label: string; route: CallRoute; ready: boolean; setup: string }

/** Place a real outbound call from the workspace number (.env) or one of the client's own numbers,
 *  and show which numbers this agent answers. */
export function PhoneTest({
  agent,
  health,
  lines,
  ready: providersReady,
  onPlaced,
}: {
  agent: Agent
  health: Health | null
  lines: PhoneLine[]
  ready: boolean
  onPlaced: () => void
}) {
  const options: From[] = [
    ...lines.map((l) => ({
      key: `line:${l.id}`,
      label: `${l.number} · ${PROVIDER_NAME[l.provider]}${l.label ? ` · ${l.label}` : ''}`,
      route: { line_id: l.id },
      // "warning" lines can still dial (e.g. the number wasn't on the first page of ExoPhones).
      ready: l.status === 'ok' || l.status === 'warning',
      setup: l.status_detail || 'Check this number on the Clients page',
    })),
    {
      key: 'twilio',
      label: 'Workspace number · Twilio',
      route: { provider: 'twilio' },
      ready: !!health?.twilio_configured,
      setup: 'Twilio account + number in .env',
    },
    {
      key: 'exotel',
      label: 'Workspace number · Exotel',
      route: { provider: 'exotel' },
      ready: !!health?.exotel_configured,
      setup: 'Exotel account + ExoPhone + flow in .env',
    },
  ]
  const [fromKey, setFromKey] = useState(() => (options.find((o) => o.ready) ?? options[0]).key)
  const from = options.find((o) => o.key === fromKey) ?? options[0]
  const [to, setTo] = useState('+91')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const isInbound = health?.inbound_agent_id === agent.id
  const answers = lines.filter((l) => l.inbound_agent_id === agent.id)

  const publicUrl = health?.public_base_url?.startsWith('https://')
  const ready = from.ready && publicUrl && providersReady

  const call = async () => {
    setError('')
    setStatus('Dialing…')
    try {
      await api.phoneCall(agent.id, to.replace(/\s/g, ''), from.route)
      setStatus('Call placed. Your phone should ring in a few seconds; latency shows in call logs afterwards.')
      setTimeout(onPlaced, 3000)
    } catch (e) {
      setStatus('')
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const items: [boolean | undefined, string][] = [
    [providersReady, "API keys for this agent's providers"],
    [publicUrl, `Public URL ${health?.public_base_url ? `(${health.public_base_url})` : '(PUBLIC_BASE_URL)'}`],
    [from.ready, from.ready ? `Calling from ${from.label}` : from.setup],
  ]

  return (
    <>
      <span className="label-sm">Readiness</span>
      <ul className="checklist">
        {items.map(([done, label]) => (
          <li key={label} className={done ? 'done' : ''}>
            <span className="mark">{done && <Icon name="check" size={11} strokeWidth={3} />}</span>
            <span className="truncate" title={label}>
              {label}
            </span>
          </li>
        ))}
      </ul>
      <span className="label-sm">Call from</span>
      <select value={from.key} onChange={(e) => setFromKey(e.target.value)} style={{ marginBottom: 16, width: '100%' }}>
        {lines.length > 0 && (
          <optgroup label="Client's numbers">
            {options
              .filter((o) => o.key.startsWith('line:'))
              .map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                  {o.ready ? '' : ' (not working)'}
                </option>
              ))}
          </optgroup>
        )}
        <optgroup label="Workspace">
          {options
            .filter((o) => !o.key.startsWith('line:'))
            .map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
                {o.ready ? '' : ' (not set up)'}
              </option>
            ))}
        </optgroup>
      </select>
      <span className="label-sm">Number to call</span>
      <div className="composer" style={{ marginTop: 0 }}>
        <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="+9198xxxxxxxx" inputMode="tel" />
        <button className="btn btn-primary" onClick={call} disabled={!ready}>
          <Icon name="phone" size={14} /> Call
        </button>
      </div>
      {!ready && (
        <p className="muted small" style={{ marginTop: 8 }}>
          Complete the readiness checklist to place real phone calls.
        </p>
      )}
      {status && (
        <p className="small" style={{ marginTop: 8 }}>
          {status}
        </p>
      )}
      {error && (
        <p className="error-text small" style={{ marginTop: 8 }}>
          {error}
        </p>
      )}
      <div className="divider" />
      <span className="label-sm">Inbound</span>
      {answers.length > 0 && (
        <ul className="checklist" style={{ marginBottom: 12 }}>
          {answers.map((l) => (
            <li key={l.id} className="done">
              <span className="mark">
                <Icon name="check" size={11} strokeWidth={3} />
              </span>
              <span className="truncate">Answers {l.number}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small" style={{ marginBottom: 10 }}>
        The client's own numbers pick their agent on the Clients page. One agent answers calls to the workspace number.
      </p>
      <button
        className={`btn ${isInbound ? 'btn-soft' : 'btn-secondary'}`}
        onClick={async () => {
          await api.setInbound(agent.id)
          setStatus('This agent now answers inbound calls to the workspace number.')
        }}
        disabled={isInbound}
      >
        {isInbound ? (
          <>
            <Icon name="check" size={14} /> Answers the workspace number
          </>
        ) : (
          'Use for the workspace number'
        )}
      </button>
    </>
  )
}
