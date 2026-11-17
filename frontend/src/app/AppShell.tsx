import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Icon, type IconName } from '@/components/Icon'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Avatar, EmptyState, Spinner } from '@/components/ui'
import { AgentsPage } from '@/features/agents/AgentsPage'
import { AgentWorkspace } from '@/features/agents/AgentWorkspace'
import { NewAgentPage } from '@/features/agents/NewAgentPage'
import { CallLogsPage } from '@/features/calls/CallLogsPage'
import { ClientsPage } from '@/features/clients/ClientsPage'
import { OverviewPage } from '@/features/overview/OverviewPage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { api, type Catalog, type Client, type Health } from '@/lib/api'
import { hashFor, viewFromHash, type Navigate, type View } from './routes'

const NAV: { page: View['page']; label: string; icon: IconName }[] = [
  { page: 'overview', label: 'Overview', icon: 'grid' },
  { page: 'agents', label: 'Agents', icon: 'bot' },
  { page: 'clients', label: 'Clients', icon: 'users' },
  { page: 'calls', label: 'Call logs', icon: 'history' },
]

/** Signed-in console: sidebar, top bar, and the page for the current URL hash. */
export function AppShell({ email, onSignOut }: { email: string; onSignOut: () => void }) {
  const [view, setViewState] = useState<View>(viewFromHash)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [clients, setClients] = useState<Client[] | null>(null)
  const [error, setError] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const dirtyRef = useRef(false)
  const onDirtyChange = useCallback((d: boolean) => {
    dirtyRef.current = d
  }, [])

  const navigate: Navigate = useCallback((next, opts) => {
    const hash = hashFor(next)
    const sameAgent = next.page === 'agent' && window.location.hash.startsWith(`#/agents/${next.clientId}/${next.agentId}/`)
    if (dirtyRef.current && !sameAgent && !confirm('You have unsaved changes. Leave without saving?')) return
    if (window.location.hash !== hash) {
      if (opts?.replace) history.replaceState(null, '', hash)
      else window.location.hash = hash
    }
    setViewState(next)
    setNavOpen(false)
    if (!sameAgent) window.scrollTo({ top: 0 })
  }, [])

  useEffect(() => {
    const onHash = () => setViewState(viewFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const reload = useCallback(async () => {
    try {
      const [c, h] = await Promise.all([api.clients(), api.health()])
      setClients(c)
      setHealth(h)
      setError('')
    } catch (e) {
      setError(`Can't reach the server (${e instanceof Error ? e.message : e}).`)
    }
  }, [])

  useEffect(() => {
    void api
      .catalog()
      .then(setCatalog)
      .catch(() => {})
    void reload()
  }, [reload])

  const list = clients ?? []
  const agentCount = list.reduce((n, c) => n + c.agents.length, 0)
  const current =
    view.page === 'agent'
      ? (() => {
          const client = list.find((c) => c.id === view.clientId)
          const agent = client?.agents.find((a) => a.id === view.agentId)
          return client && agent ? { client, agent } : null
        })()
      : null
  const activeNav = view.page === 'agent' || view.page === 'new' ? 'agents' : view.page

  const crumbs: { label: string; to?: View }[] =
    view.page === 'agent'
      ? [{ label: 'Agents', to: { page: 'agents' } }, { label: current?.client.name ?? '…', to: { page: 'clients' } }, { label: current?.agent.name ?? '…' }]
      : view.page === 'new'
        ? [{ label: 'Agents', to: { page: 'agents' } }, { label: 'Create agent' }]
        : [{ label: view.page === 'settings' ? 'Settings' : (NAV.find((n) => n.page === view.page)?.label ?? 'Overview') }]

  let content: ReactNode
  if (!clients || !catalog) {
    content = error ? null : (
      <div className="splash" style={{ minHeight: 320 }}>
        <Spinner />
      </div>
    )
  } else if (view.page === 'overview') {
    content = <OverviewPage email={email} clients={list} catalog={catalog} health={health} navigate={navigate} />
  } else if (view.page === 'agents') {
    content = <AgentsPage clients={list} catalog={catalog} health={health} navigate={navigate} />
  } else if (view.page === 'clients') {
    content = (
      <ClientsPage
        clients={list}
        navigate={navigate}
        onDelete={async (c) => {
          if (!confirm(`Delete ${c.name}? This also deletes its ${c.agents.length} agent(s) and their call history. This can't be undone.`)) return
          try {
            await api.deleteClient(c.id)
          } catch (e) {
            alert(e instanceof Error ? e.message : String(e))
          }
          await reload()
        }}
      />
    )
  } else if (view.page === 'calls') {
    content = <CallLogsPage clients={list} onOpenAgent={(r) => navigate({ page: 'agent', clientId: r.clientId, agentId: r.agentId, tab: 'logs' })} />
  } else if (view.page === 'settings') {
    content = <SettingsPage email={email} health={health} clients={list} navigate={navigate} onSignOut={onSignOut} />
  } else if (view.page === 'new') {
    content = (
      <NewAgentPage
        key={view.clientId ?? 'new'}
        clients={list}
        catalog={catalog}
        presetClientId={view.clientId}
        navigate={navigate}
        onCreated={async (clientId, agentId) => {
          await reload()
          navigate({ page: 'agent', clientId, agentId, tab: 'prompt' })
        }}
      />
    )
  } else if (current) {
    content = (
      <AgentWorkspace
        key={current.agent.id}
        client={current.client}
        agent={current.agent}
        catalog={catalog}
        health={health}
        tab={view.tab}
        navigate={navigate}
        onSaved={reload}
        onDirtyChange={onDirtyChange}
      />
    )
  } else {
    content = (
      <div className="card">
        <EmptyState
          icon="search"
          tone="gray"
          title="Agent not found"
          action={
            <button className="btn btn-secondary" onClick={() => navigate({ page: 'agents' })}>
              Back to agents
            </button>
          }
        >
          It may have been deleted along with its client.
        </EmptyState>
      </div>
    )
  }

  return (
    <div className={`shell${navOpen ? ' nav-open' : ''}`}>
      <div className="scrim" onClick={() => setNavOpen(false)} />
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate({ page: 'overview' })}>
          <span className="brand-mark">
            <Icon name="wave" size={18} />
          </span>
          <span className="brand-name">
            Voice Agent Studio
            <small>Conversational AI console</small>
          </span>
        </button>

        <button className="btn btn-primary create-btn" onClick={() => navigate({ page: 'new' })}>
          <Icon name="plus" size={16} /> Create agent
        </button>

        <nav className="nav">
          <span className="nav-label">Workspace</span>
          {NAV.map((n) => (
            <button key={n.page} className={`nav-item${activeNav === n.page ? ' active' : ''}`} onClick={() => navigate({ page: n.page } as View)}>
              <Icon name={n.icon} size={17} />
              {n.label}
              {n.page === 'agents' && clients && <span className="count">{agentCount}</span>}
              {n.page === 'clients' && clients && <span className="count">{list.length}</span>}
            </button>
          ))}
          <span className="nav-label">Account</span>
          <button className={`nav-item${view.page === 'settings' ? ' active' : ''}`} onClick={() => navigate({ page: 'settings' })}>
            <Icon name="settings" size={17} />
            Settings
          </button>
        </nav>

        <div className="sidebar-foot">
          <ThemeToggle />
          <div className="user-card">
            <Avatar name={email.split('@')[0].replace(/[._-]/g, ' ')} seed="admin" size="sm" />
            <span className="grow">
              <span className="email truncate" title={email}>
                {email}
              </span>
              <span className="role">Administrator</span>
            </span>
            <button className="btn btn-ghost btn-sm btn-icon" onClick={onSignOut} title="Sign out" aria-label="Sign out">
              <Icon name="logout" size={15} />
            </button>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="btn btn-ghost btn-icon menu-btn" onClick={() => setNavOpen(true)} aria-label="Open menu">
            <Icon name="menu" />
          </button>
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => (
              <span key={i}>
                {i > 0 && <span className="sep">/</span>}
                {c.to ? <button onClick={() => navigate(c.to!)}>{c.label}</button> : <span className="current truncate">{c.label}</span>}
              </span>
            ))}
          </nav>
        </header>

        <main className="page" key={view.page === 'agent' ? 'agent' : view.page}>
          {error && (
            <div className="banner tone-red">
              <Icon name="alert" /> <span className="grow">{error}</span>
              <button className="btn btn-secondary btn-sm" onClick={() => void reload()}>
                Retry
              </button>
            </div>
          )}
          {content}
        </main>
      </div>
    </div>
  )
}
