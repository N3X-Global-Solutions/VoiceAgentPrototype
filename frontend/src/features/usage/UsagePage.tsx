import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Icon, type IconName } from '@/components/Icon'
import { Modal } from '@/components/Modal'
import { Dot, IconChip, PageHead, Spinner } from '@/components/ui'
import { api, type CreditEntry, type CreditState, type ProviderUsage, type UsagePart, type UsageReport } from '@/lib/api'
import { formatDate } from '@/lib/format'

// One colour per provider, in a fixed order, so a provider keeps its colour in every view.
const SERIES: Record<string, string> = {
  sarvam: 'var(--series-1)',
  navana: 'var(--series-2)',
  gnani: 'var(--series-3)',
  exotel: 'var(--series-4)',
  twilio: 'var(--series-5)',
}
const color = (id: string) => SERIES[id] ?? 'var(--border-strong)'

const PERIODS = [
  { days: 7, label: '7D', long: 'last 7 days' },
  { days: 30, label: '30D', long: 'last 30 days' },
  { days: 90, label: '90D', long: 'last 90 days' },
  { days: 0, label: 'All', long: 'all time' },
]

const COLUMNS: { part: UsagePart; label: string }[] = [
  { part: 'stt', label: 'Speech recognition' },
  { part: 'llm', label: 'AI model' },
  { part: 'tts', label: 'Voice' },
  { part: 'telephony', label: 'Phone line' },
]

const STATE_TONE: Record<CreditState, 'green' | 'amber' | 'red'> = { ok: 'green', low: 'amber', empty: 'red' }
const STATE_LABEL: Record<CreditState, string> = { ok: 'Healthy', low: 'Running low', empty: 'Out of credit' }

const TOPUP_PRESETS = [100, 500, 1000, 2000]

