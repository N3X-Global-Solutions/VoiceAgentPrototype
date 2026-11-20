import type { ConfigTab } from '@/features/agents/config/tabs'

// The current page lives in the URL hash, so refresh, deep links and the back button work.

export type AgentTab = ConfigTab | 'logs'

export type View =
  | { page: 'overview' }
  | { page: 'agents' }
  | { page: 'clients' }
  | { page: 'calls' }
  | { page: 'usage' }
  | { page: 'settings' }
  | { page: 'new'; clientId?: string }
  | { page: 'agent'; clientId: string; agentId: string; tab: AgentTab }

const AGENT_TABS: AgentTab[] = ['prompt', 'providers', 'voice', 'speech', 'call', 'tools', 'logs']

export function viewFromHash(hash = window.location.hash): View {
  const [page, a, b, c] = hash.replace(/^#\/?/, '').split('/')
  switch (page) {
    case 'agents':
      if (a === 'new') return { page: 'new', clientId: b || undefined }
      if (a && b) return { page: 'agent', clientId: a, agentId: b, tab: AGENT_TABS.includes(c as AgentTab) ? (c as AgentTab) : 'prompt' }
      return { page: 'agents' }
    case 'agent': // links from before the redesign
      return a && b ? { page: 'agent', clientId: a, agentId: b, tab: 'prompt' } : { page: 'agents' }
    case 'new':
      return { page: 'new' }
    case 'clients':
      return { page: 'clients' }
    case 'calls':
      return { page: 'calls' }
    case 'usage':
      return { page: 'usage' }
    case 'settings':
      return { page: 'settings' }
    default:
      return { page: 'overview' }
  }
}

export function hashFor(view: View): string {
  switch (view.page) {
    case 'overview':
      return '#/'
    case 'new':
      return view.clientId ? `#/agents/new/${view.clientId}` : '#/agents/new'
    case 'agent':
      return `#/agents/${view.clientId}/${view.agentId}/${view.tab}`
    default:
      return `#/${view.page}`
  }
}

export type Navigate = (view: View, opts?: { replace?: boolean }) => void
