import { useState, type ReactNode } from 'react'
import { initials } from '@/lib/format'
import { toneFor, type Tone } from '@/lib/colors'
import { Icon, type IconName } from './Icon'

// Shared UI primitives. Colour comes from tones (see lib/colors.ts and styles/tokens.css).

export function Dot({ tone = 'gray', pulse }: { tone?: Tone; pulse?: boolean }) {
  return <span className={`dot tone-${tone}${pulse ? ' pulse' : ''}`} aria-hidden="true" />
}

/** Small tinted label. `solid` fills it with the tone; `dot` adds a status dot. */
export function Badge({
  tone = 'gray',
  solid,
  dot,
  icon,
  children,
  title,
}: {
  tone?: Tone
  solid?: boolean
  dot?: boolean
  icon?: IconName
  children: ReactNode
  title?: string
}) {
  return (
    <span className={`badge tone-${tone}${solid ? ' solid' : ''}`} title={title}>
      {dot && <span className="dot" aria-hidden="true" />}
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  )
}

/** Rounded square with a tinted icon: used to colour-code sections, KPIs and lists. */
export function IconChip({ icon, tone = 'gray', size = 'md' }: { icon: IconName; tone?: Tone; size?: 'sm' | 'md' | 'lg' }) {
  return (
    <span className={`icon-chip tone-${tone} ${size}`}>
      <Icon name={icon} size={size === 'lg' ? 20 : size === 'sm' ? 14 : 16} />
    </span>
  )
}

export function Avatar({ name, seed, size = 'md', square }: { name: string; seed?: string; size?: 'sm' | 'md' | 'lg' | 'xl'; square?: boolean }) {
  return (
    <span className={`avatar tone-${toneFor(seed ?? name)} ${size}${square ? ' square' : ''}`} aria-hidden="true">
      {initials(name)}
    </span>
  )
}

export function Section({
  title,
  description,
  icon,
  tone = 'gray',
  children,
  aside,
  single,
}: {
  title: string
  description?: ReactNode
  icon?: IconName
  tone?: Tone
  children: ReactNode
  aside?: ReactNode
  single?: boolean
}) {
  return (
    <section className="section">
      <header className="section-head">
        {icon && <IconChip icon={icon} tone={tone} />}
        <div className="grow">
          <h3>{title}</h3>
          {description && <p>{description}</p>}
        </div>
        {aside}
      </header>
      <div className={`section-body${single ? ' single' : ''}`}>{children}</div>
    </section>
  )
}

export function Field({ label, hint, wide, children }: { label: ReactNode; hint?: ReactNode; wide?: boolean; children: ReactNode }) {
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
    <label className={`toggle${checked ? ' on' : ''}`}>
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

export function Stat({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className={`stat${tone ? ` tone-${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {tone && <span className="dot" aria-hidden="true" />}
        {value}
      </span>
    </div>
  )
}

export type TabItem<T extends string> = { id: T; label: string; icon?: IconName; count?: number }

export function Tabs<T extends string>({ items, value, onChange }: { items: TabItem<T>[]; value: T; onChange: (id: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          className={`tab${value === t.id ? ' active' : ''}`}
          onClick={() => onChange(t.id)}
        >
          {t.icon && <Icon name={t.icon} size={15} />}
          {t.label}
          {t.count != null && t.count > 0 && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function PageHead({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  )
}

export function EmptyState({
  icon,
  tone = 'brand',
  title,
  children,
  action,
}: {
  icon: IconName
  tone?: Tone
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <IconChip icon={icon} tone={tone} size="lg" />
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function CopyField({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="copy-field">
      <code title={value}>{value}</code>
      <button
        type="button"
        className={`btn btn-ghost btn-sm${copied ? ' copied' : ''}`}
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          })
        }}
      >
        <Icon name={copied ? 'check' : 'copy'} size={14} /> {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  )
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}
