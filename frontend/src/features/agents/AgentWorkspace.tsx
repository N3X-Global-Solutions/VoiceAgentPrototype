import { useEffect, useState } from 'react'
import type { AgentTab, Navigate } from '@/app/routes'
import { Icon } from '@/components/Icon'
import { Avatar, Badge, Spinner, Tabs, type TabItem } from '@/components/ui'
import { AgentCallLogs } from '@/features/calls/AgentCallLogs'
import { TestPanel } from '@/features/testing/TestPanel'
import { api, type Agent, type AgentConfig, type Catalog, type Client, type Health } from '@/lib/api'
import { timeAgo } from '@/lib/format'
import { AgentConfigForm } from './config/AgentConfigForm'
import { CONFIG_TABS } from './config/tabs'

/** One agent: header, config sub-tabs on the left, playground on the right. */
export function AgentWorkspace({
  client,
  agent,
  catalog,
  health,
  tab,
  navigate,
  onSaved,
  onDirtyChange,
}: {
  client: Client
  agent: Agent
  catalog: Catalog
  health: Health | null
  tab: AgentTab
  navigate: Navigate
  onSaved: () => Promise<void>
  onDirtyChange: (dirty: boolean) => void
}) {
  const [name, setName] = useState(agent.name)
  const [config, setConfig] = useState<AgentConfig>(agent.config)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null)
  const [historyKey, setHistoryKey] = useState(0)
  const dirty = name !== agent.name || JSON.stringify(config) !== JSON.stringify(agent.config)
  const voice = catalog.voices.find((v) => v.id === agent.config.voice)
  const isInbound = health?.inbound_agent_id === agent.id

  useEffect(() => {
    onDirtyChange(dirty)
  }, [dirty, onDirtyChange])
  useEffect(() => () => onDirtyChange(false), [onDirtyChange])

  // Warn before closing the browser tab with unsaved edits.
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  useEffect(() => {
    if (!message || message.error) return
    const id = setTimeout(() => setMessage(null), 3500)
    return () => clearTimeout(id)
  }, [message])

  const save = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const saved = await api.updateAgent(agent.id, name.trim() || agent.name, config)
      await onSaved()
      setMessage({ text: `Saved. Calls now use v${saved.version}.` })
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true })
    } finally {
      setSaving(false)
    }
  }

  const tabs: TabItem<AgentTab>[] = [
    ...CONFIG_TABS.map((t) => (t.id === 'tools' ? { ...t, count: config.tools.length } : t)),
    { id: 'logs', label: 'Call logs', icon: 'history' },
  ]

  return (
    <>
      <div className="card agent-header">
        <Avatar name={agent.name} seed={agent.id} size="xl" />
        <div className="titles">
          <div className="eyebrow">
            <button className="row-link" onClick={() => navigate({ page: 'clients' })}>
              <Icon name="building" size={13} /> {client.name}
            </button>
            <span className="mono" title="Agent ID">
              {agent.id}
            </span>
          </div>
          <input className="title-input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Agent name" />
          <div className="meta">
            <Badge icon="hash">v{agent.version}</Badge>
            <Badge icon="globe">{catalog.languages[agent.config.language]}</Badge>
            <Badge icon="headphones">{voice ? `${voice.name} · ${voice.style}` : agent.config.voice}</Badge>
            <Badge icon="zap">{agent.config.turn_detection === 'fast' ? 'Fast turn-taking' : 'Robust turn-taking'}</Badge>
            {isInbound && (
              <Badge tone="brand" icon="inbound">
                Inbound agent
              </Badge>
            )}
            <span className="faint small">Updated {timeAgo(agent.updated_at)}</span>
          </div>
        </div>
      </div>

      <div className="workspace">
        <div className="workspace-main">
          <Tabs items={tabs} value={tab} onChange={(t) => navigate({ page: 'agent', clientId: client.id, agentId: agent.id, tab: t }, { replace: true })} />
          {tab === 'logs' ? (
            <AgentCallLogs agent={{ agentId: agent.id, agentName: agent.name, clientId: client.id, clientName: client.name }} refreshKey={historyKey} />
          ) : (
            <div className="card">
              <AgentConfigForm catalog={catalog} value={config} onChange={setConfig} tab={tab} />
            </div>
          )}
        </div>
        {/* Always mounted, so switching tabs never drops a live call. */}
        <TestPanel agent={agent} health={health} dirty={dirty} onCallEnded={() => setHistoryKey((k) => k + 1)} />
      </div>

      {(dirty || message) && (
        <div className="save-bar" role="status">
          {dirty && <span className="pulse-dot" />}
          <span className="grow">
            {message?.error ? (
              <span className="error">{message.text}</span>
            ) : dirty ? (
              'Unsaved changes. Calls keep using the saved version until you save.'
            ) : (
              <span className="row ok">
                <Icon name="check" size={14} /> {message?.text}
              </span>
            )}
          </span>
          {dirty && (
            <>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setName(agent.name)
                  setConfig(agent.config)
                  setMessage(null)
                }}
              >
                Discard
              </button>
              <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>
                {saving ? (
                  <>
                    <Spinner /> Saving…
                  </>
                ) : (
                  'Save changes'
                )}
              </button>
            </>
          )}
        </div>
      )}
    </>
  )
}
