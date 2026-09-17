import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";
import { SeverityBadge } from "../components/SeverityBadge";
import type { Severity } from "../theme/severity";
import { SEVERITY_ORDER } from "../theme/severity";

interface FindingRecord {
  id: string;
  title: string;
  severity: Severity;
  status: string;
  scanner: string;
  rule_id: string | null;
  file_path: string | null;
  line_start: number | null;
  cwe: string | null;
  first_seen: string;
  last_seen: string;
}

export function Findings() {
  const { t } = useTranslation();
  const [findings, setFindings] = useState<FindingRecord[] | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (severityFilter) params.set("severity", severityFilter);
    if (statusFilter) params.set("status", statusFilter);
    params.set("limit", "200");
    apiFetch(`/api/v1/findings?${params}`)
      .then((r) => r.json())
      .then(setFindings)
      .catch(() => setFindings([]));
  }, [severityFilter, statusFilter]);

  useEffect(load, [load]);

  const inputStyle = {
    fontFamily: "inherit",
    fontSize: 13,
    color: "var(--text-primary)",
    background: "var(--bg-page)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    padding: "6px 10px",
  };

  const statuses = ["new", "triaged", "confirmed", "false_positive", "risk_accepted", "fixed"];

  return (
    <div>
      <h1>{t("findings.title")}</h1>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <select
          style={{ ...inputStyle, minWidth: 140 }}
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
        >
          <option value="">{t("severity.label")}: {t("findings.all")}</option>
          {SEVERITY_ORDER.map((sev) => (
            <option key={sev} value={sev}>{t(`severity.${sev}`)}</option>
          ))}
        </select>
        <select
          style={{ ...inputStyle, minWidth: 160 }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">{t("status.label")}: {t("findings.all")}</option>
          {statuses.map((st) => (
            <option key={st} value={st}>{t(`status.${st}`)}</option>
          ))}
        </select>
        {findings !== null && (
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {t("findings.count", { count: findings.length })}
          </span>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {findings === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>
            {t("common.loading")}
          </p>
        ) : findings.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>
            {t("findings.empty")}
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("severity.label")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500, minWidth: 200 }}>
                  {t("findings.title")}
                </th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("findings.scanner")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("findings.file")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("status.label")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("findings.lastSeen")}</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((f) => (
                <tr key={f.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "8px 12px" }}>
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td style={{ padding: "8px 12px" }}>
                    <div style={{ fontWeight: 500 }}>{f.title.slice(0, 100)}</div>
                    {f.rule_id && (
                      <div style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                        {f.rule_id}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "8px 12px" }}>{f.scanner}</td>
                  <td
                    style={{
                      padding: "8px 12px",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      maxWidth: 250,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {f.file_path
                      ? `${f.file_path}${f.line_start ? `:${f.line_start}` : ""}`
                      : "—"}
                  </td>
                  <td style={{ padding: "8px 12px", fontSize: 12 }}>
                    {t(`status.${f.status}`)}
                  </td>
                  <td style={{ padding: "8px 12px", color: "var(--text-muted)", fontSize: 12 }}>
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
