import { useMemo } from 'react'
import type { SchemaColumn, TemplateField, TemplateSection } from '@/api/types'

export type FormValues = Record<string, any>

/** Initial values for a template: declared defaults, then type-appropriate blanks. */
export function initialValues(sections: TemplateSection[]): FormValues {
  const values: FormValues = {}
  for (const section of sections) {
    for (const field of section.fields) {
      if (field.default !== undefined) {
        values[field.name] = field.default
      } else if (field.type === 'boolean') {
        values[field.name] = false
      } else if (field.type === 'tags') {
        values[field.name] = []
      } else if (field.type === 'schema') {
        values[field.name] = [emptyColumn()]
      } else if (field.type === 'select') {
        values[field.name] = optionValue(field.options?.[0]) ?? ''
      } else {
        values[field.name] = ''
      }
    }
  }
  return values
}

function optionValue(option: string | { value: string; label: string } | undefined): string | undefined {
  if (option === undefined) return undefined
  return typeof option === 'string' ? option : option.value
}

function emptyColumn(): SchemaColumn {
  return { name: '', dataType: 'string', description: '', nullable: true, pii: false, classification: 'internal' }
}

/** Client-side mirror of the server's validation, so mistakes surface early. */
export function validate(sections: TemplateSection[], values: FormValues): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const section of sections) {
    for (const field of section.fields) {
      const value = values[field.name]
      const isEmpty =
        value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0)
      if (field.required && isEmpty) {
        errors[field.name] = `${field.title ?? field.name} is required`
        continue
      }
      if (isEmpty) continue
      if (field.pattern && typeof value === 'string' && !new RegExp(field.pattern).test(value)) {
        errors[field.name] = field.patternMessage ?? `${field.title ?? field.name} has an invalid format`
      }
      if (field.type === 'schema' && Array.isArray(value)) {
        const named = value.filter((column: SchemaColumn) => column.name?.trim())
        if (named.length === 0 && field.required) {
          errors[field.name] = 'Declare at least one column'
        } else if (new Set(named.map((c: SchemaColumn) => c.name.trim())).size !== named.length) {
          errors[field.name] = 'Column names must be unique'
        }
      }
    }
  }
  return errors
}

/** Strip rows the user left blank before submitting. */
export function cleanValues(sections: TemplateSection[], values: FormValues): FormValues {
  const out: FormValues = { ...values }
  for (const section of sections) {
    for (const field of section.fields) {
      if (field.type === 'schema' && Array.isArray(out[field.name])) {
        out[field.name] = (out[field.name] as SchemaColumn[]).filter((column) => column.name?.trim())
      }
    }
  }
  return out
}

interface Props {
  sections: TemplateSection[]
  values: FormValues
  errors: Record<string, string>
  onChange: (name: string, value: any) => void
}

export function TemplateForm({ sections, values, errors, onChange }: Props) {
  return (
    <>
      {sections.map((section) => (
        <div className="form-section" key={section.title}>
          <div className="form-section__title">{section.title}</div>
          {section.description && <div className="form-section__desc">{section.description}</div>}
          {section.fields.map((field) => (
            <Field
              key={field.name}
              field={field}
              value={values[field.name]}
              error={errors[field.name]}
              onChange={(value) => onChange(field.name, value)}
            />
          ))}
        </div>
      ))}
    </>
  )
}

