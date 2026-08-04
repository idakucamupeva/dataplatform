import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, Domain, User } from '@/api/types'
import { Card, EmptyState, ErrorBanner, Loading, Modal } from '@/components/ui'
import { colourFor } from '@/lib/format'
import { useAuth } from '@/lib/auth'

export function DomainsPage() {
  const { user } = useAuth()
  const [creating, setCreating] = useState(false)

  const domains = useQuery({ queryKey: ['domains'], queryFn: () => api.get<Domain[]>('/domains') })
  const products = useQuery({ queryKey: ['dataproducts', 'all'], queryFn: () => api.get<DataProduct[]>('/dataproducts') })

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>Domains</h1>
          <div className="page-sub">
            Ownership boundaries in the mesh. Every data product belongs to exactly one domain, and the
            domain is accountable for what it publishes.
          </div>
        </div>
        {user?.role === 'admin' && (
          <div className="page-head__actions">
            <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>New domain</button>
          </div>
        )}
      </div>

      {domains.isLoading ? (
        <Card><Loading rows={4} /></Card>
      ) : (
        <div className="grid grid--2">
          {domains.data?.map((domain) => {
            const owned = products.data?.filter((dp) => dp.domain === domain.name) ?? []
            return (
              <Card
                key={domain.id}
                title={
                  <span className="row" style={{ gap: 8 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: colourFor(domain.name) }} />
                    {domain.title}
                  </span>
                }
                actions={<span className="badge">{domain.dataProductCount} products</span>}
              >
                <p className="small muted">{domain.description || 'No description.'}</p>
                <dl className="kv">
                  <dt>Identifier</dt><dd className="mono small">{domain.name}</dd>
                  <dt>Owner</dt><dd>{domain.owner?.displayName ?? <span className="faint">unassigned</span>}</dd>
                </dl>
                {owned.length > 0 && (
                  <div className="stack stack--sm mt-2">
                    {owned.slice(0, 5).map((dp) => (
                      <div className="row row--between small" key={dp.id}>
                        <Link to={`/products/${dp.id}`}>{dp.title}</Link>
                        <span className="faint">{dp.lifecycle}</span>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            )
          })}
          {(domains.data?.length ?? 0) === 0 && (
            <Card><EmptyState title="No domains yet">A platform administrator defines the domains.</EmptyState></Card>
          )}
        </div>
      )}

      {creating && <CreateDomainModal onClose={() => setCreating(false)} />}
    </div>
  )
}

function CreateDomainModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ name: '', title: '', description: '', ownerId: '' })

  const users = useQuery({ queryKey: ['users'], queryFn: () => api.get<User[]>('/users') })
  const create = useMutation({
    mutationFn: () =>
      api.post('/domains', {
        name: form.name,
        title: form.title,
        description: form.description,
        ownerId: form.ownerId ? Number(form.ownerId) : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['domains'] })
      onClose()
    },
  })

  const set = (key: string, value: string) => setForm((f) => ({ ...f, [key]: value }))

  return (
    <Modal
      title="New domain"
      subtitle="Domains are created by the platform team; data products then choose one."
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn--primary" onClick={() => create.mutate()} disabled={!form.name || create.isPending}>
            {create.isPending ? 'Creating…' : 'Create domain'}
          </button>
        </>
      }
    >
      <div className="field">
        <label className="field__label" htmlFor="d-name">Identifier<span className="field__req">*</span></label>
        <input id="d-name" className="input input--mono" value={form.name} placeholder="supply-chain"
          onChange={(e) => set('name', e.target.value)} />
        <div className="field__help">Lowercase, dashes. It becomes part of every URN in the domain.</div>
      </div>
      <div className="field">
        <label className="field__label" htmlFor="d-title">Display name</label>
        <input id="d-title" className="input" value={form.title} onChange={(e) => set('title', e.target.value)} />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="d-desc">Description</label>
        <textarea id="d-desc" className="textarea" value={form.description} onChange={(e) => set('description', e.target.value)} />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="d-owner">Accountable owner</label>
        <select id="d-owner" className="select" value={form.ownerId} onChange={(e) => set('ownerId', e.target.value)}>
          <option value="">Unassigned</option>
          {users.data?.map((u) => <option key={u.id} value={u.id}>{u.displayName}</option>)}
        </select>
      </div>
      {create.error != null && <ErrorBanner error={create.error} />}
    </Modal>
  )
}
