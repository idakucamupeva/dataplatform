# The Data Product Descriptor

`data-product-descriptor.yaml`, at the root of every data product repository, is the
source of truth for that product. This is its specification.

The shape follows the conventions of the data mesh descriptor formats popularised by
Witboost and the Open Data Mesh specification: a Kubernetes-style envelope around a list
of components. The authoritative definition lives in
[`backend/app/schemas/descriptor.py`](../backend/app/schemas/descriptor.py); anything not
matching it is rejected with a per-field error.

## Envelope

```yaml
apiVersion: dataproduct.dmp.io/v1
kind: DataProduct
metadata: { … }
spec:
  components: [ … ]
  dependsOn: [ … ]
```

## `metadata`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | derived | `urn:dmp:<domain>:<name>:<major>`. Never author this — it is recomputed on every save. |
| `name` | slug | ✓ | Lowercase letters, digits and dashes, 3–64 characters. **Immutable** once the repository exists. |
| `displayName` | string | | Defaults to a title-cased `name`. |
| `domain` | slug | ✓ | Must be a domain registered on the platform. **Immutable.** |
| `version` | semver | ✓ | `MAJOR.MINOR.PATCH`. The major part is part of the identity. |
| `description` | string | ✓ | Under 40 characters raises a documentation warning. |
| `owner` | string | ✓ | `user:<username>` or `group:<name>`. |
| `email` | string | ✓ | A monitored mailbox — this is what a consumer contacts. |
| `maturity` | enum | | `tactical` (default) or `strategic`. Strategic products must be observable. |
| `tags` | string[] | | Discovery tags; they become marketplace facets. |
| `informationSLA` | string | | How quickly the domain answers questions, e.g. `8h`. |

## `spec.components[]`

| field | type | required | notes |
|---|---|---|---|
| `id` | string | derived | `<data product urn>:<component name>`. |
| `name` | slug | ✓ | Unique within the data product. |
| `displayName` | string | | Defaults to a title-cased `name`. |
| `description` | string | | Absent raises a documentation warning. |
| `kind` | enum | ✓ | `outputport`, `storage`, `workload` or `observability`. |
| `version` | string | | Component version, independent of the product version. |
| `technology` | string | ✓ in practice | Selects the provisioner adapter. No adapter ⇒ the deployment plan is refused. |
| `platform` | string | | Human-readable target system. |
| `useCaseTemplateId` | string | | The scaffolder template that produced the component. |
| `infrastructureTemplateId` | string | | The provisioner the template intends. |
| `dependsOn` | string[] | | Output-port URNs this component consumes. |
| `tags` | string[] | | `pii` on an output port that carries personal data. |
| `outputPortType` | string | output ports | `SQL`, `Streaming`, `Files`, … |
| `dataContract` | object | output ports | See below — governance requires it. |
| `specific` | object | ✓ | The technology-specific block; the only part a provisioner reads. |

### `dataContract`

What the producing domain promises a consumer. This is what the marketplace displays and
what the consumer accepts when requesting access.

```yaml
dataContract:
  termsAndConditions: Personal data may not leave the EU.
  endpoint: snowflake://ANALYTICS/SALES/CUSTOMER_SNAPSHOT
  schema:
    - name: customer_id
      dataType: string
      description: Stable surrogate key of the customer.
      nullable: false
      pii: false
      classification: internal
  SLA:
    intervalOfChange: 1 day
    timeliness: 2 hours
    upTime: 99.9%
```

`classification` is one of `public`, `internal`, `confidential`, `restricted`. A column
with `pii: true` classified as `public` or `internal` is a **blocking** policy violation,
as is an output port exposing personal data with empty `termsAndConditions`.

### `specific`

Free-form and never interpreted by the platform core — only by the provisioner that
claims the component's technology. Each adapter declares the keys it requires and
validates them during preflight, so a missing key is reported before anything is created.

| technology | required keys |
|---|---|
| `snowflake` | `database`, `schema`, `table` |
| `kafka` | `topic` (production additionally requires `replicationFactor` ≥ 3) |
| `s3` | `bucket`, `region` |
| `delta-lake` | `catalog`, `schema`, `table` |
| `airflow` | `dagId`, `schedule` |
| `dbt` | `project`, `model`, `targetSchema` |
| `rest` | `basePath` |
| `great-expectations` | `monitors` (must name a component of the same product) |

## `spec.dependsOn`

URNs of output ports **of other data products** that this product consumes:

```yaml
spec:
  dependsOn:
    - urn:dmp:sales:customer-360:1:customer-snapshot
```

Each entry becomes a lineage edge. A URN that does not resolve to a published output port
is a blocking policy finding — this is the rule that stops one domain from reaching into
another's storage instead of consuming its published interface.

## Complete example

```yaml
apiVersion: dataproduct.dmp.io/v1
kind: DataProduct
metadata:
  id: urn:dmp:sales:customer-360:1
  name: customer-360
  displayName: Customer 360
  domain: sales
  version: 1.0.0
  description: A single, deduplicated view of every customer.
  owner: user:alice
  email: sales-data@acme.io
  maturity: strategic
  tags: [customer, gold, gdpr]
  informationSLA: 4h
spec:
  components:
    - id: urn:dmp:sales:customer-360:1:customer-master
      name: customer-master
      displayName: Customer Master
      description: Curated Delta table holding one row per customer.
      kind: storage
      technology: delta-lake
      platform: Databricks
      useCaseTemplateId: storage-delta-lake
      specific:
        catalog: lakehouse
        schema: sales
        table: customer_master
        partitionBy: [country]

    - id: urn:dmp:sales:customer-360:1:customer-snapshot
      name: customer-snapshot
      displayName: Customer Snapshot
      description: Daily snapshot of the customer master, ready for BI.
      kind: outputport
      technology: snowflake
      platform: Snowflake
      outputPortType: SQL
      tags: [pii, gdpr]
      useCaseTemplateId: outputport-snowflake-table
      dataContract:
        termsAndConditions: >-
          Personal data is processed under the customer contract. Do not join with
          third-party identifiers and do not export outside the EU.
        endpoint: snowflake://ANALYTICS/SALES/CUSTOMER_SNAPSHOT
        schema:
          - name: customer_id
            dataType: string
            description: Stable surrogate key of the customer.
            nullable: false
            classification: internal
          - name: email
            dataType: string
            description: Primary contact address.
            pii: true
            classification: confidential
        SLA:
          intervalOfChange: 1 day
          timeliness: 2 hours
          upTime: 99.9%
      specific:
        database: ANALYTICS
        schema: SALES
        table: CUSTOMER_SNAPSHOT
        warehouse: WH_MEDIUM
        grantRole: ROLE_ANALYTICS_SALES_CUSTOMER_SNAPSHOT_READ

    - id: urn:dmp:sales:customer-360:1:snapshot-quality
      name: snapshot-quality
      displayName: Snapshot Quality
      description: Verifies freshness, volume and schema stability of the snapshot.
      kind: observability
      technology: great-expectations
      useCaseTemplateId: observability-data-quality
      specific:
        monitors: customer-snapshot
        checks:
          freshnessMinutes: 120
          minRowCount: 100000
          nullThresholdPercent: 1
          schemaDrift: true
        alerting:
          channel: '#sales-data-alerts'
          severity: high
  dependsOn: []
```
