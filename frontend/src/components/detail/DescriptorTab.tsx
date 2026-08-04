import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, PolicyReport } from '@/api/types'
import { Card, ErrorBanner, Loading } from '@/components/ui'
import { FindingList, PolicySummary } from '@/components/PolicyFindings'

/**
 * Direct editing of the source of truth. The textarea holds exactly what is in
 * the repository; saving commits it and re-runs the policies.
 */
export function DescriptorTab({ dp, canEdit }: { dp: DataProduct; canEdit: boolean }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const [message, setMessage] = useState('chore: update descriptor')
  const [report, setReport] = useState<PolicyReport | null>(null)

  const descriptor = useQuery({
    queryKey: ['descriptor', dp.id, dp.headCommit],
    queryFn: () => api.get<{ content: string }>(`/dataproducts/${dp.id}/descriptor`),
  })

  useEffect(() => {
    if (descriptor.data) setDraft(descriptor.data.content)
  }, [descriptor.data])

  const save = useMutation({
    mutationFn: () => api.put<{ policy: PolicyReport }>(`/dataproducts/${dp.id}/descriptor`, { content: draft, message }),
    onSuccess: (result) => {
      setReport(result.policy)
      queryClient.invalidateQueries({ queryKey: ['dataproduct', dp.id] })
      queryClient.invalidateQueries({ queryKey: ['descriptor', dp.id] })
    },
  })

  const dirty = descriptor.data ? draft !== descriptor.data.content : false

  return (
    <div className="split">
      <Card
        title={
          <span className="row" style={{ gap: 8 }}>
            <code className="mono">data-product-descriptor.yaml</code>
            {dirty && <span className="badge badge--warn">unsaved</span>}
          </span>
        }
        actions={
          canEdit ? (
            <div className="row" style={{ gap: 6 }}>
              <input
                className="input"
                style={{ width: 260 }}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="commit message"
              />
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={() => save.mutate()}
                disabled={!dirty || save.isPending}
              >
                {save.isPending ? 'Committing…' : 'Commit'}
              </button>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => setDraft(descriptor.data?.content ?? '')}
                disabled={!dirty}
              >
                Revert
              </button>
            </div>
          ) : undefined
        }
      >
        {descriptor.isLoading ? (
          <Loading rows={8} />
        ) : (
          <>
            {save.error != null && <div className="mb-2"><ErrorBanner error={save.error} /></div>}
            <textarea
              className="editor"
              spellCheck={false}
              value={draft}
              readOnly={!canEdit}
              onChange={(e) => setDraft(e.target.value)}
            />
            <div className="small faint mt-1">
              {draft.split('\n').length} lines · the file is committed to the product repository on save
            </div>
          </>
        )}
      </Card>

      <div className="stack">
        <Card title="After the last save">
          {report ? (
            <div className="stack stack--sm">
              <PolicySummary report={report} />
              <div className="small muted">
                {report.passed
                  ? 'Nothing blocks a release.'
                  : 'Fix the blocking findings before releasing this version.'}
              </div>
            </div>
          ) : (
            <div className="small muted">Commit a change to see how governance reacts to it.</div>
          )}
        </Card>

        {report && report.findings.length > 0 && (
          <Card title="Findings" flush>
            <FindingList findings={report.findings} />
          </Card>
        )}

        <Card title="How this file is used">
          <ul className="small muted" style={{ paddingLeft: 18, margin: 0, lineHeight: 1.8 }}>
            <li>It is the <strong>source of truth</strong>; the catalog is rebuilt from it on every commit.</li>
            <li>URNs are derived, never authored — editing the name or domain is refused.</li>
            <li>Every provisioner reads the <code>specific</code> block of its own component.</li>
            <li>Releasing tags the repository and freezes a copy of this file.</li>
          </ul>
        </Card>
      </div>
    </div>
  )
}
