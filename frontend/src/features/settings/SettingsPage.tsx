import type { Navigate } from '@/app/routes'
import { Icon } from '@/components/Icon'
import { ThemeToggle } from '@/components/ThemeToggle'
import { Avatar, Badge, CopyField, Dot, Field, IconChip, PageHead, Section } from '@/components/ui'
import { agentIndex } from '@/features/calls/useCalls'
import type { Client, Health } from '@/lib/api'

/** Account, appearance, integrations status, webhook URLs and credit guards. */
export function SettingsPage({
  email,
  health,
  clients,
  navigate,
  onSignOut,
}: {
  email: string
  health: Health | null
  clients: Client[]
  navigate: Navigate
  onSignOut: () => void
}) {
  // Telephony providers must reach the server over the internet, so prefer the configured public URL.
  const base = (health?.public_base_url || window.location.origin).replace(/\/$/, '')
  const wsBase = base.replace(/^http/, 'ws')
  const inbound = health?.inbound_agent_id ? agentIndex(clients).get(health.inbound_agent_id) : undefined

  const checks: [boolean | undefined, string, string][] = [
    [health?.provider_key_set, 'Voice AI engine', health?.provider_key_set ? 'API key configured' : "Not configured: add the provider API key to the server's .env"],
    [health?.public_base_url?.startsWith('https://'), 'Public URL', health?.public_base_url || 'Set PUBLIC_BASE_URL (needed for phone calls)'],
    [health?.twilio_configured, 'Twilio', health?.twilio_configured ? 'Account and number configured' : 'Not configured'],
    [health?.exotel_configured, 'Exotel', health?.exotel_configured ? 'Account, ExoPhone and flow configured' : 'Not configured'],
  ]

  return (
    <div style={{ maxWidth: 900 }}>
      <PageHead eyebrow="Account" title="Settings" description="Your account, appearance and the server's configuration." />

      <div className="stack">
        <div className="card">
          <Section icon="user" title="Account" description="You are signed in as the workspace administrator.">
            <div className="wide row" style={{ gap: 14 }}>
              <Avatar name={email.split('@')[0].replace(/[._-]/g, ' ')} seed="admin" size="lg" />
              <div className="grow">
                <div className="cell-title">{email}</div>
                <Badge icon="shield">
                  Administrator
                </Badge>
              </div>
              <button className="btn btn-secondary" onClick={onSignOut}>
                <Icon name="logout" /> Sign out
              </button>
            </div>
            <p className="wide muted small">
              Credentials are set on the server with <code>ADMIN_EMAIL</code> and <code>ADMIN_PASSWORD</code>. Changing the password signs every session out.
            </p>
          </Section>
          <Section icon="sun" title="Appearance" description="Light, dark, or follow your system setting." single>
            <div style={{ maxWidth: 320 }}>
              <ThemeToggle labels />
            </div>
          </Section>
        </div>

        <div className="card">
          <div className="card-head">
            <IconChip icon="server" />
            <div className="grow">
              <h3>Integrations</h3>
              <p>Read from the server's environment. Edit .env on the server and restart to change them.</p>
            </div>
          </div>
          <ul className="status-list">
            {checks.map(([ok, label, value]) => (
              <li key={label}>
                <Dot tone={ok ? 'green' : 'gray'} />
                <span className="label">{label}</span>
                <span className="value truncate" style={{ maxWidth: 380 }}>
                  {value}
                </span>
              </li>
            ))}
            <li>
              <Dot tone={inbound ? 'brand' : 'gray'} />
              <span className="label">Inbound agent</span>
              {inbound ? (
                <button className="btn btn-soft btn-sm" onClick={() => navigate({ page: 'agent', clientId: inbound.clientId, agentId: inbound.agentId, tab: 'prompt' })}>
                  {inbound.agentName} · {inbound.clientName} <Icon name="chevronRight" size={14} />
                </button>
              ) : (
                <span className="value">None. Pick one in an agent's Phone playground.</span>
              )}
            </li>
          </ul>
        </div>

        <div className="card">
          <Section icon="link" title="Telephony webhooks" description="Paste these into your phone provider so calls reach your agents." single>
            <Field label="Twilio: Voice webhook for inbound calls (HTTP POST)">
              <CopyField value={`${base}/telephony/twilio/incoming`} />
            </Field>
            <Field label="Exotel: Voicebot applet URL" hint="Outbound calls are matched to the agent that placed them; inbound calls go to the inbound agent.">
              <CopyField value={`${wsBase}/ws/telephony`} />
            </Field>
          </Section>
        </div>

        <div className="card">
          <Section
            icon="coins"
            title="Cost rates"
            description="What each call's cost is calculated from (INR, before GST). Set these in the server's .env to match your invoices."
          >
            {health ? (
              <div className="wide">
                <dl className="kv rates">
                  <RateRow label="Voice output" value={`₹${health.rates.tts_per_1k_chars} per 1,000 characters`} env="PRICE_TTS_PER_1K_CHARS" />
                  <RateRow label="Speech recognition" value={`₹${health.rates.stt_per_min} per minute of caller speech`} env="PRICE_STT_PER_MIN" />
                  <RateRow
                    label="AI model"
                    value={`₹${health.rates.llm_input_per_1m} in · ₹${health.rates.llm_cached_per_1m} cached · ₹${health.rates.llm_output_per_1m} out, per 1M tokens`}
                    env="PRICE_LLM_INPUT_PER_1M, PRICE_LLM_CACHED_PER_1M, PRICE_LLM_OUTPUT_PER_1M"
                  />
                  <RateRow
                    label="Phone line: Exotel"
                    value={`₹${health.rates.exotel_per_min} per minute, billed per ${health.rates.exotel_pulse_secs}s`}
                    env="PRICE_EXOTEL_PER_MIN, EXOTEL_PULSE_SECS"
                  />
                  <RateRow
                    label="Phone line: Twilio"
                    value={health.rates.twilio_per_min ? `₹${health.rates.twilio_per_min} per minute, billed per ${health.rates.twilio_pulse_secs}s` : 'Not set'}
                    env="PRICE_TWILIO_PER_MIN, TWILIO_PULSE_SECS"
                  />
                </dl>
              </div>
            ) : (
              <span className="muted">Loading…</span>
            )}
          </Section>
          <Section icon="shield" title="Limits" description="Server-wide limits applied to every call, whatever an agent's own settings say.">
            <Field label="Maximum call length" hint="MAX_CALL_SECONDS_CAP">
              <input value={health ? `${health.max_call_seconds_cap} seconds` : '–'} readOnly />
            </Field>
            <Field label="Maximum voice AI cost per call" hint="MAX_COST_PER_CALL_INR · phone-line cost not included">
              <input value={health ? `₹${health.max_cost_per_call_inr}` : '–'} readOnly />
            </Field>
          </Section>
        </div>
      </div>
    </div>
  )
}

function RateRow({ label, value, env }: { label: string; value: string; env: string }) {
  return (
    <>
      <dt>
        {label}
        <span className="kv-detail mono">{env}</span>
      </dt>
      <dd>{value}</dd>
    </>
  )
}
