# DataMesh Platform

A self-service **data mesh platform**: a place where a domain team can start a new data
product from a template, evolve it until it is worth consuming, have it checked against
the organisation's governance rules automatically, provision it into real environments,
and publish it to a marketplace where other domains can find it and request access.

It is built around one idea, borrowed from Backstage-based platforms such as Witboost:

> **The descriptor in the data product's own git repository is the source of truth.**
> Everything else — the catalog, the marketplace, the lineage graph, the provisioning
> plan — is derived from it and can be rebuilt from it.

<p align="center"><i>Python + FastAPI backend · React + TypeScript frontend · SQLite + git for state</i></p>

---

## Quick start

```bash
make install     # virtualenv + backend deps + npm install
make reset       # create the schema and seed a demo mesh
make backend     # http://127.0.0.1:8000   (OpenAPI docs at /docs)
make frontend    # http://127.0.0.1:5173   (in a second terminal)
```

Sign in with any demo account — the password is `password123`:

| user | role | what they show |
|---|---|---|
| `alice` | producer | owns *Customer 360* and *Order Events*, both published |
| `maya` | producer | owns *Campaign Attribution*, which consumes both of Alice's products |
| `bruno` | consumer | has access requests waiting for a decision |
| `gwen` | governance | sees the review queue and releases products under review |
| `admin` | platform team | manages domains, owns the deliberately-failing *Revenue Reporting* |

Without `make`:

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/python -m app.seed --reset
../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev
```

---

## Real GitHub repositories

By default the platform hosts each data product's repository locally (a bare repo under
`data/repos`), so it works offline and in tests. Give it a token and it uses **GitHub**
instead: scaffolding a data product creates a real repository, every descriptor change is
pushed as a commit, and every release is pushed as an annotated tag.

```bash
export DMP_GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxx   # or put it in backend/.env
# optional:
export DMP_GITHUB_OWNER=my-org                 # default: the token's user
export DMP_GITHUB_REPO_PREFIX=dmp-             # repo name: dmp-<domain>-<name>
export DMP_GITHUB_REPOS_PRIVATE=true
make backend
```

Token type: a **classic PAT** needs the `repo` scope, plus `delete_repo` if deleting a
data product should also delete its repository (otherwise deletion is skipped with a
warning). A **fine-grained token** needs *Administration: read & write* and
*Contents: read & write* on the owner. The plain `GITHUB_TOKEN` variable works as a
fallback, and `DMP_GITHUB_API_URL` points the client at a GitHub Enterprise instance.

Verify the token before creating anything:

```bash
curl -s -H "Authorization: Bearer <platform JWT>" localhost:8000/api/platform/github/status
# → {"enabled": true, "ok": true, "login": "you", "owner": "you", "scopes": ["repo", ...]}
```

The topbar shows `GitHub repos` when the mode is active, and each product's Repository
tab links to its repository on GitHub. The token itself never touches disk: workspace
remotes store the plain `https://github.com/...` URL and pushes authenticate through a
per-invocation `http.extraheader`.

Heads-up on seeding: `make reset` in GitHub mode creates the five demo repositories for
real (and deletes them again on the next `--reset`). Use
`python -m app.seed --reset --local` to keep the demo mesh offline while still using
GitHub for the products you create through the UI.

---

## What the platform does

### 1. Scaffold — a data product starts as a repository

Choosing a template produces a real git repository containing
`data-product-descriptor.yaml` plus whatever skeleton files the template declares
(a dbt model, an Airflow DAG, an Avro schema, an OpenAPI document…). The catalog then
*ingests* that descriptor: it mints the URN, projects the components into SQL and
records the lineage edges.

Templates are declarative YAML in [`backend/app/scaffolder_templates/`](backend/app/scaffolder_templates/).
A template declares the form the UI must render and the descriptor fragment it produces,
so **adding a new technology needs no frontend change at all**.

### 2. Build — components make the product real

Four kinds of component, following the data mesh taxonomy:

| kind | what it is | shipped templates |
|---|---|---|
| **storage** | data the product owns | S3 landing area, Delta Lake table |
| **workload** | what populates it | Airflow DAG, dbt transformation |
| **output port** | the public interface | Snowflake table, Kafka topic, REST API |
| **observability** | what verifies the promises | data quality monitor |

Every change — adding a component through the wizard, or hand-editing the YAML in the
descriptor editor — is committed to the product's repository with a message, and the
catalog is rebuilt from the new commit.

### 3. Govern — the rules are code, not a checklist

Ten policies run automatically on every save (advisory) and as a hard gate before a
release or a non-development deployment. They cover ownership, documentation, the
existence of an interface, data-contract completeness, service levels, personal-data
classification, component topology, observability, dependency resolution and versioning.

A finding of severity `error` blocks; `warning` and `info` inform. The rule that
personal data may not be published as `internal`, or without terms of use, is the kind
of thing this makes structurally impossible rather than merely discouraged.

### 4. Provision — one interface, many technologies

