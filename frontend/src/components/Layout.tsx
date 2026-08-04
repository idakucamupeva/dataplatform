import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Metrics, PlatformInfo } from '@/api/types'
import { useAuth } from '@/lib/auth'
import { Avatar, Badge } from '@/components/ui'

function useTheme() {
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (localStorage.getItem('dmp.theme') as 'light' | 'dark') ??
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
  )
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('dmp.theme', theme)
  }, [theme])
  return { theme, toggle: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) }
}

function NavItem({ to, children, badge }: { to: string; children: ReactNode; badge?: ReactNode }) {
  return (
    <NavLink to={to} className={({ isActive }) => `sidebar__link ${isActive ? 'is-active' : ''}`} end={to === '/'}>
      <span>{children}</span>
      {badge}
    </NavLink>
  )
}

export function Layout() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()
  const navigate = useNavigate()

  const { data: metrics } = useQuery({
    queryKey: ['metrics'],
    queryFn: () => api.get<Metrics>('/metrics'),
    refetchInterval: 30_000,
  })
  const { data: info } = useQuery({ queryKey: ['platform'], queryFn: () => api.get<PlatformInfo>('/platform/info') })

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <div className="sidebar__brand-mark">DM</div>
          <div>
            <div className="sidebar__brand-name">{info?.name ?? 'DataMesh Platform'}</div>
            <div className="sidebar__brand-sub">Self-service data mesh</div>
          </div>
        </div>

        <nav className="sidebar__section">
          <div className="sidebar__label">Build</div>
          <NavItem to="/">Overview</NavItem>
          <NavItem to="/products" badge={metrics ? <span className="badge">{metrics.dataProducts}</span> : undefined}>
            Data products
          </NavItem>
          <NavItem to="/create">New data product</NavItem>
        </nav>

        <nav className="sidebar__section">
          <div className="sidebar__label">Consume</div>
          <NavItem
            to="/marketplace"
            badge={metrics ? <span className="badge badge--ok">{metrics.published}</span> : undefined}
          >
            Marketplace
          </NavItem>
          <NavItem
            to="/access"
            badge={
              metrics && metrics.pendingAccessRequests > 0
                ? <span className="badge badge--warn">{metrics.pendingAccessRequests}</span>
                : undefined
            }
          >
            Access requests
          </NavItem>
          <NavItem to="/lineage">Mesh lineage</NavItem>
        </nav>

        <nav className="sidebar__section">
          <div className="sidebar__label">Govern</div>
          <NavItem to="/governance">Governance</NavItem>
          <NavItem to="/domains">Domains</NavItem>
        </nav>

        <div className="sidebar__foot">
          <div className="row">
            <Avatar name={user?.displayName} />
            <div style={{ minWidth: 0 }}>
              <div className="truncate" style={{ fontWeight: 600, fontSize: 13 }}>{user?.displayName}</div>
              <div className="faint small">
                {user?.role === 'user' ? 'Member' : user?.role === 'admin' ? 'Administrator' : 'Governance'}
              </div>
            </div>
          </div>
          <div className="row mt-1" style={{ gap: 6 }}>
            <button type="button" className="btn btn--sm" onClick={toggle} title="Toggle colour theme">
              {theme === 'dark' ? '☀' : '☾'}
            </button>
            <button
              type="button"
              className="btn btn--sm spacer"
              onClick={() => { logout(); navigate('/login') }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <Badge tone="badge--accent">{info?.urnNamespace ? `urn:${info.urnNamespace}` : 'mesh'}</Badge>
          <span className="small muted">
            {metrics
              ? `${metrics.dataProducts} data products · ${metrics.outputPorts} output ports · ${metrics.domains} domains`
              : ''}
          </span>
          <div className="topbar__spacer" />
          <span className="small faint">{info?.environments.join(' · ')}</span>
        </header>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
