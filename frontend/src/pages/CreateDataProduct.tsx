import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { DataProduct, Template } from '@/api/types'
import { Card, ErrorBanner, Loading } from '@/components/ui'
import { TemplateForm, cleanValues, initialValues, validate, type FormValues } from '@/components/TemplateForm'

/**
 * The scaffolder. Two steps: choose a template, fill in the form it declares.
 * The form is rendered entirely from the template's `parameters` block, so a
 * new template needs no frontend change.
 */
export function CreateDataProductPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [templateId, setTemplateId] = useState<string | null>(null)
  const [values, setValues] = useState<FormValues>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState(false)

  const templates = useQuery({
    queryKey: ['templates', 'dataproduct'],
    queryFn: () => api.get<Template[]>('/templates?type=dataproduct'),
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

  const create = useMutation({
    mutationFn: () =>
      api.post<DataProduct>('/dataproducts', { templateId, values: cleanValues(sections, values) }),
    onSuccess: (dp) => {
      queryClient.invalidateQueries({ queryKey: ['dataproducts'] })
      queryClient.invalidateQueries({ queryKey: ['metrics'] })
      navigate(`/products/${dp.id}`)
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
    if (Object.keys(found).length === 0) create.mutate()
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div className="page-head__text">
          <h1>New data product</h1>
          <div className="page-sub">
            The platform creates a git repository, writes the descriptor and registers the product in the
            catalog. Nothing is provisioned until you deploy it.
          </div>
        </div>
        {templateId && (
          <div className="page-head__actions">
            <button type="button" className="btn" onClick={() => setTemplateId(null)}>Choose another template</button>
          </div>
        )}
      </div>

      {!templateId ? (
        <Card title="Pick a template">
          {templates.isLoading ? (
            <Loading rows={3} />
          ) : (
            <div className="grid grid--2">
              {templates.data?.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="card card--interactive template-card"
                  onClick={() => setTemplateId(item.id)}
                >
                  <div className="template-card__icon">◈</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="template-card__name">{item.name}</div>
                    <div className="template-card__desc">{item.description}</div>
                    <div className="row row--wrap mt-1" style={{ gap: 5 }}>
                      {item.tags.map((tag) => <span className="badge" key={tag}>{tag}</span>)}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Card>
      ) : template.isLoading ? (
        <Card><Loading rows={6} /></Card>
      ) : (
        <div className="split">
          <Card title={template.data?.name}>
            <p className="muted small">{template.data?.description}</p>
            <TemplateForm sections={sections} values={values} errors={errors} onChange={change} />
            {create.error != null && <div className="mb-2"><ErrorBanner error={create.error} /></div>}
            <div className="row">
              <button type="button" className="btn btn--primary" onClick={submit} disabled={create.isPending}>
                {create.isPending ? 'Creating…' : 'Create data product'}
              </button>
              <button type="button" className="btn" onClick={() => setTemplateId(null)}>Back</button>
            </div>
          </Card>

          <Card title="What happens next">
            <ol className="small muted" style={{ paddingLeft: 18, margin: 0, lineHeight: 1.9 }}>
              <li>A git repository is initialised for the product.</li>
              <li><code>data-product-descriptor.yaml</code> is written and committed — this becomes the source of truth.</li>
              <li>The catalog ingests the descriptor and mints the URN.</li>
              <li>Governance policies run and report what is still missing.</li>
              <li>You add components, then release, provision and publish.</li>
            </ol>
          </Card>
        </div>
      )}
    </div>
  )
}
