import { useEffect, type ReactNode } from 'react'
import { ApiError } from '@/api/client'
import type { ComponentKind, DeploymentStatus, Lifecycle, Severity } from '@/api/types'
import {
  DEPLOY_LABEL, DEPLOY_TONE, KIND_LABEL, KIND_TONE,
  LIFECYCLE_LABEL, LIFECYCLE_ORDER, LIFECYCLE_TONE, SEVERITY_TONE,
} from '@/lib/format'

/* --------------------------------------------------------------- badges */
export function Badge({ tone = '', children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

export function LifecycleBadge({ value }: { value: Lifecycle }) {
  return (
    <Badge tone={LIFECYCLE_TONE[value]}>
      <span className="badge__dot" />
      {LIFECYCLE_LABEL[value] ?? value}
    </Badge>
  )
}

export function KindBadge({ value }: { value: ComponentKind }) {
  return <Badge tone={KIND_TONE[value]}>{KIND_LABEL[value] ?? value}</Badge>
}

export function DeploymentBadge({ value }: { value: DeploymentStatus }) {
  return <Badge tone={DEPLOY_TONE[value]}>{DEPLOY_LABEL[value] ?? value}</Badge>
}

export function SeverityBadge({ value }: { value: Severity }) {
  return <Badge tone={SEVERITY_TONE[value]}>{value}</Badge>
}

/* ---------------------------------------------------------------- cards */
export function Card({
  title, actions, children, flush, className = '',
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  flush?: boolean
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card__head">
          <h3 className="card__title">{title}</h3>
          {actions && <div className="row spacer" style={{ justifyContent: 'flex-end' }}>{actions}</div>}
        </header>
      )}
      <div className={flush ? 'card__body card__body--flush' : 'card__body'}>{children}</div>
    </section>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="card stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty__title">{title}</div>
      {children && <div className="small">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack stack--sm" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton" style={{ height: index === 0 ? 34 : 22 }} />
      ))}
    </div>
  )
}

/* --------------------------------------------------------------- banners */
export function Banner({ tone = 'info', title, children }: { tone?: string; title?: ReactNode; children?: ReactNode }) {
  return (
    <div className={`banner banner--${tone}`}>
      <div>
        {title && <strong>{title}</strong>}
        {title && children ? <> — </> : null}
        {children}
      </div>
    </div>
  )
}

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null
  if (error instanceof ApiError) {
    return (
      <div className="banner banner--error">
        <div>
          <strong>{error.detail}</strong>
          {error.lines.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {error.lines.map((line) => <li key={line}>{line}</li>)}
            </ul>
          )}
        </div>
      </div>
    )
  }
  return <div className="banner banner--error">{String((error as Error)?.message ?? error)}</div>
}

/* ---------------------------------------------------------------- modal */
export function Modal({
  title, subtitle, onClose, children, footer, wide,
}: {
  title: ReactNode
  subtitle?: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className={`modal ${wide ? 'modal--wide' : ''}`} role="dialog" aria-modal="true">
        <header className="modal__head">
          <div style={{ minWidth: 0 }}>
            <h2>{title}</h2>
            {subtitle && <div className="small muted">{subtitle}</div>}
          </div>
          <button type="button" className="btn btn--ghost btn--sm spacer" style={{ marginLeft: 'auto' }} onClick={onClose}>
            Close
          </button>
        </header>
        <div className="modal__body">{children}</div>
        {footer && <footer className="modal__foot">{footer}</footer>}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- lifecycle */
export function LifecycleTrail({ value }: { value: Lifecycle }) {
  if (value === 'retired') {
    return <Badge tone="badge--danger">Retired</Badge>
  }
  const currentIndex = LIFECYCLE_ORDER.indexOf(value)
  return (
    <div className="lifecycle">
      {LIFECYCLE_ORDER.map((state, index) => (
        <div
          key={state}
          className={`lifecycle__step ${index < currentIndex ? 'is-done' : ''} ${index === currentIndex ? 'is-current' : ''}`}
        >
          {LIFECYCLE_LABEL[state]}
        </div>
      ))}
    </div>
  )
}

/* ----------------------------------------------------------------- tabs */
export function Tabs<T extends string>({
  tabs, active, onChange,
}: {
  tabs: { id: T; label: string; count?: number }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          className={`tab ${active === tab.id ? 'is-active' : ''}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          {tab.count !== undefined && <span className="faint"> {tab.count}</span>}
        </button>
      ))}
    </div>
  )
}

/* --------------------------------------------------------------- inline */
export function Urn({ value }: { value: string }) {
  return (
    <code
      className="urn"
      title={`${value} — click to copy`}
      onClick={() => navigator.clipboard?.writeText(value)}
      style={{ cursor: 'copy' }}
    >
      {value}
    </code>
  )
}

export function Avatar({ name }: { name?: string | null }) {
  const initials = (name ?? '?')
    .split(' ')
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
  return (
    <span
      style={{
        width: 24, height: 24, borderRadius: '50%', flex: '0 0 auto',
        display: 'grid', placeItems: 'center', fontSize: 10, fontWeight: 700,
        background: 'var(--surface-3)', color: 'var(--text-muted)',
      }}
    >
      {initials}
    </span>
  )
}
