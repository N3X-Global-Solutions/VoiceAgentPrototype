import { useState, type FormEvent } from 'react'
import { Icon } from '@/components/Icon'
import { IconChip, Spinner } from '@/components/ui'
import { api } from '@/lib/api'

// Bar heights for the animated waveform on the brand panel.
const WAVE = [14, 26, 40, 30, 52, 38, 56, 44, 28, 48, 34, 20, 42, 54, 36, 24, 46, 30, 18, 34, 50, 28, 16, 24]
const YEAR = new Date().getFullYear()

export function LoginPage({ onSignedIn }: { onSignedIn: (email: string) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await api.login(email.trim(), password)
      onSignedIn(res.email)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <aside className="login-aside">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="wave" size={18} />
          </span>
          <span className="brand-name">
            Voice Agent Studio
            <small>Conversational AI console</small>
          </span>
        </div>

        <div>
          <h2>
            Voice agents that speak <em>your customers' language.</em>
          </h2>
          <p className="lede">Design, test and deploy phone agents in English and nine Indian languages, from one console.</p>
          <div className="login-wave" aria-hidden="true">
            {WAVE.map((h, i) => (
              <span key={i} style={{ height: h, animationDelay: `${(i % 8) * 0.12}s` }} />
            ))}
          </div>
          <ul className="login-features">
            <li>
              <IconChip icon="bot" size="sm" />
              Prompt, voice, language and tools for every client
            </li>
            <li>
              <IconChip icon="headphones" size="sm" />
              Test in the browser, by chat or on a real phone line
            </li>
            <li>
              <IconChip icon="activity" size="sm" />
              Latency, transcripts and cost on every call
            </li>
          </ul>
        </div>

        <div className="foot">
          <span>© {YEAR} Voice Agent Studio</span>
          <span>Powered by Sarvam AI</span>
        </div>
      </aside>

      <main className="login-main">
        <div className="login-card">
          <div className="brand mobile-brand">
            <span className="brand-mark">
              <Icon name="wave" size={18} />
            </span>
            <span className="brand-name">Voice Agent Studio</span>
          </div>

          <h1>Welcome back</h1>
          <p className="sub">Sign in with your administrator account to continue.</p>

          <form className="login-form" onSubmit={submit} noValidate>
            {error && (
              <div className="banner tone-red" role="alert" style={{ margin: 0 }}>
                <Icon name="alert" /> <span className="grow">{error}</span>
              </div>
            )}
            <label className="field">
              <span className="field-label">Email address</span>
              <div className="input-icon">
                <Icon name="mail" size={16} />
                <input
                  type="email"
                  autoComplete="username"
                  autoFocus
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@company.com"
                />
              </div>
            </label>
            <label className="field">
              <span className="field-label">Password</span>
              <div className="input-icon input-action">
                <Icon name="lock" size={16} />
                <input
                  type={show ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                />
                <button
                  type="button"
                  className="btn btn-ghost btn-sm btn-icon"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? 'Hide password' : 'Show password'}
                  title={show ? 'Hide password' : 'Show password'}
                >
                  <Icon name={show ? 'eyeOff' : 'eye'} size={16} />
                </button>
              </div>
            </label>
            <button className="btn btn-primary btn-lg btn-block" type="submit" disabled={busy || !email.trim() || !password}>
              {busy ? (
                <>
                  <Spinner /> Signing in…
                </>
              ) : (
                <>
                  Sign in <Icon name="arrowRight" size={16} />
                </>
              )}
            </button>
          </form>

          <p className="login-note">
            <Icon name="shield" size={14} /> Restricted to administrators of this workspace.
          </p>
        </div>
      </main>
    </div>
  )
}
