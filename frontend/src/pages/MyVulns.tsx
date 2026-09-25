import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { apiJson } from "../api/json";
import type { Decision, Finding } from "../api/types";
import { SeverityBadge } from "../components/SeverityBadge";
import { Tabs } from "../components/Tabs";
import { MONO, formatDate } from "../components/ui";

type Tab = "vulns" | "requests";
const SCOPES = {
  active: "status=confirmed&status=in_progress",
  open: "status=new&status=triaged&status=confirmed&status=in_progress",
} as const;
type Scope = keyof typeof SCOPES;
const CELL = { padding: "8px 12px" } as const;
const EMPTY = { padding: 16, margin: 0, color: "var(--text-muted)" } as const;

export function MyVulns() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("vulns");
  const [scope, setScope] = useState<Scope>("active");
  const [items, setItems] = useState<Finding[] | null>(null);
  const [requests, setRequests] = useState<Decision[] | null>(null);

  useEffect(() => {
    setItems(null);
    void apiJson<Finding[]>(`/api/v1/findings?mine=true&${SCOPES[scope]}&order=severity&limit=200`).then((r) =>
      setItems(r.data ?? []),
    );
  }, [scope]);

  useEffect(() => {
    if (tab === "requests") {
      void apiJson<Decision[]>("/api/v1/decisions?mine=true").then((r) => setRequests(r.data ?? []));
    }
  }, [tab]);

  return (
    <div>
      <h1>{t("my.title")}</h1>
      <Tabs
        label={t("my.title")}
        tabs={[
          { id: "vulns" as Tab, label: t("my.tabs.vulns") },
          { id: "requests" as Tab, label: t("my.tabs.requests") },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === "vulns" ? (
        <>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as Scope)}
            aria-label={t("status.label")}
            style={{ marginBottom: 12 }}
          >
            {(Object.keys(SCOPES) as Scope[]).map((s) => (
              <option key={s} value={s}>
                {t(`my.scope.${s}`)}
              </option>
            ))}
          </select>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            {items === null ? (
              <p style={EMPTY}>{t("common.loading")}</p>
            ) : items.length === 0 ? (
              <p style={EMPTY}>{t("my.empty")}</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <tbody>
                  {items.map((f) => (
                    <tr key={f.id} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={CELL}>
                        <SeverityBadge severity={f.severity} />
                      </td>
                      <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                        <Link to={`/f/SV-${f.number}`}>SV-{f.number}</Link>
                      </td>
                      <td style={CELL}>
                        <Link to={`/f/SV-${f.number}`} style={{ fontWeight: 500, color: "inherit" }}>
                          {f.title.slice(0, 120)}
                        </Link>
                        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                          {f.assignee_group?.name ?? t("team.none")} · {f.file_path ?? t("common.none")}
                        </div>
                      </td>
                      <td style={{ ...CELL, fontSize: 12 }}>{t(`status.${f.status}`)}</td>
                      <td style={{ ...CELL, fontSize: 12, color: "var(--text-muted)" }}>{formatDate(f.first_seen)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      ) : (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          {requests === null ? (
            <p style={EMPTY}>{t("common.loading")}</p>
          ) : requests.length === 0 ? (
            <p style={EMPTY}>{t("my.noRequests")}</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <tbody>
                {requests.map((d) => (
                  <tr key={d.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                      {d.finding_number && <Link to={`/f/SV-${d.finding_number}`}>SV-{d.finding_number}</Link>}
                    </td>
                    <td style={CELL}>
                      <div style={{ fontWeight: 500 }}>{d.finding_title}</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                        {t(`decision.type.${d.decision_type}`)}
                        {d.reason_tag && ` — ${t(`decision.tags.${d.reason_tag}`)}`}
                      </div>
                      {d.decision_comment && <div style={{ fontSize: 12 }}>{d.decision_comment}</div>}
                    </td>
                    <td style={{ ...CELL, fontSize: 12 }}>{t(`my.requestStatus.${d.status}`)}</td>
                    <td style={{ ...CELL, fontSize: 12, color: "var(--text-muted)" }}>{formatDate(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
