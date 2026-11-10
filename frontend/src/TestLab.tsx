import { PipecatClient, type TransportState } from '@pipecat-ai/client-js'
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport'
import { Fragment, useEffect, useRef, useState } from 'react'
import { api, type Agent, type CallSession, type Health, type LatencyTurn } from './api'
import { PerceivedLatencyProbe } from './perceivedLatency'
import { Badge, Icon, Stat, latencyTone } from './ui'

// An agent line is built from TTS segments; the same segment arrives several times
// (new → in-progress → completed), so segments are keyed by id and replaced, not appended.
type Segment = { id: number | undefined; text: string }
type Line = { role: 'user' | 'agent' | 'system'; text: string; segments?: Segment[] }

function addSegment(line: Line, seg: Segment): Line {
  const segments = [...(line.segments ?? [])]
  const i = seg.id === undefined ? -1 : segments.findIndex((s) => s.id === seg.id)
  if (i >= 0) segments[i] = seg
  else segments.push(seg)
  return { ...line, segments, text: segments.map((s) => s.text.trim()).join(' ') }
}

type Usage = { stt_seconds: number; tts_chars: number; llm_prompt_tokens: number; cost_inr: number }
type Summary = { turns: number; avg_ms: number | null; p50_ms: number | null; p95_ms: number | null; max_ms: number | null }

function ms(v: number | null | undefined) {
  return v == null ? '–' : `${Math.round(v)} ms`
}

function useAutoScroll(dep: unknown) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [dep])
  return ref
}

