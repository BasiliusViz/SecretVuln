import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { apiJson } from "../api/json";
import type { EntityNode, Finding, Group } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { SeverityBadge } from "../components/SeverityBadge";
import { MONO } from "../components/ui";
import { SEVERITY_ORDER } from "../theme/severity";

const STATUSES = ["new", "triaged", "confirmed", "in_progress", "false_positive", "risk_accepted", "fixed"];
const UNASSIGNED = "__none";
const CELL = { padding: "8px 12px" } as const;
const HEAD = { padding: "8px 12px", fontWeight: 500 } as const;

export function Findings() {
  const { t } = useTranslation();
  const can = useCan();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [severityFilter, setSeverityFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [entityFilter, setEntityFilter] = useState("");
  const [withChildren, setWithChildren] = useState(true);
  const [teamFilter, setTeamFilter] = useState("");
  const requestId = useRef(0);

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (severityFilter) params.set("severity", severityFilter);
    if (statusFilter) params.set("status", statusFilter);
    if (entityFilter) {
      params.set("entity_id", entityFilter);
      if (withChildren) params.set("include_descendants", "true");
    }
    if (teamFilter === UNASSIGNED) params.set("unassigned", "true");
    else if (teamFilter) params.set("assignee_group_id", teamFilter);
    params.set("limit", "200");
    // Фильтры меняются быстрее, чем приходят ответы — игнорируем устаревший ответ,
    // если за время запроса уже стартовал более новый.
    const id = ++requestId.current;
    void apiJson<Finding[]>(`/api/v1/findings?${params}`).then((r) => {
      if (id === requestId.current) setFindings(r.data ?? []);
    });
  }, [severityFilter, statusFilter, entityFilter, withChildren, teamFilter]);

  useEffect(load, [load]);

  useEffect(() => {
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setEntities([...(r.data ?? [])].sort((a, b) => a.path.localeCompare(b.path))),
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
