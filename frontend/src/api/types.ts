import type { Severity } from "../theme/severity";

export const OPEN_STATUSES = ["new", "triaged", "confirmed", "in_progress"];

export const REASON_TAGS = [
  "data_not_user_controlled",
  "test_code",
  "sanitized",
  "dead_code",
  "other",
] as const;
export type ReasonTag = (typeof REASON_TAGS)[number];

export interface GroupBrief {
  id: string;
  name: string;
}

export interface Group extends GroupBrief {
  description: string | null;
  source: string;
  member_count: number;
  // только в GET /groups?entity_id=: есть ли у группы finding:read на проекте
  has_access?: boolean | null;
}

export interface Finding {
  id: string;
  number: number;
  entity_id: string;
  import_id: string | null;
  title: string;
  description: string | null;
  severity: Severity;
  status: string;
  scanner: string;
  rule_id: string | null;
  cwe: string | null;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  scan_scope: string | null;
  commit_sha: string | null;
  fingerprint: string;
  first_seen: string;
  last_seen: string;
  created_at: string;
  assignee_group_id: string | null;
  assignee_user_id: string | null;
  assigned_manually: boolean;
  help_requested_at: string | null;
  sla_start_at: string | null;
  due_at: string | null;
  resolved_at: string | null;
  assignee_group: GroupBrief | null;
  assignee_user: { id: string; email: string; full_name: string | null } | null;
}

export interface FindingDetail extends Finding {
  entity_name: string;
  entity_path: string;
  code_url: string | null;
  code_url_head: string | null;
  help_text: string | null;
}

export interface FindingEvent {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  actor_name: string | null;
  from_status: string | null;
  to_status: string | null;
  reason: string | null;
  reason_tag: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Decision {
  id: string;
  finding_id: string;
  finding_number: number | null;
  finding_title: string | null;
  decision_type: "false_positive" | "risk_accepted";
  status: "pending" | "approved" | "rejected" | "expired";
  reason_tag: ReasonTag | null;
  reason: string | null;
  expires_at: string | null;
  requested_by_id: string | null;
  decision_comment: string | null;
  created_at: string;
  entity_path: string | null;
  can_approve: boolean;
}

export interface EntityNode {
  id: string;
  name: string;
  slug: string;
  path: string;
  parent_id: string | null;
  description?: string | null;
  // предок, видимый только как часть пути: серый, без перехода
  stub?: boolean;
}

export interface Binding {
  id: string;
  group_id: string;
  group_name: string;
  role_id: string;
  role_name: string;
  entity_id: string | null;
  // null — на всё дерево
  entity_path: string | null;
  created_at: string;
  created_by: string | null;
}

export interface RoleGrant {
  id: string;
  name: string;
  grantable: boolean;
  missing: string[];
}

export interface EntityBindings {
  own: Binding[];
  inherited: Binding[];
  // только при access:manage на проекте
  roles: RoleGrant[] | null;
}

export type SettingField =
  | "default_branch"
  | "owner_group_id"
  | "repo_url"
  | "repo_type"
  | "repo_path_prefix";

export interface SettingValue {
  value: string | null;
  source: "manual" | "file" | "inherited" | "unset";
  inherited_from: string | null;
}

export interface OwnershipRuleRead {
  id: string;
  pattern: string;
  group_id: string;
  group_name: string;
  position: number;
  source: string;
}

export interface EntitySettings {
  entity_id: string;
  path: string;
  fields: Record<SettingField, SettingValue>;
  ownership_rules: OwnershipRuleRead[];
  rules_source: "manual" | "file";
  inherited_rules: { entity_path: string; pattern: string; group_id: string; group_name: string }[];
  pinned_fields: string[];
  has_config_file: boolean;
  config_commit_sha: string | null;
  config_applied_at: string | null;
  warnings: string[];
  sla: EffectiveSla;
  tags: string[];
  effective_tags: { tag: string; inherited_from: string | null }[];
}

export interface EffectiveSla {
  policy_id: string | null;
  policy_name: string | null;
  /** своя политика узла; иначе унаследована (inherited_from) или по умолчанию */
  own: boolean;
  inherited_from: string | null;
  is_default: boolean;
}

export const SLA_DAY_FIELDS = ["days_critical", "days_high", "days_medium", "days_low", "days_info"] as const;
export type SlaDayField = (typeof SLA_DAY_FIELDS)[number];

export interface SlaPolicy extends Record<SlaDayField, number | null> {
  id: string;
  name: string;
  is_default: boolean;
  /** сколько проектов назначили политику напрямую */
  entities_count: number;
  created_at: string;
  updated_at: string;
}

export interface NoisyRule {
  scanner: string;
  rule_id: string;
  decided: number;
  false_positive: number;
  fp_ratio: number;
  top_reasons: { reason_tag: string; count: number }[];
}

export type MetricName = "count" | "opened" | "resolved" | "overdue" | "sla_ratio" | "mttr_days";
export type MetricGroupBy = "none" | "severity" | "scanner" | "team" | "entity" | "week";
export type MetricPeriod = "7d" | "30d" | "90d" | "365d";

/** JSON виджета дашборда — то же, что принимает POST /metrics/aggregate */
export interface MetricQuery {
  metric: MetricName;
  group_by?: MetricGroupBy;
  period?: MetricPeriod;
  filters?: { severity?: Severity[]; scanner?: string; entity_id?: string; tag?: string };
}

export interface MetricRow {
  key: string | null;
  label: string | null;
  value: number | null;
}

export interface MetricResult {
  metric: MetricName;
  group_by: MetricGroupBy;
  period: MetricPeriod;
  rows: MetricRow[];
}

export interface BulkResult {
  applied: number;
  skipped: { id: string; reason: string }[];
}

export interface UserBrief {
  id: string;
  email: string;
  display_name: string | null;
}

export interface ImportRecord {
  id: string;
  entity_id: string;
  filename: string;
  scanner: string | null;
  status: string;
  stats: { created?: number; updated?: number; duplicates?: number; total_results?: number };
  error: string | null;
  created_at: string;
  finished_at: string | null;
  uploaded_by: UserBrief | null;
}

/** Строка журнала аудита. `changes`: значение `[было, стало]` — правка поля, иначе — просто значение */
export interface AuditEntry {
  id: string;
  created_at: string;
  actor_type: "user" | "system";
  actor_id: string | null;
  actor_label: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  target_label: string | null;
  entity_id: string | null;
  entity_path: string | null;
  ip: string | null;
  changes: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
}

/** Фильтры GET /audit; `action` — точные действия или префиксы с точкой (`binding.`), объединяются через ИЛИ */
export interface AuditQuery {
  entity_id?: string;
  subtree?: boolean;
  actor?: string;
  action?: string[];
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

/** Группы фильтра «Действие» → префиксы для повторяющегося `action` */
export const AUDIT_ACTION_GROUPS: Record<string, string[]> = {
  auth: ["auth."],
  projects: ["entity.", "ownership.", "findings."],
  access: ["binding."],
  groups: ["group."],
  roles: ["role."],
  sla: ["sla_policy."],
  imports: ["import."],
};
