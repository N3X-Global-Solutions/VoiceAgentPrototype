// Formatting helpers shared across pages.

export function ms(v: number | null | undefined) {
  return v == null ? '–' : `${Math.round(v).toLocaleString()} ms`
}

export function inr(value: number, digits = 2) {
  return `₹${value.toFixed(digits)}`
}

export function duration(secs: number) {
  if (!secs) return '–'
  const s = Math.round(secs)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

export function initials(name: string) {
  return (
    name
      .split(/\s+/)
      .map((w) => w.replace(/[^\p{L}\p{N}]/gu, ''))
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join('') || '?'
  )
}

/** Backend timestamps are UTC but may lack a zone suffix. */
export function parseDate(value: string) {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`)
}

export function formatDate(value: string, withTime = false) {
  const d = parseDate(value)
  const sameYear = d.getFullYear() === new Date().getFullYear()
  const date = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: sameYear ? undefined : 'numeric' })
  return withTime ? `${date}, ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}` : date
}

export function timeAgo(value: string) {
  const secs = Math.round((Date.now() - parseDate(value).getTime()) / 1000)
  if (secs < 60) return 'just now'
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} d ago`
  return formatDate(value)
}

export function greeting(now = new Date()) {
  const h = now.getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

/** Green / amber / red for a latency against "ok" and "slow" thresholds. */
export function latencyTone(v: number | null | undefined, ok: number, slow: number): 'green' | 'amber' | 'red' | undefined {
  if (v == null) return undefined
  return v > slow ? 'red' : v > ok ? 'amber' : 'green'
}
