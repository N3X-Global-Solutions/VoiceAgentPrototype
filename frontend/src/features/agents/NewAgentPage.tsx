import { useState } from 'react'
import type { Navigate } from '@/app/routes'
import { Field, PageHead, Section, Spinner, Tabs } from '@/components/ui'
import { api, type AgentConfig, type Catalog, type Client, type ClientFields } from '@/lib/api'
import { AgentConfigForm } from './config/AgentConfigForm'
import { CONFIG_TABS, type ConfigTab } from './config/tabs'

/** Create an agent for an existing client, or a new client and its first agent. */
export function NewAgentPage({
  clients,
  catalog,
  presetClientId,
  navigate,
  onCreated,
}: {
  clients: Client[]
  catalog: Catalog
  presetClientId?: string
  navigate: Navigate
  onCreated: (clientId: string, agentId: string) => Promise<void>
}) {
  // App keys this page by presetClientId, so a different preset remounts it with fresh state.
  const [mode, setMode] = useState<'existing' | 'new'>(presetClientId || clients.length > 0 ? 'existing' : 'new')
  const [clientId, setClientId] = useState(presetClientId ?? clients[0]?.id ?? '')
  const [client, setClient] = useState<ClientFields>({ name: '', industry: '', contact_name: '', contact_phone: '', notes: '' })
  const [agentName, setAgentName] = useState('Voice agent')
  const [config, setConfig] = useState<AgentConfig>(catalog.defaults)
  const [tab, setTab] = useState<ConfigTab>('prompt')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const valid = agentName.trim() && (mode === 'existing' ? Boolean(clientId) : Boolean(client.name.trim()))

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      if (mode === 'existing') {
        const agent = await api.addAgent(clientId, agentName.trim(), config)
        await onCreated(clientId, agent.id)
      } else {
        const created = await api.createClient(client, { name: agentName.trim(), config })
        await onCreated(created.id, created.agents[0].id)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 940 }}>
      <PageHead eyebrow="Build" title="Create agent" description="Choose who the agent works for, then configure how it talks. You can change everything later." />

      <div className="card" style={{ marginBottom: 20 }}>
        <Section
          icon="building"
         
          title="Client"
          description="The business this agent answers calls for."
          aside={
            clients.length > 0 && (
              <div className="segmented">
                <button className={mode === 'existing' ? 'active' : ''} onClick={() => setMode('existing')}>
                  Existing client
                </button>
                <button className={mode === 'new' ? 'active' : ''} onClick={() => setMode('new')}>
                  New client
                </button>
              </div>
            )
          }
        >
          {mode === 'existing' ? (
            <Field label="Client" wide>
              <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.industry ? ` · ${c.industry}` : ''}
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <>
              <Field label="Client name *">
                <input value={client.name} autoFocus onChange={(e) => setClient({ ...client, name: e.target.value })} placeholder="Acme Store" />
              </Field>
              <Field label="Industry">
                <input value={client.industry} onChange={(e) => setClient({ ...client, industry: e.target.value })} placeholder="E-commerce" />
              </Field>
              <Field label="Contact name">
                <input value={client.contact_name} onChange={(e) => setClient({ ...client, contact_name: e.target.value })} />
              </Field>
              <Field label="Contact phone">
                <input value={client.contact_phone} onChange={(e) => setClient({ ...client, contact_phone: e.target.value })} inputMode="tel" />
              </Field>
              <Field label="Notes" wide>
                <textarea rows={2} value={client.notes} onChange={(e) => setClient({ ...client, notes: e.target.value })} />
              </Field>
            </>
          )}
        </Section>
        <Section icon="bot" title="Agent" description="A name your team will recognise, e.g. “Sales & support” or “Payment reminders”." single>
          <Field label="Agent name *">
            <input value={agentName} onChange={(e) => setAgentName(e.target.value)} />
          </Field>
        </Section>
      </div>

      <Tabs items={CONFIG_TABS} value={tab} onChange={setTab} />
      <div className="card">
        <AgentConfigForm catalog={catalog} value={config} onChange={setConfig} tab={tab} />
      </div>

      <div className="save-bar">
        <span className="pulse-dot brand" />
        <span className="grow">{error ? <span className="error">{error}</span> : 'New agent: review each tab, then create it.'}</span>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate({ page: 'agents' })}>
          Cancel
        </button>
        <button className="btn btn-primary btn-sm" onClick={submit} disabled={saving || !valid}>
          {saving ? (
            <>
              <Spinner /> Creating…
            </>
          ) : (
            'Create agent'
          )}
        </button>
      </div>
    </div>
  )
}
