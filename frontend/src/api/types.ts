export type Lifecycle = 'draft' | 'in_review' | 'released' | 'published' | 'retired'
export type ComponentKind = 'outputport' | 'storage' | 'workload' | 'observability'
export type Severity = 'error' | 'warning' | 'info'
export type DeploymentStatus =
  | 'not_deployed' | 'provisioning' | 'provisioned' | 'failed' | 'destroying' | 'destroyed'
export type AccessStatus = 'pending' | 'approved' | 'rejected' | 'revoked'

export interface User {
  id: number
  username: string
  displayName: string
  email: string
  role: 'admin' | 'governance' | 'user'
}

export interface SchemaColumn {
  name: string
  dataType: string
  description?: string
  nullable?: boolean
  pii?: boolean
  classification?: 'public' | 'internal' | 'confidential' | 'restricted'
  tags?: string[]
}

export interface DataContract {
  termsAndConditions?: string
  endpoint?: string
  schema?: SchemaColumn[]
  SLA?: { intervalOfChange?: string; timeliness?: string; upTime?: string; freshness?: string }
  billingPolicy?: string
}

export interface Component {
  id: number
  urn: string
  name: string
  title: string
  kind: ComponentKind
  technology: string
  description: string
  templateId: string
  platform: string
  outputPortType: string
  tags: string[]
  endpoint: string
  columnCount: number
  hasPii: boolean
  spec?: Record<string, any>
  dataContract?: DataContract | null
  access?: 'owner' | 'pending' | 'approved' | 'none'
}

export interface EnvironmentStatus {
  environment: string
  status: DeploymentStatus
  version: string | null
  deployedAt: string | null
  deploymentId: number | null
}

export interface PolicyFinding {
  policyId: string
  policyName: string
  severity: Severity
  message: string
  target: string
  remediation: string
  category: string
}

export interface PolicyReport {
  passed: boolean
  errorCount: number
  warningCount: number
  evaluatedPolicies?: string[]
  findings: PolicyFinding[]
}

export interface PolicyEvaluation extends PolicyReport {
  id: number
  trigger: string
  createdAt: string
}

export interface Version {
  id: number
  version: string
  notes: string
  commit: string
  createdBy: User | null
  createdAt: string
}

export interface Dependency {
  portUrn: string
  dataProductUrn: string
  resolved: boolean
}

export interface DataProduct {
  id: number
  urn: string
  name: string
  title: string
  description: string
  domain: string
  domainTitle: string
  owner: User | null
  lifecycle: Lifecycle
  version: string
  maturity: string
  tags: string[]
  headCommit: string
  repoPath: string
  componentCount: number
  outputPortCount: number
  publishedAt: string | null
  createdAt: string
  updatedAt: string
  environments?: EnvironmentStatus[]
  components?: Component[]
  outputPorts?: Component[]
  internalComponents?: Component[]
  versions?: Version[]
  policy?: PolicyEvaluation | null
  dependencies?: Dependency[]
  canEdit?: boolean
  gateEnvironment?: string
  releasedVersion?: string
  myRequests?: AccessRequest[]
  isOwner?: boolean
}

export interface Deployment {
  id: number
  environment: string
  status: DeploymentStatus
  operation: string
  version: string
  requestedBy: User | null
  startedAt: string
  finishedAt: string | null
  outputs: Record<string, Record<string, string>>
  logLineCount: number
  logs?: string[]
}

export interface AccessRequest {
  id: number
  status: AccessStatus
  purpose: string
  consumerDataProduct: string
  decisionNote: string
  requester: User | null
  decidedBy: User | null
  decidedAt: string | null
  createdAt: string
  dataProduct: { id: number; urn: string; title: string; domain: string; owner: User | null }
  component: { id: number; urn: string; name: string; title: string; technology: string } | null
}

export interface PlatformEvent {
  id: number
  type: string
  message: string
  actor: User | null
  dataProduct: { id: number; urn: string; title: string } | null
  payload: Record<string, any>
  createdAt: string
}

export interface TemplateField {
  name: string
  title?: string
  type?: 'string' | 'text' | 'select' | 'boolean' | 'number' | 'tags' | 'schema'
  required?: boolean
  default?: any
  options?: (string | { value: string; label: string })[]
  optionsFrom?: string
  help?: string
  placeholder?: string
  pattern?: string
  patternMessage?: string
}

export interface TemplateSection {
  title: string
  description?: string
  fields: TemplateField[]
}

export interface Template {
  id: string
  name: string
  type: 'dataproduct' | 'component'
  kind: ComponentKind | ''
  description: string
  technology: string
  platform: string
  provisioner: string
  icon: string
  tags: string[]
  parameters?: TemplateSection[]
}

export interface Domain {
  id: number
  name: string
  title: string
  description: string
  owner: User | null
  dataProductCount: number
}

export interface Metrics {
  dataProducts: number
  published: number
  components: number
  outputPorts: number
  domains: number
  users: number
  myDataProducts: number
  pendingAccessRequests: number
  byLifecycle: Record<string, number>
  byDomain: { domain: string; count: number }[]
  byTechnology: { technology: string; count: number }[]
  environments: { environment: string; provisioned: number }[]
}

export interface LineageNode {
  urn: string
  name: string
  title: string
  domain: string
  lifecycle: string
  outputPorts?: number
  external: boolean
  isRoot: boolean
}

export interface LineageGraph {
  nodes: LineageNode[]
  edges: { source: string; target: string; port: string; resolved: boolean }[]
}

export interface Commit {
  sha: string
  shortSha: string
  author: string
  email: string
  date: string
  message: string
}

export interface RepositoryInfo {
  slug: string
  path: string
  files: string[]
  commits: Commit[]
  tags: string[]
}

export interface PlatformInfo {
  name: string
  urnNamespace: string
  environments: string[]
  marketplaceGateEnvironment: string
  provisioners: { technology: string; platform: string; requiredKeys: string[] }[]
}

export interface MarketplaceResult {
  items: DataProduct[]
  total: number
  facets: {
    domains: { value: string; count: number }[]
    tags: { value: string; count: number }[]
    technologies: { value: string; count: number }[]
  }
}

export interface DeploymentPlan {
  environment: string
  steps: { component: string; kind: string; technology: string; provisioner: string | null; platform: string }[]
  problems: string[]
}
