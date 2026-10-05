import type { AuditPage, AuditQuery } from "./types";
import { apiJson } from "./json";

/** URL для GET /audit: пустые фильтры не передаём, `action` — повторяющийся параметр */
export function auditUrl(q: AuditQuery): string {
  const p = new URLSearchParams();
  if (q.entity_id) p.set("entity_id", q.entity_id);
  if (q.subtree !== undefined) p.set("subtree", String(q.subtree));
  if (q.actor?.trim()) p.set("actor", q.actor.trim());
  for (const a of q.action ?? []) p.append("action", a);
  if (q.date_from) p.set("date_from", q.date_from);
  if (q.date_to) p.set("date_to", q.date_to);
  if (q.limit !== undefined) p.set("limit", String(q.limit));
  if (q.offset !== undefined) p.set("offset", String(q.offset));
  const qs = p.toString();
  return qs ? `/api/v1/audit?${qs}` : "/api/v1/audit";
}

export function fetchAudit(q: AuditQuery) {
  return apiJson<AuditPage>(auditUrl(q));
}
