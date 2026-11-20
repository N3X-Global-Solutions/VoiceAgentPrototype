import { useState } from 'react'
import { Icon } from '@/components/Icon'
import { api, type Agent, type Health } from '@/lib/api'

/** Place a real outbound call via Twilio/Exotel, or make this the inbound agent. */
export function PhoneTest({ agent, health, ready: providersReady, onPlaced }: { agent: Agent; health: Health | null; ready: boolean; onPlaced: () => void }) {
  const [to, setTo] = useState('+91')
  const [provider, setProvider] = useState<'twilio' | 'exotel'>(health?.twilio_configured || !health?.exotel_configured ? 'twilio' : 'exotel')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const isInbound = health?.inbound_agent_id === agent.id

  const publicUrl = health?.public_base_url?.startsWith('https://')
  const configured = provider === 'twilio' ? health?.twilio_configured : health?.exotel_configured
  const ready = configured && publicUrl && providersReady

  const call = async () => {
    setError('')
    setStatus('Dialing…')
    try {
      await api.phoneCall(agent.id, to.replace(/\s/g, ''), provider)
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
    [health?.twilio_configured, 'Twilio account + number'],
    [health?.exotel_configured, 'Exotel account + ExoPhone + flow'],
  ]

  return (
    <>
      <span className="label-sm">Readiness</span>
      <ul className="checklist">
        {items.map(([done, label]) => (
          <li key={label} className={done ? 'done' : ''}>
            <span className="mark">{done && <Icon name="check" size={11} strokeWidth={3} />}</span>
            <span className="truncate">{label}</span>
          </li>
        ))}
      </ul>
      <span className="label-sm">Provider</span>
      <div className="segmented full" style={{ marginBottom: 16 }}>
        <button className={provider === 'twilio' ? 'active' : ''} onClick={() => setProvider('twilio')}>
          Twilio
        </button>
        <button className={provider === 'exotel' ? 'active' : ''} onClick={() => setProvider('exotel')}>
          Exotel
        </button>
      </div>
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
      <p className="muted small" style={{ marginBottom: 10 }}>
        One agent answers calls to your phone number.
      </p>
      <button
        className={`btn ${isInbound ? 'btn-soft' : 'btn-secondary'}`}
        onClick={async () => {
          await api.setInbound(agent.id)
          setStatus('This agent now answers inbound calls to your number.')
        }}
        disabled={isInbound}
      >
        {isInbound ? (
          <>
            <Icon name="check" size={14} /> Answers inbound calls
          </>
        ) : (
          'Use for inbound calls'
        )}
      </button>
    </>
  )
}
