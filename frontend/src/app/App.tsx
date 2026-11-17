import { useEffect, useState } from 'react'
import { Spinner } from '@/components/ui'
import { LoginPage } from '@/features/auth/LoginPage'
import { api, UNAUTHORIZED_EVENT } from '@/lib/api'
import { AppShell } from './AppShell'

type Auth = { state: 'loading' } | { state: 'out' } | { state: 'in'; email: string }

/** Auth gate: the sign-in page until there is a session, then the console. */
export default function App() {
  const [auth, setAuth] = useState<Auth>({ state: 'loading' })

  useEffect(() => {
    api
      .me()
      .then((r) => setAuth({ state: 'in', email: r.email }))
      .catch(() => setAuth({ state: 'out' }))
    const onExpired = () => setAuth({ state: 'out' })
    window.addEventListener(UNAUTHORIZED_EVENT, onExpired)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onExpired)
  }, [])

  if (auth.state === 'loading') {
    return (
      <div className="splash">
        <Spinner />
      </div>
    )
  }
  if (auth.state === 'out') return <LoginPage onSignedIn={(email) => setAuth({ state: 'in', email })} />
  return (
    <AppShell
      email={auth.email}
      onSignOut={async () => {
        await api.logout().catch(() => {})
        setAuth({ state: 'out' })
      }}
    />
  )
}
