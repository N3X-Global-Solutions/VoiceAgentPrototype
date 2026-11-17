import { useEffect, useState } from 'react'
import { api, type CallSession, type Client } from '@/lib/api'
import type { Tone } from '@/lib/colors'

export const STATUS_TONE: Record<string, Tone> = {
  completed: 'green',
  failed: 'red',
  active: 'blue',
  dialing: 'amber',
}

export const CHANNEL_LABEL: Record<string, string> = {
  browser: 'Browser',
  twilio: 'Twilio',
  exotel: 'Exotel',
  plivo: 'Plivo',
  telnyx: 'Telnyx',
  chat: 'Chat',
}

export type AgentRef = { agentId: string; agentName: string; clientId: string; clientName: string }

/** agent id → agent + client names, for labelling calls. */
export function agentIndex(clients: Client[]) {
  const map = new Map<string, AgentRef>()
  for (const c of clients) for (const a of c.agents) map.set(a.id, { agentId: a.id, agentName: a.name, clientId: c.id, clientName: c.name })
  return map
}

/** Polls the call list; agentId limits it to one agent. `null` until the first load. */
export function useCalls(agentId: string | undefined, refreshKey = 0, limit = 50, intervalMs = 5000) {
  const [calls, setCalls] = useState<CallSession[] | null>(null)
  useEffect(() => {
    let cancelled = false
    const load = () =>
      api
        .calls(agentId, limit)
        .then((c) => !cancelled && setCalls(c))
        .catch(() => {})
    void load()
    const id = setInterval(load, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [agentId, refreshKey, limit, intervalMs])
  return calls
}
