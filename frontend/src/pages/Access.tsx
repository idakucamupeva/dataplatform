import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { AccessRequest } from '@/api/types'
import { Badge, Card, EmptyState, ErrorBanner, Loading, Modal, Tabs } from '@/components/ui'
import { formatDate, timeAgo } from '@/lib/format'

const STATUS_TONE: Record<string, string> = {
  pending: 'badge--warn',
  approved: 'badge--ok',
  rejected: 'badge--danger',
  revoked: 'badge--danger',
}

export function AccessPage() {
  const [tab, setTab] = useState<'inbox' | 'outbox' | 'subscriptions'>('inbox')
  const queryClient = useQueryClient()
  const [deciding, setDeciding] = useState<{ request: AccessRequest; approve: boolean } | null>(null)

  const inbox = useQuery({ queryKey: ['access', 'inbox'], queryFn: () => api.get<AccessRequest[]>('/marketplace/access-requests/inbox') })
  const outbox = useQuery({ queryKey: ['access', 'outbox'], queryFn: () => api.get<AccessRequest[]>('/marketplace/access-requests/outbox') })
  const subscriptions = useQuery({ queryKey: ['access', 'subs'], queryFn: () => api.get<AccessRequest[]>('/marketplace/me/subscriptions') })

  const revoke = useMutation({
    mutationFn: (id: number) => api.post(`/marketplace/access-requests/${id}/revoke`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['access'] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
    },
  })

  const pending = inbox.data?.filter((r) => r.status === 'pending') ?? []
  const decided = inbox.data?.filter((r) => r.status !== 'pending') ?? []

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>Access requests</h1>
          <div className="page-sub">
            Access is a conversation between two domains: a consumer states a purpose, the producer decides.
          </div>
        </div>
      </div>

      {revoke.error != null && <ErrorBanner error={revoke.error} />}

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'inbox', label: 'To decide', count: pending.length },
          { id: 'outbox', label: 'My requests', count: outbox.data?.length },
          { id: 'subscriptions', label: 'My subscriptions', count: subscriptions.data?.length },
        ]}
      />

      {tab === 'inbox' && (
        <div className="stack">
          <Card title="Waiting for you" flush>
            {inbox.isLoading ? (
              <div className="card__body"><Loading /></div>
            ) : pending.length === 0 ? (
              <EmptyState title="Nothing to decide">
                Requests for output ports of the data products you own show up here.
              </EmptyState>
            ) : (
              <RequestTable
                requests={pending}
                showRequester
                actions={(request) => (
                  <div className="row" style={{ gap: 5, justifyContent: 'flex-end' }}>
                    <button type="button" className="btn btn--primary btn--sm" onClick={() => setDeciding({ request, approve: true })}>
                      Approve
                    </button>
                    <button type="button" className="btn btn--danger btn--sm" onClick={() => setDeciding({ request, approve: false })}>
                      Reject
                    </button>
                  </div>
                )}
              />
            )}
          </Card>

          {decided.length > 0 && (
            <Card title="Already decided" flush>
              <RequestTable
                requests={decided}
                showRequester
                actions={(request) =>
                  request.status === 'approved' ? (
                    <button type="button" className="btn btn--sm btn--danger" onClick={() => revoke.mutate(request.id)}>
                      Revoke
                    </button>
                  ) : null
                }
              />
            </Card>
          )}
        </div>
      )}

      {tab === 'outbox' && (
        <Card title="Requests you have made" flush>
          {outbox.isLoading ? (
            <div className="card__body"><Loading /></div>
          ) : (outbox.data?.length ?? 0) === 0 ? (
            <EmptyState title="You have not requested anything yet" action={<Link className="btn btn--primary" to="/marketplace">Browse the marketplace</Link>} />
          ) : (
            <RequestTable requests={outbox.data!} />
          )}
        </Card>
      )}

      {tab === 'subscriptions' && (
        <Card title="Output ports you can use" flush>
          {(subscriptions.data?.length ?? 0) === 0 ? (
            <EmptyState title="No granted access yet">
              Once a producer approves a request it appears here with the endpoint you can connect to.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Output port</th><th>Data product</th><th>Granted</th><th /></tr></thead>
                <tbody>
                  {subscriptions.data!.map((request) => (
                    <tr key={request.id}>
                      <td>
                        <strong>{request.component?.title ?? '—'}</strong>
                        <div className="small mono faint">{request.component?.urn}</div>
                      </td>
                      <td>
                        <Link to={`/marketplace/${request.dataProduct.id}`}>{request.dataProduct.title}</Link>
                        <div className="small faint">{request.dataProduct.domain}</div>
                      </td>
                      <td className="small faint nowrap">{timeAgo(request.decidedAt)}</td>
                      <td className="nowrap" style={{ textAlign: 'right' }}>
                        <Link className="btn btn--sm" to={`/marketplace/${request.dataProduct.id}`}>Open</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {deciding && (
        <DecisionModal
          request={deciding.request}
          approve={deciding.approve}
          onClose={() => setDeciding(null)}
        />
      )}
    </div>
  )
}

function RequestTable({
  requests, showRequester, actions,
}: {
  requests: AccessRequest[]
  showRequester?: boolean
  actions?: (request: AccessRequest) => React.ReactNode
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {showRequester && <th>Requested by</th>}
            <th>Output port</th>
            <th>Purpose</th>
            <th>Status</th>
            <th>When</th>
            {actions && <th />}
          </tr>
        </thead>
        <tbody>
          {requests.map((request) => (
            <tr key={request.id}>
              {showRequester && (
                <td>
                  <strong>{request.requester?.displayName}</strong>
                  <div className="small faint">{request.requester?.email}</div>
                </td>
              )}
              <td>
                <div>{request.component?.title ?? 'whole data product'}</div>
                <div className="small faint">
                  <Link to={`/marketplace/${request.dataProduct.id}`}>{request.dataProduct.title}</Link>
                </div>
              </td>
              <td className="small" style={{ maxWidth: 320 }}>
                {request.purpose}
                {request.consumerDataProduct && (
                  <div className="small faint mono mt-1">for {request.consumerDataProduct}</div>
                )}
              </td>
              <td>
                <Badge tone={STATUS_TONE[request.status]}>{request.status}</Badge>
                {request.decisionNote && <div className="small faint mt-1">“{request.decisionNote}”</div>}
              </td>
              <td className="small faint nowrap">{formatDate(request.createdAt)}</td>
              {actions && <td className="nowrap">{actions(request)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DecisionModal({
  request, approve, onClose,
}: {
  request: AccessRequest
  approve: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState('')

  const decide = useMutation({
    mutationFn: () => api.post(`/marketplace/access-requests/${request.id}/decision`, { approve, note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['access'] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      onClose()
    },
  })

  return (
    <Modal
      title={approve ? 'Approve access' : 'Reject access'}
      subtitle={`${request.requester?.displayName} → ${request.component?.title ?? request.dataProduct.title}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className={approve ? 'btn btn--primary' : 'btn btn--danger'}
            onClick={() => decide.mutate()}
            disabled={decide.isPending}
          >
            {decide.isPending ? 'Saving…' : approve ? 'Approve' : 'Reject'}
          </button>
        </>
      }
    >
      <div className="banner mb-2">
        <div><strong>Stated purpose</strong> — {request.purpose}</div>
      </div>
      <div className="field">
        <label className="field__label" htmlFor="note">Note to the requester</label>
        <textarea id="note" className="textarea" value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={approve ? 'Any conditions attached to this grant?' : 'Why is this being rejected?'} />
      </div>
      {decide.error != null && <ErrorBanner error={decide.error} />}
    </Modal>
  )
}
