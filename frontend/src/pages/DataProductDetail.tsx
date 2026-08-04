import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, LineageGraph as Graph, PlatformEvent, PolicyEvaluation, PolicyReport } from '@/api/types'
import {
  Badge, Card, EmptyState, ErrorBanner, LifecycleBadge, LifecycleTrail, Loading, Modal, Tabs, Urn,
} from '@/components/ui'
import { FindingList, PolicySummary } from '@/components/PolicyFindings'
import { ComponentsTab } from '@/components/detail/ComponentsTab'
import { DescriptorTab } from '@/components/detail/DescriptorTab'
import { DeploymentsTab } from '@/components/detail/DeploymentsTab'
import { RepositoryTab } from '@/components/detail/RepositoryTab'
import { LineageGraph } from '@/components/LineageGraph'
import { formatDate, timeAgo } from '@/lib/format'
import { DomainChip } from '@/pages/Overview'

type TabId = 'overview' | 'components' | 'descriptor' | 'governance' | 'deployments' | 'lineage' | 'repository'

export function DataProductDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<TabId>('overview')
  const [releasing, setReleasing] = useState(false)

  const dpQuery = useQuery({
    queryKey: ['dataproduct', Number(id)],
    queryFn: () => api.get<DataProduct>(`/dataproducts/${id}`),
  })
  const dp = dpQuery.data

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['dataproduct', Number(id)] })
    queryClient.invalidateQueries({ queryKey: ['metrics'] })
    queryClient.invalidateQueries({ queryKey: ['dataproducts'] })
  }

  const validate = useMutation({
    mutationFn: () => api.post<PolicyReport>(`/dataproducts/${id}/validate`),
    onSuccess: () => { invalidate(); setTab('governance') },
  })
  const submit = useMutation({
    mutationFn: () => api.post(`/dataproducts/${id}/submit`),
    onSuccess: invalidate,
  })
  const publish = useMutation({
    mutationFn: () => api.post(`/dataproducts/${id}/publish`),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: () => api.del(`/dataproducts/${id}`),
    onSuccess: () => { invalidate(); navigate('/products') },
  })

  if (dpQuery.isLoading) return <Loading rows={8} />
  if (dpQuery.error || !dp) return <ErrorBanner error={dpQuery.error ?? 'Not found'} />

  const canEdit = Boolean(dp.canEdit)
  const busyError = validate.error ?? submit.error ?? publish.error ?? remove.error

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <div className="row row--wrap mb-1" style={{ gap: 6 }}>
            <DomainChip name={dp.domain} />
            <LifecycleBadge value={dp.lifecycle} />
            <Badge tone={dp.maturity === 'strategic' ? 'badge--violet' : ''}>{dp.maturity}</Badge>
            <Badge>v{dp.version}</Badge>
          </div>
          <h1>{dp.title}</h1>
          <div className="page-sub">{dp.description}</div>
          <div className="mt-1"><Urn value={dp.urn} /></div>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn" onClick={() => validate.mutate()} disabled={validate.isPending}>
            {validate.isPending ? 'Checking…' : 'Run policies'}
          </button>
          {canEdit && dp.lifecycle === 'draft' && (
            <button type="button" className="btn" onClick={() => submit.mutate()} disabled={submit.isPending}>
              Submit for review
            </button>
          )}
          {canEdit && (dp.lifecycle === 'draft' || dp.lifecycle === 'in_review') && (
            <button type="button" className="btn btn--primary" onClick={() => setReleasing(true)}>
              Release version
            </button>
          )}
          {canEdit && dp.lifecycle === 'released' && (
            <button type="button" className="btn btn--primary" onClick={() => publish.mutate()} disabled={publish.isPending}>
              {publish.isPending ? 'Publishing…' : 'Publish to marketplace'}
            </button>
          )}
          {dp.lifecycle === 'published' && (
            <Link className="btn" to={`/marketplace/${dp.id}`}>View in marketplace</Link>
          )}
        </div>
      </div>

      {busyError != null && <ErrorBanner error={busyError} />}

      <LifecycleTrail value={dp.lifecycle} />

      <Tabs<TabId>
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'overview', label: 'Overview' },
          { id: 'components', label: 'Components', count: dp.componentCount },
          { id: 'descriptor', label: 'Descriptor' },
          { id: 'governance', label: 'Governance', count: dp.policy?.errorCount },
          { id: 'deployments', label: 'Deployments' },
          { id: 'lineage', label: 'Lineage', count: dp.dependencies?.length },
          { id: 'repository', label: 'Repository' },
        ]}
      />

      {tab === 'overview' && <OverviewTab dp={dp} onGoto={setTab} canDelete={canEdit} onDelete={() => {
        if (confirm(`Delete ${dp.title} and its repository? This cannot be undone.`)) remove.mutate()
      }} />}
      {tab === 'components' && <ComponentsTab dp={dp} canEdit={canEdit} />}
      {tab === 'descriptor' && <DescriptorTab dp={dp} canEdit={canEdit} />}
      {tab === 'governance' && <GovernanceTab dp={dp} />}
      {tab === 'deployments' && <DeploymentsTab dp={dp} canEdit={canEdit} />}
      {tab === 'lineage' && <LineageTab dp={dp} />}
      {tab === 'repository' && <RepositoryTab dp={dp} />}

      {releasing && <ReleaseModal dp={dp} onClose={() => setReleasing(false)} onDone={invalidate} />}
    </div>
  )
}

