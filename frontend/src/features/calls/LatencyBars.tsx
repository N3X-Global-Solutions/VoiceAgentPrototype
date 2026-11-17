import type { LatencyTurn } from '@/lib/api'

/** Per-turn response time, split into speech recognition, AI reply and voice. */
export function LatencyBars({ turns, heard, emptyText }: { turns: LatencyTurn[]; heard?: number[]; emptyText?: string }) {
  if (turns.length === 0) {
    return <p className="muted small">{emptyText ?? 'Per-turn latency appears after the first reply.'}</p>
  }
  const scale = Math.max(1500, ...turns.map((t) => t.total_ms))
  return (
    <>
      <div className="turns" style={{ marginTop: 0 }}>
        {turns.map((t) => {
          const stt = t.transcript_ms ?? 0
          const llmEnd = t.llm_first_text_ms ?? stt
          const ttsEnd = t.tts_first_audio_ms ?? t.total_ms
          const pct = (v: number) => `${Math.max(0, (v / scale) * 100)}%`
          const h = heard?.[t.turn - 1]
          return (
            <div className="turn" key={t.turn}>
              <span className="turn-num">#{t.turn}</span>
              <div
                className="bar"
                title={`Recognition ${stt} ms · AI reply ${llmEnd - stt} ms · Voice ${ttsEnd - llmEnd} ms${t.pause_ms ? ` · pause ${t.pause_ms} ms before` : ''}`}
              >
                <span className="seg-stt" style={{ width: pct(stt) }} />
                <span className="seg-llm" style={{ width: pct(llmEnd - stt) }} />
                <span className="seg-tts" style={{ width: pct(ttsEnd - llmEnd) }} />
              </div>
              <span className="turn-val">
                <strong>{t.total_ms.toLocaleString()}</strong> ms
                {h != null && <span className="muted"> · heard {h}</span>}
              </span>
            </div>
          )
        })}
      </div>
      <div className="legend">
        <span>
          <i className="seg-stt" />
          Recognition
        </span>
        <span>
          <i className="seg-llm" />
          AI reply
        </span>
        <span>
          <i className="seg-tts" />
          Voice
        </span>
        {heard && <span>“heard” = your mic quiet → agent audio</span>}
      </div>
    </>
  )
}
