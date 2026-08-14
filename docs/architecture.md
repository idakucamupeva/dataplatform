# Architecture

This document explains how the platform is put together and, where a choice was open,
why it was made the way it was. It assumes the reader has skimmed the [README](../README.md).

## 1. The central invariant

Every data product owns a git repository. In it, `data-product-descriptor.yaml` holds the
product's metadata, its components and its dependencies. That file is authoritative.

The relational database is a **projection** of those files:

```
descriptor.yaml  ──parse──►  Descriptor (Pydantic)  ──ingest──►  data_products
                                                                 components
                                                                 lineage_edges
```

`app/services/catalog.py::ingest` is the only function in the codebase that writes the
`components` and `lineage_edges` tables. Consequently:

* Deleting the database and re-ingesting every repository reproduces the catalog exactly.
* A producer can edit the YAML by hand — through the UI editor or, in a real deployment,
  by pushing to the repository — and the platform converges on it rather than fighting it.
* Diffs, blame, history and release tags come from git rather than from a bespoke audit
  table.

The alternative — treating the database as authoritative and exporting YAML — was
rejected because it makes the platform the only way to change a data product, which is
exactly the central bottleneck a mesh is supposed to remove.

### What the database *is* authoritative for

Things that are not properties of a data product but of the platform's operation:
users and roles, deployments and their logs, policy evaluations, access requests and the
activity feed. These have no place in a product's repository.

## 2. Module map

| module | responsibility |
|---|---|
| `services/repository.py` | git: create, commit, read at a ref, log, diff, tag |
| `services/descriptor_io.py` | YAML ⇄ `Descriptor`, normalisation, pruning, error mapping |
| `services/urns.py` | minting and parsing identity |
| `services/templates.py` | the scaffolder: template registry, form validation, rendering |
| `services/policies.py` | ten governance policies over a descriptor |
| `services/catalog.py` | ingestion (the projection), dependency resolution, events |
| `services/dataproducts.py` | the lifecycle use cases, the only writer of git + catalog |
| `services/provisioning.py` | plan, preflight, ordered execution, deployment records |
| `services/marketplace.py` | search, facets, access decisions, lineage graph |
| `provisioners/` | the `Provisioner` interface and eight technology adapters |

The dependency direction is strictly downward: routes → services → (repository, models).
No service imports a route; no model imports a service.

## 3. Data product lifecycle

```
        scaffold
           │
           ▼
      ┌─────────┐   submit    ┌───────────┐
      │  DRAFT  ├────────────►│ IN_REVIEW │      descriptor frozen while in review
      └────┬────┘             └─────┬─────┘
           │ release                │ release (governance role)
           ▼                        ▼
                   ┌──────────┐
                   │ RELEASED │  ← immutable snapshot + git tag v<version>
                   └────┬─────┘
                        │ publish  (requires a successful production deployment)
                        ▼
                  ┌───────────┐   retire   ┌─────────┐
                  │ PUBLISHED ├───────────►│ RETIRED │
                  └───────────┘            └─────────┘
```

Two gates matter:

1. **Release** re-runs the policies as a hard gate, writes the bumped version to the
   descriptor, commits, tags the repository and stores an immutable copy of the YAML in
   `data_product_versions`. Non-development deployments always run from such a snapshot,
   never from the working descriptor.
2. **Publish** additionally requires a `provisioned` deployment in the gate environment
   (`production` by default, configurable). This is what stops the marketplace from
   becoming a catalogue of intentions.

## 4. The scaffolder

A template is a YAML document with two halves.

**The form half** (`parameters`) is a list of sections, each with typed fields — `string`,
`text`, `select`, `boolean`, `number`, `tags`, `schema`. The frontend renders it
generically (`components/TemplateForm.tsx`); `select` fields may declare
`optionsFrom: domains`, which the API resolves before returning the template.

**The output half** is either `descriptor` (for a data product template) or `component`
(for a component template), plus an optional list of `files`.

Structured output is authored as **real YAML and rendered node by node**, so a template
author never fights with string indentation:

```yaml
component:
  name: "{{ name }}"                  # rendered by Jinja, stays a string
  specific:
    partitions: ${partitions}         # replaced by the raw value: an int, not "6"
    partitionBy: ${partitionBy}       # a list stays a list
```

Keys whose rendered value is empty are dropped. File bodies are ordinary Jinja templates
(this is where the DAG, the SQL and the Avro schema are generated).

The consequence: **supporting a new technology is a YAML file plus a provisioner class.**
No API route and no React component changes.

## 5. Computational governance

Each policy is a pure generator over a `PolicyContext`:

