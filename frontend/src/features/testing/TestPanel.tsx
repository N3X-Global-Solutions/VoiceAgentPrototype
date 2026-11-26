import { useState } from 'react'
import { Icon } from '@/components/Icon'
import type { Agent, Catalog, Health, PhoneLine } from '@/lib/api'
import { PART_LABEL, missingKeys, providerName } from '@/lib/providers'
import { BrowserCall } from './BrowserCall'
import { ChatTest } from './ChatTest'
import { PhoneTest } from './PhoneTest'

/** The playground docked next to the agent config: voice, chat and phone tests. */
export function TestPanel({
  agent,
  catalog,
  health,
  phoneLines,
  dirty,
  onCallEnded,
  onChangeProviders,
}: {
  agent: Agent
  catalog: Catalog
  health: Health | null
  phoneLines: PhoneLine[]
  dirty?: boolean
  onCallEnded: () => void
  onChangeProviders: () => void
}) {
  const [tab, setTab] = useState<'browser' | 'chat' | 'phone'>('browser')
  // Calls use the saved config, so readiness follows the saved providers, not unsaved edits.
  const missing = missingKeys(catalog, health, agent.config)
  const parts = [
    ['stt', agent.config.stt_provider],
    ['llm', agent.config.llm_provider],
    ['tts', agent.config.tts_provider],
  ] as const
  // Providers of this agent that are low on (or out of) the credits entered on the Usage page.
  const lowCredit = [...new Set(parts.map(([, id]) => id))]
    .map((id) => ({ id, credit: health?.credits?.[id] }))
    .filter((x) => x.credit && x.credit.status !== 'ok')

  return (
    <aside className="card test-panel">
      <div className="card-head">
        <div style={{ minWidth: 0 }}>
          <div>
            <h3>Playground</h3>
            <p title={dirty ? 'Save to test your latest edits' : undefined}>{dirty ? `Saved v${agent.version} · edits not included` : `Testing v${agent.version}`}</p>
          </div>
        </div>
        <div className="segmented">
          <button className={tab === 'browser' ? 'active' : ''} onClick={() => setTab('browser')} title="Browser voice call">
            <Icon name="mic" size={14} /> Voice
          </button>
          <button className={tab === 'chat' ? 'active' : ''} onClick={() => setTab('chat')} title="Text chat">
            <Icon name="chat" size={14} /> Chat
          </button>
          <button className={tab === 'phone' ? 'active' : ''} onClick={() => setTab('phone')} title="Phone call">
            <Icon name="phone" size={14} /> Phone
          </button>
        </div>
      </div>
      <div className="panel-body">
        <div className="stack-strip" aria-label="Providers this test uses">
          {parts.map(([kind, id]) => (
            <span key={kind} className="stack-part" title={PART_LABEL[kind]}>
              {kind === 'stt' ? 'STT' : kind === 'llm' ? 'AI' : 'Voice'} <b>{providerName(catalog, id)}</b>
            </span>
          ))}
          <button type="button" className="btn btn-ghost btn-sm" onClick={onChangeProviders} title="Choose providers">
            <Icon name="sliders" size={13} /> Change
          </button>
        </div>
        {missing.length > 0 && (
          <div className="banner tone-red">
            <Icon name="alert" />
            <span className="grow">
              Add {missing.join(' and ')} to the server's .env to test with these providers.
            </span>
          </div>
        )}
        {lowCredit.map(({ id, credit }) => (
          <div key={id} className={`banner tone-${credit!.status === 'empty' ? 'red' : 'amber'}`}>
            <Icon name="coins" />
            <span className="grow">
              {providerName(catalog, id)} {credit!.status === 'empty' ? 'has no credit left by our count' : `is low on credit: ₹${credit!.remaining.toFixed(2)} left`}.
              {' '}
              <a href="#/usage">Usage & credits</a>
            </span>
          </div>
        ))}
        {tab === 'browser' && <BrowserCall agent={agent} health={health} ready={missing.length === 0} onEnded={onCallEnded} />}
        {tab === 'chat' && <ChatTest agent={agent} />}
        {tab === 'phone' && <PhoneTest agent={agent} health={health} lines={phoneLines} ready={missing.length === 0} onPlaced={onCallEnded} />}
      </div>
    </aside>
  )
}
