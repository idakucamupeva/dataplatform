import type { PolicyFinding, PolicyReport } from '@/api/types'
import { Badge } from '@/components/ui'

const ICON: Record<string, string> = { error: '!', warning: '!', info: 'i' }

export function PolicySummary({ report }: { report: PolicyReport | null | undefined }) {
  if (!report) return <Badge>not evaluated</Badge>
  if (report.passed && report.warningCount === 0) return <Badge tone="badge--ok">All policies pass</Badge>
  return (
    <div className="row" style={{ gap: 6 }}>
      {report.errorCount > 0 && <Badge tone="badge--danger">{report.errorCount} blocking</Badge>}
      {report.warningCount > 0 && <Badge tone="badge--warn">{report.warningCount} warnings</Badge>}
      {report.errorCount === 0 && <Badge tone="badge--ok">No blockers</Badge>}
    </div>
  )
}

export function FindingList({ findings }: { findings: PolicyFinding[] }) {
  if (findings.length === 0) {
    return (
      <div className="empty">
        <div className="empty__title">Every policy passes</div>
        <div className="small">This data product satisfies the federated governance rules in force.</div>
      </div>
    )
  }
  return (
    <div>
      {findings.map((finding, index) => (
        <div className="finding" key={`${finding.policyId}-${finding.target}-${index}`}>
          <span className={`finding__icon finding__icon--${finding.severity}`}>{ICON[finding.severity]}</span>
          <div className="finding__body">
            <div className="finding__msg">{finding.message}</div>
            <div className="finding__meta">
              {finding.policyName} · <span className="mono">{finding.category}</span>
              {finding.target && <> · <span className="mono">{finding.target}</span></>}
            </div>
            {finding.remediation && <div className="finding__fix">{finding.remediation}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
