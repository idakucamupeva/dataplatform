import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { LineageGraph as Graph } from '@/api/types'
import { colourFor } from '@/lib/format'

const NODE_W = 190
const NODE_H = 58
const GAP_X = 90
const GAP_Y = 26

/**
 * A small layered DAG renderer.
 *
 * Nodes are assigned to a column by longest-path depth from a source, which is
 * enough for the shallow graphs a mesh produces and keeps every edge pointing
 * left-to-right, producer -> consumer.
 */
export function LineageGraph({ graph, onSelect }: { graph: Graph; onSelect?: (urn: string) => void }) {
  const navigate = useNavigate()

  const layout = useMemo(() => {
    const incoming = new Map<string, string[]>()
    const outgoing = new Map<string, string[]>()
    for (const node of graph.nodes) {
      incoming.set(node.urn, [])
      outgoing.set(node.urn, [])
    }
    for (const edge of graph.edges) {
      if (!incoming.has(edge.target) || !outgoing.has(edge.source)) continue
      incoming.get(edge.target)!.push(edge.source)
      outgoing.get(edge.source)!.push(edge.target)
    }

    // longest path from any root, with a visited guard so cycles cannot hang
    const depth = new Map<string, number>()
    const resolve = (urn: string, seen: Set<string>): number => {
      if (depth.has(urn)) return depth.get(urn)!
      if (seen.has(urn)) return 0
      seen.add(urn)
      const parents = incoming.get(urn) ?? []
      const value = parents.length === 0 ? 0 : Math.max(...parents.map((p) => resolve(p, seen) + 1))
      depth.set(urn, value)
      return value
    }
    for (const node of graph.nodes) resolve(node.urn, new Set())

    const columns = new Map<number, string[]>()
    for (const node of graph.nodes) {
      const column = depth.get(node.urn) ?? 0
      if (!columns.has(column)) columns.set(column, [])
      columns.get(column)!.push(node.urn)
    }

    const position = new Map<string, { x: number; y: number }>()
    let height = 0
    for (const [column, urns] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
      urns.sort()
      urns.forEach((urn, index) => {
        position.set(urn, { x: 20 + column * (NODE_W + GAP_X), y: 20 + index * (NODE_H + GAP_Y) })
      })
      height = Math.max(height, urns.length * (NODE_H + GAP_Y))
    }

    const width = 40 + (Math.max(...columns.keys(), 0) + 1) * (NODE_W + GAP_X) - GAP_X
    return { position, width: Math.max(width, 320), height: Math.max(height + 20, 140) }
  }, [graph])

  if (graph.nodes.length === 0) {
    return <div className="empty"><div className="empty__title">No lineage yet</div><div className="small">Dependencies appear here once a data product consumes another product's output port.</div></div>
  }

  return (
    <div className="graph-canvas">
      <svg width={layout.width} height={layout.height} role="img" aria-label="Lineage graph">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--border-strong)" />
          </marker>
        </defs>

        {graph.edges.map((edge, index) => {
          const from = layout.position.get(edge.source)
          const to = layout.position.get(edge.target)
          if (!from || !to) return null
          const x1 = from.x + NODE_W
          const y1 = from.y + NODE_H / 2
          const x2 = to.x
          const y2 = to.y + NODE_H / 2
          const mid = (x1 + x2) / 2
          return (
            <path
              key={index}
              className={`graph-edge ${edge.resolved ? '' : 'graph-edge--unresolved'}`}
              d={`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`}
              markerEnd="url(#arrow)"
            >
              <title>{edge.port}</title>
            </path>
          )
        })}

        {graph.nodes.map((node) => {
          const at = layout.position.get(node.urn)
          if (!at) return null
          const id = node.urn.split(':')
          return (
            <g
              key={node.urn}
              className={`graph-node ${node.isRoot ? 'is-root' : ''}`}
              transform={`translate(${at.x}, ${at.y})`}
              onClick={() => (onSelect ? onSelect(node.urn) : navigate(`/products?q=${encodeURIComponent(node.name)}`))}
            >
              <title>{node.urn}</title>
              <rect width={NODE_W} height={NODE_H} />
              <rect width={4} height={NODE_H} rx={2} fill={colourFor(node.domain)} />
              <text x={14} y={23}>
                {node.title.length > 22 ? `${node.title.slice(0, 22)}…` : node.title}
              </text>
              <text x={14} y={40} className="graph-node__sub">
                {node.domain} · {node.external ? 'external' : node.lifecycle}
                {node.outputPorts !== undefined && ` · ${node.outputPorts} port${node.outputPorts === 1 ? '' : 's'}`}
              </text>
              <text x={14} y={52} className="graph-node__sub">{id.slice(3, 5).join(':')}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
