import { Badge, EmptyState, IconChip } from '@/components/ui'
import { CallTable } from './CallTable'
import { useCalls } from './useCalls'

/** Call logs for one agent: the "Call logs" tab of the agent workspace. */
export function AgentCallLogs({ agentId, refreshKey }: { agentId: string; refreshKey: number }) {
  const calls = useCalls(agentId, refreshKey)
  return (
    <div className="card">
      <div className="card-head">
        <IconChip icon="history" tone="blue" />
        <div className="grow">
          <h3>Call logs</h3>
          <p>Every test and phone call for this agent. Click a row for the transcript and usage.</p>
        </div>
        {calls && <Badge tone="blue">{calls.length >= 50 ? 'Latest 50' : `${calls.length} call${calls.length === 1 ? '' : 's'}`}</Badge>}
      </div>
      {calls && calls.length === 0 ? (
        <EmptyState icon="headphones" title="No calls yet">
          Start a voice test from the playground on the right. Transcripts, latency and cost appear here.
        </EmptyState>
      ) : (
        <CallTable calls={calls ?? []} compact />
      )}
    </div>
  )
}
