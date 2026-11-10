import { useEffect, useState, type ReactNode } from 'react'

// Small shared UI pieces. Icons are inline SVG (Lucide-style strokes) so no icon package is needed.

const PATHS: Record<string, ReactNode> = {
  phone: (
    <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z" />
  ),
  phoneOff: (
    <>
      <path d="M10.7 13.3a16 16 0 0 0 3.4 2.6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.4 19.4 0 0 1-3.3-2.6" />
      <path d="M5.2 13.4A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8" />
      <path d="M22 2 2 22" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4" />
    </>
  ),
  chat: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  trash: <path d="M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />,
  back: <path d="M19 12H5M12 19l-7-7 7-7" />,
  wrench: (
    <path d="M14.7 6.3a4 4 0 0 0 5 5L22 13.6 13.6 22l-2.3-2.3a4 4 0 0 0-5-5L2 10.4 10.4 2l2.3 2.3a4 4 0 0 0 2 2z" />
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20" />
    </>
  ),
  zap: <path d="M13 2 3 14h9l-1 8 10-12h-9z" />,
  wave: <path d="M2 12h2M6 8v8M10 4v16M14 7v10M18 10v4M22 12h0" />,
  history: (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </>
  ),
  check: <path d="M20 6 9 17l-5-5" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  monitor: (
    <>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </>
  ),
  x: <path d="M18 6 6 18M6 6l12 12" />,
  sparkle: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" />,
  send: <path d="m22 2-7 20-4-9-9-4zM22 2 11 13" />,
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  building: (
    <>
      <rect x="4" y="2" width="16" height="20" rx="2" />
      <path d="M9 22v-4h6v4M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01" />
    </>
  ),
}

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  )
}

export function Badge({ tone = 'neutral', children }: { tone?: 'neutral' | 'green' | 'amber' | 'red' | 'blue'; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function Section({
  icon,
  title,
  description,
  children,
  aside,
}: {
  icon: IconName
  title: string
  description?: string
  children: ReactNode
  aside?: ReactNode
}) {
  return (
    <section className="section">
      <header className="section-head">
        <div className="section-icon">
          <Icon name={icon} />
        </div>
        <div className="grow">
          <h3>{title}</h3>
          {description && <p className="muted">{description}</p>}
        </div>
        {aside}
      </header>
      <div className="section-body">{children}</div>
    </section>
  )
}

export function Field({
  label,
  hint,
  wide,
  children,
}: {
  label: ReactNode
  hint?: ReactNode
  wide?: boolean
  children: ReactNode
}) {
  return (
    <label className={`field${wide ? ' wide' : ''}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-track" aria-hidden="true">
        <span className="toggle-thumb" />
      </span>
      <span>
        <span className="toggle-label">{label}</span>
        {hint && <span className="field-hint">{hint}</span>}
      </span>
    </label>
  )
}

export function Stat({ label, value, tone }: { label: string; value: string; tone?: 'green' | 'amber' | 'red' }) {
  return (
    <div className={`stat${tone ? ` stat-${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  )
}

export function latencyTone(ms: number | null | undefined, ok: number, slow: number): 'green' | 'amber' | 'red' | undefined {
  if (ms == null) return undefined
  return ms > slow ? 'red' : ms > ok ? 'amber' : 'green'
}

export function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')
}

export type Theme = 'system' | 'light' | 'dark'

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : 'system'
  } catch {
    return 'system'
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
    try {
      if (theme === 'system') localStorage.removeItem('theme')
      else localStorage.setItem('theme', theme)
    } catch {
      /* storage blocked: theme still applies for this visit */
    }
  }, [theme])

  const options: [Theme, IconName, string][] = [
    ['light', 'sun', 'Light'],
    ['system', 'monitor', 'System'],
    ['dark', 'moon', 'Dark'],
  ]
  return (
    <div className="segmented theme-toggle" role="radiogroup" aria-label="Theme">
      {options.map(([value, icon, label]) => (
        <button
          key={value}
          role="radio"
          aria-checked={theme === value}
          className={theme === value ? 'active' : ''}
          onClick={() => setTheme(value)}
          title={`${label} theme`}
        >
          <Icon name={icon} size={14} />
        </button>
      ))}
    </div>
  )
}
