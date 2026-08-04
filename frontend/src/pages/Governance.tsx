import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, PlatformInfo } from '@/api/types'
import { Badge, Card, EmptyState, Loading } from '@/components/ui'
import { timeAgo } from '@/lib/format'
import { useAuth } from '@/lib/auth'
import { DomainChip } from '@/pages/Overview'

interface Policy {
  id: string
  name: string
  description: string
  category: string
}

export function GovernancePage() {
  const { user } = useAuth()
  const canGovern = user?.role === 'admin' || user?.role === 'governance'

  const policies = useQuery({ queryKey: ['policies'], queryFn: () => api.get<Policy[]>('/policies') })
  const info = useQuery({ queryKey: ['platform'], queryFn: () => api.get<PlatformInfo>('/platform/info') })
  const queue = useQuery({
    queryKey: ['governance-queue'],
    queryFn: () => api.get<DataProduct[]>('/governance/queue'),
    enabled: canGovern,
  })

  const byCategory = new Map<string, Policy[]>()
  for (const policy of policies.data ?? []) {
    if (!byCategory.has(policy.category)) byCategory.set(policy.category, [])
    byCategory.get(policy.category)!.push(policy)
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>Federated governance</h1>
          <div className="page-sub">
            The rules every domain must satisfy, encoded once and evaluated automatically on every
            descriptor change, release and production deployment.
          </div>
        </div>
      </div>

      {canGovern && (
        <Card title="Waiting for review" flush>
          {queue.isLoading ? (
            <div className="card__body"><Loading /></div>
          ) : (queue.data?.length ?? 0) === 0 ? (
            <EmptyState title="Nothing in the review queue">
              Data products submitted for review appear here; releasing one is a governance decision.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Data product</th><th>Domain</th><th>Owner</th><th>Version</th><th>Waiting</th><th /></tr></thead>
                <tbody>
                  {queue.data!.map((dp) => (
                    <tr key={dp.id}>
                      <td>
                        <Link to={`/products/${dp.id}`} style={{ fontWeight: 600 }}>{dp.title}</Link>
                        <div className="small muted">{dp.description.slice(0, 90)}…</div>
                      </td>
                      <td><DomainChip name={dp.domain} /></td>
                      <td className="small">{dp.owner?.displayName}</td>
                      <td className="mono small">v{dp.version}</td>
                      <td className="small faint nowrap">{timeAgo(dp.updatedAt)}</td>
                      <td><Link className="btn btn--sm btn--primary" to={`/products/${dp.id}`}>Review</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <div className="split">
        <Card title={`Policies in force (${policies.data?.length ?? 0})`} flush>
          {policies.isLoading ? (
            <div className="card__body"><Loading rows={6} /></div>
          ) : (
            <div>
              {[...byCategory.entries()].map(([category, items]) => (
                <div key={category}>
                  <div style={{ padding: '9px 14px', background: 'var(--surface-2)', borderBottom: '1px solid var(--border)' }}>
                    <span className="sidebar__label" style={{ padding: 0 }}>{category}</span>
                  </div>
                  {items.map((policy) => (
                    <div key={policy.id} style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
                      <div className="row row--between">
                        <strong>{policy.name}</strong>
                        <code className="urn">{policy.id}</code>
                      </div>
                      <div className="small muted mt-1">{policy.description}</div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </Card>

        <div className="stack">
          <Card title="When policies run">
            <ul className="small muted" style={{ paddingLeft: 18, margin: 0, lineHeight: 1.9 }}>
              <li><strong>On save</strong> — advisory, so producers see problems as they work.</li>
              <li><strong>On submit and release</strong> — a hard gate; blocking findings stop the release.</li>
              <li><strong>On deployment</strong> to anything other than development — the same gate again.</li>
            </ul>
            <p className="small muted mt-2 mb-0">
              A finding with severity <Badge tone="badge--danger">error</Badge> blocks;{' '}
              <Badge tone="badge--warn">warning</Badge> and <Badge tone="badge--info">info</Badge> inform.
            </p>
          </Card>

          <Card title="Registered provisioners">
            <div className="stack stack--sm">
              {info.data?.provisioners.map((provisioner) => (
                <div className="row row--between" key={provisioner.technology}>
                  <span className="mono small">{provisioner.technology}</span>
                  <span className="faint small">{provisioner.platform}</span>
                </div>
              ))}
            </div>
            <p className="small faint mt-2 mb-0">
              A component whose technology has no registered provisioner cannot be deployed — the
              coordinator refuses the plan before touching anything.
            </p>
          </Card>

          <Card title="Marketplace gate">
            <p className="small muted mb-0">
              A data product must be released <em>and</em> provisioned in{' '}
              <code>{info.data?.marketplaceGateEnvironment}</code> before it can be published. Consumers
              never see a product that does not actually run.
            </p>
          </Card>
        </div>
      </div>
    </div>
  )
}
