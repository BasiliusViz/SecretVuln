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
}

export interface EntityNode {
  id: string;
  name: string;
  slug: string;
  path: string;
  parent_id: string | null;
  description: string | null;
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
}

export interface BulkResult {
  applied: number;
  skipped: { id: string; reason: string }[];
}