/** INR with Indian digit grouping and the sign in front ("-₹1.23"); sub-rupee amounts keep a third decimal. */
function money(v: number) {
  const a = Math.abs(v)
  const digits = a < 1 && a >= 0.0005 ? 3 : 2
  const text = `₹${a.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
  return v < -0.005 ? `-${text}` : text
}

function compact(n: number) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(Math.round(n))
}

function unitsText(p: ProviderUsage, part: UsagePart) {
  const u = p.units
  switch (part) {
    case 'stt':
      return `${(u.stt_secs / 60).toFixed(1)} min`
    case 'tts':
      return `${compact(u.tts_chars)} chars`
    case 'llm':
      return `${compact(u.input_tokens + u.output_tokens)} tokens`
    case 'telephony':
      return `${Math.round(u.phone_secs / 60)} min`
    default:
      return ''
  }
}

function daysLeftText(days: number | null, state: CreditState) {
  if (state === 'empty') return 'Top up now'
  if (days == null) return 'No recent spend'
  if (days > 365) return 'Over a year'
  if (days < 1) return 'Under a day'
  const d = Math.round(days)
  return `About ${d} day${d === 1 ? '' : 's'}`
}

/** Spend per provider over a period, and the credits left with each provider. */
export function UsagePage({ onCreditsChanged }: { onCreditsChanged: () => void }) {
  const [days, setDays] = useState(30)
  const [report, setReport] = useState<UsageReport | null>(null)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<{ provider: ProviderUsage; kind: CreditEntry['kind'] } | null>(null)
  const [historyFor, setHistoryFor] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setReport(await api.usage(days))
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [days])

  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), 30000)
    return () => clearInterval(timer)
  }, [load])

  const changed = async () => {
    await load()
    onCreditsChanged()
  }

  const period = PERIODS.find((p) => p.days === days)!
  const head = (
    <PageHead
      eyebrow="Workspace"
      title="Usage & credits"
      description="Track what every provider costs you and how much credit you have left."
      actions={
        <div className="segmented period-switch" role="group" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.days} className={days === p.days ? 'active' : ''} onClick={() => setDays(p.days)} title={p.long}>
              {p.label}
            </button>
          ))}
        </div>
      }
    />
  )

  if (!report) {
    return (
      <>
        {head}
        {error ? (
          <div className="banner tone-red">
            <Icon name="alert" /> <span className="grow">{error}</span>
          </div>
        ) : (
          <div className="splash" style={{ minHeight: 280 }}>
            <Spinner />
          </div>
        )}
      </>
    )
  }

  // Phone lines that aren't set up and never cost anything stay out of the way.
  const shown = report.providers.filter((p) => p.kind === 'voice_ai' || p.configured || p.spent > 0 || p.credit)
  const needsTopUp = shown.filter((p) => p.credit && p.credit.status !== 'ok')
  const history = shown.find((p) => p.id === historyFor)

  return (
    <div className="usage-page">
      {head}

      {error && (
        <div className="banner tone-red">
          <Icon name="alert" /> <span className="grow">Couldn't refresh: {error}</span>
        </div>
      )}

      {needsTopUp.length > 0 && (
        <div className={`banner usage-alert tone-${needsTopUp.some((p) => p.credit!.status === 'empty') ? 'red' : 'amber'}`}>
          <Icon name="alert" />
          <span className="grow">
            {needsTopUp
              .map((p) => `${p.name} ${p.credit!.status === 'empty' ? 'is out of credit' : `is running low (${money(p.credit!.remaining)} left)`}`)
              .join(' · ')}
            . Calls that use {needsTopUp.length === 1 ? 'it' : 'them'} may fail once the credit runs out.
          </span>
          <button className="btn btn-secondary btn-sm" onClick={() => setEditing({ provider: needsTopUp[0], kind: 'topup' })}>
            Top up {needsTopUp[0].name}
          </button>
        </div>
      )}

      <KpiRow report={report} providers={shown} periodLabel={period.long} />

      <div className="usage-row">
        <SpendChart report={report} providers={shown} />
        <ProviderShare report={report} providers={shown} />
      </div>

      <div className="card">
        <div className="card-head">
          <IconChip icon="coins" />
          <div className="grow">
            <h3>Credit wallets</h3>
            <p>What's left = the balance you entered + top-ups − spend since then. Re-enter the dashboard balance now and then to stay exact.</p>
          </div>
        </div>
        <div className="wallet-grid">
          {shown.map((p) => (
            <Wallet
              key={p.id}
              p={p}
              onTopUp={() => setEditing({ provider: p, kind: 'topup' })}
              onSetBalance={() => setEditing({ provider: p, kind: 'balance' })}
              onHistory={() => setHistoryFor(p.id)}
            />
          ))}
        </div>
      </div>

      <Breakdown providers={shown} periodLabel={period.long} />

      <p className="usage-foot">
        Costs are worked out from each call's measured usage and the rates in Settings (INR, before GST), so they can differ slightly from a provider's invoice.
        Rates marked as estimates in Settings are approximate.
      </p>

      {editing && (
        <CreditModal
          provider={editing.provider}
          initialKind={editing.kind}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await changed()
          }}
        />
      )}
      {history && (
        <HistoryModal
          p={history}
          onClose={() => setHistoryFor(null)}
          onChanged={changed}
          onAdd={() => {
            setHistoryFor(null)
            setEditing({ provider: history, kind: 'topup' })
          }}
        />
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- summary */

function KpiRow({ report, providers, periodLabel }: { report: UsageReport; providers: ProviderUsage[]; periodLabel: string }) {
  const total = report.total
  const prev = report.prev_total
  const change = prev != null && prev > 0.005 ? ((total - prev) / prev) * 100 : null
  const tracked = providers.filter((p) => p.credit)
  const left = tracked.reduce((s, p) => s + p.credit!.remaining, 0)
  const worst = tracked.some((p) => p.credit!.status === 'empty') ? 'red' : tracked.some((p) => p.credit!.status === 'low') ? 'amber' : null

  let trend: ReactNode = `Before GST, ${periodLabel}`
  if (change != null && Math.abs(change) >= 0.5) {
    const up = change > 0
    trend = (
      <span className={`trend ${up ? 'up' : 'down'}`}>
        <span className="arrow">
          <Icon name="arrowUpRight" size={12} />
        </span>
        {Math.abs(change) > 300 ? `Up from ${money(prev!)}` : `${Math.abs(change).toFixed(0)}% ${up ? 'more' : 'less'}`} than the period before
      </span>
    )
  }

  const kpis: { label: string; icon: IconName; value: string; sub: ReactNode; tone?: 'amber' | 'red' }[] = [
    { label: 'Total spend', icon: 'coins', value: money(total), sub: trend },
    { label: 'Calls', icon: 'phone', value: report.calls.toLocaleString('en-IN'), sub: `${report.call_minutes.toLocaleString('en-IN', { maximumFractionDigits: 1 })} min talked` },
    { label: 'Avg cost per call', icon: 'activity', value: report.calls ? money(total / report.calls) : '–', sub: report.call_minutes ? `${money(total / report.call_minutes)} per minute` : 'No calls yet' },
    {
      label: 'Credits left',
      icon: 'shield',
      value: tracked.length ? money(left) : '–',
      sub: tracked.length ? `Across ${tracked.length} tracked provider${tracked.length === 1 ? '' : 's'}` : 'Track a wallet below',
      tone: worst ?? undefined,
    },
  ]

  return (
    <div className="kpis usage-kpis">
      {kpis.map((k) => (
        <div key={k.label} className="kpi">
          <div className="kpi-top">
            <span className="kpi-label row" style={{ gap: 7 }}>
              {k.label}
              {k.tone && <Dot tone={k.tone} />}
            </span>
            <IconChip icon={k.icon} size="sm" />
          </div>
          <div className="kpi-value">{k.value}</div>
          <div className="kpi-sub">{k.sub}</div>
        </div>
      ))}
    </div>
  )
}

/** Spend per provider as a ranked list with share bars: the side panel next to the chart. */
function ProviderShare({ report, providers }: { report: UsageReport; providers: ProviderUsage[] }) {
  const total = report.total
  const rows = [...providers].sort((a, b) => b.spent - a.spent)
  return (
    <div className="card">
      <div className="card-head">
        <div className="grow">
          <h3>By provider</h3>
          <p>Share of total spend</p>
        </div>
      </div>
      <ul className="share-list">
        {rows.map((p) => {
          const pct = total > 0 ? (p.spent / total) * 100 : 0
          return (
            <li key={p.id}>
              <div className="share-top">
                <span className="swatch" style={{ background: color(p.id) }} />
                <span className="share-name">{p.name}</span>
                <span className="share-amount">{money(p.spent)}</span>
              </div>
              <div className="share-track">
                <span style={{ width: `${pct}%`, background: color(p.id) }} />
              </div>
              <div className="share-sub">
                <span>
                  {p.kind === 'phone' ? 'Phone line' : 'Voice AI'} · {p.calls} call{p.calls === 1 ? '' : 's'}
                </span>
                <span>{pct.toFixed(0)}%</span>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/* ---------------------------------------------------------------- wallets */

function Ring({ share, tone, label }: { share: number; tone: string; label: string }) {
  const r = 30
  const c = 2 * Math.PI * r
  return (
    <svg className={`ring tone-${tone}`} viewBox="0 0 76 76" width="76" height="76" role="img" aria-label={label}>
      <circle cx="38" cy="38" r={r} className="ring-track" />
      {share > 0 && <circle cx="38" cy="38" r={r} className="ring-value" strokeDasharray={`${c * share} ${c}`} transform="rotate(-90 38 38)" />}
      <text x="38" y="38" textAnchor="middle" dominantBaseline="central">
        {Math.round(share * 100)}%
      </text>
    </svg>
  )
}

function Wallet({ p, onTopUp, onSetBalance, onHistory }: { p: ProviderUsage; onTopUp: () => void; onSetBalance: () => void; onHistory: () => void }) {
  const c = p.credit
  const head = (
    <div className="wallet-head">
      <span className="swatch lg" style={{ background: color(p.id) }} />
      <div className="grow" style={{ minWidth: 0 }}>
        <div className="wallet-name">{p.name}</div>
        <div className="wallet-kind">
          {p.kind === 'phone' ? 'Phone line' : 'Voice AI'}
          {!p.configured && ' · not connected'}
        </div>
      </div>
      {c && (
        <span className={`status-pill tone-${STATE_TONE[c.status]}`}>
          <span className="dot" />
          {STATE_LABEL[c.status]}
        </span>
      )}
    </div>
  )

  if (!c) {
    return (
      <div className="wallet untracked">
        {head}
        <div className="wallet-body">
          <div className="ring-empty" aria-hidden="true">
            <Icon name="coins" size={20} />
          </div>
          <div className="wallet-figures">
            <span className="wallet-remaining muted-value">Not tracked</span>
            <span className="wallet-of">Add the balance from its dashboard</span>
          </div>
        </div>
        <div className="wallet-actions">
          <button className="btn btn-secondary btn-sm" onClick={onSetBalance}>
            <Icon name="plus" size={14} /> Track credits
          </button>
        </div>
      </div>
    )
  }

  const share = c.funded > 0 ? Math.max(0, Math.min(1, c.remaining / c.funded)) : 0
  return (
    <div className={`wallet${c.status !== 'ok' ? ` attention tone-${STATE_TONE[c.status]}` : ''}`}>
      {head}
      <div className="wallet-body">
        <Ring share={share} tone={STATE_TONE[c.status]} label={`${Math.round(share * 100)}% of credits left`} />
        <div className="wallet-figures">
          <span className="wallet-remaining">{money(c.remaining)}</span>
          <span className="wallet-of">left of {money(c.funded)}</span>
        </div>
      </div>
      <dl className="wallet-facts">
        <div>
          <dt>Runway</dt>
          <dd>{daysLeftText(c.days_left, c.status)}</dd>
          <dd className="sub">{c.per_day > 0 ? `${money(c.per_day)} per day` : 'Last 7 days'}</dd>
        </div>
        <div>
          <dt>Used</dt>
          <dd>{money(c.used)}</dd>
          <dd className="sub">since {formatDate(c.since)}</dd>
        </div>
      </dl>
      <div className="wallet-actions">
        <button className="btn btn-primary btn-sm" onClick={onTopUp}>
          <Icon name="plus" size={14} /> Top up
        </button>
        <button className="btn btn-secondary btn-sm" onClick={onSetBalance}>
          Update balance
        </button>
        <button className="btn btn-ghost btn-sm btn-icon" onClick={onHistory} title="Credit history" aria-label={`${p.name} credit history`}>
          <Icon name="history" size={15} />
        </button>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- daily chart */

/** Daily spend, stacked by provider. Hover or focus a day for its split; the table below has exact totals. */
function SpendChart({ report, providers }: { report: UsageReport; providers: ProviderUsage[] }) {
  const [hover, setHover] = useState<number | null>(null)
  const ids = providers.map((p) => p.id)
  const days = report.daily
  const totals = useMemo(() => days.map((d) => Object.values(d.by_provider).reduce((s, v) => s + v, 0)), [days])
  const max = Math.max(0, ...totals)
  const peak = totals.indexOf(max)
  const labelEvery = Math.max(1, Math.ceil(days.length / 8))
  const active = hover != null ? days[hover] : null

  return (
    <div className="card usage-chart-card">
      <div className="card-head">
        <div className="grow">
          <h3>Daily spend</h3>
          <p>{max > 0 ? `Split by provider · busiest day ${formatDate(days[peak].date)}, ${money(max)}` : 'Each bar is one day, split by provider'}</p>
        </div>
      </div>
      {max === 0 ? (
        <div className="chart-empty">
          <IconChip icon="activity" size="lg" />
          <p>No spend in this period yet.</p>
        </div>
      ) : (
        <div className="spend-chart">
          <div className="y-axis" aria-hidden="true">
            <span style={{ top: 0 }}>{money(max)}</span>
            <span style={{ top: '50%' }}>{money(max / 2)}</span>
            <span style={{ top: '100%' }}>₹0</span>
          </div>
          <div className="bars" onMouseLeave={() => setHover(null)}>
            {days.map((d, i) => (
              <div
                key={d.date}
                className={`sbar${totals[i] ? '' : ' zero'}${hover === i ? ' on' : ''}`}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                tabIndex={0}
                aria-label={`${formatDate(d.date)}: ${money(totals[i])}`}
              >
                <div className="sbar-fill" style={{ height: `${(totals[i] / max) * 100}%` }}>
                  {ids
                    .filter((id) => d.by_provider[id])
                    .map((id) => (
                      <span key={id} style={{ flexGrow: d.by_provider[id], background: color(id) }} />
                    ))}
                </div>
              </div>
            ))}
            {active && hover != null && (
              <div className={`chart-tip${hover > days.length * 0.7 ? ' flip' : ''}`} style={{ left: `${((hover + 0.5) / days.length) * 100}%` }}>
                <div className="tip-head">
                  <span>{formatDate(active.date)}</span>
                  <b>{money(totals[hover])}</b>
                </div>
                {ids
                  .filter((id) => active.by_provider[id])
                  .map((id) => (
                    <span key={id} className="tip-row">
                      <span className="swatch" style={{ background: color(id) }} />
                      <span className="grow">{providers.find((p) => p.id === id)?.name}</span>
                      {money(active.by_provider[id])}
                    </span>
                  ))}
                {!totals[hover] && <span className="muted">No spend</span>}
              </div>
            )}
          </div>
          <div className="x-axis" aria-hidden="true">
            {days.map((d, i) => (
              <span key={d.date}>{i % labelEvery === 0 ? formatDate(d.date) : ''}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- breakdown table */

function Breakdown({ providers, periodLabel }: { providers: ProviderUsage[]; periodLabel: string }) {
  const rows = [...providers].sort((a, b) => b.spent - a.spent)
  const total = rows.reduce((s, p) => s + p.spent, 0)
  const colTotal = (part: UsagePart) => rows.reduce((s, p) => s + (p.by_part[part] ?? 0), 0)
  const other = colTotal('other')

  return (
    <div className="card">
      <div className="card-head">
        <div className="grow">
          <h3>Cost breakdown</h3>
          <p>By provider and service, {periodLabel}</p>
        </div>
      </div>
      <div className="table-wrap">
        <table className="breakdown">
          <thead>
            <tr>
              <th>Provider</th>
              {COLUMNS.map((c) => (
                <th key={c.part} className="num">
                  {c.label}
                </th>
              ))}
              <th className="num">Calls</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td>
                  <span className="provider-cell">
                    <span className="swatch lg" style={{ background: color(p.id) }} />
                    <span>
                      <span className="cell-title">{p.name}</span>
                      <span className="cell-sub">{p.kind === 'phone' ? 'Phone line' : 'Voice AI'}</span>
                    </span>
                  </span>
                </td>
                {COLUMNS.map((c) => {
                  const v = p.by_part[c.part]
                  return (
                    <td key={c.part} className="num">
                      {v ? (
                        <>
                          <span className="amount">{money(v)}</span>
                          <span className="cell-sub">{unitsText(p, c.part)}</span>
                        </>
                      ) : (
                        <span className="faint">–</span>
                      )}
                    </td>
                  )
                })}
                <td className="num">
                  <span className="amount">{p.calls || <span className="faint">–</span>}</span>
                  {p.tests > 0 && <span className="cell-sub">+{p.tests} text</span>}
                </td>
                <td className="num">
                  <span className="amount strong">{money(p.spent)}</span>
                  <span className="mini-share" title={`${total ? Math.round((p.spent / total) * 100) : 0}% of spend`}>
                    <span style={{ width: `${total ? (p.spent / total) * 100 : 0}%`, background: color(p.id) }} />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>
                <span className="cell-title">Total</span>
                {other > 0 && <span className="cell-sub">incl. {money(other)} from older calls</span>}
              </td>
              {COLUMNS.map((c) => (
                <td key={c.part} className="num">
                  <span className="amount">{money(colTotal(c.part))}</span>
                </td>
              ))}
              <td className="num" />
              <td className="num">
                <span className="amount strong">{money(total)}</span>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- dialogs */

function CreditModal({
  provider,
  initialKind,
  onClose,
  onSaved,
}: {
  provider: ProviderUsage
  initialKind: CreditEntry['kind']
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const current = provider.credit
  const [kind, setKind] = useState<CreditEntry['kind']>(current ? initialKind : 'balance')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [alertBelow, setAlertBelow] = useState(current?.alert_below != null ? String(current.alert_below) : '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const value = Number(amount)
  const valid = amount.trim() !== '' && Number.isFinite(value) && value >= 0 && (kind === 'balance' || value > 0)
  const after = !valid ? null : kind === 'balance' ? value : (current?.remaining ?? 0) + value

  const save = async () => {
    if (!valid) return
    setSaving(true)
    setError('')
    try {
      await api.addCredit(provider.id, kind, value, note)
      const alertValue = alertBelow.trim() === '' ? null : Number(alertBelow)
      if (alertValue !== (current?.alert_below ?? null) && (alertValue == null || Number.isFinite(alertValue))) {
        await api.setCreditAlert(provider.id, alertValue)
      }
      await onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  return (
    <Modal
      size="sm"
      title={current ? `${provider.name} credits` : `Track ${provider.name} credits`}
      subtitle={current ? `${money(current.remaining)} left now` : "Start from the balance on the provider's dashboard"}
      leading={<span className="swatch xl" style={{ background: color(provider.id) }} />}
      onClose={onClose}
      footer={
        <>
          <span>{after != null ? <>New balance: <b className="text-strong">{money(after)}</b></> : null}</span>
          <span className="row" style={{ gap: 8, flexWrap: 'nowrap' }}>
            <button className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!valid || saving} onClick={() => void save()}>
              {saving ? 'Saving…' : kind === 'topup' ? 'Add top-up' : 'Save balance'}
            </button>
          </span>
        </>
      }
    >
      <form
        className="credit-form"
        onSubmit={(e) => {
          e.preventDefault()
          void save()
        }}
      >
        {current && (
          <div className="segmented full" role="group" aria-label="What are you entering?">
            <button type="button" className={kind === 'topup' ? 'active' : ''} onClick={() => setKind('topup')}>
              <Icon name="plus" size={14} /> I added credits
            </button>
            <button type="button" className={kind === 'balance' ? 'active' : ''} onClick={() => setKind('balance')}>
              <Icon name="sliders" size={14} /> Correct the balance
            </button>
          </div>
        )}

        <label className="field">
          <span className="field-label">{kind === 'topup' ? 'Amount added' : 'Balance on the dashboard right now'}</span>
          <span className="money-input">
            <span className="prefix">₹</span>
            <input type="number" min={0} step="0.01" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} autoFocus placeholder="0.00" />
          </span>
          <span className="field-hint">
            {kind === 'topup' ? 'Added to what is left now.' : 'Spend is counted from this moment. Use it whenever our figure drifts from the dashboard.'}
          </span>
        </label>
        {kind === 'topup' && (
          <div className="chips" role="group" aria-label="Quick amounts">
            {TOPUP_PRESETS.map((v) => (
              <button type="button" key={v} className={`chip${value === v ? ' on' : ''}`} onClick={() => setAmount(String(v))}>
                ₹{v.toLocaleString('en-IN')}
              </button>
            ))}
          </div>
        )}

        <label className="field">
          <span className="field-label">
            Note <span className="faint">(optional)</span>
          </span>
          <input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="e.g. invoice number, free credits" />
        </label>

        <div className="alert-row">
          <IconChip icon="alert" size="sm" tone="amber" />
          <div className="grow">
            <span className="alert-title">Low-credit warning</span>
            <span className="field-hint">Leave empty to warn at 20% left</span>
          </div>
          <span className="money-input sm">
            <span className="prefix">₹</span>
            <input type="number" min={0} step="1" inputMode="decimal" value={alertBelow} onChange={(e) => setAlertBelow(e.target.value)} placeholder="Auto" aria-label="Warn below (₹)" />
          </span>
        </div>

        {error && (
          <div className="banner tone-red" style={{ margin: 0 }}>
            <Icon name="alert" /> <span className="grow">{error}</span>
          </div>
        )}
        <button type="submit" hidden />
      </form>
    </Modal>
  )
}

function HistoryModal({ p, onClose, onChanged, onAdd }: { p: ProviderUsage; onClose: () => void; onChanged: () => Promise<void>; onAdd: () => void }) {
  return (
    <Modal
      size="sm"
      title={`${p.name} credit history`}
      subtitle={p.credit ? `${money(p.credit.remaining)} left now` : undefined}
      leading={<span className="swatch xl" style={{ background: color(p.id) }} />}
      onClose={onClose}
      footer={
        <>
          <span>Only the latest balance and the top-ups after it count.</span>
          <button className="btn btn-primary btn-sm" onClick={onAdd}>
            <Icon name="plus" size={14} /> Top up
          </button>
        </>
      }
    >
      {p.entries.length === 0 ? (
        <p className="muted" style={{ padding: 20, margin: 0 }}>
          No entries yet.
        </p>
      ) : (
        <ul className="history-list">
          {p.entries.map((e) => (
            <li key={e.id}>
              <IconChip icon={e.kind === 'topup' ? 'plus' : 'sliders'} size="sm" tone={e.kind === 'topup' ? 'green' : 'gray'} />
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="cell-title">{e.kind === 'topup' ? `Top-up of ${money(e.amount_inr)}` : `Balance set to ${money(e.amount_inr)}`}</div>
                <div className="cell-sub truncate">
                  {formatDate(e.at, true)}
                  {e.note && ` · ${e.note}`}
                </div>
              </div>
              <button
                className="btn btn-ghost btn-sm btn-icon"
                title="Delete this entry"
                aria-label="Delete this entry"
                onClick={async () => {
                  if (!confirm('Delete this credit entry? What is left is recalculated without it.')) return
                  try {
                    await api.deleteCredit(e.id)
                    await onChanged()
                  } catch (err) {
                    alert(err instanceof Error ? err.message : String(err))
                  }
                }}
              >
                <Icon name="trash" size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}
