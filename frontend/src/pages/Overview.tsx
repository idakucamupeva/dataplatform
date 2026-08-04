import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, Metrics, PlatformEvent } from '@/api/types'
import { Card, EmptyState, LifecycleBadge, Loading, Stat } from '@/components/ui'
import { LIFECYCLE_LABEL, colourFor, timeAgo } from '@/lib/format'
import { useAuth } from '@/lib/auth'

export function OverviewPage() {
  const { user } = useAuth()
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: () => api.get<Metrics>('/metrics') })
  const mine = useQuery({
    queryKey: ['dataproducts', 'mine'],
    queryFn: () => api.get<DataProduct[]>('/dataproducts?scope=mine'),
  })
  const events = useQuery({ queryKey: ['events'], queryFn: () => api.get<PlatformEvent[]>('/events?limit=18') })

  const m = metrics.data

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>Good to see you, {user?.displayName.split(' ')[0]}</h1>
          <div className="page-sub">
            Everything the mesh knows about itself: what exists, what is published and what changed.
          </div>
        </div>
        <div className="page-head__actions">
          <Link className="btn btn--primary" to="/create">New data product</Link>
          <Link className="btn" to="/marketplace">Browse marketplace</Link>
        </div>
      </div>

      <div className="grid grid--4">
        <Stat label="Data products" value={m?.dataProducts ?? '—'} hint={`${m?.myDataProducts ?? 0} owned by you`} />
        <Stat label="Published" value={m?.published ?? '—'} hint="available in the marketplace" />
        <Stat label="Output ports" value={m?.outputPorts ?? '—'} hint={`${m?.components ?? 0} components in total`} />
        <Stat
          label="Awaiting your decision"
          value={m?.pendingAccessRequests ?? '—'}
          hint={<Link to="/access">access requests</Link>}
        />
      </div>

      <div className="split">
        <div className="stack">
          <Card
            title="Your data products"
            actions={<Link className="btn btn--sm" to="/products">See all</Link>}
            flush
          >
            {mine.isLoading ? (
              <div className="card__body"><Loading /></div>
            ) : (mine.data?.length ?? 0) === 0 ? (
              <EmptyState title="You do not own a data product yet">
                Start from a template — the platform creates the repository and the descriptor for you.
                <div className="mt-2"><Link className="btn btn--primary" to="/create">Create one</Link></div>
              </EmptyState>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Data product</th>
                      <th>Domain</th>
                      <th>State</th>
                      <th>Components</th>
                      <th>Environments</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mine.data!.map((dp) => (
                      <tr key={dp.id}>
                        <td>
                          <Link to={`/products/${dp.id}`} style={{ fontWeight: 600 }}>{dp.title}</Link>
                          <div className="faint small mono">{dp.name}</div>
                        </td>
                        <td><DomainChip name={dp.domain} /></td>
                        <td><LifecycleBadge value={dp.lifecycle} /></td>
                        <td className="nowrap">
                          {dp.componentCount}
                          <span className="faint"> ({dp.outputPortCount} port{dp.outputPortCount === 1 ? '' : 's'})</span>
                        </td>
                        <td>
                          <div className="row" style={{ gap: 4 }}>
                            {(dp.environments ?? []).map((env) => (
                              <span
                                key={env.environment}
                                title={`${env.environment}: ${env.status}`}
                                className={`badge ${env.status === 'provisioned' ? 'badge--ok' : env.status === 'failed' ? 'badge--danger' : ''}`}
                              >
                                {env.environment.slice(0, 3)}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="nowrap faint">{timeAgo(dp.updatedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="grid grid--2">
            <Card title="Lifecycle">
              {m ? <Distribution data={Object.entries(m.byLifecycle).map(([k, v]) => ({ label: LIFECYCLE_LABEL[k] ?? k, value: v }))} /> : <Loading rows={4} />}
            </Card>
            <Card title="Output ports by technology">
              {m ? (
                m.byTechnology.length === 0
                  ? <div className="muted small">No output ports yet.</div>
                  : <Distribution data={m.byTechnology.map((t) => ({ label: t.technology, value: t.count }))} />
              ) : <Loading rows={4} />}
            </Card>
          </div>
        </div>

        <div className="stack">
          <Card title="Provisioned per environment">
            {m ? (
              <div className="stack stack--sm">
                {m.environments.map((env) => (
                  <div key={env.environment} className="row row--between">
                    <span className="mono small">{env.environment}</span>
                    <span className="badge badge--ok">{env.provisioned}</span>
                  </div>
                ))}
              </div>
            ) : <Loading rows={3} />}
          </Card>

          <Card title="Activity" flush>
            {events.isLoading ? (
              <div className="card__body"><Loading /></div>
            ) : (events.data?.length ?? 0) === 0 ? (
              <div className="card__body muted small">Nothing has happened yet.</div>
            ) : (
              <div className="card__body">
                <div className="timeline">
                  {events.data!.map((event) => (
                    <div className="timeline__item" key={event.id}>
                      <span className="timeline__dot" />
                      <div>{event.message}</div>
                      <div className="timeline__meta">
                        {event.actor?.displayName ?? 'system'}
                        {event.dataProduct && (
                          <> · <Link to={`/products/${event.dataProduct.id}`}>{event.dataProduct.title}</Link></>
                        )}
                        {' · '}{timeAgo(event.createdAt)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

export function DomainChip({ name }: { name: string }) {
  return (
    <span className="badge" style={{ background: `${colourFor(name)}1f`, color: colourFor(name) }}>
      {name}
    </span>
  )
}

function Distribution({ data }: { data: { label: string; value: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <div className="stack stack--sm">
      {data.map((entry) => (
        <div key={entry.label}>
          <div className="row row--between small">
            <span>{entry.label}</span>
            <span className="faint">{entry.value}</span>
          </div>
          <div className="progress-track" style={{ marginTop: 3 }}>
            <div className="progress-fill" style={{ width: `${(entry.value / max) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}
