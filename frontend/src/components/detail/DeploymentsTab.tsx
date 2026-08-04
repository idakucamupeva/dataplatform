import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, Deployment, DeploymentPlan, PlatformInfo } from '@/api/types'
import { Badge, Card, DeploymentBadge, EmptyState, ErrorBanner, Loading, Modal } from '@/components/ui'
import { formatDate, timeAgo } from '@/lib/format'

export function DeploymentsTab({ dp, canEdit }: { dp: DataProduct; canEdit: boolean }) {
  const queryClient = useQueryClient()
  const [logs, setLogs] = useState<Deployment | null>(null)
  const [planFor, setPlanFor] = useState<string | null>(null)

  const info = useQuery({ queryKey: ['platform'], queryFn: () => api.get<PlatformInfo>('/platform/info') })
  const history = useQuery({
    queryKey: ['deployments', dp.id],
    queryFn: () => api.get<Deployment[]>(`/dataproducts/${dp.id}/deployments`),
  })

  const deploy = useMutation({
    mutationFn: (environment: string) =>
      api.post<Deployment>(`/dataproducts/${dp.id}/deployments`, { environment }),
    onSuccess: (deployment) => {
      setLogs(deployment)
      queryClient.invalidateQueries({ queryKey: ['dataproduct', dp.id] })
      queryClient.invalidateQueries({ queryKey: ['deployments', dp.id] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  const destroy = useMutation({
    mutationFn: (environment: string) => api.del<Deployment>(`/dataproducts/${dp.id}/deployments?environment=${environment}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataproduct', dp.id] })
      queryClient.invalidateQueries({ queryKey: ['deployments', dp.id] })
    },
  })

  const openLogs = async (deploymentId: number) => {
    setLogs(await api.get<Deployment>(`/dataproducts/${dp.id}/deployments/${deploymentId}`))
  }

  return (
    <div className="stack">
      {deploy.error != null && <ErrorBanner error={deploy.error} />}
      {destroy.error != null && <ErrorBanner error={destroy.error} />}

      <div className="grid grid--3">
        {(dp.environments ?? []).map((env) => (
          <Card
            key={env.environment}
            title={<span className="mono">{env.environment}</span>}
            actions={<DeploymentBadge value={env.status} />}
          >
            <div className="stack stack--sm">
              <div className="small muted">
                {env.version ? <>Version <strong>{env.version}</strong></> : 'Never provisioned'}
                {env.deployedAt && <> · {timeAgo(env.deployedAt)}</>}
              </div>
              {env.environment === dp.gateEnvironment && (
                <div className="small faint">Publishing to the marketplace requires this environment.</div>
              )}
              {canEdit && (
                <div className="row" style={{ gap: 6 }}>
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    onClick={() => deploy.mutate(env.environment)}
                    disabled={deploy.isPending}
                  >
                    {env.status === 'provisioned' ? 'Re-provision' : 'Provision'}
                  </button>
                  <button type="button" className="btn btn--sm" onClick={() => setPlanFor(env.environment)}>
                    Plan
                  </button>
                  {env.status === 'provisioned' && (
                    <button
                      type="button"
                      className="btn btn--sm btn--danger"
                      onClick={() => { if (confirm(`Destroy the ${env.environment} deployment?`)) destroy.mutate(env.environment) }}
                    >
                      Destroy
                    </button>
                  )}
                </div>
              )}
              {env.deploymentId && (
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => openLogs(env.deploymentId!)}>
                  View logs
                </button>
              )}
            </div>
          </Card>
        ))}
      </div>

      <Card title="Deployment history" flush>
        {history.isLoading ? (
          <div className="card__body"><Loading /></div>
        ) : (history.data?.length ?? 0) === 0 ? (
          <EmptyState title="Never provisioned">
            Provision into {info.data?.environments[0] ?? 'development'} to see what the adapters would do.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>#</th><th>Environment</th><th>Version</th><th>Operation</th>
                  <th>Status</th><th>By</th><th>When</th><th />
                </tr>
              </thead>
              <tbody>
                {history.data!.map((deployment) => (
                  <tr key={deployment.id}>
                    <td className="faint mono">{deployment.id}</td>
                    <td className="mono">{deployment.environment}</td>
                    <td className="mono small">{deployment.version}</td>
                    <td className="small">{deployment.operation}</td>
                    <td><DeploymentBadge value={deployment.status} /></td>
                    <td className="small">{deployment.requestedBy?.displayName ?? '—'}</td>
                    <td className="small faint nowrap">{formatDate(deployment.finishedAt ?? deployment.startedAt)}</td>
                    <td>
                      <button type="button" className="btn btn--sm" onClick={() => openLogs(deployment.id)}>
                        Logs
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {logs && (
        <Modal
          title={`Deployment #${logs.id} — ${logs.environment}`}
          subtitle={<>version {logs.version} · <DeploymentBadge value={logs.status} /></>}
          wide
          onClose={() => setLogs(null)}
        >
          <div className="stack">
            {Object.keys(logs.outputs ?? {}).length > 0 && (
              <Card title="Provisioned resources" flush>
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Component</th><th>Resource</th><th>Value</th></tr></thead>
                    <tbody>
                      {Object.entries(logs.outputs).flatMap(([component, outputs]) =>
                        Object.entries(outputs).map(([key, value]) => (
                          <tr key={`${component}-${key}`}>
                            <td className="mono small">{component}</td>
                            <td className="small">{key}</td>
                            <td className="mono small" style={{ wordBreak: 'break-all' }}>{String(value)}</td>
                          </tr>
                        )),
                      )}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
            <pre className="code-block code-block--terminal">{(logs.logs ?? []).join('\n')}</pre>
          </div>
        </Modal>
      )}

      {planFor && <PlanModal dp={dp} environment={planFor} onClose={() => setPlanFor(null)} />}
    </div>
  )
}

function PlanModal({ dp, environment, onClose }: { dp: DataProduct; environment: string; onClose: () => void }) {
  const plan = useQuery({
    queryKey: ['plan', dp.id, environment],
    queryFn: () => api.post<DeploymentPlan>(`/dataproducts/${dp.id}/deployments/plan?environment=${environment}`),
  })

  return (
    <Modal title={`Plan — ${environment}`} subtitle="What the coordinator would run, in order" onClose={onClose}>
      {plan.isLoading ? (
        <Loading rows={4} />
      ) : (
        <div className="stack">
          {(plan.data?.problems.length ?? 0) > 0 && (
            <div className="banner banner--error">
              <div>
                <strong>This plan would be refused</strong>
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                  {plan.data!.problems.map((problem) => <li key={problem}>{problem}</li>)}
                </ul>
              </div>
            </div>
          )}
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>#</th><th>Component</th><th>Kind</th><th>Adapter</th></tr></thead>
              <tbody>
                {plan.data?.steps.map((step, index) => (
                  <tr key={step.component}>
                    <td className="faint">{index + 1}</td>
                    <td className="mono">{step.component}</td>
                    <td><Badge>{step.kind}</Badge></td>
                    <td className="small">
                      {step.provisioner ?? <span className="badge badge--danger">no adapter</span>}
                      {step.platform && <span className="faint"> · {step.platform}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="small muted">
            Storage is created first, then workloads, then output ports, then observability — so every
            component exists by the time something else points at it.
          </div>
        </div>
      )}
    </Modal>
  )
}
