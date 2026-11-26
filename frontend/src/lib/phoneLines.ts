import type { LineStatus, PhoneProvider } from './api'
import type { Tone } from './colors'

export const PROVIDER_NAME: Record<PhoneProvider, string> = { exotel: 'Exotel', plivo: 'Plivo' }

export const LINE_STATUS: Record<LineStatus, { tone: Tone; label: string }> = {
  ok: { tone: 'green', label: 'Connected' },
  warning: { tone: 'amber', label: 'Check setup' },
  error: { tone: 'red', label: 'Not working' },
  unchecked: { tone: 'gray', label: 'Not checked' },
}
