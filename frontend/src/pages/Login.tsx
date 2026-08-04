import { useState, type FormEvent } from 'react'
import { useAuth } from '@/lib/auth'
import { ErrorBanner } from '@/components/ui'

const DEMO_ACCOUNTS = [
  { username: 'alice', role: 'Producer — owns Customer 360 and Order Events' },
  { username: 'maya', role: 'Producer — owns Campaign Attribution' },
  { username: 'bruno', role: 'Consumer — has access requests in flight' },
  { username: 'gwen', role: 'Federated governance — reviews releases' },
  { username: 'admin', role: 'Platform team — manages domains and templates' },
]

export function LoginPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [form, setForm] = useState({ username: '', password: '', email: '', fullName: '' })
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const set = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await login(form.username, form.password)
      else await register(form)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card stack">
        <div className="row" style={{ gap: 12 }}>
          <div className="sidebar__brand-mark" style={{ width: 38, height: 38, fontSize: 15 }}>DM</div>
          <div>
            <h1 style={{ fontSize: 20 }}>DataMesh Platform</h1>
            <div className="small muted">Build, govern and publish data products.</div>
          </div>
        </div>

        <div className="card">
          <div className="card__body">
            <div className="tabs mb-2">
              <button type="button" className={`tab ${mode === 'login' ? 'is-active' : ''}`} onClick={() => setMode('login')}>
                Sign in
              </button>
              <button type="button" className={`tab ${mode === 'register' ? 'is-active' : ''}`} onClick={() => setMode('register')}>
                Create account
              </button>
            </div>

            <form onSubmit={submit}>
              <div className="field">
                <label className="field__label" htmlFor="username">Username</label>
                <input
                  id="username"
                  className="input"
                  value={form.username}
                  autoComplete="username"
                  onChange={(e) => set('username', e.target.value)}
                  required
                />
              </div>

              {mode === 'register' && (
                <>
                  <div className="field">
                    <label className="field__label" htmlFor="email">E-mail</label>
                    <input id="email" type="email" className="input" value={form.email}
                      onChange={(e) => set('email', e.target.value)} required />
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="fullName">Full name</label>
                    <input id="fullName" className="input" value={form.fullName}
                      onChange={(e) => set('fullName', e.target.value)} />
                  </div>
                </>
              )}

              <div className="field">
                <label className="field__label" htmlFor="password">Password</label>
                <input
                  id="password"
                  type="password"
                  className="input"
                  value={form.password}
                  autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                  onChange={(e) => set('password', e.target.value)}
                  required
                />
              </div>

              {error != null && <div className="mb-2"><ErrorBanner error={error} /></div>}

              <button type="submit" className="btn btn--primary btn--block" disabled={busy}>
                {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
              </button>
            </form>
          </div>

          {mode === 'login' && (
            <div className="card__foot">
              <div className="login-hint stack stack--sm">
                <div><strong>Demo accounts</strong> — password <code>password123</code></div>
                {DEMO_ACCOUNTS.map((account) => (
                  <button
                    key={account.username}
                    type="button"
                    className="row"
                    style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left', font: 'inherit', color: 'inherit' }}
                    onClick={() => setForm({ ...form, username: account.username, password: 'password123' })}
                  >
                    <code style={{ minWidth: 54 }}>{account.username}</code>
                    <span className="faint">{account.role}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
