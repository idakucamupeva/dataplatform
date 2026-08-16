import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, query } from '@/api/client'
import type { MarketplaceResult } from '@/api/types'
import { Badge, Card, EmptyState, Loading } from '@/components/ui'
import { timeAgo } from '@/lib/format'
import { DomainChip } from '@/pages/Overview'

export function MarketplacePage() {
  const [search, setSearch] = useState('')
  const [domain, setDomain] = useState('')
  const [tag, setTag] = useState('')
  const [technology, setTechnology] = useState('')

  const result = useQuery({
    queryKey: ['marketplace', search, domain, tag, technology],
    queryFn: () => api.get<MarketplaceResult>(`/marketplace${query({ q: search, domain, tag, technology })}`),
  })

  const facets = result.data?.facets
  const clear = () => { setDomain(''); setTag(''); setTechnology('') }
  const filtered = Boolean(domain || tag || technology)

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>Marketplace</h1>
          <div className="page-sub">
            Published data products, with the contract you get and the terms you accept. Request access to
            an output port and the owning domain decides.
          </div>
        </div>
      </div>

      <div className="split">
        <div className="stack">
          <input
            className="input"
            placeholder="Search published data products…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          {result.isLoading ? (
            <Card><Loading rows={6} /></Card>
          ) : (result.data?.items.length ?? 0) === 0 ? (
            <Card>
              <EmptyState title="Nothing published matches">
                Try clearing the filters, or ask a domain to publish the data you need.
              </EmptyState>
            </Card>
          ) : (
            <>
              <div className="small muted">
                {result.data!.total} published data product{result.data!.total === 1 ? '' : 's'}
              </div>
              <div className="grid grid--2">
                {result.data!.items.map((dp) => (
                  <Link key={dp.id} to={`/marketplace/${dp.id}`} className="card card--interactive">
                    <div className="card__body">
                      <div className="row row--between mb-1">
                        <DomainChip name={dp.domain} />
                        <Badge tone={dp.maturity === 'strategic' ? 'badge--violet' : ''}>{dp.maturity}</Badge>
                      </div>
                      <h3>{dp.title}</h3>
                      <div className="small muted mt-1" style={{ minHeight: 38 }}>
                        {dp.description.length > 160 ? `${dp.description.slice(0, 160)}…` : dp.description}
                      </div>

                      <div className="stack stack--sm mt-2">
                        {(dp.outputPorts ?? []).map((port) => (
                          <div className="row row--between small" key={port.id}>
                            <span className="row" style={{ gap: 6 }}>
                              <Badge tone="badge--accent">{port.technology}</Badge>
                              <span>{port.title}</span>
                            </span>
                            <span className="faint">
                              {port.columnCount} cols{port.hasPii ? ' · pii' : ''}
                            </span>
                          </div>
                        ))}
                      </div>

                      <div className="row row--between mt-2 small faint">
                        <span className="row row--wrap" style={{ gap: 5 }}>
                          {dp.tags.slice(0, 3).map((t) => <span className="badge" key={t}>{t}</span>)}
                        </span>
                        <span>published {timeAgo(dp.publishedAt)}</span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="stack">
          <Card
            title="Filters"
            actions={filtered ? <button type="button" className="btn btn--ghost btn--sm" onClick={clear}>Clear</button> : undefined}
          >
            <FacetGroup label="Domain" values={facets?.domains} active={domain} onPick={setDomain} />
            <FacetGroup label="Technology" values={facets?.technologies} active={technology} onPick={setTechnology} />
            <FacetGroup label="Tag" values={facets?.tags} active={tag} onPick={setTag} />
          </Card>

          <Card title="How access works">
            <ol className="small muted" style={{ paddingLeft: 18, margin: 0, lineHeight: 1.8 }}>
              <li>Read the data contract and the terms of the output port.</li>
              <li>Request access, stating what you will use the data for.</li>
              <li>The owning domain approves or rejects — you are notified either way.</li>
              <li>Approved access appears in your subscriptions and can be revoked later.</li>
            </ol>
          </Card>
        </div>
      </div>
    </div>
  )
}

function FacetGroup({
  label, values, active, onPick,
}: {
  label: string
  values?: { value: string; count: number }[]
  active: string
  onPick: (value: string) => void
}) {
  if (!values || values.length === 0) return null
  return (
    <div className="mb-2">
      <div className="sidebar__label" style={{ padding: '0 0 6px' }}>{label}</div>
      <div className="row row--wrap" style={{ gap: 6 }}>
        {values.map((entry) => (
          <button
            key={entry.value}
            type="button"
            className={`chip ${active === entry.value ? 'is-active' : ''}`}
            onClick={() => onPick(active === entry.value ? '' : entry.value)}
          >
            {entry.value}<span className="faint"> {entry.count}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