function Field({
  field, value, error, onChange,
}: {
  field: TemplateField
  value: any
  error?: string
  onChange: (value: any) => void
}) {
  const label = field.title ?? field.name
  const options = useMemo(
    () => (field.options ?? []).map((o) => (typeof o === 'string' ? { value: o, label: o } : o)),
    [field.options],
  )

  if (field.type === 'boolean') {
    return (
      <div className="field">
        <label className="switch">
          <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
          <span>{label}</span>
        </label>
        {field.help && <div className="field__help">{field.help}</div>}
      </div>
    )
  }

  return (
    <div className="field">
      <label className="field__label" htmlFor={`f-${field.name}`}>
        {label}
        {field.required && <span className="field__req" title="Required">*</span>}
      </label>

      {field.type === 'text' ? (
        <textarea
          id={`f-${field.name}`}
          className="textarea"
          value={value ?? ''}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : field.type === 'select' ? (
        <select id={`f-${field.name}`} className="select" value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="" disabled>Choose…</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      ) : field.type === 'number' ? (
        <input
          id={`f-${field.name}`}
          className="input"
          type="number"
          value={value ?? ''}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        />
      ) : field.type === 'tags' ? (
        <TagInput value={Array.isArray(value) ? value : []} placeholder={field.placeholder} onChange={onChange} />
      ) : field.type === 'schema' ? (
        <SchemaEditor value={Array.isArray(value) ? value : []} onChange={onChange} />
      ) : (
        <input
          id={`f-${field.name}`}
          className="input"
          value={value ?? ''}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}

      {field.help && <div className="field__help">{field.help}</div>}
      {error && <div className="field__error">{error}</div>}
    </div>
  )
}

function TagInput({
  value, placeholder, onChange,
}: {
  value: string[]
  placeholder?: string
  onChange: (value: string[]) => void
}) {
  return (
    <>
      <input
        className="input"
        value={value.join(', ')}
        placeholder={placeholder ?? 'comma, separated, values'}
        onChange={(e) => onChange(e.target.value.split(',').map((part) => part.trim()).filter(Boolean))}
      />
      {value.length > 0 && (
        <div className="row row--wrap" style={{ gap: 5, marginTop: 4 }}>
          {value.map((tag) => <span className="badge" key={tag}>{tag}</span>)}
        </div>
      )}
    </>
  )
}

const DATA_TYPES = ['string', 'integer', 'long', 'double', 'decimal', 'boolean', 'date', 'timestamp', 'struct', 'array']
const CLASSIFICATIONS = ['public', 'internal', 'confidential', 'restricted']

/** Table editor for a data contract schema. */
function SchemaEditor({ value, onChange }: { value: SchemaColumn[]; onChange: (value: SchemaColumn[]) => void }) {
  const update = (index: number, patch: Partial<SchemaColumn>) => {
    onChange(value.map((column, i) => (i === index ? { ...column, ...patch } : column)))
  }

  return (
    <div>
      {/* header and rows share ONE grid (rows are display: contents), so the
          NULL / PII / CLASS labels always sit exactly over their columns */}
      <div className="table-wrap">
        <div className="schema-grid">
          <div className="schema-grid__head">Column</div>
          <div className="schema-grid__head">Type</div>
          <div className="schema-grid__head">Description</div>
          <div className="schema-grid__head schema-row__check" title="May the column be null?">Null</div>
          <div className="schema-grid__head schema-row__check" title="Does the column carry personal data?">PII</div>
          <div className="schema-grid__head">Class</div>

          {value.map((column, index) => (
            <div className="schema-row" key={index}>
              <input
                className="input input--mono"
                value={column.name}
                placeholder="customer_id"
                onChange={(e) => update(index, { name: e.target.value })}
              />
              <select className="select" value={column.dataType} onChange={(e) => update(index, { dataType: e.target.value })}>
                {DATA_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
              <input
                className="input"
                value={column.description ?? ''}
                placeholder="What a consumer can rely on"
                onChange={(e) => update(index, { description: e.target.value })}
              />
              <input
                type="checkbox"
                className="schema-row__check"
                aria-label="nullable"
                checked={column.nullable !== false}
                onChange={(e) => update(index, { nullable: e.target.checked })}
              />
              <input
                type="checkbox"
                className="schema-row__check"
                aria-label="personal data"
                checked={Boolean(column.pii)}
                onChange={(e) =>
                  update(index, {
                    pii: e.target.checked,
                    // personal data may not stay `internal` — governance rejects it
                    classification: e.target.checked && (column.classification ?? 'internal') === 'internal'
                      ? 'confidential'
                      : column.classification,
                  })
                }
              />
              <div className="row" style={{ gap: 4 }}>
                <select
                  className="select"
                  value={column.classification ?? 'internal'}
                  onChange={(e) => update(index, { classification: e.target.value as SchemaColumn['classification'] })}
                >
                  {CLASSIFICATIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  title="Remove column"
                  onClick={() => onChange(value.filter((_, i) => i !== index))}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <button type="button" className="btn btn--sm" onClick={() => onChange([...value, emptyColumn()])}>
        + Add column
      </button>
    </div>
  )
}
