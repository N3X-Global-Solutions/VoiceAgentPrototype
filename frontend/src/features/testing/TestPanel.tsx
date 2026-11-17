import { useState } from 'react'
import { Icon } from '@/components/Icon'
import type { Agent, Health } from '@/lib/api'
import { BrowserCall } from './BrowserCall'
import { ChatTest } from './ChatTest'
import { PhoneTest } from './PhoneTest'

/** The playground docked next to the agent config: voice, chat and phone tests. */
export function TestPanel({ agent, health, dirty, onCallEnded }: { agent: Agent; health: Health | null; dirty?: boolean; onCallEnded: () => void }) {
  const [tab, setTab] = useState<'browser' | 'chat' | 'phone'>('browser')

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
        {tab === 'browser' && <BrowserCall agent={agent} health={health} onEnded={onCallEnded} />}
        {tab === 'chat' && <ChatTest agent={agent} />}
        {tab === 'phone' && <PhoneTest agent={agent} health={health} onPlaced={onCallEnded} />}
      </div>
    </aside>
  )
}