/* ------------------------------------------------------------- overview */
function OverviewTab({
  dp, onGoto, canDelete, onDelete,
}: {
  dp: DataProduct
  onGoto: (tab: TabId) => void
  canDelete: boolean
  onDelete: () => void
}) {
  const events = useQuery({
    queryKey: ['dp-events', dp.id],
    queryFn: () => api.get<PlatformEvent[]>(`/dataproducts/${dp.id}/events?limit=15`),
  })

  const ports = (dp.components ?? []).filter((c) => c.kind === 'outputport')

  return (
    <div className="split">
      <div className="stack">
        <Card title="Next step">
          <NextStep dp={dp} onGoto={onGoto} />
        </Card>

        <Card
          title={`Output ports (${ports.length})`}
          actions={<button type="button" className="btn btn--sm" onClick={() => onGoto('components')}>Manage</button>}
          flush
        >
          {ports.length === 0 ? (
            <EmptyState title="No output port yet">
              A data product with no output port cannot be consumed — governance blocks the release.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Port</th><th>Technology</th><th>Contract</th><th>Endpoint</th></tr></thead>
                <tbody>
                  {ports.map((port) => (
                    <tr key={port.id}>
                      <td>
                        <strong>{port.title}</strong>
                        <div className="small muted">{port.description}</div>
                      </td>
                      <td><Badge>{port.technology}</Badge></td>
                      <td className="small">
                        {port.columnCount} columns
                        {port.hasPii && <> · <Badge tone="badge--warn">pii</Badge></>}
                      </td>
                      <td className="mono small" style={{ wordBreak: 'break-all' }}>{port.endpoint}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Activity" flush>
          {events.isLoading ? (
            <div className="card__body"><Loading /></div>
          ) : (
            <div className="card__body">
              <div className="timeline">
                {events.data?.map((event) => (
                  <div className="timeline__item" key={event.id}>
                    <span className="timeline__dot" />
                    <div>{event.message}</div>
                    <div className="timeline__meta">
                      {event.actor?.displayName ?? 'system'} · {timeAgo(event.createdAt)}
                      {event.payload?.commit && <> · <code>{String(event.payload.commit).slice(0, 8)}</code></>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="stack">
        <Card title="Governance" actions={<PolicySummary report={dp.policy} />}>
          <div className="stack stack--sm">
            <div className="small muted">
              {dp.policy
                ? `Last evaluated ${timeAgo(dp.policy.createdAt)} (${dp.policy.trigger}).`
                : 'Not evaluated yet.'}
            </div>
            <button type="button" className="btn btn--sm" onClick={() => onGoto('governance')}>See findings</button>
          </div>
        </Card>

        <Card title="Details">
          <dl className="kv">
            <dt>Owner</dt><dd>{dp.owner?.displayName} <span className="faint">{dp.owner?.email}</span></dd>
            <dt>Domain</dt><dd>{dp.domainTitle}</dd>
            <dt>Maturity</dt><dd>{dp.maturity}</dd>
            <dt>Version</dt><dd>v{dp.version}</dd>
            <dt>Components</dt><dd>{dp.componentCount}</dd>
            <dt>Created</dt><dd>{formatDate(dp.createdAt)}</dd>
            <dt>Updated</dt><dd>{formatDate(dp.updatedAt)}</dd>
            {dp.publishedAt && (<><dt>Published</dt><dd>{formatDate(dp.publishedAt)}</dd></>)}
          </dl>
          {dp.tags.length > 0 && (
            <div className="row row--wrap mt-2" style={{ gap: 5 }}>
              {dp.tags.map((tag) => <span className="badge" key={tag}>{tag}</span>)}
            </div>
          )}
        </Card>

        <Card title="Environments">
          <div className="stack stack--sm">
            {(dp.environments ?? []).map((env) => (
              <div className="row row--between" key={env.environment}>
                <span className="mono small">{env.environment}</span>
                <span className={`badge ${env.status === 'provisioned' ? 'badge--ok' : env.status === 'failed' ? 'badge--danger' : ''}`}>
                  {env.status.replace('_', ' ')}
                </span>
              </div>
            ))}
          </div>
        </Card>

        {canDelete && dp.lifecycle !== 'published' && (
          <Card title="Danger zone">
            <p className="small muted">
              Deleting removes the catalog entry and the git repository. Published products must be
              retired first.
            </p>
            <button type="button" className="btn btn--danger btn--sm" onClick={onDelete}>Delete data product</button>
          </Card>
        )}
      </div>
    </div>
  )
}

function NextStep({ dp, onGoto }: { dp: DataProduct; onGoto: (tab: TabId) => void }) {
  const ports = dp.outputPortCount
  const errors = dp.policy?.errorCount ?? 0
  const gateEnv = dp.gateEnvironment ?? 'production'
  const gateDeployed = (dp.environments ?? []).some((e) => e.environment === gateEnv && e.status === 'provisioned')

  let message: string
  let action: { label: string; tab: TabId } | null = null

  if (ports === 0) {
    message = 'Add an output port — without one the product has no interface and cannot be released.'
    action = { label: 'Add components', tab: 'components' }
  } else if (errors > 0) {
    message = `${errors} governance finding${errors === 1 ? '' : 's'} block the release.`
    action = { label: 'Review findings', tab: 'governance' }
  } else if (dp.lifecycle === 'draft') {
    message = 'Everything passes. Submit for governance review, or release a version straight away.'
  } else if (dp.lifecycle === 'in_review') {
    message = 'Waiting for federated governance to release the version. The descriptor is frozen meanwhile.'
  } else if (dp.lifecycle === 'released' && !gateDeployed) {
    message = `Released. Provision into ${gateEnv} before publishing to the marketplace.`
    action = { label: 'Provision', tab: 'deployments' }
  } else if (dp.lifecycle === 'released') {
    message = 'Provisioned and released — publish it so consumers can find and request it.'
  } else if (dp.lifecycle === 'published') {
    message = 'Live in the marketplace. Changes here need a new release before consumers see them.'
  } else {
    message = 'This data product is retired.'
  }

  return (
    <div className="row row--wrap">
      <span>{message}</span>
      {action && (
        <button type="button" className="btn btn--sm" onClick={() => onGoto(action!.tab)}>{action.label}</button>
      )}
    </div>
  )
}

/* ----------------------------------------------------------- governance */
function GovernanceTab({ dp }: { dp: DataProduct }) {
  const history = useQuery({
    queryKey: ['policy-history', dp.id],
    queryFn: () => api.get<PolicyEvaluation[]>(`/dataproducts/${dp.id}/policy-history`),
  })
  const policies = useQuery({
    queryKey: ['policies'],
    queryFn: () => api.get<{ id: string; name: string; description: string; category: string }[]>('/policies'),
  })

  const latest = history.data?.[0] ?? dp.policy ?? null

  return (
    <div className="split">
      <div className="stack">
        <Card
          title="Latest evaluation"
          actions={<PolicySummary report={latest} />}
          flush
        >
          {history.isLoading ? (
            <div className="card__body"><Loading /></div>
          ) : latest ? (
            <FindingList findings={latest.findings} />
          ) : (
            <EmptyState title="Not evaluated yet">Run the policies from the header to see where this product stands.</EmptyState>
          )}
        </Card>

        <Card title="Evaluation history" flush>
          {(history.data?.length ?? 0) === 0 ? (
            <div className="card__body muted small">No evaluation recorded yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>When</th><th>Trigger</th><th>Result</th><th>Blocking</th><th>Warnings</th></tr></thead>
                <tbody>
                  {history.data!.map((evaluation) => (
                    <tr key={evaluation.id}>
                      <td className="small faint nowrap">{formatDate(evaluation.createdAt)}</td>
                      <td className="small mono">{evaluation.trigger}</td>
                      <td>
                        <Badge tone={evaluation.passed ? 'badge--ok' : 'badge--danger'}>
                          {evaluation.passed ? 'passed' : 'blocked'}
                        </Badge>
                      </td>
                      <td>{evaluation.errorCount}</td>
                      <td>{evaluation.warningCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Card title="Policies in force" flush>
        {policies.isLoading ? (
          <div className="card__body"><Loading /></div>
        ) : (
          <div>
            {policies.data?.map((policy) => (
              <div key={policy.id} style={{ padding: '11px 14px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontWeight: 580 }}>{policy.name}</div>
                <div className="small muted">{policy.description}</div>
                <div className="small faint mt-1"><code>{policy.id}</code> · {policy.category}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------- lineage */
function LineageTab({ dp }: { dp: DataProduct }) {
  const graph = useQuery({
    queryKey: ['dp-lineage', dp.id],
    queryFn: () => api.get<Graph>(`/dataproducts/${dp.id}/lineage?depth=3`),
  })

  return (
    <div className="stack">
      <Card title="Consumption graph" flush>
        {graph.isLoading ? <div className="card__body"><Loading rows={5} /></div> : <LineageGraph graph={graph.data!} />}
      </Card>

      <Card title="Declared dependencies" flush>
        {(dp.dependencies?.length ?? 0) === 0 ? (
          <div className="card__body muted small">
            This data product does not consume any other product's output port.
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Output port</th><th>Producing data product</th><th>Status</th></tr></thead>
              <tbody>
                {dp.dependencies!.map((dependency) => (
                  <tr key={dependency.portUrn}>
                    <td><Urn value={dependency.portUrn} /></td>
                    <td className="mono small">{dependency.dataProductUrn}</td>
                    <td>
                      <Badge tone={dependency.resolved ? 'badge--ok' : 'badge--warn'}>
                        {dependency.resolved ? 'resolved' : 'not published'}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

/* -------------------------------------------------------------- release */
function ReleaseModal({ dp, onClose, onDone }: { dp: DataProduct; onClose: () => void; onDone: () => void }) {
  const [version, setVersion] = useState(bump(dp.version))
  const [notes, setNotes] = useState('')

  const release = useMutation({
    mutationFn: () => api.post(`/dataproducts/${dp.id}/release`, { version, notes }),
    onSuccess: () => { onDone(); onClose() },
  })

  return (
    <Modal
      title="Release a version"
      subtitle="Freezes the descriptor, tags the repository and makes the version deployable to production."
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn--primary" onClick={() => release.mutate()} disabled={release.isPending}>
            {release.isPending ? 'Releasing…' : `Release v${version}`}
          </button>
        </>
      }
    >
      <div className="field">
        <label className="field__label" htmlFor="version">Version</label>
        <input id="version" className="input input--mono" value={version} onChange={(e) => setVersion(e.target.value)} />
        <div className="field__help">
          Semantic version. Changing the major number mints a new URN, so existing consumers keep
          resolving to the contract they signed up for.
        </div>
      </div>
      <div className="field">
        <label className="field__label" htmlFor="notes">Release notes</label>
        <textarea id="notes" className="textarea" value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="What changed for consumers?" />
      </div>
      {release.error != null && <ErrorBanner error={release.error} />}
    </Modal>
  )
}

function bump(version: string): string {
  const [major, minor] = version.split('.').map(Number)
  return `${major}.${(minor ?? 0) + 1}.0`
}
