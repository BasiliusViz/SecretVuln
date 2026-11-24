import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { apiJson } from "../api/json";
import { OPEN_STATUSES } from "../api/types";
import type { EntityNode, Finding, Group, MetricResult } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { AiVerdictBadge, AiVerdictFilter, applyAiVerdictFilter } from "../components/AiVerdictBadge";
import { DueBadge } from "../components/DueBadge";
import { SeverityBadge } from "../components/SeverityBadge";
import { KevBadge, formatPercent } from "../components/ThreatIntel";
import { MONO } from "../components/ui";
import { SEVERITY_ORDER } from "../theme/severity";

const STATUSES = ["new", "triaged", "confirmed", "in_progress", "false_positive", "risk_accepted", "fixed"];
const UNASSIGNED = "__none";
// Все открытые статусы разом — так открывается список с плитки дашборда
const OPEN = "open";
const EPSS_STEPS = [1, 10, 50] as const;
const ORDERS = ["last_seen", "due_at", "severity", "number", "epss_max"] as const;
const CELL = { padding: "8px 12px" } as const;
const HEAD = { padding: "8px 12px", fontWeight: 500 } as const;

export function Findings() {
  const { t } = useTranslation();
  const can = useCan();
  // Начальные фильтры из адреса: /vulnerabilities?kev=true&status=open&entity_id=…
  const [searchParams] = useSearchParams();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [severityFilter, setSeverityFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState(() => searchParams.get("status") ?? "");
  const [entityFilter, setEntityFilter] = useState(() => searchParams.get("entity_id") ?? "");
  const [withChildren, setWithChildren] = useState(true);
  const [teamFilter, setTeamFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [aiFilter, setAiFilter] = useState("");
  const [hasMemory, setHasMemory] = useState(false);
  const [kevOnly, setKevOnly] = useState(() => searchParams.get("kev") === "true");
  const [minEpss, setMinEpss] = useState("");
  const [hasBdu, setHasBdu] = useState(false);
  const [cweCategory, setCweCategory] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [order, setOrder] = useState<(typeof ORDERS)[number]>("last_seen");
  const [tags, setTags] = useState<string[]>([]);
  const requestId = useRef(0);

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (severityFilter) params.set("severity", severityFilter);
    if (statusFilter === OPEN) OPEN_STATUSES.forEach((st) => params.append("status", st));
    else if (statusFilter) params.set("status", statusFilter);
    if (entityFilter) {
      params.set("entity_id", entityFilter);
      if (withChildren) params.set("include_descendants", "true");
    }
    if (teamFilter === UNASSIGNED) params.set("unassigned", "true");
    else if (teamFilter) params.set("assignee_group_id", teamFilter);
    if (tagFilter) params.set("tag", tagFilter);
    if (overdueOnly) params.set("overdue", "true");
    applyAiVerdictFilter(params, aiFilter);
    if (hasMemory) params.set("has_memory", "true");
    if (kevOnly) params.set("kev", "true");
    if (minEpss) params.set("min_epss", String(Number(minEpss) / 100));
    if (hasBdu) params.set("has_bdu", "true");
    if (cweCategory) params.set("cwe_category", cweCategory);
    params.set("order", order);
    params.set("limit", "200");
    // Фильтры меняются быстрее, чем приходят ответы — игнорируем устаревший ответ,
    // если за время запроса уже стартовал более новый.
    const id = ++requestId.current;
    void apiJson<Finding[]>(`/api/v1/findings?${params}`).then((r) => {
      if (id === requestId.current) setFindings(r.data ?? []);
    });
  }, [severityFilter, statusFilter, entityFilter, withChildren, teamFilter, tagFilter, overdueOnly, aiFilter, hasMemory, kevOnly, minEpss, hasBdu, cweCategory, order]);

  useEffect(load, [load]);

  useEffect(() => {
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setEntities([...(r.data ?? [])].sort((a, b) => a.path.localeCompare(b.path))),
    );
    void apiJson<string[]>("/api/v1/tags").then((r) => setTags(r.data ?? []));
    // Отдельного списка категорий нет — берём категории открытых находок из метрик
    void apiJson<MetricResult>("/api/v1/metrics/aggregate", "POST", { metric: "count", group_by: "cwe_category" }).then(
      (r) =>
        setCategories(
          (r.data?.rows ?? [])
            .map((row) => row.key)
            .filter((k): k is string => !!k)
            .sort((a, b) => a.localeCompare(b)),
        ),
    );
  }, []);

  const canSeeGroups = can("group:read");
  useEffect(() => {
    if (canSeeGroups) void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
  }, [canSeeGroups]);

  const inputStyle = {
    fontFamily: "inherit",
    fontSize: 13,
    color: "var(--text-primary)",
    background: "var(--bg-page)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    padding: "6px 10px",
  };

  return (
    <div>
      <h1>{t("vulns.title")}</h1>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <select
          style={{ ...inputStyle, minWidth: 140 }}
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          aria-label={t("severity.label")}
        >
          <option value="">
            {t("severity.label")}: {t("vulns.all")}
          </option>
          {SEVERITY_ORDER.map((sev) => (
            <option key={sev} value={sev}>
              {t(`severity.${sev}`)}
            </option>
          ))}
        </select>
        <select
          style={{ ...inputStyle, minWidth: 160 }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label={t("status.label")}
        >
          <option value="">
            {t("status.label")}: {t("vulns.all")}
          </option>
          <option value={OPEN}>{t("vulns.allOpen")}</option>
          {STATUSES.map((st) => (
            <option key={st} value={st}>
              {t(`status.${st}`)}
            </option>
          ))}
        </select>
        <select
          style={{ ...inputStyle, minWidth: 200 }}
          value={entityFilter}
          onChange={(e) => setEntityFilter(e.target.value)}
          aria-label={t("vulns.project")}
        >
          <option value="">{t("vulns.allProjects")}</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.path}
            </option>
          ))}
        </select>
        {entityFilter && (
          <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={withChildren} onChange={(e) => setWithChildren(e.target.checked)} />
            {t("vulns.includeChildren")}
          </label>
        )}
        <select
          style={{ ...inputStyle, minWidth: 160 }}
          value={teamFilter}
          onChange={(e) => setTeamFilter(e.target.value)}
          aria-label={t("team.label")}
        >
          <option value="">{t("team.all")}</option>
          <option value={UNASSIGNED}>{t("team.none")}</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        {tags.length > 0 && (
          <select
            style={{ ...inputStyle, minWidth: 120 }}
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            aria-label={t("vulns.tag")}
          >
            <option value="">
              {t("vulns.tag")}: {t("vulns.all")}
            </option>
            {tags.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>
        )}
        <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={overdueOnly} onChange={(e) => setOverdueOnly(e.target.checked)} />
          {t("vulns.overdueOnly")}
        </label>
        <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={hasMemory} onChange={(e) => setHasMemory(e.target.checked)} />
          {t("vulns.hasMemory")}
        </label>
        <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={kevOnly} onChange={(e) => setKevOnly(e.target.checked)} />
          {t("vulns.kevOnly")}
        </label>
        <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={hasBdu} onChange={(e) => setHasBdu(e.target.checked)} />
          {t("vulns.hasBdu")}
        </label>
        <select
          style={{ ...inputStyle, minWidth: 120 }}
          value={minEpss}
          onChange={(e) => setMinEpss(e.target.value)}
          aria-label={t("vulns.minEpss")}
        >
          <option value="">
            {t("vulns.minEpss")}: {t("vulns.all")}
          </option>
          {EPSS_STEPS.map((n) => (
            <option key={n} value={n}>
              {t("vulns.epssFrom", { value: n })}
            </option>
          ))}
        </select>
        {categories.length > 0 && (
          <select
            style={{ ...inputStyle, minWidth: 160, maxWidth: 260 }}
            value={cweCategory}
            onChange={(e) => setCweCategory(e.target.value)}
            aria-label={t("vulns.cweCategory")}
          >
            <option value="">
              {t("vulns.cweCategory")}: {t("vulns.all")}
            </option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        )}
        <AiVerdictFilter value={aiFilter} onChange={setAiFilter} style={{ ...inputStyle, minWidth: 160 }} />
        <select
          style={{ ...inputStyle, minWidth: 160 }}
          value={order}
          onChange={(e) => setOrder(e.target.value as (typeof ORDERS)[number])}
          aria-label={t("vulns.order")}
        >
          {ORDERS.map((o) => (
            <option key={o} value={o}>
              {t(`vulns.orderBy.${o}`)}
            </option>
          ))}
        </select>
        {findings !== null && (
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("vulns.count", { count: findings.length })}</span>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {findings === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("common.loading")}</p>
        ) : findings.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("vulns.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={HEAD}>{t("vulns.number")}</th>
                <th style={HEAD}>{t("severity.label")}</th>
                <th style={{ ...HEAD, minWidth: 200 }}>{t("vulns.title")}</th>
                <th style={HEAD}>{t("team.label")}</th>
                <th style={HEAD}>{t("vulns.scanner")}</th>
                <th style={HEAD}>{t("vulns.file")}</th>
                <th style={HEAD}>{t("status.label")}</th>
                <th style={HEAD}>{t("due.label")}</th>
                <th style={HEAD}>{t("vulns.epss")}</th>
                <th style={HEAD}>{t("vulns.kev")}</th>
                <th style={HEAD}>{t("ai.verdict.label")}</th>
                <th style={HEAD}>{t("vulns.lastSeen")}</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((f) => (
                <tr key={f.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                    <Link to={`/f/SV-${f.number}`}>SV-{f.number}</Link>
                  </td>
                  <td style={CELL}>
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td style={CELL}>
                    <Link to={`/f/SV-${f.number}`} style={{ fontWeight: 500, color: "inherit" }}>
                      {f.title.slice(0, 100)}
                    </Link>
                    {f.memory && (
                      <span
                        title={t("memory.badgeTitle", { decision: t(`decision.type.${f.memory.decision}`) })}
                        style={{
                          marginLeft: 8,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          fontSize: 11,
                          padding: "1px 8px",
                          borderRadius: 99,
                          background: "var(--accent-bg)",
                          color: "var(--accent)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        <span aria-hidden="true">◆</span>
                        {t("memory.badge")}
                      </span>
                    )}
                    {f.rule_id && <div style={{ ...MONO, fontSize: 11, color: "var(--text-muted)" }}>{f.rule_id}</div>}
                  </td>
                  <td style={{ ...CELL, fontSize: 12 }}>{f.assignee_group?.name ?? t("team.none")}</td>
                  <td style={CELL}>{f.scanner}</td>
                  <td
                    style={{
                      ...CELL,
                      ...MONO,
                      maxWidth: 250,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {f.file_path ? `${f.file_path}${f.line_start ? `:${f.line_start}` : ""}` : t("common.none")}
                  </td>
                  <td style={{ ...CELL, fontSize: 12 }}>{t(`status.${f.status}`)}</td>
                  <td style={{ ...CELL, fontSize: 12 }}>
                    <DueBadge dueAt={f.due_at} status={f.status} />
                  </td>
                  <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                    {f.epss_max != null ? formatPercent(f.epss_max) : t("common.none")}
                  </td>
                  <td style={CELL}>{f.kev && <KevBadge compact />}</td>
                  <td style={CELL}>
                    <AiVerdictBadge verdict={f.ai_verdict} />
                  </td>
                  <td style={{ ...CELL, color: "var(--text-muted)", fontSize: 12 }}>
                    {new Date(f.last_seen).toLocaleString("ru-RU")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
