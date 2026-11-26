import { useState } from 'react'
import { Icon } from '@/components/Icon'
import { Modal } from '@/components/Modal'
import { Badge, CopyField, EmptyState, Field, IconChip, Spinner } from '@/components/ui'
import { api, type Client, type Health, type PhoneLine, type PhoneLineInput, type PhoneProvider } from '@/lib/api'
import { LINE_STATUS, PROVIDER_NAME } from '@/lib/phoneLines'

const EXOTEL_REGIONS = [
  { host: 'api.exotel.com', label: 'Singapore (api.exotel.com)' },
  { host: 'api.in.exotel.com', label: 'Mumbai (api.in.exotel.com)' },
]

/** A client's own Exotel/Plivo numbers: list, add, edit, re-check and remove. */
export function PhoneLinesModal({
  client,
  health,
  initialLineId,
  onClose,
  onChanged,
}: {
  client: Client
  health: Health | null
  initialLineId?: string
  onClose: () => void
  onChanged: () => Promise<void> | void
}) {
  const initial = initialLineId ? client.phone_lines.find((l) => l.id === initialLineId) : undefined
  // null = the list; 'new' = the add form; a line = its edit form.
  const [editing, setEditing] = useState<PhoneLine | 'new' | null>(initial ?? (client.phone_lines.length ? null : 'new'))
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const lines = client.phone_lines
  const agentName = (id: string) => client.agents.find((a) => a.id === id)?.name

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key)
    setNotice('')
    try {
      await fn()
      await onChanged()
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  if (editing) {
    return (
      <LineForm
        client={client}
        health={health}
        line={editing === 'new' ? null : editing}
        onCancel={() => (lines.length ? setEditing(null) : onClose())}
        onClose={onClose}
        onSaved={async (saved) => {
          await onChanged()
          // Fully working: back to the list. Otherwise the form shows what to fix.
          if (saved.status === 'ok') {
            setEditing(null)
            setNotice(`${saved.number} is connected.`)
          }
        }}
      />
    )
  }

  return (
    <Modal
      size="md"
      title="Phone numbers"
      subtitle={`${client.name} · the client's own Exotel or Plivo numbers`}
      leading={<IconChip icon="phone" tone="brand" />}
      onClose={onClose}
      footer={
        <>
          <span>Calls on these numbers are billed to the client's own provider account.</span>
          <button className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>
            <Icon name="plus" size={14} /> Add number
          </button>
        </>
      }
    >
      {notice && (
        <div className="banner" style={{ margin: '16px 20px 0' }}>
          <Icon name="alert" size={15} /> {notice}
        </div>
      )}
      {lines.length === 0 ? (
        <EmptyState icon="phone" title="No numbers yet">
          Add the client's Exotel or Plivo number so their agents call from it and answer calls to it.
        </EmptyState>
      ) : (
        <ul className="line-list">
          {lines.map((line) => {
            const st = LINE_STATUS[line.status]
            const answeredBy = agentName(line.inbound_agent_id)
            return (
              <li key={line.id}>
                <div className="line-main">
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div className="row" style={{ gap: 8 }}>
                      <span className="cell-title mono">{line.number}</span>
                      {line.label && <span className="muted small">{line.label}</span>}
                    </div>
                    <div className="row" style={{ gap: 6, marginTop: 6 }}>
                      <Badge tone="gray">{PROVIDER_NAME[line.provider]}</Badge>
                      <Badge tone={st.tone} dot title={line.status_detail}>
                        {st.label}
                      </Badge>
                      <span className="muted small">
                        <Icon name="inbound" size={12} /> {answeredBy ? `Answered by ${answeredBy}` : 'No agent answers calls'}
                      </span>
                    </div>
                  </div>
                  <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                    <button className="btn btn-ghost btn-sm" disabled={!!busy} onClick={() => run(`check-${line.id}`, () => api.checkPhoneLine(line.id).then(() => {}))}>
                      {busy === `check-${line.id}` ? <Spinner /> : <Icon name="activity" size={14} />} Check
                    </button>
                    <button className="btn btn-secondary btn-sm" disabled={!!busy} onClick={() => setEditing(line)}>
                      Edit
                    </button>
                    <button
                      className="btn btn-danger btn-sm btn-icon"
                      disabled={!!busy}
                      title={`Remove ${line.number}`}
                      onClick={() => {
                        const extra = line.provider === 'plivo' ? ' The number gets back the Plivo application it had before.' : ''
                        if (!confirm(`Remove ${line.number} from ${client.name}?${extra}`)) return
                        void run(`delete-${line.id}`, async () => {
                          const r = await api.deletePhoneLine(line.id)
                          if (r.warning) alert(r.warning)
                        })
                      }}
                    >
                      {busy === `delete-${line.id}` ? <Spinner /> : <Icon name="trash" size={14} />}
                    </button>
                  </div>
                </div>
                {line.status_detail && line.status !== 'ok' && <p className={`line-detail tone-${st.tone}`}>{line.status_detail}</p>}
                {line.provider === 'exotel' && <ExotelSetup line={line} />}
              </li>
            )
          })}
        </ul>
      )}
    </Modal>
  )
}

