import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, RepositoryInfo, Version } from '@/api/types'
import { Badge, Card, Loading } from '@/components/ui'
import { formatDate, timeAgo } from '@/lib/format'

export function RepositoryTab({ dp }: { dp: DataProduct }) {
  const [path, setPath] = useState<string>(dp.name ? 'data-product-descriptor.yaml' : '')

  const repo = useQuery({
    queryKey: ['repository', dp.id, dp.headCommit],
    queryFn: () => api.get<RepositoryInfo>(`/dataproducts/${dp.id}/repository`),
  })
  const file = useQuery({
    queryKey: ['repofile', dp.id, path, dp.headCommit],
    queryFn: () => api.get<{ content: string }>(`/dataproducts/${dp.id}/repository/file?path=${encodeURIComponent(path)}`),
    enabled: Boolean(path),
  })
  const versions = useQuery({
    queryKey: ['versions', dp.id],
    queryFn: () => api.get<Version[]>(`/dataproducts/${dp.id}/versions`),
  })

  return (
    <div className="stack">
      <Card title="Repository">
        <dl className="kv">
          <dt>Location</dt><dd className="mono small">{repo.data?.path ?? dp.repoPath}</dd>
          <dt>Branch</dt><dd className="mono small">main</dd>
          <dt>HEAD</dt><dd className="mono small">{dp.headCommit}</dd>
          <dt>Release tags</dt>
          <dd>
            {(repo.data?.tags.length ?? 0) === 0
              ? <span className="faint">none yet</span>
              : repo.data!.tags.map((tag) => <Badge key={tag} tone="badge--info">{tag}</Badge>)}
          </dd>
        </dl>
      </Card>

      <div className="split">
        <Card title={<span className="mono">{path || 'select a file'}</span>} flush>
          {file.isLoading ? (
            <div className="card__body"><Loading rows={6} /></div>
          ) : (
            <pre className="code-block" style={{ border: 'none', borderRadius: 0, maxHeight: 520 }}>
              {file.data?.content ?? ''}
            </pre>
          )}
        </Card>

        <div className="stack">
          <Card title="Files" flush>
            {repo.isLoading ? (
              <div className="card__body"><Loading /></div>
            ) : (
              <div className="file-tree" style={{ padding: 6 }}>
                {repo.data?.files.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className={`file-tree__item ${name === path ? 'is-active' : ''}`}
                    style={{ width: '100%', border: 'none', background: 'none', textAlign: 'left' }}
                    onClick={() => setPath(name)}
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}
          </Card>

          <Card title="Commits" flush>
            {repo.isLoading ? (
              <div className="card__body"><Loading /></div>
            ) : (
              <div className="card__body">
                <div className="timeline">
                  {repo.data?.commits.map((commit) => (
                    <div className="timeline__item" key={commit.sha}>
                      <span className="timeline__dot" />
                      <div>{commit.message}</div>
                      <div className="timeline__meta">
                        <code>{commit.shortSha}</code> · {commit.author} · {timeAgo(commit.date)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>

      <Card title="Released versions" flush>
        {(versions.data?.length ?? 0) === 0 ? (
          <div className="card__body muted small">No version has been released yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Version</th><th>Notes</th><th>Commit</th><th>Released by</th><th>When</th></tr></thead>
              <tbody>
                {versions.data!.map((version) => (
                  <tr key={version.id}>
                    <td><Badge tone="badge--info">v{version.version}</Badge></td>
                    <td className="small">{version.notes || <span className="faint">—</span>}</td>
                    <td className="mono small">{version.commit}</td>
                    <td className="small">{version.createdBy?.displayName ?? '—'}</td>
                    <td className="small faint nowrap">{formatDate(version.createdAt)}</td>
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