```python
def _check_personal_data(ctx: PolicyContext):
    for port in ctx.descriptor.output_ports:
        ...
        yield Finding(policy_id=..., severity=Severity.ERROR, message=..., remediation=...)
```

Because a policy is a pure function of the descriptor (plus an optional dependency
resolver), the same rule set is reused in three places without duplication:

| trigger | effect |
|---|---|
| descriptor saved / component added | advisory — shown in the editor, stored as an evaluation |
| submit for review, release | **blocking** — the transition is refused |
| deploy to any non-development environment | **blocking** — the deployment is refused |

Every run is persisted in `policy_evaluations`, which gives the governance tab a history
rather than only a current state.

The ten policies: `ownership-declared`, `documented`, `interface-exists`,
`contract-complete`, `sla-declared`, `pii-protected`, `topology-sound`, `observable`,
`dependencies-resolvable`, `versioning-honest`.

## 6. Provisioning

```
descriptor ──► plan (ordered by kind) ──► preflight (every adapter validates) ──► execute
                                                │                                   │
                                          any problem?                        per-component
                                                │                              logs + outputs
                                                ▼                                   │
                                        409, nothing touched                        ▼
                                                                            Deployment row
```

Ordering is `storage → workload → outputport → observability`: storage must exist before a
workload writes to it, an output port should not be exposed before there is data behind
it, and the observability component references the others by name.

Preflight is separated from execution on purpose. Collecting *all* problems before
starting means a refused deployment leaves nothing half-created, which is what makes
re-running one safe.

`Provisioner` is a four-method interface: `technology`, `validate`, `provision`,
`destroy`. Adapters are registered by technology in `provisioners/__init__.py`. A
component whose technology has no adapter fails preflight with a clear message rather
than silently doing nothing.

## 7. Identity

```
data product : urn:dmp:<domain>:<name>:<major>
component    : urn:dmp:<domain>:<name>:<major>:<component>
```

The major version is part of the identity, so `1.0.0 → 2.0.0` mints a new URN and a
consumer bound to `:1` keeps resolving the contract it agreed to. URNs are *derived* — a
pure function of (domain, name, major, component name) recomputed on every ingestion — so
they cannot drift from the fields they describe. Renaming a product or moving it between
domains is refused; the answer is a new data product.

## 8. Access and lineage

An access request names an output port, a purpose and optionally the consuming data
product. The owning domain decides; grants can be revoked. Endpoints are hidden in the
marketplace until access is approved, while the data contract itself stays public —
that asymmetry is the point of a marketplace.

Lineage edges are rebuilt from the `dependsOn` blocks on every ingestion and marked
`resolved` when the target URN matches a published output port. Unresolved edges are both
a blocking policy finding and a visible warning in the mesh graph, which catches the two
common failures: a typo in a URN, and depending on something the producing domain never
published.

## 9. Frontend

React 18 + TypeScript + Vite, React Router for navigation and TanStack Query for server
state. There is no UI framework: one hand-written stylesheet with design tokens
(`styles/app.css`) supports both colour themes and keeps the vocabulary small enough to
read in one sitting.

Two components carry most of the leverage:

* `components/TemplateForm.tsx` renders any template's form from its JSON description,
  including the data-contract table editor. This is why templates are frontend-free.
* `components/LineageGraph.tsx` lays a DAG out in columns by longest-path depth and draws
  it as inline SVG, with a visited guard so a cyclic graph cannot hang the renderer.

`scripts/ssr-smoke.tsx` renders every route with `react-dom/server` against a running
backend, priming the query cache with real API responses first, so pages are exercised in
their populated state. It is a cheap substitute for a browser-driven end-to-end suite.

## 10. Known limits

* The provisioner adapters simulate infrastructure. The interface is real; the calls are not.
* Deployments run synchronously inside the request. A real platform would queue them and
  stream logs; the `Deployment` record already models an asynchronous run
  (`status`, `started_at`, `finished_at`), so the change is contained.
* Authentication is a local user table issuing JWTs, not an enterprise identity provider,
  and roles are platform-wide rather than per-domain groups.
* Git remotes are bare repositories on the local filesystem **unless a GitHub token is
  configured** (`DMP_GITHUB_TOKEN`), in which case each data product gets a real GitHub
  repository and all commits/tags are pushed there (`services/github.py` +
  `RepositoryService`). The mode is chosen per operation, so the same deployment can be
  switched by changing one environment variable.
* SQLite by default. `DMP_DATABASE_URL` accepts any SQLAlchemy URL; nothing in the schema
  is SQLite-specific.