export function TestLab({ agent, health, onCallEnded }: { agent: Agent; health: Health | null; onCallEnded: () => void }) {
  const [tab, setTab] = useState<'browser' | 'chat' | 'phone'>('browser')

  return (
    <div className="card test-panel">
      <div className="panel-head">
        <h3>Test agent</h3>
        <div className="segmented">
          <button className={tab === 'browser' ? 'active' : ''} onClick={() => setTab('browser')}>
            <Icon name="mic" size={14} /> Voice
          </button>
          <button className={tab === 'chat' ? 'active' : ''} onClick={() => setTab('chat')}>
            <Icon name="chat" size={14} /> Chat
          </button>
          <button className={tab === 'phone' ? 'active' : ''} onClick={() => setTab('phone')}>
            <Icon name="phone" size={14} /> Phone
          </button>
        </div>
      </div>
      <div className="panel-body">
        {tab === 'browser' && <BrowserCall agent={agent} health={health} onEnded={onCallEnded} />}
        {tab === 'chat' && <ChatTest agent={agent} />}
        {tab === 'phone' && <PhoneCall agent={agent} health={health} onPlaced={onCallEnded} />}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ browser call

const STATE_LABEL: Record<string, string> = {
  idle: 'Ready to call',
  disconnected: 'Call ended',
  error: 'Call failed',
  connecting: 'Connecting…',
  authenticating: 'Connecting…',
  authenticated: 'Connecting…',
  initializing: 'Connecting…',
  initialized: 'Connecting…',
  connected: 'Live',
  ready: 'Live',
  disconnecting: 'Ending…',
}

function BrowserCall({ agent, health, onEnded }: { agent: Agent; health: Health | null; onEnded: () => void }) {
  const clientRef = useRef<PipecatClient | null>(null)
  const probeRef = useRef<PerceivedLatencyProbe | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [heard, setHeard] = useState<number[]>([])
  const [state, setState] = useState<TransportState | 'idle'>('idle')
  const [lines, setLines] = useState<Line[]>([])
  const [turns, setTurns] = useState<LatencyTurn[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [greetingMs, setGreetingMs] = useState<number | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0)

  const connected = state === 'connected' || state === 'ready'
  const busy = state !== 'idle' && state !== 'disconnected' && state !== 'error'
  const visibleLines = lines.filter((l) => l.role !== 'system')
  const scrollRef = useAutoScroll(lines)
  const cap = Math.min(agent.config.max_call_seconds, health?.max_call_seconds_cap ?? 300)

  useEffect(() => {
    if (!connected) return
    const started = Date.now()
    const id = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(id)
  }, [connected])

  useEffect(
    () => () => {
      void clientRef.current?.disconnect()
      probeRef.current?.stop()
    },
    [],
  )

  const start = async () => {
    setLines([])
    setTurns([])
    setHeard([])
    probeRef.current?.stop()
    const probe = new PerceivedLatencyProbe((v) => setHeard((h) => [...h, v]))
    probeRef.current = probe
    setSummary(null)
    setGreetingMs(null)
    setUsage(null)
    setError('')
    setElapsed(0)

    const client = new PipecatClient({
      transport: new SmallWebRTCTransport({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] }),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onTransportStateChanged: (s) => setState(s),
        onTrackStarted: (track, participant) => {
          if (track.kind !== 'audio') return
          if (participant?.local) {
            probe.attach(track, 'local')
            return
          }
          if (!audioRef.current) return
          audioRef.current.srcObject = new MediaStream([track])
          void audioRef.current.play()
          probe.attach(track, 'remote')
        },
        onUserTranscript: (data) => {
          if (data.final) setLines((l) => [...l, { role: 'user', text: data.text }])
        },
        onBotOutput: (data) => {
          if (!data.text?.trim()) return
          // Without a segment id, only the first ("new") message of a segment is new text.
          if (data.segment_id === undefined && data.spoken_status && data.spoken_status !== 'new') return
          const seg = { id: data.segment_id, text: data.text }
          setLines((l) => {
            const last = l[l.length - 1]
            if (last?.role === 'agent') return [...l.slice(0, -1), addSegment(last, seg)]
            return [...l, addSegment({ role: 'agent', text: '' }, seg)]
          })
        },
        onUserStartedSpeaking: () => setLines((l) => (l[l.length - 1]?.role === 'agent' ? [...l, { role: 'system', text: '' }] : l)),
        onServerMessage: (msg: { type: string } & Record<string, unknown>) => {
          if (msg.type === 'latency') {
            setTurns((t) => [...t, msg as unknown as LatencyTurn])
            setSummary(msg.summary as Summary)
          } else if (msg.type === 'usage') {
            setUsage(msg as unknown as Usage)
          } else if (msg.type === 'greeting_latency') {
            setGreetingMs(msg.greeting_ms as number)
          } else if (msg.type === 'error') {
            setError(String(msg.message))
          }
        },
        onError: (m) => setError(JSON.stringify(m.data ?? m)),
        onDisconnected: () => {
          probe.stop()
          setState('disconnected')
          setTimeout(onEnded, 1500) // the backend saves the call when the pipeline ends
        },
      },
    })
    clientRef.current = client
    try {
      setState('connecting')
      await client.connect({ webrtcRequestParams: { endpoint: `/api/agents/${agent.id}/offer` } })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('error')
    }
  }

  const stop = async () => {
    await clientRef.current?.disconnect()
    setState('disconnected')
  }

  const mmss = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`
  const heardAvg = heard.length ? Math.round(heard.reduce((a, b) => a + b, 0) / heard.length) : null

  return (
    <>
      {!health?.sarvam_key_set && (
        <div className="banner banner-red">
          <Icon name="x" /> SARVAM_API_KEY is not set in .env. Add it and restart the backend.
        </div>
      )}
      <div className="call-stage">
        {!busy ? (
          <button className="call-btn start" onClick={start} disabled={!health?.sarvam_key_set} title="Start call">
            <Icon name="phone" size={22} />
          </button>
        ) : (
          <button className="call-btn end" onClick={stop} title="End call">
            <Icon name="phoneOff" size={22} />
          </button>
        )}
        <div className="call-meta">
          <div className="title">{STATE_LABEL[state] ?? state}</div>
          <div className="sub">
            {connected ? (
              <Badge tone="green">
                <span className="dot pulse" /> Live
              </Badge>
            ) : busy ? (
              <Badge tone="blue">
                <span className="dot pulse" /> Connecting
              </Badge>
            ) : (
              <span className="muted small">Use headphones · mic access needed</span>
            )}
            {usage && <Badge>₹{usage.cost_inr.toFixed(2)}</Badge>}
            <span className="muted small">
              cap {cap}s · ₹{health?.max_cost_per_call_inr ?? 5}
            </span>
          </div>
        </div>
        {(connected || elapsed > 0) && <div className="timer">{mmss}</div>}
      </div>
      <audio ref={audioRef} autoPlay />
      {error && (
        <div className="banner banner-red" style={{ marginTop: 12, marginBottom: 0 }}>
          <Icon name="x" /> <span className="grow">{error}</span>
        </div>
      )}

      <div className="bubbles" ref={scrollRef}>
        {visibleLines.length === 0 && (
          <div className="bubbles-empty">
            <Icon name="wave" size={22} />
            <p>Press the green button and start talking. The conversation appears here.</p>
          </div>
        )}
        {visibleLines.map((l, i) => (
          <div key={i} className={`bubble ${l.role}`}>
            {l.text}
          </div>
        ))}
      </div>

      <div className="stats">
        <Stat label="You heard" value={ms(heardAvg)} tone={latencyTone(heardAvg, 1500, 2200)} />
        <Stat label="Server avg" value={ms(summary?.avg_ms)} tone={latencyTone(summary?.avg_ms, 1000, 1400)} />
        <Stat label="Server p95" value={ms(summary?.p95_ms)} tone={latencyTone(summary?.p95_ms, 1200, 1700)} />
        <Stat label="Greeting" value={ms(greetingMs)} tone={latencyTone(greetingMs, 800, 1500)} />
      </div>
      <TurnBars turns={turns} heard={heard} />
    </>
  )
}

function TurnBars({ turns, heard }: { turns: LatencyTurn[]; heard: number[] }) {
  if (turns.length === 0) {
    return <p className="muted small" style={{ marginTop: 10 }}>Per-turn latency appears after your first reply.</p>
  }
  const scale = Math.max(1500, ...turns.map((t) => t.total_ms))
  return (
    <>
      <div className="turns">
        {turns.map((t) => {
          const stt = t.transcript_ms ?? 0
          const llmEnd = t.llm_first_text_ms ?? stt
          const ttsEnd = t.tts_first_audio_ms ?? t.total_ms
          const pct = (v: number) => `${Math.max(0, (v / scale) * 100)}%`
          const h = heard[t.turn - 1]
          return (
            <div className="turn" key={t.turn}>
              <span className="turn-num">#{t.turn}</span>
              <div
                className="bar"
                title={`STT ${stt} ms · LLM ${llmEnd - stt} ms · TTS ${ttsEnd - llmEnd} ms${t.pause_ms ? ` · pause ${t.pause_ms} ms before` : ''}`}
              >
                <span className="seg-stt" style={{ width: pct(stt) }} />
                <span className="seg-llm" style={{ width: pct(llmEnd - stt) }} />
                <span className="seg-tts" style={{ width: pct(ttsEnd - llmEnd) }} />
              </div>
              <span className="turn-val">
                <strong>{t.total_ms}</strong> ms
                {h != null && <span className="muted"> · heard {h}</span>}
              </span>
            </div>
          )
        })}
      </div>
      <div className="legend">
        <span>
          <i className="seg-stt" />
          Transcript
        </span>
        <span>
          <i className="seg-llm" />
          LLM
        </span>
        <span>
          <i className="seg-tts" />
          Voice
        </span>
        <span>“heard” = your mic quiet → agent audio</span>
      </div>
    </>
  )
}

// ------------------------------------------------------------------ text chat

type ChatMessage = { role: 'user' | 'assistant'; content: string; meta?: string; tools?: string[] }

function ChatTest({ agent }: { agent: Agent }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [spent, setSpent] = useState(0)
  const scrollRef = useAutoScroll(messages.length + (busy ? 1 : 0))

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    const next = [...messages, { role: 'user' as const, content: text }]
    setMessages(next)
    setInput('')
    setBusy(true)
    setError('')
    try {
      const res = await api.chat(agent.id, next.map(({ role, content }) => ({ role, content })))
      setSpent((s) => s + res.cost_inr)
      setMessages([
        ...next,
        {
          role: 'assistant',
          content: res.reply + (res.ended ? ' · call ended' : ''),
          meta: `${res.latency_ms} ms · ₹${res.cost_inr.toFixed(3)}`,
          tools: res.tool_calls.map((t) => `${t.name}(${JSON.stringify(t.arguments)}) → ${JSON.stringify(t.result).slice(0, 140)}`),
        },
      ])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="row between">
        <span className="muted small">Same prompt and tools as a call, no audio · ~₹0.01–0.05 per message</span>
        <Badge>₹{spent.toFixed(3)} spent</Badge>
      </div>
      <div className="bubbles" ref={scrollRef}>
        <div className="bubble agent">{agent.config.greeting}</div>
        {messages.map((m, i) => (
          <Fragment key={i}>
            {m.tools?.map((t, j) => (
              <div key={j} className="tool-call">
                <Icon name="wrench" size={13} /> {t}
              </div>
            ))}
            <div className={`bubble ${m.role === 'user' ? 'user' : 'agent'}`}>
              {m.content}
              {m.meta && <span className="meta">{m.meta}</span>}
            </div>
          </Fragment>
        ))}
        {busy && <div className="bubble agent muted">…</div>}
      </div>
      {error && <p className="error-text small" style={{ marginTop: 8 }}>{error}</p>}
      <div className="composer">
        <input
          value={input}
          placeholder="Type what a caller would say…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button className="btn btn-primary" onClick={send} disabled={busy || !input.trim()} title="Send">
          <Icon name="send" />
        </button>
        <button className="btn btn-ghost" onClick={() => setMessages([])} title="Reset conversation">
          Reset
        </button>
      </div>
    </>
  )
}

// ------------------------------------------------------------------ phone call

function PhoneCall({ agent, health, onPlaced }: { agent: Agent; health: Health | null; onPlaced: () => void }) {
  const [to, setTo] = useState('+91')
  const [provider, setProvider] = useState<'twilio' | 'exotel'>(
    health?.twilio_configured || !health?.exotel_configured ? 'twilio' : 'exotel',
  )
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const isInbound = health?.inbound_agent_id === agent.id

  const publicUrl = health?.public_base_url?.startsWith('https://')
  const configured = provider === 'twilio' ? health?.twilio_configured : health?.exotel_configured
  const ready = configured && publicUrl && health?.sarvam_key_set

  const call = async () => {
    setError('')
    setStatus('Dialing…')
    try {
      await api.phoneCall(agent.id, to.replace(/\s/g, ''), provider)
      setStatus('Call placed. Your phone should ring in a few seconds; latency shows in call history afterwards.')
      setTimeout(onPlaced, 3000)
    } catch (e) {
      setStatus('')
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const items: [boolean | undefined, string][] = [
    [health?.sarvam_key_set, 'Sarvam API key'],
    [publicUrl, `Public URL ${health?.public_base_url ? `(${health.public_base_url})` : '(ngrok, PUBLIC_BASE_URL)'}`],
    [health?.twilio_configured, 'Twilio account + number'],
    [health?.exotel_configured, 'Exotel account + ExoPhone + flow'],
  ]

  return (
    <>
      <ul className="checklist">
        {items.map(([done, label]) => (
          <li key={label} className={done ? 'done' : ''}>
            <span className="mark">{done && <Icon name="check" size={11} />}</span>
            {label}
          </li>
        ))}
      </ul>
      <div className="segmented" style={{ marginBottom: 10 }}>
        <button className={provider === 'twilio' ? 'active' : ''} onClick={() => setProvider('twilio')}>
          Twilio
        </button>
        <button className={provider === 'exotel' ? 'active' : ''} onClick={() => setProvider('exotel')}>
          Exotel
        </button>
      </div>
      <div className="composer">
        <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="+9198xxxxxxxx" />
        <button className="btn btn-primary" onClick={call} disabled={!ready}>
          <Icon name="phone" size={14} /> Call
        </button>
      </div>
      {!ready && <p className="muted small" style={{ marginTop: 8 }}>Complete the checklist above to place real phone calls.</p>}
      {status && <p className="small" style={{ marginTop: 8 }}>{status}</p>}
      {error && <p className="error-text small" style={{ marginTop: 8 }}>{error}</p>}
      <div style={{ marginTop: 14 }}>
        <button
          className="btn btn-secondary"
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
      </div>
    </>
  )
}

// ------------------------------------------------------------------ history

const STATUS_TONE: Record<string, 'green' | 'red' | 'amber' | 'blue'> = {
  completed: 'green',
  failed: 'red',
  active: 'blue',
  dialing: 'amber',
}

export function CallHistory({ agentId, refreshKey }: { agentId: string; refreshKey: number }) {
  const [calls, setCalls] = useState<CallSession[]>([])
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () => api.calls(agentId).then((c) => !cancelled && setCalls(c))
    void load()
    const id = setInterval(load, 5000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [agentId, refreshKey])

  return (
    <div className="card history">
      <div className="panel-head">
        <h3 className="row">
          <Icon name="history" /> Call history
        </h3>
        <span className="muted small">{calls.length} calls · click a row for the transcript</span>
      </div>
      {calls.length === 0 ? (
        <p className="muted" style={{ padding: 20 }}>
          No calls yet. Start a voice test to see transcripts, latency and cost here.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Turns</th>
                <th>Latency avg / p95</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c) => {
                const when = new Date(c.started_at + (c.started_at.endsWith('Z') ? '' : 'Z'))
                return (
                  <Fragment key={c.id}>
                    <tr className="clickable" onClick={() => setOpen(open === c.id ? null : c.id)}>
                      <td>
                        {when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}{' '}
                        <span className="muted">{when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}</span>
                      </td>
                      <td>
                        <span className="row">
                          <Icon name={c.channel === 'browser' ? 'mic' : 'phone'} size={14} />
                          {c.channel}
                          {c.phone_number && <span className="muted">{c.phone_number}</span>}
                        </span>
                      </td>
                      <td>
                        <Badge tone={STATUS_TONE[c.status] ?? 'neutral'}>{c.status}</Badge>
                      </td>
                      <td className="num">{c.duration_secs ? `${c.duration_secs}s` : '–'}</td>
                      <td className="num">{c.turns}</td>
                      <td className="num">
                        <span className={`badge badge-${latencyTone(c.latency_avg_ms, 1000, 1400) ?? 'neutral'}`}>
                          {ms(c.latency_avg_ms)}
                        </span>{' '}
                        <span className="muted">/ {ms(c.latency_p95_ms)}</span>
                      </td>
                      <td className="num">₹{c.cost_inr.toFixed(2)}</td>
                    </tr>
                    {open === c.id && (
                      <tr>
                        <td colSpan={7} className="detail-cell">
                          {c.error && <p className="error-text small">{c.error}</p>}
                          <p className="muted small">
                            STT {c.stt_seconds}s · TTS {c.tts_chars} chars · LLM {c.llm_prompt_tokens} in /{' '}
                            {c.llm_completion_tokens} out tokens · agent v{c.agent_version}
                          </p>
                          <div className="bubbles compact">
                            {c.transcript.length === 0 && <div className="bubbles-empty">No transcript.</div>}
                            {c.transcript.map((l, i) => (
                              <div key={i} className={`bubble ${l.role}`}>
                                {l.text}
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