The coordinator resolves every component to a **provisioner adapter** by technology,
validates the whole plan *before* touching anything, then executes in dependency order:
storage → workloads → output ports → observability. Each adapter returns the resource
identifiers it created, which are stored on the deployment and shown in the UI.

The shipped adapters simulate Snowflake, Kafka, S3, Delta Lake, Airflow, dbt, Kubernetes
and the observability platform. Replacing a simulator with a real Terraform or API call
means implementing one class — nothing else in the platform knows the difference.

### 5. Publish — the marketplace

Publishing requires a released version **and** a successful production deployment, so a
consumer never sees a product that does not actually run. In the marketplace a consumer
reads the full data contract (schema, classifications, SLA, terms) before requesting
access; the owning domain approves or rejects, and can revoke later. Naming a consuming
data product on the request makes the dependency appear in the mesh lineage graph.

---

## Architecture

```
┌──────────────────────── React + TypeScript (Vite) ────────────────────────┐
│  Builder            Marketplace         Governance        Lineage         │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │  REST + JWT
┌───────────────────────────────▼───────────────────────────────────────────┐
│  FastAPI                                                                  │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐  │
│  │scaffolder│ │descriptor │ │ policy   │ │provisioning│ │ marketplace  │  │
│  │(templates│ │ (parse /  │ │ engine   │ │coordinator │ │ + access +   │  │
│  │  + form) │ │  validate)│ │(10 rules)│ │            │ │   lineage    │  │
│  └────┬─────┘ └─────┬─────┘ └────┬─────┘ └──────┬─────┘ └──────┬───────┘  │
│       └─────────────┴────────────┴──────────────┴──────────────┘          │
│                     │                           │                         │
│              ┌──────▼───────┐          ┌────────▼─────────┐               │
│              │ git repos    │  ingest  │ provisioner      │               │
│              │ (source of   ├─────────►│ registry         │               │
│              │  truth)      │          │ 8 adapters       │               │
│              └──────┬───────┘          └──────────────────┘               │
│                     │                                                     │
│              ┌──────▼───────────────────────────────┐                     │
│              │ SQL catalog — a derived read model   │                     │
│              └──────────────────────────────────────┘                     │
└───────────────────────────────────────────────────────────────────────────┘
```

More detail, including the state machine and the reasoning behind each choice, is in
[`docs/architecture.md`](docs/architecture.md). The descriptor format is specified in
[`docs/descriptor.md`](docs/descriptor.md).

### Layout

```
backend/
  app/
    api/routes/          auth · templates · dataproducts · marketplace · platform
    core/                settings, database, security
    models/              SQLAlchemy: users, catalog, operations
    schemas/descriptor   the descriptor contract (Pydantic)
    services/            repository (git) · descriptor_io · templates · policies
                         provisioning · catalog · marketplace · dataproducts
    provisioners/        the adapter interface and eight technology adapters
    scaffolder_templates/  10 declarative templates
    seed.py              builds the demo mesh through the real service layer
  tests/                 49 tests: descriptor, policies, templates, git, API journeys
frontend/
  src/
    api/                 typed client and the shared response types
    components/          design-system primitives, dynamic form renderer, lineage SVG
    pages/               overview · products · scaffolder · detail · marketplace ·
                         access · governance · domains · lineage
  scripts/ssr-smoke.tsx  headless render of every route against a live backend
```

---

## Verifying it

```bash
make test     # 49 backend tests: unit + full API journeys
make smoke    # renders all 10 UI routes with real API data (backend must be running)
make build    # type-checks and builds the production frontend bundle
```

The backend tests run against a throwaway data directory — their own SQLite file and
their own git repositories — so they never touch your demo mesh.

---

## Notes for the thesis

Things worth pointing at when writing this up:

- **Source of truth.** `app/services/catalog.py::ingest` is the *only* code that writes
  the `components` and `lineage_edges` tables. Delete the database and re-ingest every
  repository and you get the same catalog back. That is what makes "the repository is the
  source of truth" a property rather than a claim.
- **Computational governance.** `app/services/policies.py` — each policy is a pure
  function over a descriptor, which is why the same rules can run as an editor hint, a
  release gate and a deployment gate without being written three times.
- **Self-service without a bottleneck.** A new supported technology is one YAML template
  plus one provisioner class. Neither the frontend nor the API changes.
- **Identity and versioning.** The major version is part of the URN
  (`urn:dmp:sales:customer-360:1`), so a breaking change mints a new identity and existing
  consumers keep resolving the contract they agreed to.
- **The gate to the marketplace** is deliberately mechanical — released *and* provisioned
  in production — because a catalog that lists things which do not run is the failure mode
  every data catalog eventually reaches.

### Where the simulation stops

The provisioner adapters do not call real infrastructure, authentication is a single
JWT-issuing service rather than a corporate IdP, and the git remotes are bare
repositories on the local filesystem rather than GitHub. Each of those is isolated behind
one interface (`Provisioner`, `app/core/security.py`, `RepositoryService`) precisely so
the substitution is mechanical.
