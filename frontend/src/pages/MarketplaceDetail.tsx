import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Component, DataProduct, LineageGraph as Graph } from '@/api/types'
import { Badge, Card, ErrorBanner, Loading, Modal, Urn } from '@/components/ui'
import { SchemaTable } from '@/components/detail/ComponentsTab'
import { LineageGraph } from '@/components/LineageGraph'
import { formatDate, timeAgo } from '@/lib/format'
import { DomainChip } from '@/pages/Overview'

export function MarketplaceDetailPage() {
  const { id } = useParams()
  const [requesting, setRequesting] = useState<Component | null>(null)

  const dpQuery = useQuery({
    queryKey: ['marketplace', Number(id)],
    queryFn: () => api.get<DataProduct>(`/marketplace/${id}`),
  })
  const lineage = useQuery({
    queryKey: ['dp-lineage', Number(id)],
    queryFn: () => api.get<Graph>(`/dataproducts/${id}/lineage?depth=2`),
  })

  if (dpQuery.isLoading) return <Loading rows={8} />
  if (dpQuery.error || !dpQuery.data) return <ErrorBanner error={dpQuery.error ?? 'Not found'} />
  const dp = dpQuery.data

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <div className="row row--wrap mb-1" style={{ gap: 6 }}>
            <DomainChip name={dp.domain} />
            <Badge tone="badge--ok">published</Badge>
            <Badge tone={dp.maturity === 'strategic' ? 'badge--violet' : ''}>{dp.maturity}</Badge>
            <Badge>v{dp.releasedVersion ?? dp.version}</Badge>
          </div>
          <h1>{dp.title}</h1>
          <div className="page-sub">{dp.description}</div>
          <div className="mt-1"><Urn value={dp.urn} /></div>
        </div>
        <div className="page-head__actions">
          <Link className="btn" to="/marketplace">Back to marketplace</Link>
          {dp.isOwner && <Link className="btn" to={`/products/${dp.id}`}>Open in builder</Link>}
        </div>
      </div>

      <div className="split">
        <div className="stack">
          {(dp.outputPorts ?? []).map((port) => (
            <Card
              key={port.id}
              title={
                <span className="row" style={{ gap: 8 }}>
                  {port.title}
                  <Badge tone="badge--accent">{port.technology}</Badge>
                  {port.hasPii && <Badge tone="badge--warn">personal data</Badge>}
                </span>
              }
              actions={<AccessButton port={port} onRequest={() => setRequesting(port)} />}
            >
              <p className="muted small">{port.description}</p>

              <dl className="kv mb-2">
                <dt>Endpoint</dt>
                <dd className="mono small">
                  {port.access === 'approved' || port.access === 'owner'
                    ? port.endpoint
                    : <span className="faint">visible once access is granted</span>}
                </dd>
                <dt>Interval of change</dt><dd>{port.dataContract?.SLA?.intervalOfChange || '—'}</dd>
                <dt>Timeliness</dt><dd>{port.dataContract?.SLA?.timeliness || '—'}</dd>
                <dt>Availability</dt><dd>{port.dataContract?.SLA?.upTime || '—'}</dd>
              </dl>

              {port.dataContract?.termsAndConditions && (
                <div className="banner banner--info mb-2">
                  <div><strong>Terms</strong> — {port.dataContract.termsAndConditions}</div>
                </div>
              )}

              <div className="card" style={{ boxShadow: 'none' }}>
                <div className="card__head">
                  <h3 className="card__title">Data contract — {port.columnCount} columns</h3>
                </div>
                <SchemaTable columns={port.dataContract?.schema} />
              </div>
            </Card>
          ))}

          <Card title="Lineage" flush>
            {lineage.isLoading ? <div className="card__body"><Loading rows={4} /></div> : <LineageGraph graph={lineage.data!} />}
          </Card>
        </div>

        <div className="stack">
          <Card title="Owned by">
            <dl className="kv">
              <dt>Domain</dt><dd>{dp.domainTitle}</dd>
              <dt>Owner</dt><dd>{dp.owner?.displayName}</dd>
              <dt>Contact</dt><dd className="small">{dp.owner?.email}</dd>
              <dt>Published</dt><dd>{formatDate(dp.publishedAt)}</dd>
              <dt>Updated</dt><dd>{timeAgo(dp.updatedAt)}</dd>
            </dl>
            {dp.tags.length > 0 && (
              <div className="row row--wrap mt-2" style={{ gap: 5 }}>
                {dp.tags.map((tag) => <span className="badge" key={tag}>{tag}</span>)}
              </div>
            )}
          </Card>

          <Card title="Running in">
            <div className="stack stack--sm">
              {(dp.environments ?? []).filter((e) => e.status === 'provisioned').map((env) => (
                <div className="row row--between" key={env.environment}>
                  <span className="mono small">{env.environment}</span>
                  <Badge tone="badge--ok">{env.version}</Badge>
                </div>
              ))}
            </div>
          </Card>

          {(dp.myRequests?.length ?? 0) > 0 && (
            <Card title="Your requests" flush>
              <div>
                {dp.myRequests!.map((request) => (
                  <div key={request.id} style={{ padding: '11px 14px', borderBottom: '1px solid var(--border)' }}>
                    <div className="row row--between">
                      <span className="small mono">{request.component?.name ?? 'whole product'}</span>
                      <Badge tone={
                        request.status === 'approved' ? 'badge--ok'
                          : request.status === 'pending' ? 'badge--warn'
                            : 'badge--danger'
                      }>{request.status}</Badge>
                    </div>
                    <div className="small muted mt-1">{request.purpose}</div>
                    {request.decisionNote && <div className="small faint mt-1">“{request.decisionNote}”</div>}
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card title="Internal components">
            <div className="stack stack--sm">
              {(dp.internalComponents ?? []).map((component) => (
                <div className="row row--between small" key={component.id}>
                  <span>{component.title}</span>
                  <span className="faint">{component.technology}</span>
                </div>
              ))}
              {(dp.internalComponents?.length ?? 0) === 0 && <span className="small faint">None declared.</span>}
            </div>
          </Card>
        </div>
      </div>

      {requesting && <RequestModal dp={dp} port={requesting} onClose={() => setRequesting(null)} />}
    </div>
  )
}

function AccessButton({ port, onRequest }: { port: Component; onRequest: () => void }) {
  if (port.access === 'owner') return <Badge tone="badge--ok">you own this</Badge>
  if (port.access === 'approved') return <Badge tone="badge--ok">access granted</Badge>
  if (port.access === 'pending') return <Badge tone="badge--warn">request pending</Badge>
  return <button type="button" className="btn btn--primary btn--sm" onClick={onRequest}>Request access</button>
}

function RequestModal({ dp, port, onClose }: { dp: DataProduct; port: Component; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [purpose, setPurpose] = useState('')
  const [consumer, setConsumer] = useState('')

  const mine = useQuery({
    queryKey: ['dataproducts', 'mine'],
    queryFn: () => api.get<DataProduct[]>('/dataproducts?scope=mine'),
  })

  const submit = useMutation({
    mutationFn: () =>
      api.post(`/marketplace/${dp.id}/access-requests`, {
        componentId: port.id,
        purpose,
        consumerDataProduct: consumer,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['marketplace', dp.id] })
      queryClient.invalidateQueries({ queryKey: ['access'] })
      onClose()
    },
  })

  return (
    <Modal
      title={`Request access to ${port.title}`}
      subtitle={port.urn}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => submit.mutate()}
            disabled={purpose.trim().length < 10 || submit.isPending}
          >
            {submit.isPending ? 'Sending…' : 'Send request'}
          </button>
        </>
      }
    >
      <div className="banner banner--info mb-2">
        <div>
          <strong>What you are agreeing to</strong> — {port.dataContract?.termsAndConditions || 'no specific terms declared.'}
        </div>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="purpose">Purpose<span className="field__req">*</span></label>
        <textarea
          id="purpose"
          className="textarea"
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          placeholder="What will you do with this data? The owning domain decides on this basis."
        />
        <div className="field__help">At least 10 characters.</div>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="consumer">Consuming data product</label>
        <select id="consumer" className="select" value={consumer} onChange={(e) => setConsumer(e.target.value)}>
          <option value="">Not on behalf of a data product</option>
          {mine.data?.map((product) => (
            <option key={product.id} value={product.urn}>{product.title}</option>
          ))}
        </select>
        <div className="field__help">
          Naming the consumer makes the dependency visible in the mesh lineage.
        </div>
      </div>

      {submit.error != null && <ErrorBanner error={submit.error} />}
    </Modal>
  )
}
