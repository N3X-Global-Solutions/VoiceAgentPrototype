import { Badge, EmptyState, IconChip } from '@/components/ui'
import { CallTable } from './CallTable'
import { useCalls, type AgentRef } from './useCalls'

/** Call logs for one agent: the "Call logs" tab of the agent workspace. */
export function AgentCallLogs({ agent, refreshKey }: { agent: AgentRef; refreshKey: number }) {
  const calls = useCalls(agent.agentId, refreshKey)
  return (
    <div className="card">
      <div className="card-head">
        <IconChip icon="history" />
        <div className="grow">
          <h3>Call logs</h3>
          <p>Every test and phone call for this agent. Click a row for the transcript and usage.</p>
        </div>
        {calls && <Badge>{calls.length >= 50 ? 'Latest 50' : `${calls.length} call${calls.length === 1 ? '' : 's'}`}</Badge>}
      </div>
      {calls && calls.length === 0 ? (
        <EmptyState icon="headphones" title="No calls yet">
          Start a voice test in the playground. Each call's transcript, response times and cost appear here.
        </EmptyState>
      ) : (
        <CallTable calls={calls ?? []} agent={agent} compact />
      )}
    </div>
  )
}
