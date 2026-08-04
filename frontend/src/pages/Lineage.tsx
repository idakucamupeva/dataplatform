import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, LineageGraph as Graph } from '@/api/types'
import { Badge, Card, Loading } from '@/components/ui'
import { LineageGraph } from '@/components/LineageGraph'

export function LineagePage() {
  const navigate = useNavigate()
  const graph = useQuery({ queryKey: ['lineage'], queryFn: () => api.get<Graph>('/lineage') })
  const products = useQuery({ queryKey: ['dataproducts', 'all'], queryFn: () => api.get<DataProduct[]>('/dataproducts') })

  const byUrn = new Map((products.data ?? []).map((dp) => [dp.urn, dp]))
  const unresolved = graph.data?.edges.filter((edge) => !edge.resolved) ?? []

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>Mesh lineage</h1>
          <div className="page-sub">
            How data flows between domains. An arrow means the target consumes an output port of the
            source — the only sanctioned way for one data product to depend on another.
          </div>
        </div>
      </div>

      <Card title="The mesh" flush>
        {graph.isLoading ? (
          <div className="card__body"><Loading rows={6} /></div>
        ) : (
          <LineageGraph
            graph={graph.data!}
            onSelect={(urn) => {
              const dp = byUrn.get(urn)
              if (dp) navigate(`/products/${dp.id}`)
            }}
          />
        )}
      </Card>

      <div className="grid grid--2">
        <Card title="Dependencies" flush>
          {(graph.data?.edges.length ?? 0) === 0 ? (
            <div className="card__body muted small">No data product consumes another one yet.</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Producer</th><th>Consumer</th><th>Via output port</th><th>Status</th></tr></thead>
                <tbody>
                  {graph.data!.edges.map((edge, index) => (
                    <tr key={index}>
                      <td className="small">{byUrn.get(edge.source)?.title ?? edge.source}</td>
                      <td className="small">{byUrn.get(edge.target)?.title ?? edge.target}</td>
                      <td><code className="urn">{edge.port}</code></td>
                      <td>
                        <Badge tone={edge.resolved ? 'badge--ok' : 'badge--warn'}>
                          {edge.resolved ? 'published' : 'dangling'}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Health">
          <div className="stack stack--sm">
            <div className="row row--between">
              <span className="small">Data products in the graph</span>
              <Badge>{graph.data?.nodes.length ?? 0}</Badge>
            </div>
            <div className="row row--between">
              <span className="small">Dependencies</span>
              <Badge>{graph.data?.edges.length ?? 0}</Badge>
            </div>
            <div className="row row--between">
              <span className="small">Dangling dependencies</span>
              <Badge tone={unresolved.length > 0 ? 'badge--warn' : 'badge--ok'}>{unresolved.length}</Badge>
            </div>
          </div>
          <p className="small muted mt-2 mb-0">
            A dangling dependency points at an output port that is not published — either the producer
            has not released it yet, or the URN is wrong. Governance reports it as a blocking finding.
          </p>
        </Card>
      </div>
    </div>
  )
}
