import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Component, ComponentKind, DataProduct, Template } from '@/api/types'
import { Badge, Card, EmptyState, ErrorBanner, KindBadge, Loading, Modal, Urn } from '@/components/ui'
import { TemplateForm, cleanValues, initialValues, validate, type FormValues } from '@/components/TemplateForm'
import { KIND_LABEL } from '@/lib/format'

const KIND_ORDER: ComponentKind[] = ['storage', 'workload', 'outputport', 'observability']

const KIND_BLURB: Record<ComponentKind, string> = {
  storage: 'Where the data product keeps the data it owns.',
  workload: 'What populates and maintains that data.',
  outputport: 'The public interface — what consumers actually use.',
  observability: 'What verifies the promises made to consumers.',
}

export function ComponentsTab({ dp, canEdit }: { dp: DataProduct; canEdit: boolean }) {
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState<ComponentKind | null>(null)
  const [inspecting, setInspecting] = useState<Component | null>(null)

  const remove = useMutation({
    mutationFn: (name: string) => api.del(`/dataproducts/${dp.id}/components/${name}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dataproduct', dp.id] }),
  })

  const grouped = useMemo(() => {
    const map = new Map<ComponentKind, Component[]>()
    for (const kind of KIND_ORDER) map.set(kind, [])
    for (const component of dp.components ?? []) map.get(component.kind)?.push(component)
    return map
  }, [dp.components])

  return (
    <div className="stack">
      {remove.error != null && <ErrorBanner error={remove.error} />}

      {KIND_ORDER.map((kind) => {
        const components = grouped.get(kind) ?? []
        return (
          <Card
            key={kind}
            title={
              <span className="row" style={{ gap: 8 }}>
                <KindBadge value={kind} />
                <span className="faint" style={{ fontWeight: 400 }}>{KIND_BLURB[kind]}</span>
              </span>
            }
            actions={
              canEdit ? (
                <button type="button" className="btn btn--sm" onClick={() => setAdding(kind)}>
                  + Add {KIND_LABEL[kind].toLowerCase()}
                </button>
              ) : undefined
            }
            flush
          >
            {components.length === 0 ? (
              <div className="card__body muted small">
                No {KIND_LABEL[kind].toLowerCase()} component yet.
              </div>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Component</th>
                      <th>Technology</th>
                      <th>Details</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {components.map((component) => (
                      <tr key={component.id}>
                        <td>
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            style={{ padding: 0, fontWeight: 620 }}
                            onClick={() => setInspecting(component)}
                          >
                            {component.title}
                          </button>
                          <div className="small muted">{component.description}</div>
                          <div className="mt-1"><Urn value={component.urn} /></div>
                        </td>
                        <td className="nowrap">
                          <Badge>{component.technology}</Badge>
                          {component.platform && <div className="small faint mt-1">{component.platform}</div>}
                        </td>
                        <td className="small">
                          {component.kind === 'outputport' ? (
                            <div className="stack stack--sm">
                              <span>{component.columnCount} columns{component.hasPii && ' · contains personal data'}</span>
                              {component.endpoint && <code className="mono faint">{component.endpoint}</code>}
                            </div>
                          ) : (
                            <span className="faint">{summarise(component)}</span>
                          )}
                        </td>
                        <td className="nowrap">
                          <div className="row" style={{ gap: 4, justifyContent: 'flex-end' }}>
                            <button type="button" className="btn btn--sm" onClick={() => setInspecting(component)}>
                              Inspect
                            </button>
                            {canEdit && (
                              <button
                                type="button"
                                className="btn btn--sm btn--danger"
                                onClick={() => {
                                  if (confirm(`Remove component '${component.name}' from the descriptor?`)) {
                                    remove.mutate(component.name)
                                  }
                                }}
                              >
                                Remove
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )
      })}

      {adding && (
        <AddComponentModal dp={dp} kind={adding} onClose={() => setAdding(null)} />
      )}
      {inspecting && (
        <Modal
          title={inspecting.title}
          subtitle={inspecting.urn}
          wide
          onClose={() => setInspecting(null)}
        >
          <ComponentDetail component={inspecting} />
        </Modal>
      )}
    </div>
  )
}

function summarise(component: Component): string {
  const spec = component.spec?.specific ?? {}
  const keys = ['table', 'bucket', 'topic', 'dagId', 'model', 'monitors', 'basePath']
  for (const key of keys) if (spec[key]) return `${key}: ${spec[key]}`
  return Object.keys(spec).slice(0, 3).join(', ')
}

export function ComponentDetail({ component }: { component: Component }) {
  const contract = component.dataContract
  return (
    <div className="stack">
      <p className="muted">{component.description}</p>

      <dl className="kv">
        <dt>Kind</dt><dd><KindBadge value={component.kind} /></dd>
        <dt>Technology</dt><dd>{component.technology} {component.platform && <span className="faint">· {component.platform}</span>}</dd>
        <dt>Template</dt><dd className="mono small">{component.templateId || '—'}</dd>
        {component.outputPortType && (<><dt>Port type</dt><dd>{component.outputPortType}</dd></>)}
        {contract?.endpoint && (<><dt>Endpoint</dt><dd className="mono small">{contract.endpoint}</dd></>)}
      </dl>

      {contract?.SLA && (
        <Card title="Service levels">
          <dl className="kv">
            <dt>Interval of change</dt><dd>{contract.SLA.intervalOfChange || '—'}</dd>
            <dt>Timeliness</dt><dd>{contract.SLA.timeliness || '—'}</dd>
            <dt>Availability</dt><dd>{contract.SLA.upTime || '—'}</dd>
          </dl>
        </Card>
      )}

      {contract?.schema && contract.schema.length > 0 && (
        <Card title={`Data contract — ${contract.schema.length} columns`} flush>
          <SchemaTable columns={contract.schema} />
        </Card>
      )}

      {contract?.termsAndConditions && (
        <Card title="Terms and conditions">
          <p className="small muted mb-0">{contract.termsAndConditions}</p>
        </Card>
      )}

      <Card title="Provisioning parameters" flush>
        <pre className="code-block" style={{ border: 'none', borderRadius: 0 }}>
          {JSON.stringify(component.spec?.specific ?? {}, null, 2)}
        </pre>
      </Card>
    </div>
  )
}

export function SchemaTable({ columns }: { columns: NonNullable<Component['dataContract']>['schema'] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Column</th>
            <th>Type</th>
            <th>Description</th>
            <th>Nullable</th>
            <th>Classification</th>
          </tr>
        </thead>
        <tbody>
          {(columns ?? []).map((column) => (
            <tr key={column.name}>
              <td className="mono nowrap">
                {column.name}
                {column.pii && <> <Badge tone="badge--warn">pii</Badge></>}
              </td>
              <td className="mono faint nowrap">{column.dataType}</td>
              <td className="small">{column.description || <span className="faint">—</span>}</td>
              <td className="small faint">{column.nullable === false ? 'no' : 'yes'}</td>
              <td>
                <Badge tone={column.classification === 'restricted' ? 'badge--danger' : column.classification === 'confidential' ? 'badge--warn' : ''}>
                  {column.classification ?? 'internal'}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AddComponentModal({ dp, kind, onClose }: { dp: DataProduct; kind: ComponentKind; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [templateId, setTemplateId] = useState<string | null>(null)
  const [values, setValues] = useState<FormValues>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState(false)

  const templates = useQuery({
    queryKey: ['templates', 'component', kind],
    queryFn: () => api.get<Template[]>(`/templates?type=component&kind=${kind}`),
  })
  const template = useQuery({
    queryKey: ['template', templateId],
    queryFn: () => api.get<Template>(`/templates/${templateId}`),
    enabled: Boolean(templateId),
  })
  const sections = useMemo(() => template.data?.parameters ?? [], [template.data])

  useEffect(() => {
    if (sections.length > 0) {
      setValues(initialValues(sections))
      setErrors({})
      setTouched(false)
    }
  }, [sections])

  const add = useMutation({
    mutationFn: () =>
      api.post(`/dataproducts/${dp.id}/components`, { templateId, values: cleanValues(sections, values) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataproduct', dp.id] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      onClose()
    },
  })

  function change(name: string, value: any) {
    const next = { ...values, [name]: value }
    setValues(next)
    if (touched) setErrors(validate(sections, next))
  }

  function submit() {
    const found = validate(sections, values)
    setErrors(found)
    setTouched(true)
    if (Object.keys(found).length === 0) add.mutate()
  }

  return (
    <Modal
      title={`Add ${KIND_LABEL[kind].toLowerCase()}`}
      subtitle={templateId ? template.data?.name : 'Choose the technology to use'}
      wide
      onClose={onClose}
      footer={
        templateId ? (
          <>
            <button type="button" className="btn" onClick={() => setTemplateId(null)}>Back</button>
            <button type="button" className="btn btn--primary" onClick={submit} disabled={add.isPending}>
              {add.isPending ? 'Adding…' : 'Add component'}
            </button>
          </>
        ) : undefined
      }
    >
      {!templateId ? (
        templates.isLoading ? (
          <Loading rows={3} />
        ) : (templates.data?.length ?? 0) === 0 ? (
          <EmptyState title="No template available">The platform team has not published a template for this kind yet.</EmptyState>
        ) : (
          <div className="grid grid--2">
            {templates.data!.map((item) => (
              <button key={item.id} type="button" className="card card--interactive template-card" onClick={() => setTemplateId(item.id)}>
                <div className="template-card__icon">◇</div>
                <div style={{ minWidth: 0 }}>
                  <div className="template-card__name">{item.name}</div>
                  <div className="template-card__desc">{item.description}</div>
                  <div className="row row--wrap mt-1" style={{ gap: 5 }}>
                    <Badge tone="badge--accent">{item.technology}</Badge>
                    {item.tags.map((tag) => <span className="badge" key={tag}>{tag}</span>)}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )
      ) : template.isLoading ? (
        <Loading rows={5} />
      ) : (
        <>
          <p className="muted small">{template.data?.description}</p>
          <TemplateForm sections={sections} values={values} errors={errors} onChange={change} />
          {add.error != null && <ErrorBanner error={add.error} />}
        </>
      )}
    </Modal>
  )
}
