import { useMemo } from 'react'
import type { Navigate } from '@/app/routes'
import { Icon, type IconName } from '@/components/Icon'
import { Avatar, Badge, Dot, EmptyState, IconChip } from '@/components/ui'
import { CallTable } from '@/features/calls/CallTable'
import { agentIndex, useCalls } from '@/features/calls/useCalls'
import type { Catalog, Client, Health } from '@/lib/api'
import type { Tone } from '@/lib/colors'
import { greeting, inr, latencyTone, parseDate, timeAgo } from '@/lib/format'

const DAYS = 14
const HERO_WAVE = [30, 56, 84, 60, 100, 72, 46, 90, 64, 36, 70, 48, 24]

type Kpi = { label: string; value: string; unit?: string; sub: string; icon: IconName; status?: Tone }

/** Dashboard: KPIs, call volume + system status, recent calls + recently edited agents. */
export function OverviewPage({
  email,
  clients,
  catalog,
  health,
  navigate,
}: {
  email: string
  clients: Client[]
  catalog: Catalog | null
  health: Health | null
  navigate: Navigate
}) {
  const calls = useCalls(undefined, 0, 200, 15000)
  const agents = useMemo(() => agentIndex(clients), [clients])

  const stats = useMemo(() => {
    const list = calls ?? []
    const voice = list.filter((c) => c.latency_avg_ms != null)
    const finished = list.filter((c) => c.status === 'completed' || c.status === 'failed')
    const now = new Date()
    const today = now.toDateString()
    const days = Array.from({ length: DAYS }, (_, i) => {
      const d = new Date(now)
      d.setHours(0, 0, 0, 0)
      d.setDate(d.getDate() - (DAYS - 1 - i))
      return { date: d, count: 0 }
    })
    for (const c of list) {
      const key = parseDate(c.started_at).toDateString()
      const day = days.find((x) => x.date.toDateString() === key)
      if (day) day.count++
    }
    return {
      total: list.length,
      today: list.filter((c) => parseDate(c.started_at).toDateString() === today).length,
      avgLatency: voice.length ? voice.reduce((s, c) => s + (c.latency_avg_ms ?? 0), 0) / voice.length : null,
      successRate: finished.length ? (finished.filter((c) => c.status === 'completed').length / finished.length) * 100 : null,
      spend: list.reduce((s, c) => s + c.cost_inr, 0),
      minutes: list.reduce((s, c) => s + c.duration_secs, 0) / 60,
      days,
    }
  }, [calls])

  const first = email.split('@')[0].split(/[._-]/)[0]
  const name = first.charAt(0).toUpperCase() + first.slice(1)
  const head = <Hero name={name} navigate={navigate} />

  if (clients.length === 0) {
    return (
      <>
        {head}
        <div className="card">
          <EmptyState
            icon="bot"
            title="Create your first voice agent"
            action={
              <button className="btn btn-primary" onClick={() => navigate({ page: 'new' })}>
                <Icon name="plus" /> Create agent
              </button>
            }
          >
            Each agent belongs to a client and has its own prompt, language, voice and tools. Test it in the browser in seconds.
          </EmptyState>
        </div>
      </>
    )
  }

  const kpis: Kpi[] = [
    { label: 'Active agents', value: String(agents.size), sub: `Across ${clients.length} client${clients.length === 1 ? '' : 's'}`, icon: 'bot' },
    { label: 'Calls', value: calls ? String(stats.total) : '–', sub: `${stats.today} today · ${stats.minutes.toFixed(1)} min talked`, icon: 'phone' },
    {
      label: 'Avg response time',
      value: stats.avgLatency != null ? Math.round(stats.avgLatency).toLocaleString() : '–',
      unit: stats.avgLatency != null ? 'ms' : undefined,
      sub: 'Caller stops → agent speaks',
      icon: 'timer',
      status: latencyTone(stats.avgLatency, 1000, 1400),
    },
    {
      label: 'Success rate',
      value: stats.successRate != null ? stats.successRate.toFixed(0) : '–',
      unit: stats.successRate != null ? '%' : undefined,
      sub: 'Calls completed without error',
      icon: 'check',
    },
    { label: 'Usage cost', value: inr(stats.spend), sub: 'Estimated, all calls', icon: 'coins' },
  ]
  const maxDay = Math.max(1, ...stats.days.map((d) => d.count))
  const recentAgents = clients
    .flatMap((c) => c.agents.map((a) => ({ client: c, agent: a })))
    .sort((x, y) => parseDate(y.agent.updated_at).getTime() - parseDate(x.agent.updated_at).getTime())
    .slice(0, 5)
  const telephony = [health?.twilio_configured && 'Twilio', health?.exotel_configured && 'Exotel'].filter(Boolean).join(' · ')
  const inbound = health?.inbound_agent_id ? agents.get(health.inbound_agent_id) : undefined

  return (
    <>
      {head}

      <div className="kpis">
        {kpis.map((k) => (
          <div key={k.label} className="kpi">
            <div className="kpi-top">
              <span className="kpi-label row" style={{ gap: 7 }}>
                {k.label}
                {k.status && <Dot tone={k.status} />}
              </span>
              <IconChip icon={k.icon} size="sm" />
            </div>
            <div className="kpi-value">
              {k.value}
              {k.unit && <small>{k.unit}</small>}
            </div>
            <div className="kpi-sub">{k.sub}</div>
          </div>
        ))}
      </div>

      <div className="row-2-1">
        <div className="card">
          <div className="card-head">
            <div className="grow">
              <h3>Call volume</h3>
              <p>Calls per day, last {DAYS} days</p>
            </div>
            <Badge>{stats.days.reduce((s, d) => s + d.count, 0)} calls</Badge>
          </div>
          <div className="chart">
            <div className="chart-grid" role="img" aria-label={`Calls per day over the last ${DAYS} days`}>
              {stats.days.map((d) => (
                <div
                  key={d.date.toISOString()}
                  className={`daybar${d.count === 0 ? ' zero' : ''}`}
                  title={`${d.date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}: ${d.count} call${d.count === 1 ? '' : 's'}`}
                >
                  <span style={{ height: `${(d.count / maxDay) * 100}%` }} />
                </div>
              ))}
            </div>
            <div className="daybar-labels">
              {stats.days.map((d, i) => (
                <span key={i}>{i % 2 === 1 ? '' : d.date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}</span>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h3 className="grow">System status</h3>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate({ page: 'settings' })}>
              Settings
            </button>
          </div>
          <ul className="status-list">
            <li>
              <Dot tone={health?.provider_key_set ? 'green' : 'red'} />
              <span className="label">Voice AI engine</span>
              <Badge tone={health?.provider_key_set ? 'green' : 'red'}>{health?.provider_key_set ? 'Connected' : 'Not configured'}</Badge>
            </li>
            <li>
              <Dot tone={telephony ? 'green' : 'gray'} />
              <span className="label">Telephony</span>
              <span className="value">{telephony || 'Not configured'}</span>
            </li>
            <li>
              <Dot tone={health?.public_base_url?.startsWith('https://') ? 'green' : 'gray'} />
              <span className="label">Public URL</span>
              <span className="value truncate" style={{ maxWidth: 200 }}>
                {health?.public_base_url?.replace(/^https?:\/\//, '') || 'Not set'}
              </span>
            </li>
            <li>
              <Dot tone={inbound ? 'brand' : 'gray'} />
              <span className="label">Inbound agent</span>
              <span className="value truncate" style={{ maxWidth: 200 }}>
                {inbound ? inbound.agentName : 'None'}
              </span>
            </li>
          </ul>
        </div>
      </div>

      <div className="row-2-1">
        <div className="card">
          <div className="card-head">
            <div className="grow">
              <h3>Recent calls</h3>
              <p>Click a call to see its transcript and details</p>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate({ page: 'calls' })}>
              View all <Icon name="arrowRight" size={14} />
            </button>
          </div>
          {calls && calls.length === 0 ? (
            <EmptyState icon="headphones" title="No calls yet">
              Open an agent and start a browser test call.
            </EmptyState>
          ) : (
            <CallTable
              calls={(calls ?? []).slice(0, 6)}
              agents={agents}
              compact
              onOpenAgent={(r) => navigate({ page: 'agent', clientId: r.clientId, agentId: r.agentId, tab: 'logs' })}
            />
          )}
        </div>

        <div className="card">
          <div className="card-head">
            <h3 className="grow">Recently edited agents</h3>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate({ page: 'agents' })}>
              All agents
            </button>
          </div>
          <ul className="status-list">
            {recentAgents.map(({ client, agent }) => (
              <li key={agent.id} className="clickable" onClick={() => navigate({ page: 'agent', clientId: client.id, agentId: agent.id, tab: 'prompt' })}>
                <Avatar name={agent.name} seed={agent.id} square />
                <span className="label">
                  <span className="cell-title truncate" style={{ display: 'block' }}>
                    {agent.name}
                  </span>
                  <span className="cell-sub">
                    {client.name} · {catalog?.languages[agent.config.language] ?? agent.config.language}
                  </span>
                </span>
                <span className="value nowrap">{timeAgo(agent.updated_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  )
}

/** Greeting banner with an animated waveform. */
function Hero({ name, navigate }: { name: string; navigate: Navigate }) {
  return (
    <div className="hero">
      <div>
        <h1>
          {greeting()}, {name}
        </h1>
        <p>Here's how your voice agents are doing. Build a new agent, or jump into the logs to review recent conversations.</p>
        <div className="actions">
          <button className="btn btn-white" onClick={() => navigate({ page: 'new' })}>
            <Icon name="plus" /> Create agent
          </button>
          <button className="btn btn-glass" onClick={() => navigate({ page: 'calls' })}>
            <Icon name="history" /> View call logs
          </button>
        </div>
      </div>
      <div className="hero-art" aria-hidden="true">
        {HERO_WAVE.map((h, i) => (
          <span key={i} style={{ height: h, animationDelay: `${i * 0.11}s` }} />
        ))}
      </div>
    </div>
  )
}
