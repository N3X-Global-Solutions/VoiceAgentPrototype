import { Fragment, useState } from 'react'
import { Icon } from '@/components/Icon'
import { Badge } from '@/components/ui'
import { api, type Agent } from '@/lib/api'
import { useAutoScroll } from './useAutoScroll'

type ChatMessage = { role: 'user' | 'assistant'; content: string; meta?: string; tools?: string[] }

/** Text chat against the same prompt and tools as a call, without audio. */
export function ChatTest({ agent }: { agent: Agent }) {
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
        <span className="muted small">Same prompt and tools, no audio · ~₹0.01–0.05 / message</span>
        <Badge tone="brand">₹{spent.toFixed(3)} spent</Badge>
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
        {busy && (
          <div className="bubble agent typing" aria-label="Agent is typing">
            <i />
            <i />
            <i />
          </div>
        )}
      </div>
      {error && (
        <p className="error-text small" style={{ marginTop: 8 }}>
          {error}
        </p>
      )}
      <div className="composer">
        <input
          value={input}
          placeholder="Type what a caller would say…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button className="btn btn-primary btn-icon" onClick={send} disabled={busy || !input.trim()} title="Send" aria-label="Send">
          <Icon name="send" />
        </button>
        <button className="btn btn-secondary btn-icon" onClick={() => setMessages([])} title="Reset conversation" aria-label="Reset conversation">
          <Icon name="history" />
        </button>
      </div>
    </>
  )
}
