import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, query } from '@/api/client'
import type { DataProduct, Domain } from '@/api/types'
import { Card, DeploymentBadge, EmptyState, LifecycleBadge, Loading } from '@/components/ui'
import { LIFECYCLE_LABEL, timeAgo } from '@/lib/format'
import { DomainChip } from '@/pages/Overview'

const LIFECYCLES = ['draft', 'in_review', 'released', 'published', 'retired']

export function DataProductsPage() {
  const [scope, setScope] = useState<'all' | 'mine'>('all')
  const [search, setSearch] = useState('')
  const [domain, setDomain] = useState('')
  const [lifecycle, setLifecycle] = useState('')

  const domains = useQuery({ queryKey: ['domains'], queryFn: () => api.get<Domain[]>('/domains') })
  const products = useQuery({
    queryKey: ['dataproducts', scope, search, domain, lifecycle],
    queryFn: () => api.get<DataProduct[]>(`/dataproducts${query({ scope, q: search, domain, lifecycle })}`),
  })

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>Data products</h1>
          <div className="page-sub">Everything registered in the mesh, whatever state it is in.</div>
        </div>
        <div className="page-head__actions">
          <Link className="btn btn--primary" to="/create">New data product</Link>
        </div>
      </div>

      <div className="row row--wrap">
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder="Search by name or title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="row" style={{ gap: 6 }}>
          <button type="button" className={`chip ${scope === 'all' ? 'is-active' : ''}`} onClick={() => setScope('all')}>
            All
          </button>
          <button type="button" className={`chip ${scope === 'mine' ? 'is-active' : ''}`} onClick={() => setScope('mine')}>
            Mine
          </button>
        </div>
        <select className="select" style={{ maxWidth: 180 }} value={domain} onChange={(e) => setDomain(e.target.value)}>
          <option value="">All domains</option>
          {domains.data?.map((d) => <option key={d.id} value={d.name}>{d.title}</option>)}
        </select>
        <select className="select" style={{ maxWidth: 180 }} value={lifecycle} onChange={(e) => setLifecycle(e.target.value)}>
          <option value="">Any state</option>
          {LIFECYCLES.map((state) => <option key={state} value={state}>{LIFECYCLE_LABEL[state]}</option>)}
        </select>
      </div>

      {products.isLoading ? (
        <Card><Loading rows={6} /></Card>
      ) : (products.data?.length ?? 0) === 0 ? (
        <Card>
          <EmptyState
            title="Nothing matches"
            action={<Link className="btn btn--primary" to="/create">Create a data product</Link>}
          >
            Adjust the filters, or start a new data product from a template.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid grid--2">
          {products.data!.map((dp) => (
            <Link key={dp.id} to={`/products/${dp.id}`} className="card card--interactive" style={{ color: 'inherit', textDecoration: 'none' }}>
              <div className="card__body">
                <div className="row row--between mb-1">
                  <DomainChip name={dp.domain} />
                  <LifecycleBadge value={dp.lifecycle} />
                </div>
                <h3>{dp.title}</h3>
                <div className="small muted mt-1" style={{ minHeight: 38 }}>
                  {dp.description.length > 150 ? `${dp.description.slice(0, 150)}…` : dp.description}
                </div>
                <div className="row row--wrap mt-1" style={{ gap: 5 }}>
                  {dp.tags.slice(0, 4).map((tag) => <span className="badge" key={tag}>{tag}</span>)}
                </div>
                <div className="row row--between mt-2 small faint">
                  <span>v{dp.version} · {dp.componentCount} components · {dp.outputPortCount} ports</span>
                  <span>{timeAgo(dp.updatedAt)}</span>
                </div>
                {dp.environments && (
                  <div className="row row--wrap mt-1" style={{ gap: 6 }}>
                    {dp.environments.map((env) => (
                      <span key={env.environment} className="row" style={{ gap: 4 }}>
                        <span className="small faint">{env.environment}</span>
                        <DeploymentBadge value={env.status} />
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
