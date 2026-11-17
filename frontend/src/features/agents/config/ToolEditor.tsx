import { useState } from 'react'
import { Icon } from '@/components/Icon'
import { Badge, Field, IconChip } from '@/components/ui'
import type { HttpTool } from '@/lib/api'

/** One HTTP tool the agent can call mid-conversation. */
export function ToolEditor({ tool, onChange, onRemove }: { tool: HttpTool; onChange: (t: HttpTool) => void; onRemove: () => void }) {
  const [paramsText, setParamsText] = useState(JSON.stringify(tool.parameters, null, 2))
  const [headersText, setHeadersText] = useState(JSON.stringify(tool.headers, null, 2))
  const [jsonError, setJsonError] = useState('')

  const parseJson = (text: string, apply: (v: Record<string, never>) => void) => {
    try {
      apply(text.trim() ? JSON.parse(text) : {})
      setJsonError('')
    } catch {
      setJsonError('Invalid JSON')
    }
  }

  return (
    <div className="tool">
      <div className="tool-head">
        <IconChip icon="wrench" tone="green" size="sm" />
        <code className="grow">{tool.name || 'new_tool'}</code>
        <Badge tone={tool.method === 'GET' ? 'blue' : 'brand'}>{tool.method}</Badge>
        {jsonError && <Badge tone="red">{jsonError}</Badge>}
        <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onRemove} title="Remove tool">
          <Icon name="trash" size={14} />
        </button>
      </div>
      <div className="tool-body">
        <Field label="Name" hint="snake_case, e.g. check_order_status">
          <input value={tool.name} onChange={(e) => onChange({ ...tool, name: e.target.value })} placeholder="check_order_status" />
        </Field>
        <Field label="Method">
          <select value={tool.method} onChange={(e) => onChange({ ...tool, method: e.target.value as 'GET' | 'POST' })}>
            <option>POST</option>
            <option>GET</option>
          </select>
        </Field>
        <Field label="When should the agent use it?" wide>
          <input value={tool.description} onChange={(e) => onChange({ ...tool, description: e.target.value })} />
        </Field>
        <Field label="URL" wide>
          <input value={tool.url} onChange={(e) => onChange({ ...tool, url: e.target.value })} />
        </Field>
        <Field label="Parameters" hint="JSON Schema properties">
          <textarea
            className="mono"
            rows={5}
            value={paramsText}
            placeholder='{"order_id": {"type": "string"}}'
            onChange={(e) => {
              setParamsText(e.target.value)
              parseJson(e.target.value, (v) => onChange({ ...tool, parameters: v }))
            }}
          />
        </Field>
        <Field label="Headers" hint="JSON, e.g. an Authorization header">
          <textarea
            className="mono"
            rows={5}
            value={headersText}
            placeholder='{"Authorization": "Bearer ..."}'
            onChange={(e) => {
              setHeadersText(e.target.value)
              parseJson(e.target.value, (v) => onChange({ ...tool, headers: v }))
            }}
          />
        </Field>
        <Field label="Required parameters" hint="Comma separated" wide>
          <input
            value={tool.required.join(', ')}
            onChange={(e) =>
              onChange({
                ...tool,
                required: e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </Field>
      </div>
    </div>
  )
}
