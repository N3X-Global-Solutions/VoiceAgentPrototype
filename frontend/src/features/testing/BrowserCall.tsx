import { PipecatClient, type TransportState } from '@pipecat-ai/client-js'
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport'
import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/Icon'
import { Badge, Stat } from '@/components/ui'
import { LatencyBars } from '@/features/calls/LatencyBars'
import type { Agent, Health, LatencyTurn } from '@/lib/api'
import { latencyTone, ms } from '@/lib/format'
import { PerceivedLatencyProbe } from './perceivedLatency'
import { useAutoScroll } from './useAutoScroll'

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

/** Talk to the agent from the browser over WebRTC, with live transcript, latency and cost. */
export function BrowserCall({ agent, health, ready, onEnded }: { agent: Agent; health: Health | null; ready: boolean; onEnded: () => void }) {
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
      <div className={`call-stage${connected ? ' live' : ''}`}>
        <div className="orb-wrap">
          {connected && (
            <>
              <span className="ring" />
              <span className="ring" />
            </>
          )}
          {!busy ? (
            <button className="call-btn" onClick={start} disabled={!ready} title="Start call" aria-label="Start call">
              <Icon name="phone" size={20} />
            </button>
          ) : (
            <button className="call-btn end" onClick={stop} title="End call" aria-label="End call">
              <Icon name="phoneOff" size={20} />
            </button>
          )}
        </div>
        <div className="call-meta">
          <div className="title">{STATE_LABEL[state] ?? state}</div>
          <div className="sub">
            {connected ? (
              <Badge tone="green" dot>
                Live
              </Badge>
            ) : busy ? (
              <Badge tone="amber" dot>
                Connecting
              </Badge>
            ) : (
              <span>
                Cap {cap}s · ₹{health?.max_cost_per_call_inr ?? 5} per call · use headphones
              </span>
            )}
            {usage && <Badge>₹{usage.cost_inr.toFixed(2)}</Badge>}
          </div>
        </div>
        {(connected || elapsed > 0) && <span className="timer">{mmss}</span>}
      </div>
      <audio ref={audioRef} autoPlay />
      {error && (
        <div className="banner tone-red" style={{ marginTop: 12, marginBottom: 0 }}>
          <Icon name="alert" /> <span className="grow">{error}</span>
        </div>
      )}

      <div className="bubbles" ref={scrollRef}>
        {visibleLines.length === 0 && (
          <div className="bubbles-empty">
            <Icon name="wave" size={22} />
            <p>Start a call and talk to the agent. The live transcript appears here.</p>
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
      <div style={{ marginTop: 14 }}>
        <LatencyBars turns={turns} heard={heard} emptyText="Per-turn response times appear after your first reply." />
      </div>
    </>
  )
}