/** Exotel has no API to point a number at us: the client pastes this URL into their call flow. */
function ExotelSetup({ line }: { line: PhoneLine }) {
  if (!line.urls.voicebot) {
    return <p className="line-detail tone-amber">Set PUBLIC_BASE_URL to an https URL to get this number's Voicebot URL.</p>
  }
  return (
    <div className="line-setup">
      <span className="field-label">Voicebot applet URL</span>
      <CopyField value={line.urls.voicebot} />
      <span className="field-hint">
        In Exotel's App Bazaar, add a Voicebot applet with this URL to the flow, and set the flow on this ExoPhone. Use the same flow's ID for outbound calls.
      </span>
    </div>
  )
}

function emptyInput(client: Client): PhoneLineInput {
  return {
    provider: 'exotel',
    label: '',
    number: '',
    inbound_agent_id: client.agents[0]?.id ?? '',
    settings: { subdomain: 'api.exotel.com' },
    secrets: {},
    price_per_min: null,
    pulse_secs: null,
  }
}

function LineForm({
  client,
  health,
  line,
  onCancel,
  onClose,
  onSaved,
}: {
  client: Client
  health: Health | null
  line: PhoneLine | null
  onCancel: () => void
  onClose: () => void
  onSaved: (line: PhoneLine) => Promise<void>
}) {
  const [value, setValue] = useState<PhoneLineInput>(() =>
    line
      ? {
          provider: line.provider,
          label: line.label,
          number: line.number,
          inbound_agent_id: line.inbound_agent_id,
          settings: { ...line.settings },
          secrets: {}, // blank = keep the saved ones
          price_per_min: line.price_per_min,
          pulse_secs: line.pulse_secs,
        }
      : emptyInput(client),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  // After a save that didn't fully work, stay on the form and show why.
  const [result, setResult] = useState<PhoneLine | null>(null)

  const exotel = value.provider === 'exotel'
  const setSetting = (k: string, v: string) => setValue({ ...value, settings: { ...value.settings, [k]: v } })
  const setSecret = (k: string, v: string) => setValue({ ...value, secrets: { ...value.secrets, [k]: v } })
  const secretHint = (k: string) => (line?.secrets[k] ? `Saved (${line.secrets[k]}). Leave blank to keep it.` : undefined)
  const needSecret = (k: string) => !line?.secrets[k] && !value.secrets[k]?.trim()

  const required = exotel ? ['account_sid'] : ['auth_id']
  const valid =
    value.number.replace(/\D/g, '').length >= 7 &&
    required.every((k) => value.settings[k]?.trim()) &&
    !(exotel ? ['api_key', 'api_token'] : ['auth_token']).some(needSecret)

  const defaultRate = exotel ? health?.rates.exotel_per_min : health?.rates.plivo_per_min
  const defaultPulse = exotel ? health?.rates.exotel_pulse_secs : health?.rates.plivo_pulse_secs

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      const saved = line ? await api.updatePhoneLine(line.id, value) : await api.addPhoneLine(client.id, value)
      if (saved.status !== 'ok') setResult(saved)
      await onSaved(saved)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  if (result) {
    const st = LINE_STATUS[result.status]
    return (
      <Modal
        size="md"
        title={`${result.number} saved`}
        subtitle={client.name}
        leading={<IconChip icon="phone" tone={st.tone} />}
        onClose={onClose}
        footer={
          <>
            <span />
            <button className="btn btn-primary btn-sm" onClick={onCancel}>
              Done
            </button>
          </>
        }
      >
        <div className="credit-form">
          <div className={`banner tone-${st.tone}`} style={{ margin: 0 }}>
            <Icon name="alert" size={15} /> {result.status_detail || st.label}
          </div>
          {result.provider === 'exotel' && <ExotelSetup line={result} />}
        </div>
      </Modal>
    )
  }

  return (
    <Modal
      size="md"
      title={line ? `Edit ${line.number}` : 'Add a phone number'}
      subtitle={`${client.name} · their own ${exotel ? 'Exotel' : 'Plivo'} account`}
      leading={<IconChip icon="phone" tone="brand" />}
      onClose={onClose}
      footer={
        <>
          <span className="error-text">{error}</span>
          <span className="row" style={{ gap: 8, flexWrap: 'nowrap' }}>
            <button className="btn btn-ghost" onClick={onCancel}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !valid}>
              {saving ? (
                <>
                  <Spinner /> Checking…
                </>
              ) : (
                'Save and check'
              )}
            </button>
          </span>
        </>
      }
    >
      <div className="section-body line-form">
        <Field label="Provider" wide>
          <div className="segmented full">
            {(['exotel', 'plivo'] as PhoneProvider[]).map((p) => (
              <button
                key={p}
                className={value.provider === p ? 'active' : ''}
                disabled={!!line && line.provider !== p}
                onClick={() => setValue({ ...value, provider: p, settings: p === 'exotel' ? { subdomain: 'api.exotel.com' } : {}, secrets: {} })}
              >
                {PROVIDER_NAME[p]}
              </button>
            ))}
          </div>
        </Field>

        <Field label={exotel ? 'ExoPhone *' : 'Phone number *'} hint={exotel ? 'The virtual number, as Exotel shows it.' : 'With country code, e.g. +91 80 3123 4567.'}>
          <input value={value.number} onChange={(e) => setValue({ ...value, number: e.target.value })} placeholder={exotel ? '08047112233' : '+918031234567'} inputMode="tel" autoFocus />
        </Field>
        <Field label="Label" hint="Optional, e.g. “Support line”.">
          <input value={value.label} onChange={(e) => setValue({ ...value, label: e.target.value })} />
        </Field>

        <Field label="Answers calls to this number" wide hint="Outbound calls can use this number from any of the client's agents.">
          <select value={value.inbound_agent_id} onChange={(e) => setValue({ ...value, inbound_agent_id: e.target.value })}>
            <option value="">No agent (calls are declined)</option>
            {client.agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>

        {exotel ? (
          <>
            <Field label="Account SID *" hint="Exotel dashboard → API settings.">
              <input value={value.settings.account_sid ?? ''} onChange={(e) => setSetting('account_sid', e.target.value)} autoComplete="off" />
            </Field>
            <Field label="Region">
              <select value={value.settings.subdomain ?? 'api.exotel.com'} onChange={(e) => setSetting('subdomain', e.target.value)}>
                {EXOTEL_REGIONS.map((r) => (
                  <option key={r.host} value={r.host}>
                    {r.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={`API key${line ? '' : ' *'}`} hint={secretHint('api_key')}>
              <input type="password" value={value.secrets.api_key ?? ''} onChange={(e) => setSecret('api_key', e.target.value)} autoComplete="new-password" />
            </Field>
            <Field label={`API token${line ? '' : ' *'}`} hint={secretHint('api_token')}>
              <input type="password" value={value.secrets.api_token ?? ''} onChange={(e) => setSecret('api_token', e.target.value)} autoComplete="new-password" />
            </Field>
            <Field label="Flow (app) ID" wide hint="Needed for outbound calls: the number at the end of the flow's URL in App Bazaar. The flow needs a Voicebot applet; you get its URL after saving.">
              <input value={value.settings.flow_app_id ?? ''} onChange={(e) => setSetting('flow_app_id', e.target.value)} placeholder="123456" />
            </Field>
          </>
        ) : (
          <>
            <Field label="Auth ID *" hint="Plivo console → overview.">
              <input value={value.settings.auth_id ?? ''} onChange={(e) => setSetting('auth_id', e.target.value)} autoComplete="off" />
            </Field>
            <Field label={`Auth token${line ? '' : ' *'}`} hint={secretHint('auth_token')}>
              <input type="password" value={value.secrets.auth_token ?? ''} onChange={(e) => setSecret('auth_token', e.target.value)} autoComplete="new-password" />
            </Field>
            <div className="inline-alert wide" style={{ background: 'var(--blue-soft)', color: 'var(--blue-text)' }}>
              <Icon name="link" size={15} />
              <span style={{ flex: 1, minWidth: 0 }}>
                Saving connects the number for you: it creates an application in the client's Plivo account and links the number to it. Removing the number gives back the
                application it had before.
              </span>
            </div>
          </>
        )}

        <Field label="Line rate (₹ per minute)" hint={`Optional: for this number's cost in call logs. Default ₹${defaultRate ?? 0}.`}>
          <input
            type="number"
            min={0}
            step="0.01"
            value={value.price_per_min ?? ''}
            placeholder={String(defaultRate ?? '')}
            onChange={(e) => setValue({ ...value, price_per_min: e.target.value === '' ? null : Number(e.target.value) })}
          />
        </Field>
        <Field label="Billing pulse (seconds)" hint={`Default ${defaultPulse ?? 60}s.`}>
          <input
            type="number"
            min={1}
            step={1}
            value={value.pulse_secs ?? ''}
            placeholder={String(defaultPulse ?? '')}
            onChange={(e) => setValue({ ...value, pulse_secs: e.target.value === '' ? null : Number(e.target.value) })}
          />
        </Field>
      </div>
    </Modal>
  )
}
